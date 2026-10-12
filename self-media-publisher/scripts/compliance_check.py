#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自媒体发布前合规预检。

扫描稿件（单个文件或整个目录），检查三类风险：

  1. block —— 广告法绝对化用语 / 医疗金融高危词，命中必须回改，否则限流或违规
  2. warn  —— 擦边表述，需人工判断
  3. 平台特定 —— 导流词、联系方式（小红书、微博等风控严格）

用法：
    python compliance_check.py <路径>            # 文件或目录
    python compliance_check.py <目录> --json     # 输出 JSON
    python compliance_check.py <目录> --quiet    # 只输出有问题的文件

退出码：有 block 级命中返回 1，否则返回 0（便于在流程里做门禁）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 规则库

# (规则 id, 级别, 匹配模式, 修改建议)
COMMON_RULES: list[tuple[str, str, str, str]] = [
    # --- block：绝对化 / 无法证实的最高级 ---
    ("absolute-superlative", "block",
     r"最(佳|好|优|大|小|高|低|强|弱|快|慢|新|旧|先进|专业|权威|受欢迎|值得|实惠|便宜|贵|多|少|火|热门|流行)",
     "改为「较／更／相对」，或补上可核实的比较对象与依据"),
    ("absolute-only", "block",
     r"(唯一|独家|仅此一家|绝无仅有|史无前例)",
     "改为「少见的／鲜有的」，或直接陈述事实"),
    ("absolute-top", "block",
     r"(国家级|世界级|全球领先|国际领先|行业第一|全国第一|第一品牌|销量冠军|排名第一|遥遥领先|世界第一|全球第一)",
     "删除或改为可核实的排名来源（如「XX 机构 2025 年报告中的第 N 位」）"),
    ("absolute-guarantee", "block",
     r"(100%|百分之百|百分百)(有效|管用|成功|安全|满意)?",
     "改为「在多数情况下」「按我们的样本」等限定表述"),
    ("absolute-perfect", "block",
     r"(顶级|极致|完美无缺|无可挑剔|绝对|彻底解决|包治|根治|永不)",
     "改为具体、可验证的效果描述"),
    # --- block：医疗 / 保健 / 金融高危 ---
    ("medical-claim", "block",
     r"(治疗|治愈|根治|药到病除|降血压|降血糖|抗癌|神效|疗效显著)",
     "非医疗资质内容不得出现疗效声称，删除或改为「有助于」并加免责说明"),
    ("finance-claim", "block",
     r"(稳赚|保本|零风险|无风险|包赚|必涨|稳赚不赔|日入过万|躺赚)",
     "金融收益承诺属违规，删除或改为「存在亏损可能」并加风险提示"),
    # --- warn：擦边 ---
    ("absolute-mild", "warn",
     r"(第一|首个|首创|领先|极致体验|爆款|全网最低)",
     "需人工判断：若有权威依据可保留并注明来源，否则改写"),
    ("exclusive-mild", "warn",
     r"(史上|空前|颠覆|碾压|秒杀一切)",
     "夸张表述，建议弱化"),
    # --- warn：绝对化承诺 / 效果 ---
    ("promise", "warn",
     r"(保证|必定|肯定能|一定能|绝对能)(有效|成功|通过|提升|赚钱)?",
     "改为概率性表述"),
]

PLATFORM_RULES: dict[str, list[tuple[str, str, str, str]]] = {
    "xiaohongshu": [
        ("xhs-drainage", "block",
         r"(微信号|vx|VX|weixin|微信|加微|私聊我|私信我|加我好友|QQ号|扣扣)",
         "小红书严禁站外导流，改为「主页」「评论区」等站内引导"),
        ("xhs-link", "block",
         r"(https?://|www\.|淘宝|淘口令|链接在评论)",
         "小红书不留外链，改为「主页有」「评论区置顶」"),
        ("xhs-phone", "block",
         r"1[3-9]\d{9}",
         "出现手机号，必须删除"),
        ("xhs-superlative-count", "warn",
         r"(全网|史上最|第一)",
         "小红书对夸张用词敏感，建议弱化"),
    ],
    "weibo": [
        ("weibo-phone", "block",
         r"1[3-9]\d{9}",
         "出现手机号，必须删除"),
        ("weibo-drainage", "warn",
         r"(微信号|加微|私聊)",
         "微博导流词易被限流，谨慎使用"),
    ],
    "wechat": [
        ("wechat-link", "warn",
         r"(https?://|www\.)",
         "公众号正文外部链接会被剥成纯文本，确认是否白名单域名"),
    ],
    "toutiao": [
        ("toutiao-link", "warn",
         r"(https?://|www\.)",
         "头条正文外链权重低，建议改为引导站内互动"),
    ],
    "zhihu": [
        ("zhihu-drainage", "warn",
         r"(微信号|加微|私聊|公众号|关注我)",
         "知乎对营销内容限流，建议弱化或改为价值输出"),
    ],
}

FILENAME_HINTS: dict[str, str] = {
    "wechat": "wechat", "公众号": "wechat", "gzh": "wechat", "mp": "wechat",
    "zhihu": "zhihu", "知乎": "zhihu",
    "toutiao": "toutiao", "头条": "toutiao",
    "xiaohongshu": "xiaohongshu", "xhs": "xiaohongshu", "小红书": "xiaohongshu",
    "weibo": "weibo", "微博": "weibo",
}

TEXT_SUFFIXES = {".md", ".txt", ".markdown"}

# ---------------------------------------------------------------- 逻辑


def detect_platform(path: Path) -> str:
    """从文件名推断平台，推断不出返回 all。"""
    name = path.stem.lower()
    for hint, platform in FILENAME_HINTS.items():
        if hint in name:
            return platform
    return "all"


def collect_rules(platform: str) -> list[tuple[str, str, str, str]]:
    rules = list(COMMON_RULES)
    if platform != "all":
        rules.extend(PLATFORM_RULES.get(platform, []))
    else:
        # 未识别平台时把所有平台规则都算上，宁可多提示
        for extra in PLATFORM_RULES.values():
            rules.extend(extra)
    return rules


def scan_text(text: str, rules: list[tuple[str, str, str, str]]) -> list[dict]:
    hits: list[dict] = []
    for rule_id, level, pattern, suggestion in rules:
        try:
            compiled = re.compile(pattern)
        except re.error:
            continue
        for m in compiled.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append({
                "rule": rule_id,
                "level": level,
                "match": m.group(0),
                "line": line_no,
                "suggestion": suggestion,
            })
    # 去重：同一行同一词只留一条
    seen: set[tuple[str, int, str]] = set()
    unique: list[dict] = []
    for h in hits:
        key = (h["rule"], h["line"], h["match"])
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return sorted(unique, key=lambda x: x["line"])


def gather_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(
            p for p in target.rglob("*")
            if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
        )
    return []


def check(target: Path) -> dict:
    files = gather_files(target)
    results: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            results.append({"file": str(f), "error": str(exc), "hits": []})
            continue
        platform = detect_platform(f)
        hits = scan_text(text, collect_rules(platform))
        results.append({
            "file": str(f),
            "platform": platform,
            "hits": hits,
            "blocks": sum(1 for h in hits if h["level"] == "block"),
            "warns": sum(1 for h in hits if h["level"] == "warn"),
        })
    total_block = sum(r.get("blocks", 0) for r in results)
    total_warn = sum(r.get("warns", 0) for r in results)
    return {
        "target": str(target),
        "files_scanned": len(files),
        "total_block": total_block,
        "total_warn": total_warn,
        "results": results,
    }


def render(report: dict, quiet: bool = False) -> None:
    if not report["files_scanned"]:
        print("未找到可扫描的文本文件（支持 .md / .txt）")
        return
    for item in report["results"]:
        if "error" in item:
            print(f"[读取失败] {item['file']}: {item['error']}")
            continue
        hits = item["hits"]
        if quiet and not hits:
            continue
        print(f"\n=== {item['file']}  (平台: {item['platform']}) ===")
        if not hits:
            print("  通过，无命中")
            continue
        for h in hits:
            mark = "[BLOCK]" if h["level"] == "block" else "[WARN ]"
            print(f"  {mark} L{h['line']:>4}  「{h['match']}」  ({h['rule']})")
            print(f"            → {h['suggestion']}")
    print(f"\n合计：{report['files_scanned']} 个文件，"
          f"BLOCK {report['total_block']} 处，WARN {report['total_warn']} 处")
    if report["total_block"]:
        print("存在 BLOCK 级命中，发布前必须回改。")
    else:
        print("无 BLOCK 级命中，可进入发布流程。")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="自媒体稿件合规预检")
    parser.add_argument("target", help="稿件文件或目录")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--quiet", action="store_true", help="只显示有命中的文件")
    args = parser.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"路径不存在：{target}")
        return 2

    report = check(target)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        render(report, quiet=args.quiet)
    return 1 if report["total_block"] else 0


if __name__ == "__main__":
    sys.exit(main())
