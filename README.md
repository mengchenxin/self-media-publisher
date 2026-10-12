# self-media-publisher

> 一个 WorkBuddy Skill：把**一个选题**变成**五个平台上的五篇不同文章**，并且真正发出去。

不是「帮你写文章」——写文章模型本来就会。这个 skill 解决的是模型默认做不好的三件事：

1. **平台硬规格** —— 各平台的字数上限、图片比例、话题数量、发布入口都不一样，凭印象写必错。
2. **真实的发布操作序列** —— 浏览器自动化发布有一堆反直觉的坑（`set viewport` 会重置页面、话题必须从联想框点选、SPA 输入不生效）。
3. **发布前的门禁** —— 广告法绝对化用语和导流词是中国平台限流的头号原因；平台之间内容雷同会互相压流量。

---

## 包含两个 skill

| 目录 | 作用 |
| --- | --- |
| [`self-media-publisher`](./self-media-publisher) | 主流程：选题 → 母稿 → 一稿多改 → 配图 → 预检 → 发布 → 数据回收 |
| [`agent-browser-login-setup`](./agent-browser-login-setup) | 浏览器持久登录态配置与实测踩坑清单，主流程发布环节的排障配套 |

两者相互独立，可单独安装。但只要用到「自动登录网页」的功能，第二个就一定会用上——因为 `agent-browser` 默认的登录态**不跨轮次保留**，这一点官方文档没有写。

---

## 支持的平台

| 平台 | 类型 | 标题字数 | 正文字数 | 封面 / 图片 |
| --- | --- | --- | --- | --- |
| 微信公众号 | 长文 | 16–24（硬上限 64） | 2000–4000 | 封面 2.35:1 |
| 知乎 | 长文 | 20–30 | 2000–6000 | 任意 |
| 今日头条 | 长文 | 15–25（硬上限 30） | 1000–3000 | 1:1 或 3:2 |
| 小红书 | 短图文 | ≤ 20 | 300–600（硬上限 1000） | 3:4 竖版 |
| 微博 | 短图文 | — | 100–300（硬上限 2000） | 1:1，最多 9 张 |

---

## 流水线

| 阶段 | 做什么 | 靠什么 |
| --- | --- | --- |
| 0 前置确认 | 平台清单、账号权限、输出目录、浏览器 profile | `references/platform-specs.md` |
| 1 选题调研 | 用户给选题则核查，没给则出 5 个候选 | WebSearch / WebFetch |
| 2 写作母稿 | 3000–4000 字，按信息块组织（唯一事实来源） | `assets/article-template.md` |
| 3 一稿多改 | 每平台重写成独立版本 | `references/rewrite-playbook.md` |
| 4 配图 | 文字卡片用 HTML 渲染截图，不用 AI 生图 | `scripts/render_card.py` |
| 5 预检 | 规格 + 合规 + 版本间重复度，一条命令三道门禁 | `scripts/preflight_check.py` |
| 6 发布 | 幂等检查 → 草稿 → 截图给用户确认 → 才点发布 | `references/publish-runbook.md` |
| 7 台账 | 记录各平台状态与链接 | `scripts/publish_log.py` |
| 8 数据回收 | 24h / 72h 回抓数据并算增幅 | `scripts/stats_log.py` |

**两条红线**：未获用户明确确认不点最终发布按钮；预检有 BLOCK 级命中不许发布。

---

## 工具清单

| 脚本 | 用途 |
| --- | --- |
| `scripts/preflight_check.py` | 统一预检门禁：平台规格 + 合规 + 重复度。退出码非 0 即拦截 |
| `scripts/compliance_check.py` | 广告法绝对化用语 / 平台导流词 / 手机号词库，被 preflight 复用 |
| `scripts/publish_log.py` | 发布台账，含 `check` 幂等门禁（避免重复群发） |
| `scripts/stats_log.py` | 数据回收台账，自动计算 24h → 72h 增幅 |
| `scripts/render_card.py` | 生成文字卡片 HTML（6 套配色主题），供浏览器截图 |
| `assets/card-template.html` | 卡片样式模板，可直接改视觉 |
| `assets/article-template.md` | 母稿结构模板 |

全部脚本只依赖 Python 标准库，不需要 pip 安装任何东西。

```
python scripts/preflight_check.py <文章目录>     # 预检
python scripts/preflight_check.py --show-specs   # 查看平台规格表
python scripts/render_card.py --list-themes      # 查看卡片主题
```

---

## 安装

把两个目录放进 WorkBuddy 的 skill 目录即可：

```bash
git clone https://github.com/<你的用户名>/self-media-publisher.git

# 用户级（所有项目可用）
cp -r self-media-publisher/self-media-publisher \
      self-media-publisher/agent-browser-login-setup \
      ~/.workbuddy/skills/

# 或项目级（仅当前仓库共享）
cp -r self-media-publisher/self-media-publisher \
      self-media-publisher/agent-browser-login-setup \
      <你的项目>/.workbuddy/skills/
```

## 依赖

- **Python 3.9+**（已在 3.13 实测）—— 仅脚本需要，全部标准库
- **agent-browser + Chrome** —— 仅「发布」和「卡片截图」环节需要；只做写作与预检可以不装

```bash
npm install -g agent-browser
agent-browser install        # 下载 Chrome，约 200MB
```

## 快速开始

1. 安装浏览器（见上），并确认 `node -e "console.log('ok')"` 能正常输出
2. **验证连通性**：带上 `--profile` 启动后 `agent-browser get url`，确认不是 `chrome-error://`
3. **只挑 1 个平台**登录并跑通全流程（推荐微博：门槛最低、字数最少）
4. 通过后再登录其余平台，每个平台登录成功后 `agent-browser state save auth-<平台>.json` 备份
5. 最后才铺多平台

第 3 步是在验证「登录态能跨 `close` 保留」——**这一步不通过，多平台铺开都是空谈**。

---

## 实测结论（这些坑不值得再踩一次）

全部在 Windows + agent-browser 1.x（Chrome 155）实测：

| 结论 | 说明 |
| --- | --- |
| **`agent-browser` 默认登录态不持久** | 默认 `--user-data-dir` 是 `%LOCALAPPDATA%\Temp\agent-browser-chrome-<随机UUID>`，进程退出即废。必须显式 `--profile <固定目录>` |
| **`--profile` 只在启动守护进程那次生效** | 守护进程运行中再传会被静默忽略并告警，换参数前必须 `close --all` |
| **系统代理会打断浏览器** | 有 `HTTP_PROXY` / `HTTPS_PROXY` 而代理不可用时，`open` 报 `ERR_NO_SUPPORTED_PROXIES`，页面根本打不开 |
| **`set viewport` 会把页面重置为 `about:blank`** | 截图前必须先 `set viewport` 再**重新 `open` 一次**，否则截到空白图。它返回 `✓ Done` 但不保证生效，需 `eval window.innerWidth` 自检 |
| **不能用 `eval "document.cookie"` 判断登录态** | 报 `Access is denied`，读不到。改用 `snapshot` 看是否出现账号信息 |
| **内容尺寸 == 视口尺寸时滚动条会互相挤压** | 把页脚挤出可视区，症状是「DOM 里有、截图里没有」。加 `overflow: hidden` 解决 |

---

## 已知限制

- **发布选择器未沉淀。** 新平台第一次发布建议先 dry-run（只填表不点发布，停在草稿 + 截图确认），再正式发。
- **部分平台的数据面板是 canvas 图表**，`snapshot` 读不到数值，需要截图人工读数。抓不到的指标应留空，不要填 0。
- **登录态持久化机制已验证**（profile 目录确实落盘），但「真实登录某平台 → `close` → 重开仍登录」的端到端验证需要真实账号，尚未完成。首次使用请按快速开始第 3 步自行确认。
- 平台会改版。字数与比例以 `references/platform-specs.md` 为准，若发布报错，以页面实际为准并回改文档。

---

## 许可证

[MIT](./LICENSE)
