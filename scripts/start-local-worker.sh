#!/usr/bin/env bash
set -euo pipefail

cd /Users/heyunshen/work/PROJECT/jdc/ai-spider-app

PYTHON=/Users/heyunshen/miniconda3/bin/python3
export PATH=/opt/homebrew/bin:/Users/heyunshen/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
export PYTHONPATH=backend
export WORKER_API_TOKEN="$(
  "$PYTHON" - <<'PY'
from app.config import settings
if not settings.WORKER_API_TOKEN:
    raise SystemExit("WORKER_API_TOKEN is not configured")
print(settings.WORKER_API_TOKEN)
PY
)"

exec "$PYTHON" worker/main.py \
  --server http://45.205.27.116:8081 \
  --node-key local-mac-SZMAC-F7F7KPQ2 \
  --name '本地采集机' \
  --version 'local-worker' \
  --poll-interval 5
