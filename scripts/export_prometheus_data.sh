#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

RESULT_DIR="${1:?Uso: export_prometheus_data.sh <diretorio_resultado> <inicio_epoch> <fim_epoch> <servico_api> [pilot|official] [cobertura_minima]}"
START_EPOCH="${2:?Inicio epoch obrigatorio}"
END_EPOCH="${3:?Fim epoch obrigatorio}"
API_SERVICE="${4:?Servico da API obrigatorio}"
RUN_MODE="${5:-pilot}"
MINIMUM_CADVISOR_COVERAGE_PERCENT="${6:-90}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
PYTHON_BIN="$(python_bin)"
mkdir -p "$RESULT_DIR"

curl -fsS "$PROMETHEUS_URL/-/ready" >/dev/null
arguments=(
  "$SCRIPT_DIR/export_prometheus_data.py"
  --url "$PROMETHEUS_URL" \
  --output "$RESULT_DIR/prometheus_series.json" \
  --start "$START_EPOCH" \
  --end "$END_EPOCH" \
  --step 5 \
  --require-postgres \
  --minimum-cadvisor-coverage-percent "$MINIMUM_CADVISOR_COVERAGE_PERCENT" \
  --component "api=$API_SERVICE,tcc_benchmark_${API_SERVICE//-/_}" \
  --component "postgresql=postgres,tcc_benchmark_postgres" \
  --component "locust=locust,tcc_benchmark_locust"
)
if [ "$RUN_MODE" = official ]; then arguments+=(--require-cadvisor); fi
"$PYTHON_BIN" "${arguments[@]}"
