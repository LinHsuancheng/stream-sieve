# Project: Personal Information Agent

## 当前定位

本项目是一个跨平台、CLI-first、Agent-friendly 的个人信息流系统。核心目标是把用户自己选择的信息源转成可增量同步、可抽取、可被 LLM 过滤和摘要的 normalized feed。

当前项目最重要的结论是：**Browser runtime 必须优先支持 attached real browser profile**。很多 source 的可访问性来自用户真实浏览器里的 Cookie、登录态、风控状态和扩展，而不是 Playwright managed profile 或简单 storage state。

## 当前报告架构

报告已经从简单的 Markdown 摘要升级为结构化 newsletter：

```text
Article
  -> field-specific scoring
  -> field-specific analysis
  -> digest JSON
  -> fixed HTML/CSS renderer
  -> SMTP or filesystem delivery
```

LLM 只负责筛选和生成 JSON 内容，不负责 HTML、CSS、标题链接、来源、日期、分数或阅读时间的展示。HTML 模板位于 `stream_sieve/render/html.py`，是固定的阅读型 publication layout；后续修改报告视觉时必须先得到明确指示，不要因为参考了其他主题而自动替换模板。

当前 field：

```text
ai_news, tech, business, economics, politics, society, cognition
```

每个 field 有自己的 source、时间范围、评分 profile 和最多展示数量。`ai_news` 与 `tech` 分开，避免 AI 新闻占满一般技术栏目。

快速调试配置：

```bash
./run configs/runs/debug-wsj-zhihu.yaml
```

该配置只使用 `wsj-home` 和 `zhihu-home`，对应的临时 source registry 是 `sourcepool.debug.yaml`。

## 当前已验证链路

```text
WSL Python / shell
  -> Windows cmd.exe
  -> Windows playwright-cli.cmd
  -> Playwright Extension token attach
  -> Stable Edge Profile 1
  -> WSJ / Zhihu rendered page
  -> snapshot returned to WSL
```

已验证：

- WSL 可以调用 Windows `cmd.exe`。
- Windows 已安装 `@playwright/cli`。
- `PLAYWRIGHT_MCP_EXTENSION_TOKEN` 用正确的 `cmd.exe /C "set TOKEN&& playwright-cli..."` 形式注入后，connect URL 包含 `token=`。
- Stable Edge `Profile 1` 可被 extension attach。
- WSJ 首页、WSJ 文章页、知乎首页 rendered snapshot 可读。
- Zhihu snapshot 显示已登录主页内容。
- WSJ 文章页可读标题、作者、时间、正文开头和 paywall/subscription 区域。

## Browser Strategy

```text
HTTP accessible
  -> HTTP acquire

Public JavaScript page
  -> managed / ephemeral Playwright

Authenticated page
  -> attached real Edge profile when real browser identity matters
  -> persistent Playwright profile only when auth is migratable

Authenticated + extension-dependent page
  -> attached Stable Edge Profile 1 + Playwright Extension token
```

当前主线：

```text
attached Stable Edge Profile 1
```

不是当前主线：

```text
Playwright --profile persistent profile
Edge Dev
clone User Data
copy profile folders
CDP
```

这些可以保留为备选实验，但不进入默认路线。

## Runtime 边界

浏览器是 transport，不是 Agent。

```text
Browser
  -> login/session/extensions/rendered DOM
  -> RawDocument or snapshot/html
  -> Extractor
  -> Article
```

Agent 的位置：

```text
first-time onboarding / recipe generation / broken source repair
```

日常运行应尽量是 deterministic recipe，而不是每天让 LLM 自己浏览网页。

## Secrets

绝不提交：

- `PLAYWRIGHT_MCP_EXTENSION_TOKEN`
- Cookies
- browser profiles
- storageState
- SMTP password
- LLM API key
- SQLite runtime DB

推荐本机路径：

```text
C:\Users\33301\.stream-sieve\secrets\playwright-extension-token
~/.stream-sieve/secrets/playwright-extension-token
```

当前脚本中出现的 token 仅用于本地实验，后续需要 regenerate。

## Source Health

Source 必须显式记录失败状态，不能 silent failure。

```text
HEALTHY
DEGRADED
AUTH_REQUIRED
BLOCKED_BY_VERIFICATION
BROKEN
DISABLED
```

规则：

- 浏览器不可用 -> `DEGRADED`
- extension attach 需要 Allow -> `AUTH_REQUIRED`
- 网站验证页 / 401 robot check -> `BLOCKED_BY_VERIFICATION`
- selector/assertion 失败 -> `BROKEN`
- 用户禁用 -> `DISABLED`

同步保证依赖 SQLite 增量状态，不依赖浏览器或 daemon 永久在线。
