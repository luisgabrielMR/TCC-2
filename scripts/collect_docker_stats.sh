#!/usr/bin/env bash
set -euo pipefail

LANGUAGE="${1:-manual}"
SCENARIO_NAME="${2:-mixed}"
RUN_NUMBER="${3:-1}"
RESULT_DIR="results/raw/$LANGUAGE/$SCENARIO_NAME/run_$RUN_NUMBER"
mkdir -p "$RESULT_DIR"

docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.NetIO}},{{.BlockIO}}" \
  > "$RESULT_DIR/docker_stats.csv"

echo "Docker stats salvos em $RESULT_DIR/docker_stats.csv"
