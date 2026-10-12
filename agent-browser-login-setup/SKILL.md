---
name: agent-browser-login-setup
description: 配置 agent-browser 的持久登录态，使浏览器自动化能跨轮次保持已登录状态。当任务需要"用浏览器自动登录某网站并保持登录"、"登录态每次都要重登"、"agent-browser 打开页面报 ERR_NO_SUPPORTED_PROXIES"、"自动化发布/后台操作要求已登录"时使用。已在 Windows + agent-browser 1.x（Chrome 155）实测验证。
agent_created: true
---

# agent-browser 持久登录态配置

解决一个会让登录类浏览器自动化**静默失败**的坑：`agent-browser` 默认用临时 profile，登录态不跨轮保留。

## 三条铁律（全部实测验证）

### 铁律 1：默认不持久，必须显式指定 profile

不带参数时，Chromium 的 `--user-data-dir` 是：

```
%LOCALAPPDATA%\Temp\agent-browser-chrome-<随机UUID>
```

进程退出即废弃 → **每次运行都要重新登录**。临时验证时不会发现（同一守护进程内登录态是保留的），一旦换轮次就全部失效。

验证方法（Windows）：

```bash
agent-browser open https://example.com
# 另开 PowerShell：
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Select-Object -ExpandProperty CommandLine | Select-String user-data-dir
```

看到带 UUID 的 Temp 路径 = 不持久。

**修正**：用 `--profile <固定目录>` 建持久 profile：

```bash
agent-browser --profile "$HOME/.agent-browser/profiles/<项目名>" open https://example.com
```

`--profile Default` 则是复用本机 Chrome 的默认 profile（可直接继承日常登录态），但**必须先完全退出 Chrome**，否则用户目录被占用会冲突。

### 铁律 2：启动参数只在启动守护进程那次生效

`--profile` / `--args` / `--proxy` 都是守护进程启动参数。守护进程已在运行时再传会被**静默忽略**，只打印一行告警：

```
⚠ --profile ignored: daemon already running. Use 'agent-browser close' first to restart with new options.
```

**换参数前必须先 `agent-browser close --all`。** 否则你以为换了 profile，其实还在用旧的。

### 铁律 3：系统代理会打断浏览器

若环境有 `HTTP_PROXY` / `HTTPS_PROXY`（常见于科学上网或企业代理），Chromium 会读取它。代理不可用时 `open` 直接失败：

```
✗ Navigation failed: net::ERR_NO_SUPPORTED_PROXIES
```

**判断**：`agent-browser get url` 若返回 `chrome-error://chromewebdata/`，就是网络层问题，**不要继续往页面填表**。

**修正**：启动时加 `--args "--no-proxy-server"` 直连；或确认代理端口确实在监听，去掉该参数。

## 标准配置流程

```bash
# 1. 安装（约 200MB，Chromium 落到 ~/.agent-browser/browsers/）
npm install -g agent-browser && agent-browser install

# 2. 确认 Node 真的能执行代码（agent-browser 内部要 spawn Node）
node -e "console.log('ok')"     # 必须打印 ok

# 3. 关掉旧守护进程，用固定 profile 启动
agent-browser close --all
agent-browser --args "--no-proxy-server" \
              --profile "$HOME/.agent-browser/profiles/myproj" \
              open https://目标站/后台

# 4. 验证连通性（关键，别跳过）
agent-browser get url            # 不能是 chrome-error://chromewebdata/

# 5. 人工登录一次：把窗口交给用户扫码/输密码，然后确认
agent-browser snapshot | grep -i "登录\|扫码"   # 有命中就是还没登录
# 登录成功后：
agent-browser snapshot           # 应出现账号昵称/头像

# 6. 立刻备份登录态，profile 损坏时可恢复
agent-browser state save ./auth.json
```

## 验证持久化是否成功（必做一次）

这是整套配置的**唯一验收标准**，不要跳过：

```bash
agent-browser close                                  # 关掉守护进程
agent-browser --profile "<同一个目录>" open <目标站>
agent-browser snapshot                               # 仍显示账号信息 = 成功
```

省事的话用 `--session-name <名字>` 代替 `--profile`，它自动存取 cookies + localStorage，更轻量：

```bash
agent-browser --session-name myproj open https://目标站
```

## 登录态载体选择

| 机制 | 适用场景 | 注意 |
| --- | --- | --- |
| `--profile <目录>` | 长期使用，最稳 | 首次需人工登录一次 |
| `--profile Default` | 复用日常 Chrome 登录态 | 必须先退出 Chrome |
| `--session-name <名>` | 轻量，只要 cookies + localStorage | 不含扩展、证书等 |
| `--state <json>` | 备份/迁移登录态 | `state save/load/list/clear` |
| `--auto-connect` | 已有 Chrome 在跑，直接接管 | 不新开进程 |
| `agent-browser auth save/login` | 无扫码验证的站点，存账号密码自动登录 | 凭据落盘，注意安全 |

## 反模式（会浪费大量时间）

| 反模式 | 后果 |
| --- | --- |
| 不带 `--profile` 就指望登录态保留 | 每轮重登，且失败方式隐蔽 |
| 在守护进程运行时改 `--profile` | 参数被忽略，行为与预期不符 |
| 用 `eval "document.cookie"` 判断登录态 | 报 `Access is denied for this document`，读不到。**改用 `snapshot`** |
| 页面报 `chrome-error://` 还继续填表 | 在错误页上操作，全部无效 |
| 任务中途 `close` | 会话结束，后续步骤丢失登录态。整轮只在最后 `close` 一次 |

## 附：截图与视口的实测陷阱

做「渲染 HTML → 截图」这类任务时（例如生成社交媒体首图），这两条会直接决定成败：

### 陷阱 1：`set viewport` 会把当前页面重置为 about:blank

| 试过的做法 | 结果 |
| --- | --- |
| **先 open → set viewport → 再 open → screenshot** | ✅ 视口生效且页面完整 |
| 先 set viewport → 再 open | ❌ 视口仍是默认值 |
| open → set viewport → 直接 screenshot | ❌ 得到纯空白图 |
| 只加启动参数 `--window-size=1080,1440` | ❌ 视口完全不变 |

正确顺序：

```bash
agent-browser close --all
agent-browser --args "--no-proxy-server" --profile <p> open "file:///<页面的绝对路径>"
agent-browser set viewport 1080 1440
agent-browser open "file:///<页面的绝对路径>"     # ← 必须再打开一次
agent-browser wait 700
agent-browser screenshot <输出路径>
agent-browser set viewport 1440 900              # 截完还原
```

**验证方法**：截图前先 `agent-browser eval "window.innerWidth+'x'+window.innerHeight"`
确认视口真的生效了，再截。不要凭 `✓ Done` 就认为设成功 —— 它确实返回成功，但视口可能没变。

### 陷阱 2：截图前注意滚动条

页面内容与视口尺寸相等时，Chromium 会同时出现垂直和水平滚动条，两者互相挤压尺寸，
把页面底部内容挤出可视区（症状是「页脚在 DOM 里存在但截图里看不到」）。
在被截图的 HTML 上加 `html, body { overflow: hidden; }` 即可。

**诊断方法**：不要靠肉眼猜，直接量：

```bash
agent-browser eval "(()=>{const e=document.querySelector('.footer');const b=e.getBoundingClientRect();return JSON.stringify({viewport:window.innerWidth+'x'+window.innerHeight,docH:document.documentElement.scrollHeight,el:[Math.round(b.top),Math.round(b.bottom)]})})()"
```

DOM 里有、截图里没有 —— 那是可视区问题，不是渲染问题。

## 已知的 skill 文档缺口

`agent-browser` 官方 SKILL.md 只列了 7 个基础命令（open/wait/snapshot/screenshot/click/type/close），**未提及** `--profile`、持久化限制、代理问题。实际能力远不止于此，`agent-browser --help` 还有：

`eval` / `cookies` / `storage` / `tab` / `batch` / `record` / `console` / `errors` /
`pushstate` / `vitals` / `state` / `auth`（Auth Vault）/ `diff` / `network` / `dashboard`。

遇到该 skill 文档没写的能力，先跑 `agent-browser --help` 和 `agent-browser skills get core --full`。
