# Action Report

Date: 2026-08-12

## Executive Summary

The high-risk browser transport path is viable.

Validated path:

```text
WSL
  -> cmd.exe
  -> playwright-cli.cmd
  -> PLAYWRIGHT_MCP_EXTENSION_TOKEN
  -> Playwright Extension
  -> Stable Edge Profile 1
  -> rendered WSJ / Zhihu pages
  -> snapshot returned to WSL
```

The project should now proceed with an attached-real-browser backend as the first browser backend.

## Verified Commands

Attach with token:

```bash
cmd.exe /C "set PLAYWRIGHT_MCP_EXTENSION_TOKEN=<token>&& playwright-cli.cmd --s=edge-p1 attach --extension=msedge"
```

Navigate:

```bash
cmd.exe /C "playwright-cli.cmd --s=edge-p1 goto https://www.wsj.com"
```

Snapshot:

```bash
cmd.exe /C "playwright-cli.cmd --s=edge-p1 snapshot"
```

One-click WSJ smoke test:

```bash
./scripts/one_click_wsj_attached.sh
```

Config-based Zhihu smoke test:

```bash
python3 scripts/check_browser_config.py --config configs/browser_check.example.yaml --skip-launch
```

## What Worked

### Token attach

A direct WSL command works:

```bash
cmd.exe /C "set PLAYWRIGHT_MCP_EXTENSION_TOKEN=<token>&& playwright-cli.cmd --s=edge-p1 attach --extension=msedge"
```

Attach output includes:

```text
&token=<token>
Session `edge-p1` created, attached to `msedge`.
```

No manual Allow prompt is required when the token reaches the Windows Playwright process.

### WSJ

WSJ home:

- Page title: `The Wall Street Journal - Breaking News, Business, Financial & Economic News, World News and Video`
- Snapshot contains homepage story cards and links.

WSJ article:

- Page title: `Why Wall Street and Nvidia Are Building an Exotic Money Pipeline for the AI Boom - WSJ`
- Snapshot contains title, subtitle, authors, publish time, first paragraphs, and subscription/paywall area.

### Zhihu

Zhihu home:

- Page title: `(1 条消息) 首页 - 知乎`
- Snapshot contains logged-in navigation, user avatar, feed items, question links, answer snippets, vote counts, save/like buttons.

This validates extension-dependent authenticated browsing enough for MVP browser acquire experiments.

## What Failed / Lessons

### Playwright persistent profile is not the default path

`playwright-cli open --persistent --profile=...` can launch a managed profile, but it does not naturally provide the exact daily browser identity/extensions needed by our target sources.

Status: fallback only.

### Edge Dev is not needed

Edge Dev introduced extra profile/channel confusion and did not improve the core path.

Status: out of default route.

### Copying User Data is not needed

Copying Edge `User Data` introduces Local State, encrypted cookies, locks and profile registry risks.

Status: do not use for MVP.

### Python subprocess launch of Edge via `cmd start` is unreliable

Manual shell command can start Edge, but Python `subprocess.run(["cmd.exe", "/C", "start ..."])` returned access denied in this environment.

Workaround: do not make browser launch a Phase 0 gate. Assume user or wrapper ensures Edge Profile 1 is running. Later use PowerShell `Start-Process` if launch is required.

### Text output can hit encoding issues

`--content text` previously hit a `UnicodeDecodeError`. Browser backend must use:

```python
encoding="utf-8", errors="replace"
```

## Current Recommended Runtime

```text
User keeps Stable Edge Profile 1 available
  -> Playwright Extension installed
  -> source logins/extensions configured
  -> token stored outside repo
  -> stream-sieve attaches with token
  -> navigate/read snapshot/html
  -> detach only
```

Normal run must not close or kill the external browser.

## Next Engineering Step

Implement Python backend equivalent to the working shell command:

```python
class WindowsEdgeExtensionBackend:
    owns_browser = False
    session = "edge-p1"

    def attach(self): ...
    def goto(self, url): ...
    def snapshot(self): ...
    def html(self): ...
    def detach(self): ...
```

Then expose:

```bash
stream-sieve browser inspect --url https://www.zhihu.com
stream-sieve browser inspect --url https://www.wsj.com
```

## Phase 1 Update: 2026-08-12

Implemented minimal backend and CLI:

```text
stream-sieve/browser/base.py
stream-sieve/browser/windows_edge_extension.py
stream-sieve/cli.py
```

Verified commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m stream_sieve.cli browser inspect \
  --url https://www.zhihu.com \
  --scroll 2 \
  --wait 5
```

Result:

- attach ok
- connect URL contained `token=`
- manual Allow prompt not detected
- Zhihu logged-in homepage snapshot read after scrolling

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m stream_sieve.cli browser inspect \
  --url https://www.wsj.com \
  --wait 5
```

Result:

- attach ok
- connect URL contained `token=`
- manual Allow prompt not detected
- WSJ homepage rendered snapshot read successfully

CLI output now redacts the extension token as `<redacted>`.

## Security Note

The token used during experiments was exposed in chat. Regenerate it before keeping the setup for real use, then store it only under `~/.stream-sieve/secrets/` or `C:\Users\33301\.stream-sieve\secrets\`.
