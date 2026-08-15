#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

BASE_URL="${1:-$LOCUST_HOST}"
mkdir -p results/raw/warmup
PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix results/raw/warmup/warmup --prepare

echo "Rodando warmup em $BASE_URL por ${WARMUP_DURATION_SECONDS}s..."
SCENARIO=warmup docker compose --profile load run --rm \
  -e SCENARIO=warmup \
  -e PAYLOAD_DIR=/mnt/payloads \
  locust \
  -f locustfile.py \
  --headless \
  -u "$WARMUP_USERS" \
  -r "$WARMUP_SPAWN_RATE" \
  -t "${WARMUP_DURATION_SECONDS}s" \
  --host "$BASE_URL" \
  --csv /mnt/results/raw/warmup/warmup \
  --only-summary
"$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix results/raw/warmup/warmup

echo "Warmup concluido. Resultados de warmup nao entram na coleta principal."
