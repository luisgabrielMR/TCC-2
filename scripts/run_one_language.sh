#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

LANGUAGE="${1:?Uso: ./scripts/run_one_language.sh language scenario run_number}"
SCENARIO_NAME="${2:-mixed}"
RUN_NUMBER="${3:-1}"
API_SERVICE="$(api_service_for_language "$LANGUAGE")"
API_DIR="apps/$API_SERVICE"
RESULT_DIR="results/raw/$LANGUAGE/$SCENARIO_NAME/run_$RUN_NUMBER"
API_STARTED=false
METRICS_STARTED=false
MAIN_RUN_STARTED=false
METRICS_STOP_FILE="$RESULT_DIR/.stop_docker_stats"
METRICS_PID=""

case "$LANGUAGE" in
  python)
    LANGUAGE_VERSION="Python 3.12.14"
    DRIVER_VERSION="psycopg 3.2.3"
    HTTP_FRAMEWORK="FastAPI 0.115.6 + Uvicorn 0.34.0"
    DRIVER_NOTES="psycopg_pool 3.2.4"
    ;;
  node)
    LANGUAGE_VERSION="Node.js 22.23.2"
    DRIVER_VERSION="pg 8.13.1"
    HTTP_FRAMEWORK="Express 4.22.2"
    DRIVER_NOTES="pg.Pool: min evita remocao abaixo do limite, mas nao preabre conexoes"
    ;;
  java)
    LANGUAGE_VERSION="Java Temurin 21.0.11+10 LTS"
    DRIVER_VERSION="PostgreSQL JDBC 42.7.4"
    HTTP_FRAMEWORK="JDK HttpServer + Jackson 2.17.2"
    DRIVER_NOTES="HikariCP 5.1.0"
    ;;
  go)
    LANGUAGE_VERSION="Go 1.23.12"
    DRIVER_VERSION="lib/pq 1.10.9"
    HTTP_FRAMEWORK="net/http"
    DRIVER_NOTES="database/sql nao oferece timeout de aquisicao; o valor equivalente limita o ping inicial"
    ;;
  dotnet)
    LANGUAGE_VERSION=".NET 8.0.30"
    DRIVER_VERSION="Npgsql 8.0.5"
    HTTP_FRAMEWORK="ASP.NET Core Minimal API"
    DRIVER_NOTES="Pooling nativo do Npgsql"
    ;;
esac

cleanup() {
  if [ "$METRICS_STARTED" = true ]; then
    touch "$METRICS_STOP_FILE"
    wait "$METRICS_PID" >/dev/null 2>&1 || true
  fi
  if [ "$MAIN_RUN_STARTED" = true ]; then
    "$SCRIPT_DIR/reset_db.sh" >/dev/null 2>&1 || true
  fi
  if [ "$API_STARTED" = true ]; then
    docker compose stop "$API_SERVICE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [ ! -f "$API_DIR/Dockerfile" ]; then
  echo "A API '$LANGUAGE' ainda nao foi implementada em $API_DIR/Dockerfile."
  echo "A base esta pronta; implemente a API antes de executar a coleta dessa linguagem."
  exit 2
fi

mkdir -p "$RESULT_DIR"

START_TIME="$(date -Iseconds)"
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

docker compose --profile monitoring up -d postgres-exporter prometheus grafana cadvisor
"$SCRIPT_DIR/reset_db.sh"

docker compose --profile "$LANGUAGE" up -d --build "$API_SERVICE"
API_STARTED=true
wait_for_api "$API_BASE_URL"

docker compose --profile load run --rm --no-deps --entrypoint python locust \
  /mnt/scripts/contract_test_api.py --base-url "$LOCUST_HOST"
"$SCRIPT_DIR/smoke_test_api.sh" "$API_BASE_URL"
"$SCRIPT_DIR/run_warmup.sh" "$LOCUST_HOST"

# O reset depois do warmup deve ocorrer sem reiniciar a API.
"$SCRIPT_DIR/reset_db.sh"

rm -f "$METRICS_STOP_FILE"
METRICS_START_EPOCH="$(date +%s)"
"$SCRIPT_DIR/collect_docker_stats.sh" "$RESULT_DIR" "$METRICS_STOP_FILE" "$METRICS_SAMPLE_INTERVAL_SECONDS" \
  > "$RESULT_DIR/docker_stats_collector.log" 2>&1 &
METRICS_PID=$!
METRICS_STARTED=true
MAIN_RUN_STARTED=true

SCENARIO="$SCENARIO_NAME" docker compose --profile load run --rm \
  -e SCENARIO="$SCENARIO_NAME" \
  -e PAYLOAD_DIR=/mnt/payloads \
  locust \
  -f locustfile.py \
  --headless \
  -u "$LOCUST_USERS" \
  -r "$LOCUST_SPAWN_RATE" \
  -t "$LOCUST_DURATION" \
  --host "$LOCUST_HOST" \
  --csv "/mnt/$RESULT_DIR/locust" \
  --only-summary

touch "$METRICS_STOP_FILE"
wait "$METRICS_PID"
METRICS_STARTED=false
rm -f "$METRICS_STOP_FILE"
METRICS_END_EPOCH="$(date +%s)"
"$SCRIPT_DIR/export_prometheus_data.sh" "$RESULT_DIR" "$METRICS_START_EPOCH" "$METRICS_END_EPOCH"
"$SCRIPT_DIR/reset_db.sh"
MAIN_RUN_STARTED=false

END_TIME="$(date -Iseconds)"
API_IMAGE="$(docker compose images -q "$API_SERVICE" 2>/dev/null || echo unknown)"

cat > "$RESULT_DIR/metadata.json" <<JSON
{
  "language": "$LANGUAGE",
  "scenario": "$SCENARIO_NAME",
  "run_number": $RUN_NUMBER,
  "started_at": "$START_TIME",
  "finished_at": "$END_TIME",
  "git_commit": "$COMMIT_SHA",
  "docker_image": "$API_IMAGE",
  "language_version": "$LANGUAGE_VERSION",
  "postgres_driver_version": "$DRIVER_VERSION",
  "http_library_or_framework": "$HTTP_FRAMEWORK",
  "framework_justification": "Somente HTTP, JSON, SQL explicito e pool de conexoes; nenhum ORM e utilizado.",
  "database_initial_state": "Seed deterministico carregado por database/reset/reset_database.sql.",
  "warmup": {
    "enabled": true,
    "duration_seconds": $WARMUP_DURATION_SECONDS,
    "users": $WARMUP_USERS,
    "spawn_rate": $WARMUP_SPAWN_RATE,
    "included_in_results": false
  },
  "database_pool": {
    "min": $DB_POOL_MIN,
    "max": $DB_POOL_MAX,
    "acquire_timeout_seconds": $DB_POOL_ACQUIRE_TIMEOUT_SECONDS,
    "idle_timeout_seconds": $DB_POOL_IDLE_TIMEOUT_SECONDS,
    "max_lifetime_seconds": $DB_POOL_MAX_LIFETIME_SECONDS,
    "driver_specific_notes": "$DRIVER_NOTES"
  },
  "framework_policy": {
    "minimum_framework_usage": true,
    "http_library_or_framework": "$HTTP_FRAMEWORK",
    "justification": "Estrutura minima para expor o contrato HTTP comum mantendo SQL explicito.",
    "orm_used": false
  },
  "easy_execution": {
    "launcher_used": "scripts/run_one_language.sh",
    "manual_command_available": true
  },
  "locust": {
    "users": $LOCUST_USERS,
    "spawn_rate": $LOCUST_SPAWN_RATE,
    "duration": "$LOCUST_DURATION",
    "host": "$LOCUST_HOST"
  },
  "metrics": {
    "sample_interval_seconds": $METRICS_SAMPLE_INTERVAL_SECONDS,
    "docker_stats_source": "continuous docker stats",
    "prometheus_source": "PostgreSQL exporter query_range",
    "started_epoch": $METRICS_START_EPOCH,
    "finished_epoch": $METRICS_END_EPOCH
  },
  "notes": ""
}
JSON

docker compose stop "$API_SERVICE"
API_STARTED=false

echo "Rodada concluida: $RESULT_DIR"
