#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前统一预检门禁：平台规格 + 合规 + 版本间重复度。

一条命令回答「这批稿子现在能不能发」。三类问题一起查：

  1. 规格 —— 标题超字数会被截断、话题没填够拿不到冷启动流量、图片比例不对会被裁切。
     这些是发布当场失败或效果打折的直接原因，纯机械可查。
  2. 合规 —— 广告法绝对化用语、平台导流词、手机号。复用 compliance_check.py 的词库。
  3. 重复度 —— 各平台版本之间不能是「同一篇文章」。平台有重复度检测，
     互相雷同会同时压流量。所以这条设计原则必须变成硬指标，不能靠自觉。

依赖文章目录的命名约定（见 references/rewrite-playbook.md）：

    <文章目录>/
    ├── master.md           # 母稿，不参与规格校验
    ├── wechat.md           # 公众号
    ├── zhihu.md            # 知乎
    ├── toutiao.md          # 头条
    ├── xiaohongshu.md      # 小红书
    ├── weibo.md            # 微博
    └── images/             # 配图

平台版本文件建议带 frontmatter（缺失时会退化推导，但会告警）：

    ---
    platform: xiaohongshu
    title: 居家办公3年｜我以为很爽，结果效率崩了
    tags: 居家办公, 效率, 职场
    images: images/xhs-1.jpg, images/xhs-2.jpg
    ---
    <正文>

用法：
    python preflight_check.py <文章目录>
    python preflight_check.py <文章目录> --json
    python preflight_check.py --show-specs

退出码：存在 FAIL 或合规 BLOCK 命中 → 1（可作为流程门禁）；否则 0。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import compliance_check  # noqa: E402
except ImportError:  # 单独拷贝本脚本时仍可运行，只是少了合规扫描
    compliance_check = None

# ---------------------------------------------------------------- 平台规格
# 三元组含义：(建议下限, 建议上限, 硬上限)。硬上限为 None 表示没有硬性截断。
# 与 references/platform-specs.md 保持同步 —— 平台改版后两边都要改。

SPECS: dict[str, dict] = {
    "wechat": {
        "name": "公众号",
        "file": "wechat.md",
        "title": (16, 24, 64),
        "body": (2000, 4000, None),
        "tags": (0, 0, 0),
        "images": (1, 4),
        "cover_ratio": (2.35, 0.06),
    },
    "zhihu": {
        "name": "知乎",
        "file": "zhihu.md",
        "title": (20, 30, None),
        "body": (2000, 6000, None),
        "tags": (3, 3, 5),
        "images": (0, 6),
    },
    "toutiao": {
        "name": "头条",
        "file": "toutiao.md",
        "title": (15, 25, 30),
        "body": (1000, 3000, None),
        "tags": (1, 3, 3),
        "images": (1, 3),
    },
    "xiaohongshu": {
        "name": "小红书",
        "file": "xiaohongshu.md",
        "title": (15, 20, 20),
        "body": (300, 600, 1000),
        "tags": (5, 10, 10),
        "images": (1, 18),
        "all_ratio": (0.75, 0.04),
    },
    "weibo": {
        "name": "微博",
        "file": "weibo.md",
        "title": None,
        "body": (100, 300, 2000),
        "tags": (1, 3, 3),
        "images": (0, 9),
    },
}

RATIO_LABEL = {
    "cover_ratio": "封面比例",
    "all_ratio": "图片比例",
}

# 重复度阈值（字符 3-gram Jaccard）。经验值，可按实际体感调整。
SIMILARITY_WARN = 0.45
SIMILARITY_FAIL = 0.60

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# ---------------------------------------------------------------- 工具函数


def read_image_size(path: Path) -> tuple[int, int] | None:
    """只靠文件头读图片尺寸，不依赖 Pillow。"""
    try:
        data = path.read_bytes()[:262144]
    except OSError:
        return None
    if len(data) < 24:
        return None

    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))

    if data[:3] == b"GIF":
        return (int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"))

    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return (int.from_bytes(data[i + 7:i + 9], "big"),
                        int.from_bytes(data[i + 5:i + 7], "big"))
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
        return None

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X":
            return (int.from_bytes(data[24:27], "little") + 1,
                    int.from_bytes(data[27:30], "little") + 1)
        if chunk == b"VP8 ":
            return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                    int.from_bytes(data[28:30], "little") & 0x3FFF)
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    return None


def parse_article(path: Path) -> tuple[dict, str]:
    """拆分 frontmatter 与正文。没有 frontmatter 时返回空 dict。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, str] = {}
    body = text
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        parts = stripped.split("---", 2)
        if len(parts) >= 3:
            header, body = parts[1], parts[2]
            for line in header.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, body.strip()


def split_list(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,，]", value) if item.strip()]


def count_chars(text: str) -> int:
    """按非空白字符计数 —— 中文场景下比 len() 更贴近平台的统计口径。"""
    return len(re.sub(r"\s", "", text))


def extract_title(meta: dict, body: str) -> tuple[str, str | None]:
    """返回 (标题, 告警)。优先 frontmatter，其次正文首个标题行。"""
    if meta.get("title"):
        return meta["title"], None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip(), "未用 frontmatter，标题取自正文首个标题行"
        if line:
            return line, "未用 frontmatter，标题取自正文首行"
    return "", "无法识别标题"


def ngrams(text: str, n: int = 3) -> set[str]:
    compact = re.sub(r"\s", "", text)
    return {compact[i:i + n] for i in range(max(len(compact) - n + 1, 0))}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------- 单项检查


def check_range(label: str, value: int, low: int, high: int,
                hard_cap: int | None, unit: str = "字") -> tuple[list[str], list[str]]:
    fails, warns = [], []
    if hard_cap is not None and value > hard_cap:
        fails.append(f"{label} {value}{unit} 超出硬上限 {hard_cap}{unit}，会被截断")
    elif value < low:
        warns.append(f"{label} {value}{unit}，低于建议下限 {low}{unit}")
    elif value > high:
        warns.append(f"{label} {value}{unit}，高于建议上限 {high}{unit}")
    return fails, warns


def check_images(paths: list[Path], spec: dict) -> tuple[list[str], list[str], list[str]]:
    fails, warns, notes = [], [], []
    lo, hi = spec["images"]
    n = len(paths)
    if n < lo:
        warns.append(f"图片只有 {n} 张，建议至少 {lo} 张")
    elif n > hi:
        fails.append(f"图片 {n} 张，超出上限 {hi} 张")

    rule_key = "cover_ratio" if spec.get("cover_ratio") else (
        "all_ratio" if spec.get("all_ratio") else None)
    if not rule_key:
        return fails, warns, notes

    target, tolerance = spec[rule_key]
    label = RATIO_LABEL[rule_key]
    targets = paths[:1] if rule_key == "cover_ratio" else paths

    for img in targets:
        size = read_image_size(img)
        if size is None:
            warns.append(f"{img.name} 读不出尺寸，无法校验{label}（跳过）")
            continue
        w, h = size
        if h == 0:
            continue
        ratio = w / h
        if abs(ratio - target) > tolerance:
            fails.append(
                f"{img.name} 比例 {ratio:.2f}:1（{w}×{h}），"
                f"{label}要求 {target}:1，发布页会裁切")
        else:
            notes.append(f"{img.name} {w}×{h} 比例合格")
    return fails, warns, notes


def check_platform(key: str, path: Path, article_dir: Path) -> dict:
    spec = SPECS[key]
    meta, body = parse_article(path)

    fails: list[str] = []
    warns: list[str] = []
    notes: list[str] = []

    if spec["title"]:
        title, title_warn = extract_title(meta, body)
        if title_warn:
            warns.append(title_warn)
        lo, hi, cap = spec["title"]
        f, w = check_range("标题", count_chars(title), lo, hi, cap)
        fails += f
        warns += w
    else:
        # 该平台没有独立标题（如微博，正文即内容）：不做标题校验，也不做推导告警
        title = meta.get("title", "")

    body_len = count_chars(body)
    lo, hi, cap = spec["body"]
    f, w = check_range("正文", body_len, lo, hi, cap)
    fails += f
    warns += w

    tags = split_list(meta.get("tags", ""))
    if not tags:
        inline = re.findall(r"#([^#\s]{1,20})#", body)
        inline += re.findall(r"#([^#\s]{1,20})(?=\s|$)", body)
        tags = list(dict.fromkeys(inline))
        if tags:
            warns.append("话题数量取自正文内联 #标签#，建议改用 frontmatter 的 tags 字段")
    lo, hi, cap = spec["tags"]
    if cap:
        n_tags = len(tags)
        if n_tags > cap:
            fails.append(f"话题 {n_tags} 个，超出上限 {cap} 个")
        elif n_tags < lo:
            warns.append(f"话题只有 {n_tags} 个，该平台建议 {lo}–{hi} 个（影响冷启动流量）")
        else:
            notes.append(f"话题 {n_tags} 个，合格")

    img_paths = []
    for raw in split_list(meta.get("images", "")):
        candidate = article_dir / raw
        if candidate.exists():
            img_paths.append(candidate)
        else:
            warns.append(f"frontmatter 里的图片不存在：{raw}")
    if not img_paths and not meta.get("images"):
        img_dir = article_dir / "images"
        if img_dir.is_dir():
            img_paths = sorted(
                p for p in img_dir.iterdir()
                if p.suffix.lower() in IMAGE_SUFFIXES
                and p.stem.startswith(key[:4]))
            if img_paths:
                warns.append(f"未声明 images 字段，按文件名前缀猜出 {len(img_paths)} 张图")

    f, w, n_ = check_images(img_paths, spec)
    fails += f
    warns += w
    notes += n_

    hits = []
    if compliance_check is not None:
        hits = compliance_check.scan_text(
            path.read_text(encoding="utf-8", errors="replace"),
            compliance_check.collect_rules(key))
    blocks = [h for h in hits if h["level"] == "block"]

    return {
        "platform": key,
        "name": spec["name"],
        "file": path.name,
        "title": title,
        "title_len": count_chars(title) if title else 0,
        "body_len": body_len,
        "tags": tags,
        "images": [str(p.relative_to(article_dir)) for p in img_paths],
        "fails": fails,
        "warns": warns,
        "notes": notes,
        "compliance": hits,
        "compliance_blocks": len(blocks),
        "status": "FAIL" if (fails or blocks) else ("WARN" if warns else "PASS"),
    }


def check_similarity(checked: list[dict], bodies: dict[str, str]) -> list[dict]:
    """两两比对各平台版本，抓「复制粘贴」。"""
    findings = []
    keys = [c["platform"] for c in checked if c["platform"] in bodies]
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            ta, tb = bodies[a], bodies[b]
            if not ta or not tb:
                continue
            body_sim = jaccard(ngrams(ta), ngrams(tb))
            head_sim = jaccard(ngrams(ta[:300]), ngrams(tb[:300]))
            title_a = next(c["title"] for c in checked if c["platform"] == a)
            title_b = next(c["title"] for c in checked if c["platform"] == b)
            title_same = bool(title_a) and title_a == title_b

            level = None
            reasons = []
            if title_same:
                level = "FAIL"
                reasons.append("标题完全相同 —— 至少改标题")
            if body_sim >= SIMILARITY_FAIL:
                level = "FAIL"
                reasons.append(f"正文 3-gram 相似度 {body_sim:.0%}，视为同一篇的复制")
            elif body_sim >= SIMILARITY_WARN and level != "FAIL":
                level = "WARN"
                reasons.append(f"正文相似度 {body_sim:.0%} 偏高")
            if head_sim >= SIMILARITY_FAIL and not title_same:
                level = "FAIL" if level != "WARN" else "WARN"
                reasons.append(f"开头 300 字相似度 {head_sim:.0%}，开头需要重写")

            if level:
                findings.append({
                    "pair": [SPECS[a]["name"], SPECS[b]["name"]],
                    "keys": [a, b],
                    "body_similarity": round(body_sim, 3),
                    "head_similarity": round(head_sim, 3),
                    "title_same": title_same,
                    "level": level,
                    "reasons": reasons,
                })
    return findings


# ---------------------------------------------------------------- 主流程


def run(article_dir: Path) -> dict:
    checked: list[dict] = []
    bodies: dict[str, str] = {}
    missing: list[str] = []

    for key, spec in SPECS.items():
        path = article_dir / spec["file"]
        if not path.exists():
            missing.append(spec["name"])
            continue
        checked.append(check_platform(key, path, article_dir))
        _, body = parse_article(path)
        bodies[key] = body

    similarity = check_similarity(checked, bodies)

    fails = sum(len(c["fails"]) for c in checked) + \
        sum(1 for s in similarity if s["level"] == "FAIL")
    warns = sum(len(c["warns"]) for c in checked) + \
        sum(1 for s in similarity if s["level"] == "WARN")
    blocks = sum(c["compliance_blocks"] for c in checked)

    return {
        "article_dir": str(article_dir),
        "platforms_checked": [c["name"] for c in checked],
        "platforms_missing": missing,
        "results": checked,
        "similarity": similarity,
        "total_fail": fails,
        "total_warn": warns,
        "total_compliance_blocks": blocks,
        "verdict": "BLOCK" if (fails or blocks) else ("WARN" if warns else "PASS"),
    }


def render(report: dict) -> None:
    print(f"文章目录：{report['article_dir']}")
    if not report["platforms_checked"]:
        print("未找到任何平台版本文件（wechat.md / zhihu.md / toutiao.md / "
              "xiaohongshu.md / weibo.md）")
        return
    print(f"已检查平台：{'、'.join(report['platforms_checked'])}")
    if report["platforms_missing"]:
        print(f"未找到（跳过）：{'、'.join(report['platforms_missing'])}")
    print()

    for c in report["results"]:
        mark = {"PASS": "通过", "WARN": "告警", "FAIL": "不合格"}[c["status"]]
        print(f"=== {c['name']} ({c['file']}) · {mark} ===")
        print(f"  标题({c['title_len']}字)：{c['title'] or '（未识别）'}")
        print(f"  正文 {c['body_len']} 字，话题 {len(c['tags'])} 个，图片 {len(c['images'])} 张")
        for item in c["fails"]:
            print(f"  [FAIL] {item}")
        for item in c["warns"]:
            print(f"  [WARN] {item}")
        for item in c["notes"]:
            print(f"  [ OK ] {item}")
        for h in c["compliance"]:
            tag = "[BLOCK]" if h["level"] == "block" else "[WARN ]"
            print(f"  {tag} L{h['line']} 「{h['match']}」 → {h['suggestion']}")
        print()

    if report["similarity"]:
        print("=== 版本间重复度 ===")
        for s in report["similarity"]:
            print(f"  [{s['level']}] {s['pair'][0]} ↔ {s['pair'][1]}"
                  f"（正文 {s['body_similarity']:.0%}，开头 {s['head_similarity']:.0%}）")
            for reason in s["reasons"]:
                print(f"         → {reason}")
        print()
    else:
        print("=== 版本间重复度 ===\n  无可比对的平台版本\n")

    verdict = {"PASS": "全部通过，可以进入发布流程。",
               "WARN": "有告警项，确认可接受后再发布。",
               "BLOCK": "存在不合格项或合规 BLOCK 命中，发布前必须回改。"}[report["verdict"]]
    print(f"结论：{verdict}")
    print(f"（不合格 {report['total_fail']} 处，告警 {report['total_warn']} 处，"
          f"合规 BLOCK {report['total_compliance_blocks']} 处）")


def show_specs() -> None:
    print("平台规格（与 references/platform-specs.md 同步维护）\n")
    header = f"{'平台':<8}{'标题':<18}{'正文':<20}{'话题':<12}{'图片':<10}比例"
    print(header)
    print("-" * 84)
    for key, spec in SPECS.items():
        def fmt(t):
            if not t:
                return "—"
            lo, hi, cap = t
            return f"{lo}–{hi}" + (f"（硬上限{cap}）" if cap else "")
        ratio = ""
        if spec.get("cover_ratio"):
            ratio = f"首图 {spec['cover_ratio'][0]}:1"
        elif spec.get("all_ratio"):
            ratio = f"全部 {spec['all_ratio'][0]}:1"
        print(f"{spec['name']:<8}{fmt(spec['title']):<18}{fmt(spec['body']):<20}"
              f"{fmt(spec['tags']):<12}{spec['images'][0]}–{spec['images'][1]:<7}{ratio}")
    print(f"\n重复度阈值：正文相似度 ≥{SIMILARITY_FAIL:.0%} 判不合格，"
          f"≥{SIMILARITY_WARN:.0%} 告警；标题完全相同直接不合格。")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="发布前统一预检门禁")
    parser.add_argument("article_dir", nargs="?", help="文章目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--show-specs", action="store_true", help="打印平台规格表")
    args = parser.parse_args()

    if args.show_specs:
        show_specs()
        return 0
    if not args.article_dir:
        parser.error("需要提供文章目录（或使用 --show-specs）")

    target = Path(args.article_dir)
    if not target.is_dir():
        print(f"目录不存在：{target}")
        return 2

    report = run(target)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        render(report)
    return 1 if report["verdict"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
