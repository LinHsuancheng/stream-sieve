#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFIG="${CONFIG:-configs/runs/full-email-test.local.yaml}"
ENV_FILE="${ENV_FILE:-.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE; copy .env.example to .env and fill keys" >&2
  exit 2
fi

if [[ ! -f configs/delivery.gmail.yaml ]]; then
  echo "missing configs/delivery.gmail.yaml; copy configs/delivery.gmail.example.yaml and fill SMTP settings" >&2
  exit 2
fi

.venv/bin/python scripts/run_pipeline.py "$CONFIG" --env-file "$ENV_FILE"
