# Stream Sieve

Stream Sieve is a CLI-first personal information feed pipeline. It reads user-chosen sources, extracts structured articles, stores incremental state in SQLite, scores articles with an LLM, builds a Markdown/HTML brief, and delivers it through configurable backends.

The project does not try to be a hot-list or recommendation feed. The user chooses the sources; Stream Sieve turns them into a normalized, incremental, LLM-rankable feed.

## Current MVP

This repository currently supports:

- Browser-backed source discovery and acquisition through Linux Google Chrome CDP.
- YAML source recipes for WSJ and Zhihu examples.
- HTML/article extraction with Trafilatura and optional XPath selectors.
- SQLite incremental storage and deduplication.
- OpenAI-compatible LLM editorial scoring.
- Structured article analysis.
- LLM-synthesized Markdown brief generation with lightweight topic clustering.
- Delivery through filesystem or SMTP.

The working end-to-end loop is:

```text
Source YAML
  -> discover ItemRef
  -> acquire RawDocument
  -> extract Article
  -> save/dedup in SQLite
  -> LLM score
  -> article analysis
  -> cluster/synthesize
  -> brief
  -> delivery
```

## Architecture

```text
sources/*.yaml
      |
      v
Discovery
  browser / rss / url
      |
      v
ItemRef
      |
      v
Acquire
  browser / http
      |
      v
RawDocument
      |
      v
Extract
  trafilatura / xpath / cleanup
      |
      v
Article
      |
      v
SQLite
  articles / source_state / article_scores
  article_analysis
      |
      v
LLM scorer
      |
      v
Article analyzer
      |
      v
Brief synthesizer
      |
      v
Delivery
  filesystem / smtp
```

The browser is transport, not the agent. The daily runtime should execute deterministic source recipes. Agents can help create or repair recipes later.

## Repository Layout

```text
stream_sieve/
  browser/                 Linux Google Chrome CDP backend
  delivery/                filesystem and SMTP delivery
  render/                  Markdown-to-HTML rendering
  cli.py                   command-line entrypoint
  analyze.py               OpenAI-compatible structured article analyzer
  cluster.py               Lightweight article clustering helpers
  digest.py                LLM digest synthesis and Markdown rendering
  llm_scorer.py            OpenAI-compatible batch scorer
  models.py                ItemRef / RawDocument / Article
  pipeline.py              discover/acquire/extract/sync
  relevance.py             local keyword ranker
  storage.py               SQLite store

config.yaml                daily run config

sources/
  wsj-home.yaml
  zhihu-follow.yaml
  zhihu-home.yaml

configs/
  runs/daily.example.yaml
  runs/full-email-test.example.yaml
  delivery.example.yaml
  delivery.gmail.example.yaml

scripts/
  check_phase0.py
  run_pipeline.py
  test_full_email_pipeline.sh
  run_wsj_pipeline.sh

.codex/
  PROJECT.md
  ROADMAP.md
  TASKS.md
  DECISIONS.md
  ACTION_REPORT.md
```

## Installation

Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install -g @playwright/cli@latest
```

For authenticated browser sources, use the Chrome profile configured in `config.yaml`:

```bash
google-chrome --user-data-dir="$HOME/.stream-sieve/chrome-profile"
```

Log in to target sites once in that window, then close it. `./run` starts the same profile with CDP enabled.

## Secrets

Do not commit API keys, cookies, SMTP passwords, browser profiles, or SQLite runtime databases.

Typical environment variables:

```bash
export STREAM_SIEVE_LLM_API_KEY='...'
export STREAM_SIEVE_EMAIL_USER='...'
export STREAM_SIEVE_EMAIL_PASSWORD='...'
```

For one-command local runs, copy `.env.example` to `.env` and fill values:

```bash
cp .env.example .env
```

`scripts/run_pipeline.py` and `scripts/run_wsj_pipeline.sh` load `.env` automatically. `.env` is ignored by git.

Runtime database defaults to:

```text
~/.stream-sieve/stream-sieve.db
```

## Daily Run

The shortest full run is:

```bash
./run
```

Preview the commands without running browser, LLM, or email work:

```bash
./run --dry-run
```

The sync step does not try to classify login, verification, paywall, or other page states. If extraction returns empty content, the item is skipped; otherwise the extracted article is saved for later scoring.

`config.yaml` is the daily run config. It starts Linux Google Chrome with `--remote-debugging-port` and attaches through CDP.

## Main Knobs

- `browser_boot.enabled`, `user_data_dir`, `remote_debugging_port`, `startup_wait_seconds`: Linux Chrome startup settings.
- `sources[].sync_limit`: per-source acquire limit.
- `discovery.wait`, `discovery.scroll`, `discovery.scroll_delta`, `discovery.scroll_wait`: browser discovery timing and depth.
- `acquire.wait`: page settle time before reading HTML.
- `extract.min_content_chars`: minimum extracted article length before saving.
- `scoring.model`, `scoring.base_url`: LLM backend.
- `scoring.limit`, `scoring.batch_size`, `scoring.timeout`, `scoring.retries`: LLM throughput and retry behavior.
- `scoring.nonthink`: request non-thinking mode from compatible OpenAI-style providers.
- `scoring.sample_chars`: max content sample characters per article. Scoring sends title plus this sample, not the full article.
- `source_pool`: optional source registry path. Defaults to `sourcepool.yaml` and adds source tier/type/quality priors to LLM-stage inputs.
- `analysis.min_score`, `analysis.limit`, `analysis.content_chars`: article analysis selection and context size.
- `brief.min_score`, `brief.limit`, `brief.excerpt_chars`: email selection and display length.
- `delivery.config`, `delivery.delivery_key`, `delivery.resend`: destination and resend behavior.

## Source Configuration

A source is a logical information source plus the strategies needed to read it.

Example:

```yaml
id: wsj-home
name: WSJ Home

browser:
  session: chrome-main
  cdp_endpoint: http://127.0.0.1:9222

discovery:
  type: browser
  url: https://www.wsj.com
  wait: 5
  include_url_regex: "wsj\\.com/.+"
  exclude_url_regex: "(subscribe|login|market-data|client/silent-login|#comments)"

acquire:
  type: browser
  wait: 5

extract:
  type: trafilatura
```

Supported source fields used today:

- `browser.channel`
- `browser.session`
- `browser.token_file`
- `discovery.type`
- `discovery.url`
- `discovery.wait`
- `discovery.scroll`
- `discovery.scroll_delta`
- `discovery.scroll_wait`
- `discovery.include_url_regex`
- `discovery.exclude_url_regex`
- `acquire.type`
- `acquire.wait`
- `extract.type`
- `extract.external_id_regex`
- `extract.content_xpath`
- `extract.metadata_xpath`
- `extract.metadata_regex`
- `extract.cleanup.drop_lines`
- `extract.cleanup.stop_before`

## Delivery Configuration

Filesystem delivery:

```yaml
delivery:
  type: filesystem
  path: /tmp/stream-sieve-brief.html
```

SMTP delivery:

```yaml
delivery:
  type: smtp
  from: "Stream Sieve <feed@example.com>"
  to:
    - user@example.com
  attachment_prefix: stream-sieve-daily-brief
  smtp:
    host: smtp.example.com
    port: 587
    security: starttls
    username_env: STREAM_SIEVE_EMAIL_USER
    password_env: STREAM_SIEVE_EMAIL_PASSWORD
```

SMTP delivery keeps the email body as a short plain-text notice and sends the
rendered newsletter as an HTML attachment. The attachment filename includes
the local send time to the minute, for example
`stream-sieve-daily-brief-2026-08-15-1430.html`. `attachment_prefix` is
optional and defaults to `stream-sieve-daily-brief`.

Gmail example:

```bash
cp configs/delivery.gmail.example.yaml configs/delivery.gmail.yaml
```

Then edit addresses or use environment variables.

## Common Commands

Check browser environment:

```bash
.venv/bin/python -m stream_sieve.cli browser inspect \
  --url https://www.zhihu.com \
  --content snapshot \
  --max-chars 12000
```

Discover items:

```bash
.venv/bin/python -m stream_sieve.cli discover sources/wsj-home.yaml --limit 5
```

Sync new articles into SQLite:

```bash
.venv/bin/python -m stream_sieve.cli sync sources/wsj-home.yaml --limit 3
```

Score unscored articles:

```bash
STREAM_SIEVE_LLM_API_KEY='...' \
.venv/bin/python -m stream_sieve.cli score \
  --source wsj-home \
  --limit 10 \
  --model deepseek-v4-flash-0731 \
  --base-url https://api.openlux.ai/v1/chat/completions \
  --sample-chars 50 \
  --batch-size 8 \
  --nonthink
```

Analyze high-scored articles:

```bash
STREAM_SIEVE_LLM_API_KEY='...' \
.venv/bin/python -m stream_sieve.cli analyze \
  --source wsj-home \
  --min-score 6.5 \
  --limit 10 \
  --model deepseek-v4-flash-0731 \
  --base-url https://api.openlux.ai/v1/chat/completions \
  --content-chars 4000 \
  --batch-size 5 \
  --nonthink
```

Build a brief:

```bash
.venv/bin/python -m stream_sieve.cli brief \
  --source wsj-home \
  --min-score 7 \
  --output /tmp/stream-sieve-wsj-brief.md
```

Send a brief:

```bash
.venv/bin/python -m stream_sieve.cli send \
  --config configs/delivery.example.yaml \
  --source wsj-home \
  --min-score 7
```

`send` records delivered article IDs in SQLite and skips them on later runs. Use `--resend` to force a resend, or `--delivery-key` to keep separate delivery histories for different destinations.

Inspect state:

```bash
.venv/bin/python -m stream_sieve.cli status
.venv/bin/python -m stream_sieve.cli articles --source wsj-home --limit 10
.venv/bin/python -m stream_sieve.cli scores --source wsj-home --limit 10
.venv/bin/python -m stream_sieve.cli analyses --source wsj-home --limit 10
```

`sourcepool.yaml` classifies sources by tier, type, domains, quality priors, and policy flags. Those priors are added to the scoring, analysis, and digest inputs so the LLM can distinguish primary reporting, professional editorial sources, curated technical sources, and social discovery.

## Multi-Source Run Config

Edit `config.yaml` for the daily run. `.env` is only for secrets and environment overrides.

Dry-run:

```bash
./run --dry-run
```

Run:

```bash
./run
```

The run config executes:

```text
sync all browser sources with one attach/tab
score unscored articles in merged batches
analyze high-scored articles into reusable briefing notes
brief all sources together using source metadata and article clusters
send one delivery
status
```

Full email test:

```bash
cp configs/delivery.gmail.example.yaml configs/delivery.gmail.yaml
# edit configs/delivery.gmail.yaml or use env-based SMTP settings

scripts/test_full_email_pipeline.sh
```

The full email test uses `configs/runs/full-email-test.example.yaml`, includes `wsj-home`, `zhihu-follow`, and `zhihu-home`, and uses `delivery_key: gmail-full-test` so repeated test runs do not resend the same articles unless the delivery key is changed or `resend: true` is set in the run config.

## End-to-End WSJ Script

`scripts/run_wsj_pipeline.sh` is kept as a small single-source convenience wrapper.

Dry-run configuration:

```bash
DRY_RUN=1 scripts/run_wsj_pipeline.sh
```

Run full pipeline and write HTML to filesystem delivery:

```bash
scripts/run_wsj_pipeline.sh
```

Run with SMTP delivery:

```bash
DELIVERY_CONFIG=configs/delivery.gmail.yaml \
scripts/run_wsj_pipeline.sh
```

Script environment variables:

```text
PY
SOURCE
SOURCE_ID
DB
SYNC_LIMIT
SCORE_LIMIT
MIN_SCORE
BRIEF_OUT
DELIVERY_CONFIG
SUBJECT
MODEL
BASE_URL
DRY_RUN
```

## Current Limits

- Browser sources intentionally support Linux Google Chrome CDP only.
- Source onboarding is still manual YAML editing.
- LLM article analysis and digest synthesis are implemented; clustering is a lightweight lexical MVP, not embedding-backed semantic clustering.
- SMTP and filesystem delivery exist; Gmail/Outlook API integrations are intentionally not included.
- SQLite migrations are minimal and suitable for the MVP stage.

## Project Management

Codex project notes live in `.codex/`:

- [.codex/PROJECT.md](.codex/PROJECT.md)
- [.codex/ROADMAP.md](.codex/ROADMAP.md)
- [.codex/TASKS.md](.codex/TASKS.md)
- [.codex/DECISIONS.md](.codex/DECISIONS.md)
- [.codex/ACTION_REPORT.md](.codex/ACTION_REPORT.md)
