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

if [ ! -f "$API_DIR/Dockerfile" ]; then
  echo "A API '$LANGUAGE' ainda nao foi implementada em $API_DIR/Dockerfile."
  echo "A base esta pronta; implemente a API antes de executar a coleta dessa linguagem."
  exit 2
fi

mkdir -p "$RESULT_DIR"

START_TIME="$(date -Iseconds)"
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

"$SCRIPT_DIR/reset_db.sh"

docker compose --profile "$LANGUAGE" up -d --build "$API_SERVICE"
wait_for_api "$API_BASE_URL"

"$SCRIPT_DIR/smoke_test_api.sh" "$API_BASE_URL"
"$SCRIPT_DIR/run_warmup.sh" "$API_BASE_URL"

# O reset depois do warmup deve ocorrer sem reiniciar a API.
"$SCRIPT_DIR/reset_db.sh"

SCENARIO="$SCENARIO_NAME" docker compose --profile load run --rm \
  -e SCENARIO="$SCENARIO_NAME" \
  -e PAYLOAD_DIR=/mnt/payloads \
  locust \
  -f locustfile.py \
  --headless \
  -u "$LOCUST_USERS" \
  -r "$LOCUST_SPAWN_RATE" \
  -t "$LOCUST_DURATION" \
  --host "$API_BASE_URL" \
  --csv "/mnt/$RESULT_DIR/locust" \
  --only-summary

"$SCRIPT_DIR/collect_docker_stats.sh" "$LANGUAGE" "$SCENARIO_NAME" "$RUN_NUMBER" || true
"$SCRIPT_DIR/export_prometheus_data.sh" "$LANGUAGE" "$SCENARIO_NAME" "$RUN_NUMBER" || true

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
  "language_version": "",
  "postgres_driver_version": "",
  "http_library_or_framework": "",
  "framework_justification": "Uso minimo de framework conforme docs/methodological-notes.md.",
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
    "driver_specific_notes": ""
  },
  "framework_policy": {
    "minimum_framework_usage": true,
    "http_library_or_framework": "",
    "justification": "",
    "orm_used": false
  },
  "easy_execution": {
    "launcher_used": "",
    "manual_command_available": true
  },
  "locust": {
    "users": $LOCUST_USERS,
    "spawn_rate": $LOCUST_SPAWN_RATE,
    "duration": "$LOCUST_DURATION"
  },
  "notes": ""
}
JSON

docker compose stop "$API_SERVICE"

echo "Rodada concluida: $RESULT_DIR"
