# Decision Records

## DR-001: WSL Core + Windows Browser Runtime

状态：Accepted

项目代码、Python、SQLite、LLM API 和 Email 运行在 WSL；Windows 负责真实浏览器运行时。

原因：

- WSL 更适合 Python CLI-first 开发。
- Windows Edge 中已有真实登录态、Cookie、扩展和风控状态。
- WSL 可以调用 Windows executable。

## DR-002: Browser 是 Transport

状态：Accepted

Browser acquire 返回 rendered document，不直接返回最终 Article。

原因：

- Browser 负责认证、扩展、JavaScript 渲染和最终 DOM。
- Extraction 独立于 acquire，可以后续升级。
- RawDocument / snapshot / HTML 可以重复处理。

## DR-003: Agent 是 Compiler / Repairer

状态：Accepted

Agent 不作为每日 runtime crawler。Agent 用于首次理解 source、生成 recipe、修复 BROKEN source。

原因：

- 每日 LLM 浏览成本高且不稳定。
- Recipe + assertions 更适合可维护的 feed processor。

## DR-004: Persistent Profile First

状态：Rejected / Superseded

曾考虑使用 Playwright `--persistent --profile` 作为默认 authenticated runtime。实验显示它能启动和保存部分状态，但不满足核心需求：复用用户真实 Edge profile 的扩展、风控状态和 browser-bound sessions。

保留用途：可迁移认证的 source。

## DR-005: Attached Real Profile First

状态：Accepted

默认 authenticated/extension-dependent browser runtime 使用真实 Stable Edge `Profile 1` + Playwright Extension attach。

当前已验证命令：

```bash
cmd.exe /C "set PLAYWRIGHT_MCP_EXTENSION_TOKEN=<token>&& playwright-cli.cmd --s=edge-p1 attach --extension=msedge"
cmd.exe /C "playwright-cli.cmd --s=edge-p1 goto https://www.wsj.com"
cmd.exe /C "playwright-cli.cmd --s=edge-p1 snapshot"
```

要求：

- Edge `Profile 1` 中安装 Playwright Extension。
- Edge `Profile 1` 中登录需要的 source。
- Token 必须进入 Windows `playwright-cli.cmd` 进程环境。
- Runtime cleanup 默认 detach，不 close / kill 用户浏览器。

## DR-006: Token 注入方式

状态：Accepted

从 WSL 调 Windows `playwright-cli.cmd` 时，token 注入必须使用已验证形式：

```bash
cmd.exe /C "set PLAYWRIGHT_MCP_EXTENSION_TOKEN=<token>&& playwright-cli.cmd --s=edge-p1 attach --extension=msedge"
```

不要使用未验证的通用 env 注入假设。判断标准是 connect URL 中必须出现：

```text
&token=<token>
```

如果没有 `token=`，继续测试网站没有意义。

## DR-007: SQLite First

状态：Accepted

第一版使用 SQLite，不引入 PostgreSQL、Redis 或 vector database。

同步语义：

```text
last successful cursor / last_seen_id
  -> offline or blocked
  -> rerun after auth restored
  -> catch up from last known state
```

## DR-008: SMTP First

状态：Accepted

第一版使用 Python `smtplib` 发送 HTML email。Gmail API 等专用 adapter 后续再加。

## DR-009: No Profile Copy For Now

状态：Accepted

当前不复制 Edge User Data，不创建 Edge Dev 路线，不复制 `Default` 到 `Profile N`。

原因：

- 复制 profile 会引入 Local State、加密 Cookie、锁文件和 profile registry 问题。
- 当前 Stable Edge `Profile 1` 已能工作。
- 保持实验和 MVP 简单。
