#!/usr/bin/env bash
set -euo pipefail

LANGUAGE="${1:-manual}"
SCENARIO_NAME="${2:-mixed}"
RUN_NUMBER="${3:-1}"
RESULT_DIR="results/raw/$LANGUAGE/$SCENARIO_NAME/run_$RUN_NUMBER"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"
mkdir -p "$RESULT_DIR"

if command -v curl >/dev/null 2>&1 && curl -fsS "$PROMETHEUS_URL/-/ready" >/dev/null 2>&1; then
  curl -fsS "$PROMETHEUS_URL/api/v1/query?query=up" > "$RESULT_DIR/prometheus_up.json"
  echo "Consulta Prometheus salva em $RESULT_DIR/prometheus_up.json"
else
  cat > "$RESULT_DIR/prometheus_export_note.txt" <<TXT
Prometheus nao estava disponivel em $PROMETHEUS_URL no momento da exportacao.
Suba com: docker compose --profile monitoring up -d prometheus postgres-exporter grafana
TXT
  echo "Prometheus indisponivel; nota salva em $RESULT_DIR/prometheus_export_note.txt"
fi
