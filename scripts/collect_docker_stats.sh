#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

RESULT_DIR="${1:?Uso: collect_docker_stats.sh <diretorio_resultado> [stop_file] [intervalo]}"
STOP_FILE="${2:-$RESULT_DIR/.stop_docker_stats}"
INTERVAL="${3:-${METRICS_SAMPLE_INTERVAL_SECONDS:-2}}"
BOUNDS_FILE="${4:-$RESULT_DIR/locust_measurement_bounds.json}"
PYTHON_BIN="$(python_bin)"
mkdir -p "$RESULT_DIR"

"$PYTHON_BIN" "$SCRIPT_DIR/collect_docker_stats.py" \
  --output "$RESULT_DIR/docker_stats_raw.csv" \
  --stop-file "$STOP_FILE" \
  --interval "$INTERVAL" \
  --bounds "$BOUNDS_FILE"
