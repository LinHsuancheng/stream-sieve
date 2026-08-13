#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${ENV_FILE:-.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PY="${PY:-.venv/bin/python}"
SOURCE="${SOURCE:-sources/wsj-home.yaml}"
SOURCE_ID="${SOURCE_ID:-wsj-home}"
DB="${DB:-$HOME/.stream-sieve/stream-sieve.db}"
SYNC_LIMIT="${SYNC_LIMIT:-3}"
SCORE_LIMIT="${SCORE_LIMIT:-10}"
MIN_SCORE="${MIN_SCORE:-7}"
SAMPLE_CHARS="${SAMPLE_CHARS:-50}"
BRIEF_OUT="${BRIEF_OUT:-/tmp/stream-sieve-wsj-brief.md}"
DELIVERY_CONFIG="${DELIVERY_CONFIG:-configs/delivery.example.yaml}"
SUBJECT="${SUBJECT:-Stream Sieve WSJ Brief}"
MODEL="${MODEL:-deepseek-v4-flash-0731}"
BASE_URL="${BASE_URL:-https://api.openlux.ai/v1/chat/completions}"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  cat <<EOF
PY=$PY
SOURCE=$SOURCE
SOURCE_ID=$SOURCE_ID
DB=$DB
SYNC_LIMIT=$SYNC_LIMIT
SCORE_LIMIT=$SCORE_LIMIT
MIN_SCORE=$MIN_SCORE
BRIEF_OUT=$BRIEF_OUT
DELIVERY_CONFIG=$DELIVERY_CONFIG
SUBJECT=$SUBJECT
MODEL=$MODEL
BASE_URL=$BASE_URL
SAMPLE_CHARS=$SAMPLE_CHARS
EOF
  exit 0
fi

if [[ -z "${STREAM_SIEVE_LLM_API_KEY:-}" && -z "${DEEPSEEK_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
  echo "missing LLM key: set STREAM_SIEVE_LLM_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY" >&2
  exit 2
fi

echo "== sync =="
"$PY" -m stream_sieve.cli sync "$SOURCE" \
  --db "$DB" \
  --limit "$SYNC_LIMIT" \
  --output /tmp/stream-sieve-wsj-sync.md

echo
echo "== score =="
"$PY" -m stream_sieve.cli score \
  --db "$DB" \
  --source "$SOURCE_ID" \
  --limit "$SCORE_LIMIT" \
  --model "$MODEL" \
  --base-url "$BASE_URL" \
  --sample-chars "$SAMPLE_CHARS" \
  --nonthink

echo
echo "== brief =="
"$PY" -m stream_sieve.cli brief \
  --db "$DB" \
  --source "$SOURCE_ID" \
  --min-score "$MIN_SCORE" \
  --output "$BRIEF_OUT"

echo
echo "== send =="
"$PY" -m stream_sieve.cli send \
  --config "$DELIVERY_CONFIG" \
  --db "$DB" \
  --source "$SOURCE_ID" \
  --min-score "$MIN_SCORE" \
  --subject "$SUBJECT"

echo
echo "== status =="
"$PY" -m stream_sieve.cli status --db "$DB"
