#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多平台数据回收台账。

发布不是终点 —— 这篇内容在五个平台各自跑成什么样，得在 24h 和 72h 各抓一次才知道。
本脚本只负责记录与对比，抓取动作按 `references/publish-runbook.md` 第六节用浏览器完成。

为什么单独一个台账：
    发布台账一行 = 一个平台的最终状态，是一张快照。
    数据台账一行 = 某个平台在某个时点的一组指标，是时间序列（24h / 72h 各一行）。
    塞进同一张表会让列爆炸且无法对比，所以分开。

用法：
    python stats_log.py init   --log stats-log.csv
    python stats_log.py add    --log stats-log.csv --article "远程办公三年" \\
                               --platform 公众号 --age 24h --reads 860 --likes 34
    python stats_log.py list   --log stats-log.csv --article "远程办公三年"
    python stats_log.py report --log stats-log.csv --article "远程办公三年"

只填抓得到的指标，抓不到的留空（各平台暴露的指标不一样，不要填 0 冒充）。
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

FIELDS = ["抓取日期", "文章ID", "标题", "平台", "数据时点",
          "曝光", "阅读", "点赞", "评论", "转发", "收藏", "涨粉", "备注"]

METRICS = ["曝光", "阅读", "点赞", "评论", "转发", "收藏", "涨粉"]

DEFAULT_LOG = "stats-log.csv"
PLATFORM_ORDER = ["公众号", "知乎", "头条", "小红书", "微博"]


def load(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def save(log_path: Path, rows: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def to_int(value) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(str(value).replace(",", "").replace("+", "").strip())
    except ValueError:
        return None


def cmd_init(args) -> int:
    log_path = Path(args.log)
    if log_path.exists() and not args.force:
        print(f"数据台账已存在：{log_path}（加 --force 覆盖重建）")
        return 0
    save(log_path, [])
    print(f"已创建数据台账：{log_path}")
    return 0


def cmd_add(args) -> int:
    log_path = Path(args.log)
    rows = load(log_path)

    key = (args.article_id, args.platform, args.age)
    for row in rows:
        if (row.get("文章ID"), row.get("平台"), row.get("数据时点")) == key:
            print(f"该文章在 {args.platform} 的 {args.age} 时点已有记录，"
                  f"如需覆盖请先删除该行。")
            return 0

    row = {
        "抓取日期": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "文章ID": args.article_id,
        "标题": args.article,
        "平台": args.platform,
        "数据时点": args.age,
        "备注": args.note or "",
    }
    for metric in METRICS:
        attr = {"曝光": "impressions", "阅读": "reads", "点赞": "likes",
                "评论": "comments", "转发": "shares", "收藏": "favorites",
                "涨粉": "followers"}[metric]
        value = getattr(args, attr, None)
        row[metric] = "" if value is None else value

    filled = [f"{m}={row[m]}" for m in METRICS if row[m] != ""]
    if not filled:
        print("没有提供任何指标，请至少给一个（如 --reads）。")
        return 1

    rows.append(row)
    save(log_path, rows)
    print(f"已记录：{args.article} → {args.platform} [{args.age}]  " + " ".join(filled))
    return 0


def ordered_platforms(platforms) -> list[str]:
    return sorted(platforms,
                  key=lambda p: PLATFORM_ORDER.index(p) if p in PLATFORM_ORDER else 99)


def cmd_list(args) -> int:
    rows = load(Path(args.log))
    if args.article:
        rows = [r for r in rows if r.get("标题") == args.article
                or r.get("文章ID") == args.article]
    if not rows:
        print("无记录。")
        return 0
    header = f"{'平台':<6} {'时点':<5} " + " ".join(f"{m:>6}" for m in METRICS)
    print(header)
    print("-" * len(header))
    for r in rows:
        cells = " ".join(f"{r.get(m, '') or '-':>6}" for m in METRICS)
        print(f"{r.get('平台',''):<6} {r.get('数据时点',''):<5} {cells}")
    print(f"\n共 {len(rows)} 条")
    return 0


def cmd_report(args) -> int:
    rows = load(Path(args.log))
    if args.article:
        rows = [r for r in rows if r.get("标题") == args.article
                or r.get("文章ID") == args.article]
    if not rows:
        print("无记录。")
        return 0

    title = rows[0].get("标题", "")
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for r in rows:
        groups.setdefault(r.get("平台", ""), []).append(r)

    print(f"文章：{title}\n")
    header = f"{'平台':<6} {'时点':<5} " + " ".join(f"{m:>6}" for m in METRICS)
    print(header)
    print("-" * (len(header) + 2))

    for platform in ordered_platforms(groups.keys()):
        series = groups[platform]
        for r in series:
            cells = " ".join(f"{r.get(m, '') or '-':>6}" for m in METRICS)
            print(f"{platform:<6} {r.get('数据时点',''):<5} {cells}")

        if len(series) >= 2:
            first, last = series[0], series[-1]
            f_reads, l_reads = to_int(first.get("阅读")), to_int(last.get("阅读"))
            if f_reads is not None and l_reads is not None:
                if f_reads > 0:
                    pct = (l_reads - f_reads) / f_reads * 100
                    print(f"{'':<6} └ 阅读 {f_reads} → {l_reads}（{pct:+.0f}%）"
                          f"，{first.get('数据时点')} → {last.get('数据时点')}")
                else:
                    print(f"{'':<6} └ 阅读 {f_reads} → {l_reads}")
        print()

    print("提示：24h → 72h 若几乎没涨，说明平台已停止推荐，可据此判断是否要换标题重发。")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="多平台数据回收台账")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="创建数据台账文件")
    p_init.add_argument("--log", default=DEFAULT_LOG)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="新增一次数据抓取记录")
    p_add.add_argument("--log", default=DEFAULT_LOG)
    p_add.add_argument("--article", required=True, help="文章标题")
    p_add.add_argument("--article-id", dest="article_id", help="文章 ID（默认用标题）")
    p_add.add_argument("--platform", required=True, help="平台名")
    p_add.add_argument("--age", required=True, help="数据时点，如 24h / 72h")
    p_add.add_argument("--impressions", type=int, help="曝光量")
    p_add.add_argument("--reads", type=int, help="阅读量")
    p_add.add_argument("--likes", type=int, help="点赞")
    p_add.add_argument("--comments", type=int, help="评论")
    p_add.add_argument("--shares", type=int, help="转发")
    p_add.add_argument("--favorites", type=int, help="收藏")
    p_add.add_argument("--followers", type=int, help="涨粉")
    p_add.add_argument("--note")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="列出数据记录")
    p_list.add_argument("--log", default=DEFAULT_LOG)
    p_list.add_argument("--article")
    p_list.set_defaults(func=cmd_list)

    p_rep = sub.add_parser("report", help="按平台对比各时点数据")
    p_rep.add_argument("--log", default=DEFAULT_LOG)
    p_rep.add_argument("--article")
    p_rep.set_defaults(func=cmd_report)

    args = parser.parse_args()
    if args.cmd == "add" and not args.article_id:
        args.article_id = args.article
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
