#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

BASE_URL="${1:-$LOCUST_HOST}"
SCENARIO_NAME="${2:-mixed}"
USERS="${3:-$LOCUST_USERS}"
SPAWN_RATE="${4:-$LOCUST_SPAWN_RATE}"
RESULT_RELATIVE="${5:-results/raw/warmup/manual_$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$RESULT_RELATIVE"
PYTHON_BIN="$(python_bin)"

run_attempt() {
  local attempt="$1"
  local duration_seconds="$2"
  local attempt_relative="$RESULT_RELATIVE/warmup/attempt_$attempt"
  local host_prefix="$attempt_relative/locust"
  mkdir -p "$attempt_relative"
  "$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix "$host_prefix" --prepare || return 2

  echo "Warmup $attempt: $SCENARIO_NAME, $USERS usuarios, ${duration_seconds}s..."
  docker compose --profile load run --rm \
    -e SCENARIO="$SCENARIO_NAME" \
    -e PAYLOAD_DIR=/mnt/payloads \
    -e LOCUST_WAIT_SECONDS="$LOCUST_WAIT_SECONDS" \
    locust \
    -f locustfile.py \
    --headless \
    -u "$USERS" \
    -r "$SPAWN_RATE" \
    -t "${duration_seconds}s" \
    --host "$BASE_URL" \
    --csv "/mnt/$host_prefix" \
    --only-summary || return 2
  "$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix "$host_prefix" || return 2
  "$PYTHON_BIN" "$SCRIPT_DIR/validate_warmup_stability.py" \
    --stats "${host_prefix}_stats.csv" \
    --history "${host_prefix}_stats_history.csv" \
    --scenario "$SCENARIO_NAME" \
    --expected-users "$USERS" \
    --window-seconds "$WARMUP_STABILITY_WINDOW_SECONDS" \
    --max-rps-drift-percent "$WARMUP_MAX_RPS_DRIFT_PERCENT" \
    --output "$attempt_relative/validation.json" || return 2
  "$PYTHON_BIN" -c 'import json,sys; raise SystemExit(0 if json.load(open(sys.argv[1], encoding="utf-8"))["stable"] else 1)' \
    "$attempt_relative/validation.json"
}

TOTAL_WARMUP_SECONDS="$WARMUP_DURATION_SECONDS"
attempt_status=0
run_attempt 1 "$WARMUP_DURATION_SECONDS" || attempt_status=$?
if [ "$attempt_status" -eq 2 ]; then
  echo "Falha operacional durante o warmup." >&2
  exit 1
fi
if [ "$attempt_status" -eq 1 ]; then
  echo "Warmup ainda instavel; restaurando o banco antes da tentativa adicional."
  "$SCRIPT_DIR/reset_db.sh"
  retry_status=0
  run_attempt 2 "$WARMUP_RETRY_DURATION_SECONDS" || retry_status=$?
  if [ "$retry_status" -ne 0 ]; then
    echo "Warmup nao estabilizou dentro do limite configurado." >&2
    exit 1
  fi
  TOTAL_WARMUP_SECONDS=$((WARMUP_DURATION_SECONDS + WARMUP_RETRY_DURATION_SECONDS))
fi

printf '%s\n' "$TOTAL_WARMUP_SECONDS" > "$RESULT_RELATIVE/warmup/total_duration_seconds.txt"
echo "Warmup estavel concluido. Seus resultados nao entram na coleta principal."
