#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多平台发布台账：记录每篇文章在各个平台的发布状态。

用途是让「全流程」可追溯 —— 哪篇发到哪、发没发成、链接在哪、为什么跳过。
不要用记忆代替台账：同一篇文章往往分几次才铺完所有平台。

用法：
    python publish_log.py init   --log publish-log.csv
    python publish_log.py check  --log publish-log.csv --article "远程办公三年"
                                 # 发布前先跑这条：标出已发过的平台，避免重复群发
    python publish_log.py add    --log publish-log.csv --article "远程办公三年" \\
                                 --platform 公众号 --status published --url https://...
    python publish_log.py update --log publish-log.csv --article "远程办公三年" \\
                                 --platform 小红书 --status published_no_image
    python publish_log.py list   --log publish-log.csv [--article X] [--status published]
    python publish_log.py summary --log publish-log.csv --article "远程办公三年"

状态取值（约定）：
    draft             已存草稿，未发布
    pending_review    已发出，需事后回查是否限流（小红书）
    published         已发布
    published_no_image 已发布但缺图（降级）
    failed:<原因>     发布失败
    blocked:<原因>    被权限/审核/登录拦住
    skipped:<原因>    主动跳过
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

FIELDS = ["日期", "文章ID", "标题", "平台", "状态", "链接", "稿件路径", "备注"]
DEFAULT_LOG = "publish-log.csv"
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


def article_id(title: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    slug = "".join(ch for ch in title if ch.isalnum())[:12]
    return f"{stamp}-{slug}" if slug else stamp


def cmd_init(args) -> int:
    log_path = Path(args.log)
    if log_path.exists() and not args.force:
        print(f"台账已存在：{log_path}（加 --force 覆盖重建）")
        return 0
    save(log_path, [])
    print(f"已创建台账：{log_path}")
    return 0


def cmd_add(args) -> int:
    log_path = Path(args.log)
    rows = load(log_path)
    aid = args.article_id or article_id(args.article)

    for row in rows:
        if row.get("文章ID") == aid and row.get("平台") == args.platform:
            print(f"该文章在该平台已有记录（{row.get('日期')}，状态 {row.get('状态')}）。"
                  f"如需变更请用 update。")
            return 0

    rows.append({
        "日期": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "文章ID": aid,
        "标题": args.article,
        "平台": args.platform,
        "状态": args.status,
        "链接": args.url or "",
        "稿件路径": args.file or "",
        "备注": args.note or "",
    })
    save(log_path, rows)
    print(f"已记录：{args.article} → {args.platform} [{args.status}]  (ID {aid})")
    return 0


def cmd_update(args) -> int:
    log_path = Path(args.log)
    rows = load(log_path)
    target = [r for r in rows
              if r.get("平台") == args.platform
              and (args.article_id and r.get("文章ID") == args.article_id
                   or args.article and r.get("标题") == args.article)]
    if not target:
        print("未找到匹配记录，请先 add。")
        return 1

    for row in target:
        old_status = row.get("状态", "")
        if args.status:
            row["状态"] = args.status
        if args.url:
            row["链接"] = args.url
        if args.file:
            row["稿件路径"] = args.file
        # 从失败/跳过改回成功时，自动清掉旧的失败原因，避免台账自相矛盾
        was_failure = old_status.split(":", 1)[0] in ("failed", "blocked", "skipped")
        now_success = args.status.startswith("published") if args.status else False
        if args.note:
            row["备注"] = args.note
        elif was_failure and now_success:
            row["备注"] = ""
        row["日期"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save(log_path, rows)
    print(f"已更新 {len(target)} 条：{args.platform} → {args.status or '(状态未变)'}")
    return 0


def cmd_list(args) -> int:
    rows = load(Path(args.log))
    if args.article:
        rows = [r for r in rows if r.get("标题") == args.article
                or r.get("文章ID") == args.article]
    if args.status:
        rows = [r for r in rows if r.get("状态", "").startswith(args.status)]
    if not rows:
        print("无记录。")
        return 0
    width = max(len(r.get("标题", "")) for r in rows) + 2
    for r in rows:
        print(f"{r.get('日期',''):<17} {r.get('标题',''):<{width}} "
              f"{r.get('平台',''):<5} {r.get('状态',''):<18} {r.get('链接','')}")
    print(f"\n共 {len(rows)} 条")
    return 0


def cmd_summary(args) -> int:
    rows = load(Path(args.log))
    if args.article:
        rows = [r for r in rows if r.get("标题") == args.article
                or r.get("文章ID") == args.article]
    if not rows:
        print("无记录。")
        return 0

    title = rows[0].get("标题", "")
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        groups.setdefault(r.get("平台", ""), r)

    done = sum(1 for r in rows if r.get("状态", "").startswith("published"))
    print(f"文章：{title}")
    print(f"已发布 {done}/{len(rows)} 个平台\n")
    print(f"{'平台':<6} {'状态':<18} 链接")
    print("-" * 60)
    ordered = sorted(groups.items(),
                     key=lambda kv: PLATFORM_ORDER.index(kv[0])
                     if kv[0] in PLATFORM_ORDER else 99)
    for platform, r in ordered:
        print(f"{platform:<6} {r.get('状态',''):<18} {r.get('链接','')}")
        if r.get("备注"):
            print(f"{'':<6} └ {r['备注']}")
    return 0


def cmd_check(args) -> int:
    """发布前幂等门禁：报告该文章哪些平台已经发过。

    重复发布的代价极高（公众号群发一天只有一次机会，重发等于浪费当天额度），
    所以每次开始发布流程前先跑一次本命令。
    """
    rows = load(Path(args.log))
    if args.article:
        rows = [r for r in rows if r.get("标题") == args.article
                or r.get("文章ID") == args.article]

    existing: dict[str, dict] = {}
    for r in rows:
        existing.setdefault(r.get("平台", ""), r)

    if not existing:
        print("台账中无该文章记录 —— 可以按计划发布所有平台。")
        return 0

    def key(platform: str) -> int:
        return PLATFORM_ORDER.index(platform) if platform in PLATFORM_ORDER else 99

    already = [(p, r) for p, r in existing.items() if r.get("状态", "").startswith("published")]
    others = [(p, r) for p, r in existing.items() if (p, r) not in already]

    print(f"文章：{args.article or '（全部）'}\n")
    for platform, r in sorted(already, key=lambda kv: key(kv[0])):
        print(f"  [已发布] {platform}  {r.get('状态')}  {r.get('链接','')}")
    for platform, r in sorted(others, key=lambda kv: key(kv[0])):
        print(f"  [未完成] {platform}  {r.get('状态')}")

    if already:
        names = "、".join(p for p, _ in already)
        print(f"\n⚠ 以下平台已发布过，默认应跳过：{names}")
        print("  仅当内容已改动或上次被限流时才重发 —— 那属于明确决定，不是默认行为。")
        return 1

    print("\n没有已发布的平台，可以按计划发布。")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="多平台发布台账")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="创建台账文件")
    p_init.add_argument("--log", default=DEFAULT_LOG)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    def add_common(p, need_platform=True):
        p.add_argument("--log", default=DEFAULT_LOG)
        p.add_argument("--article", help="文章标题")
        p.add_argument("--article-id", dest="article_id", help="文章 ID（默认自动生成）")
        if need_platform:
            p.add_argument("--platform", required=True, help="平台名")

    p_add = sub.add_parser("add", help="新增一条发布记录")
    add_common(p_add)
    p_add.add_argument("--status", required=True)
    p_add.add_argument("--url")
    p_add.add_argument("--file", help="该平台稿件路径")
    p_add.add_argument("--note")
    p_add.set_defaults(func=cmd_add)

    p_upd = sub.add_parser("update", help="更新状态/链接")
    add_common(p_upd)
    p_upd.add_argument("--status")
    p_upd.add_argument("--url")
    p_upd.add_argument("--file")
    p_upd.add_argument("--note")
    p_upd.set_defaults(func=cmd_update)

    p_list = sub.add_parser("list", help="列出记录")
    p_list.add_argument("--log", default=DEFAULT_LOG)
    p_list.add_argument("--article")
    p_list.add_argument("--status")
    p_list.set_defaults(func=cmd_list)

    p_sum = sub.add_parser("summary", help="按文章汇总各平台状态")
    p_sum.add_argument("--log", default=DEFAULT_LOG)
    p_sum.add_argument("--article")
    p_sum.set_defaults(func=cmd_summary)

    p_chk = sub.add_parser("check", help="发布前幂等门禁：已发布过的平台会被标出")
    p_chk.add_argument("--log", default=DEFAULT_LOG)
    p_chk.add_argument("--article")
    p_chk.set_defaults(func=cmd_check)

    args = parser.parse_args()
    if args.cmd in ("add", "update") and not args.article and not args.article_id:
        parser.error("--article 或 --article-id 至少提供一个")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
