#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

RESULT_DIR="${1:?Uso: export_prometheus_data.sh <diretorio_resultado> <inicio_epoch> <fim_epoch>}"
START_EPOCH="${2:?Inicio epoch obrigatorio}"
END_EPOCH="${3:?Fim epoch obrigatorio}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
PYTHON_BIN="$(python_bin)"
mkdir -p "$RESULT_DIR"

curl -fsS "$PROMETHEUS_URL/-/ready" >/dev/null
"$PYTHON_BIN" "$SCRIPT_DIR/export_prometheus_data.py" \
  --url "$PROMETHEUS_URL" \
  --output "$RESULT_DIR/prometheus_series.json" \
  --start "$START_EPOCH" \
  --end "$END_EPOCH" \
  --step 5
