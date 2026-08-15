# Tasks

## Current Status

Phase 0 browser transport is validated. Phase 1/2 minimal source pipeline is now runnable: hand-written source YAML can discover ItemRef, acquire RawDocument, and extract Article.

## Done

- [x] WSL Python available.
- [x] WSL can call Windows `cmd.exe`.
- [x] Windows `@playwright/cli` installed.
- [x] Playwright Extension installed in working Edge profile.
- [x] Token attach works when invoked as `cmd.exe /C "set TOKEN&& playwright-cli..."`.
- [x] Connect URL contains `token=`.
- [x] No manual Allow prompt in token flow.
- [x] WSJ home snapshot readable.
- [x] WSJ article snapshot readable.
- [x] Zhihu logged-in home snapshot readable.
- [x] One-click WSJ attached script exists: `scripts/one_click_wsj_attached.sh`.
- [x] Config browser check exists: `scripts/check_browser_config.py`.
- [x] Minimal package exists: `stream-sieve/`.
- [x] `WindowsEdgeExtensionBackend` exists.
- [x] `stream-sieve browser inspect` CLI exists via `python3 -m stream_sieve.cli browser inspect`.
- [x] New CLI verified against Zhihu with scroll.
- [x] New CLI verified against WSJ.
- [x] CLI output redacts extension token.
- [x] `discover sources/zhihu-home.yaml` emits ItemRef JSONL.
- [x] `discover sources/wsj-home.yaml` emits ItemRef JSONL.
- [x] `extract sources/zhihu-home.yaml --index 0` emits Article JSON.
- [x] `extract sources/wsj-home.yaml --index 0` emits Article JSON.
- [x] `run-once sources/zhihu-home.yaml --limit 1` emits markdown.

## Immediate Next Tasks

1. Add profile/session preflight:
   - `playwright-cli list`
   - attach output must include `token=`
   - page title / URL sanity checks
2. Add machine-readable output mode only when another tool consumes CLI output.

## Report Pipeline Status

- [x] Source registry includes field, tier, source type, quality and policy metadata.
- [x] Score prompt is field-specific and assigns a direct score without weighted sum.
- [x] Score and analysis requests are grouped by field/source set rather than one request per source.
- [x] Digest prompt returns JSON-only content references using article IDs.
- [x] HTML renderer uses database metadata for title, URL, source, date, score and reading time.
- [x] HTML/CSS report template is fixed and should not be changed implicitly by future agents.
- [x] Debug run exists for `wsj-home` + `zhihu-home`: `configs/runs/debug-wsj-zhihu.yaml`.
- [ ] Add malformed JSON recovery/retry for scorer responses.
- [ ] Make Markdown fallback consume the new `article_id`/`content` digest schema completely.

## Browser Tasks

- [x] Implement `WindowsEdgeExtensionBackend`.
- [x] Implement `attach()` using verified Windows command form.
- [x] Implement `goto()`.
- [x] Implement `snapshot()`.
- [x] Implement `html()` with decode fallback.
- [x] Implement `text()` with decode fallback.
- [x] Implement `scroll()`.
- [x] Implement `detach()` without closing Edge.
- [x] Add `stream-sieve browser inspect --url <url>`.
- [x] Add no-close safety: normal backend only exposes `detach()`, no `kill-all` path.
- [x] Add token-file setup documentation.
- [ ] Add machine-readable output mode for CLI.

## Data Model Tasks

- [ ] Create `pyproject.toml`.
- [x] Create `stream-sieve/` package.
- [x] Implement `stream-sieve/models.py`.
- [x] Implement minimal SourceDefinition YAML loader.
- [x] Implement SQLite schema.

## RSS / HTTP Tasks

- [x] RSS discovery with feedparser.
- [ ] ETag / Last-Modified persistence.
- [x] HTTP acquire with httpx.
- [x] Browser acquire with attached Edge.
- [x] Trafilatura extraction.
- [x] Source health gate in sync: auth/verification/paywall/short pages are skipped.
- [ ] RawDocument cache.

## Open Risks

- WSJ may show subscription/paywall content; extractor must classify this explicitly.
- Some pages may require manual verification; state must not advance on verification pages.
- Playwright Extension token is powerful and must be treated as a secret.
- Attached browser profile can expose tabs/cookies; source-specific runs should avoid opening unrelated sensitive tabs in the attached profile.

## Definition of Done

A browser source task is done only when:

- It has a deterministic command to reproduce.
- It does not require manual Allow in normal token flow.
- It marks auth/verification failures explicitly.
- It does not advance cursor on failed acquire/extract.
- It does not commit secrets or runtime browser data.
