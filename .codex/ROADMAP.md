# Roadmap

## Phase 0: Browser Transport Validation

状态：Completed

已完成：

- WSL Python / shell 可调用 Windows `cmd.exe`。
- Windows `playwright-cli.cmd` 可用。
- Stable Edge `Profile 1` + Playwright Extension token attach 可用。
- WSJ rendered snapshot 可读。
- WSJ article snapshot 可读到标题、作者、时间、正文开头和订阅区域。
- Zhihu rendered snapshot 可读，并显示已登录首页内容。
- 一键 smoke 脚本：`scripts/one_click_wsj_attached.sh`。
- 配置化 smoke 脚本：`scripts/check_browser_config.py`。

核心验收命令：

```bash
./scripts/one_click_wsj_attached.sh
python3 scripts/check_browser_config.py --config configs/browser_check.example.yaml --skip-launch
```

## Phase 1: Browser Backend MVP

目标：把已验证脚本沉淀为 Python backend。

实现：

- `WindowsEdgeExtensionBackend`
- `owns_browser = False`
- `attach()`
- `goto(url)`
- `snapshot()`
- `text()`
- `html()`
- `detach()`
- token 从 secret file 读取
- 输出解码容错：`encoding="utf-8", errors="replace"`

验收：

- `stream-sieve browser inspect --source zhihu` 能无 Allow 读取 snapshot。
- connect URL 中包含 `token=`。
- attach 到错 profile 时能失败并提示。

## Phase 2: Core Data Models

实现：

- `ItemRef`
- `RawDocument`
- `Article`
- `SourceDefinition`
- `SourceState`

验收：

- dataclass / schema 明确。
- content hash 稳定。
- Source health 支持 `AUTH_REQUIRED` 和 `BLOCKED_BY_VERIFICATION`。

## Phase 3: RSS Discovery

实现：

```text
RSS / Atom -> feedparser -> ItemRef[] -> SQLite state
```

要求：

- ETag / Last-Modified。
- 304 Not Modified。
- external_id / canonical URL 初步 dedup。

## Phase 4: HTTP Acquire + Extraction

实现：

```text
URL -> httpx -> RawDocument -> Trafilatura -> Article
```

CLI：

```bash
stream-sieve extract <url>
```

## Phase 5: Browser Acquire

实现：

```text
ItemRef URL
  -> WindowsEdgeExtensionBackend.goto(url)
  -> snapshot/html/text
  -> RawDocument
  -> extractor
```

要求：

- 对 WSJ / Zhihu 添加 assertions。
- 遇到 sign-in / subscribe / verification 页面时标记 health，不推进 cursor。

## Phase 6: Recipe System

YAML 支持：

```yaml
browser:
  mode: attached
  backend: edge_extension
  session: edge-p1
  browser: msedge

discovery:
  type: rss

acquire:
  type: browser

extract:
  type: trafilatura

assertions:
  required_text_absent:
    - 访问暂时受限
  min_content_chars: 500
```

## Phase 7: Incremental Sync

实现：

```text
discover N
  -> filter seen
  -> acquire new only
  -> extract
  -> content hash dedup
  -> persist Article
```

## Phase 8: LLM Relevance

输入：

```text
Article[] + interests.md
```

输出：

```json
{"relevance": 8.0, "importance": 7.0, "novelty": 6.5, "reason": "..."}
```

## Phase 9: Digest + Email

实现：

```text
candidates -> clustering -> synthesis -> markdown/html -> SMTP
```
