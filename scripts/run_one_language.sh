#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

LANGUAGE="${1:?Uso: ./scripts/run_one_language.sh language scenario run_number load_profile}"
SCENARIO_NAME="${2:-mixed}"
RUN_NUMBER="${3:-0}"
LOAD_PROFILE="${4:-environment}"

if [ "$LANGUAGE" = java ] && [ "$WARMUP_RETRY_DURATION_SECONDS" -lt 600 ]; then
  WARMUP_RETRY_DURATION_SECONDS=600
fi

case "$LOAD_PROFILE" in
  environment) ;;
  controlled_50) LOCUST_USERS=50; LOCUST_SPAWN_RATE=10 ;;
  capacity_100) LOCUST_USERS=100; LOCUST_SPAWN_RATE=20 ;;
  capacity_200) LOCUST_USERS=200; LOCUST_SPAWN_RATE=40 ;;
  *) echo "Perfil invalido: $LOAD_PROFILE" >&2; exit 2 ;;
esac
if [[ "$LOAD_PROFILE" == capacity_* && "$SCENARIO_NAME" != mixed ]]; then
  echo "Os perfis de capacidade usam o workload mixed." >&2
  exit 2
fi

case "$LOAD_PROFILE" in
  capacity_100) RESULT_SCENARIO="${SCENARIO_NAME}_capacity_100" ;;
  capacity_200) RESULT_SCENARIO="${SCENARIO_NAME}_capacity_200" ;;
  *) RESULT_SCENARIO="$SCENARIO_NAME" ;;
esac
if [ "$RUN_NUMBER" -le 0 ]; then
  RUN_NUMBER=1
  for run_path in results/raw/"$LANGUAGE"/"$RESULT_SCENARIO"/run_*; do
    [ -d "$run_path" ] || continue
    candidate="${run_path##*_}"
    if [[ "$candidate" =~ ^[0-9]+$ ]] && [ "$candidate" -ge "$RUN_NUMBER" ]; then
      RUN_NUMBER=$((candidate + 1))
    fi
  done
fi
API_SERVICE="$(api_service_for_language "$LANGUAGE")"
API_DIR="apps/$API_SERVICE"
RESULT_DIR="results/raw/$LANGUAGE/$RESULT_SCENARIO/run_$RUN_NUMBER"
if [ -f "$RESULT_DIR/locust_stats.csv" ]; then
  echo "A rodada ja existe: $RESULT_DIR. Use run_number 0 para selecionar a proxima automaticamente." >&2
  exit 2
fi
BENCHMARK_KIND="controlled_load"
if [[ "$LOAD_PROFILE" == capacity_* ]]; then BENCHMARK_KIND="capacity"; fi
API_STARTED=false
METRICS_STARTED=false
MAIN_RUN_STARTED=false
DATABASE_NEEDS_RESET=false
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
  if [ "$MAIN_RUN_STARTED" = true ] || [ "$DATABASE_NEEDS_RESET" = true ]; then
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

# Os testes de contrato escrevem no banco; o warmup parte do estado inicial conhecido.
DATABASE_NEEDS_RESET=true
"$SCRIPT_DIR/reset_db.sh"
DATABASE_NEEDS_RESET=false
DATABASE_NEEDS_RESET=true
"$SCRIPT_DIR/run_warmup.sh" "$LOCUST_HOST" "$SCENARIO_NAME" "$LOCUST_USERS" "$LOCUST_SPAWN_RATE" "$RESULT_DIR"
WARMUP_TOTAL_SECONDS="$(cat "$RESULT_DIR/warmup/total_duration_seconds.txt")"
WARMUP_ATTEMPTS=1
if [ "$WARMUP_TOTAL_SECONDS" -gt "$WARMUP_DURATION_SECONDS" ]; then WARMUP_ATTEMPTS=2; fi

# O reset depois do warmup deve ocorrer sem reiniciar a API.
"$SCRIPT_DIR/reset_db.sh"
DATABASE_NEEDS_RESET=false

rm -f "$METRICS_STOP_FILE"
METRICS_START_EPOCH="$(date +%s)"
"$SCRIPT_DIR/collect_docker_stats.sh" "$RESULT_DIR" "$METRICS_STOP_FILE" "$METRICS_SAMPLE_INTERVAL_SECONDS" \
  > "$RESULT_DIR/docker_stats_collector.log" 2>&1 &
METRICS_PID=$!
METRICS_STARTED=true
MAIN_RUN_STARTED=true
DATABASE_NEEDS_RESET=true

PYTHON_BIN="$(python_bin)"
TEST_STARTED_AT="$(date -Iseconds)"
TEST_STARTED_EPOCH="$(date +%s)"
"$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix "$RESULT_DIR/locust" --prepare

SCENARIO="$SCENARIO_NAME" docker compose --profile load run --rm \
  -e SCENARIO="$SCENARIO_NAME" \
  -e PAYLOAD_DIR=/mnt/payloads \
  -e LOCUST_WAIT_SECONDS="$LOCUST_WAIT_SECONDS" \
  locust \
  -f locustfile.py \
  --headless \
  -u "$LOCUST_USERS" \
  -r "$LOCUST_SPAWN_RATE" \
  -t "$LOCUST_DURATION" \
  --host "$LOCUST_HOST" \
  --csv "/mnt/$RESULT_DIR/locust" \
  --only-summary
"$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix "$RESULT_DIR/locust"
TEST_FINISHED_AT="$(date -Iseconds)"
TEST_FINISHED_EPOCH="$(date +%s)"
TEST_ELAPSED_SECONDS=$((TEST_FINISHED_EPOCH - TEST_STARTED_EPOCH))

touch "$METRICS_STOP_FILE"
wait "$METRICS_PID"
METRICS_STARTED=false
rm -f "$METRICS_STOP_FILE"
"$PYTHON_BIN" "$ROOT_DIR/scripts/validate_warmup_stability.py" \
  --stats "$RESULT_DIR/locust_stats.csv" \
  --history "$RESULT_DIR/locust_stats_history.csv" \
  --scenario "$SCENARIO_NAME" \
  --expected-users "$LOCUST_USERS" \
  --phase-label "Measurement" \
  --window-seconds "$WARMUP_STABILITY_WINDOW_SECONDS" \
  --max-rps-drift-percent "$WARMUP_MAX_RPS_DRIFT_PERCENT" \
  --output "$RESULT_DIR/measurement_stability.json"
MEASUREMENT_STABILITY="$(cat "$RESULT_DIR/measurement_stability.json")"
METRICS_END_EPOCH="$(date +%s)"
"$SCRIPT_DIR/export_prometheus_data.sh" "$RESULT_DIR" "$METRICS_START_EPOCH" "$METRICS_END_EPOCH"
"$SCRIPT_DIR/reset_db.sh"
MAIN_RUN_STARTED=false
DATABASE_NEEDS_RESET=false

END_TIME="$(date -Iseconds)"
API_IMAGE="$(docker compose images -q "$API_SERVICE" 2>/dev/null || echo unknown)"
THEORETICAL_RPS_CEILING="$($PYTHON_BIN -c 'import sys; print(round(float(sys.argv[1]) / float(sys.argv[2]), 3))' "$LOCUST_USERS" "$LOCUST_WAIT_SECONDS")"
NOTES="Carga controlada; nao representa a capacidade maxima da API."
if [ "$BENCHMARK_KIND" = capacity ]; then
  NOTES="Teste extra de escalabilidade; representa o limite pratico observado neste ambiente."
fi

cat > "$RESULT_DIR/metadata.json" <<JSON
{
  "language": "$LANGUAGE",
  "scenario": "$RESULT_SCENARIO",
  "workload_scenario": "$SCENARIO_NAME",
  "load_profile": "$LOAD_PROFILE",
  "methodology_version": 4,
  "benchmark_kind": "$BENCHMARK_KIND",
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
    "scenario": "$SCENARIO_NAME",
    "users": $LOCUST_USERS,
    "spawn_rate": $LOCUST_SPAWN_RATE,
    "requested_duration_seconds": $WARMUP_DURATION_SECONDS,
    "retry_duration_seconds": $WARMUP_RETRY_DURATION_SECONDS,
    "total_duration_seconds": $WARMUP_TOTAL_SECONDS,
    "attempts": $WARMUP_ATTEMPTS,
    "stability_window_seconds": $WARMUP_STABILITY_WINDOW_SECONDS,
    "max_rps_drift_percent": $WARMUP_MAX_RPS_DRIFT_PERCENT,
    "stable": true,
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
    "wait_seconds": $LOCUST_WAIT_SECONDS,
    "theoretical_rps_ceiling": $THEORETICAL_RPS_CEILING,
    "host": "$LOCUST_HOST"
  },
  "test_phase": {
    "started_at": "$TEST_STARTED_AT",
    "finished_at": "$TEST_FINISHED_AT",
    "elapsed_seconds": $TEST_ELAPSED_SECONDS,
    "excludes_warmup": true
  },
  "measurement_stability": $MEASUREMENT_STABILITY,
  "metrics": {
    "sample_interval_seconds": $METRICS_SAMPLE_INTERVAL_SECONDS,
    "docker_stats_source": "continuous docker stats",
    "prometheus_source": "PostgreSQL exporter query_range",
    "started_epoch": $METRICS_START_EPOCH,
    "finished_epoch": $METRICS_END_EPOCH
  },
  "notes": "$NOTES"
}
JSON

docker compose stop "$API_SERVICE"
API_STARTED=false

echo "Rodada concluida: $RESULT_DIR"
