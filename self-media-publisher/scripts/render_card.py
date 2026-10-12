#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成小红书首图文字卡片（3:4，1080×1440）。

为什么不用 AI 生图：
    ImageGen 渲染中文长文本不可靠 —— 会糊字、缺笔画、写错字。
    而小红书首图恰恰需要精确、可复现的大字排版。所以改用 HTML 渲染 + 浏览器截图：
    字体、字号、换行完全可控，改一个词重跑一次即可，不消耗生图额度。

产出的是 HTML，不是 PNG。截图由浏览器完成（见 references/publish-runbook.md 第七节）。
注意截图顺序不能乱 —— `set viewport` 会重置页面，必须先设视口再重新打开一次：

    agent-browser set viewport 1080 1440
    agent-browser open file:///<卡片 html 的绝对路径>   # 设完视口必须再打开一次
    agent-browser screenshot <输出目录>/images/xhs-1.png

用法：
    python render_card.py --title "居家办公3年|我以为很爽结果效率崩了" \
                          --kicker "远程办公 / 效率" --footer "@你的账号"
    python render_card.py --title "..." --theme coral --out images/xhs-1.html
    python render_card.py --list-themes

标题里的 `|` 表示强制换行 —— 首图换行位置对可读性影响很大，值得手工控制。
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

TPL_PATH = Path(__file__).resolve().parent.parent / "assets" / "card-template.html"

# 主题配色：小红书信息流里底图对比越强越容易被点开
THEMES: dict[str, dict[str, str]] = {
    "ink":   {"bg": "#111111", "fg": "#FFFFFF", "accent": "#FFD028", "label": "黑底黄（最醒目）"},
    "paper": {"bg": "#F7F4ED", "fg": "#1A1A1A", "accent": "#E4572E", "label": "米白底橘（耐看）"},
    "coral": {"bg": "#FF5A5F", "fg": "#FFFFFF", "accent": "#FFE066", "label": "珊瑚红（强情绪）"},
    "ocean": {"bg": "#0B3C5D", "fg": "#FFFFFF", "accent": "#7FD1B9", "label": "深海蓝（专业感）"},
    "grape": {"bg": "#4C3BCF", "fg": "#FFFFFF", "accent": "#FFD028", "label": "紫罗兰（年轻）"},
    "mint":  {"bg": "#E8F5E9", "fg": "#14301C", "accent": "#2E7D32", "label": "薄荷绿（清爽）"},
}


def auto_size(title: str) -> int:
    """按字数与行数估算字号 —— 首图字数越少字号越大，视觉冲击越强。"""
    lines = title.count("|") + 1
    plain = title.replace("|", "").replace(" ", "")
    n = len(plain)
    if n <= 8:
        size = 132
    elif n <= 12:
        size = 112
    elif n <= 16:
        size = 96
    elif n <= 20:
        size = 84
    elif n <= 28:
        size = 72
    else:
        size = 64
    if lines >= 3:
        size = int(size * 0.82)
    elif lines == 2 and n <= 10:
        size = int(size * 0.92)
    return size


def build(title: str, kicker: str, footer: str, theme: str, size: int | None) -> str:
    if not TPL_PATH.exists():
        raise FileNotFoundError(f"缺少模板文件：{TPL_PATH}")
    palette = THEMES[theme]

    rendered_title = "<br>".join(
        html.escape(part.strip()) for part in title.split("|")
    )
    final_size = size or auto_size(title)

    text = TPL_PATH.read_text(encoding="utf-8")
    for key, value in {
        "{{BG}}": palette["bg"],
        "{{FG}}": palette["fg"],
        "{{ACCENT}}": palette["accent"],
        "{{SIZE}}": str(final_size),
        "{{KICKER}}": html.escape(kicker or "&nbsp;"),
        "{{TITLE}}": rendered_title,
        "{{FOOTER}}": html.escape(footer or "&nbsp;"),
    }.items():
        text = text.replace(key, value)
    return text


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="生成小红书首图文字卡片（HTML）")
    parser.add_argument("--title", help="卡片主标题，用 | 控制换行")
    parser.add_argument("--kicker", default="", help="顶部小标签（分类 / 序号）")
    parser.add_argument("--footer", default="", help="底部署名或引导语")
    parser.add_argument("--theme", default="ink", choices=sorted(THEMES),
                        help="配色主题，默认 ink")
    parser.add_argument("--size", type=int, help="强制字号，默认按字数自动计算")
    parser.add_argument("--out", help="输出 HTML 路径，默认 ./xhs-card.html")
    parser.add_argument("--list-themes", action="store_true", help="列出可选主题")
    args = parser.parse_args()

    if args.list_themes:
        for name, spec in THEMES.items():
            print(f"  {name:<8}{spec['label']:<20}{spec['bg']} / {spec['accent']}")
        return 0

    if not args.title:
        parser.error("需要 --title（或使用 --list-themes）")

    out = Path(args.out) if args.out else Path("xhs-card.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(args.title, args.kicker, args.footer, args.theme, args.size),
                   encoding="utf-8")

    size = args.size or auto_size(args.title)
    print(f"已生成卡片：{out.resolve()}")
    print(f"  主题 {args.theme}，字号 {size}px，行数 {args.title.count('|') + 1}")
    print()
    print("下一步（用浏览器截图，不要用 AI 生图）：")
    print(f"  agent-browser close --all")
    print(f"  agent-browser --args \"--no-proxy-server\" --profile <profile> open file:///{out.resolve().as_posix()}")
    print("  agent-browser set viewport 1080 1440")
    print(f"  agent-browser open file:///{out.resolve().as_posix()}   # 必须再打开一次")
    print("  agent-browser wait 700")
    print("  agent-browser screenshot <输出目录>/images/xhs-1.png")
    print("  agent-browser set viewport 1440 900    # 截完还原，否则影响后续页面")
    print()
    print("为什么 set viewport 之后要再 open 一次：")
    print("  set viewport 会把当前页面重置为 about:blank。若直接截图只会得到一张空白图。")
    print("  只设窗口尺寸（--window-size）或只调换顺序都不生效，这是实测结论。")
    print()
    print("截完务必用 Read 工具看一眼图 —— 检查是否溢出、断行是否合理。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
