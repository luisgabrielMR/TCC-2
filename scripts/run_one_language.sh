#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

LANGUAGE="${1:?Uso: ./scripts/run_one_language.sh language scenario run_number load_profile run_mode}"
SCENARIO_NAME="${2:-mixed}"
RUN_NUMBER="${3:-0}"
LOAD_PROFILE="${4:-environment}"
RUN_MODE="${5:-pilot}"
if [ "$RUN_MODE" != pilot ] && [ "$RUN_MODE" != official ]; then
  echo "Modo invalido: $RUN_MODE. Use pilot ou official." >&2
  exit 2
fi

# LOAD_TARGET_RPS marca os perfis de taxa fixa: a vazao e variavel controlada,
# igual para as cinco linguagens, e a comparacao passa a ser de latencia e
# recursos. Vazio nos demais perfis.
LOAD_TARGET_RPS=""
case "$LOAD_PROFILE" in
  environment) ;;
  # Taxa fixa: 50 usuarios com pacing de 0,25 s produzem 200 req/s exatos, com
  # folga em relacao ao limite da implementacao mais lenta.
  fixed_200) LOCUST_USERS=50; LOCUST_SPAWN_RATE=10; LOCUST_WAIT_SECONDS=0.25; LOAD_TARGET_RPS=200 ;;
  # Malha fechada: sem pacing, cada usuario dispara a proxima requisicao assim
  # que a anterior responde. A vazao volta a ser variavel de resposta.
  saturation_25) LOCUST_USERS=25; LOCUST_SPAWN_RATE=25; LOCUST_WAIT_SECONDS=0 ;;
  saturation_50) LOCUST_USERS=50; LOCUST_SPAWN_RATE=25; LOCUST_WAIT_SECONDS=0 ;;
  saturation_100) LOCUST_USERS=100; LOCUST_SPAWN_RATE=25; LOCUST_WAIT_SECONDS=0 ;;
  saturation_200) LOCUST_USERS=200; LOCUST_SPAWN_RATE=40; LOCUST_WAIT_SECONDS=0 ;;
  saturation_400) LOCUST_USERS=400; LOCUST_SPAWN_RATE=80; LOCUST_WAIT_SECONDS=0 ;;
  # Perfis anteriores, preservados para releitura do historico.
  controlled_50) LOCUST_USERS=50; LOCUST_SPAWN_RATE=10 ;;
  capacity_100) LOCUST_USERS=100; LOCUST_SPAWN_RATE=20 ;;
  capacity_200) LOCUST_USERS=200; LOCUST_SPAWN_RATE=40 ;;
  *) echo "Perfil invalido: $LOAD_PROFILE" >&2; exit 2 ;;
esac
if [[ ( "$LOAD_PROFILE" == capacity_* || "$LOAD_PROFILE" == saturation_* || "$LOAD_PROFILE" == fixed_* ) && "$SCENARIO_NAME" != mixed ]]; then
  echo "Os perfis de capacidade, saturacao e taxa fixa usam o workload mixed." >&2
  exit 2
fi
# run_warmup.sh e um processo separado e leria o padrao do .env. O aquecimento
# precisa do mesmo pacing da medicao, entao o valor do perfil e exportado.
export LOCUST_WAIT_SECONDS

case "$LOAD_PROFILE" in
  capacity_100|capacity_200|fixed_*|saturation_*) RESULT_SCENARIO="${SCENARIO_NAME}_${LOAD_PROFILE}" ;;
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
# A carga percorre a rede interna do Docker. O proxy de porta do host acrescenta
# um salto de encaminhamento que aparecia integralmente na latencia medida:
# o GET /health, que nao consulta o banco, custava de 6 a 7 ms por esse caminho.
# LOCUST_HOST_OVERRIDE permite voltar ao caminho pelo host para comparacao.
LOCUST_HOST="${LOCUST_HOST_OVERRIDE:-http://$API_SERVICE:8000}"
RESULT_DIR="results/raw/$LANGUAGE/$RESULT_SCENARIO/run_$RUN_NUMBER"
if [ -f "$RESULT_DIR/locust_stats.csv" ]; then
  echo "A rodada ja existe: $RESULT_DIR. Use run_number 0 para selecionar a proxima automaticamente." >&2
  exit 2
fi
BENCHMARK_KIND="controlled_load"
if [[ "$LOAD_PROFILE" == capacity_* ]]; then BENCHMARK_KIND="capacity"; fi
if [[ "$LOAD_PROFILE" == fixed_* ]]; then BENCHMARK_KIND="fixed_rate"; fi
if [[ "$LOAD_PROFILE" == saturation_* ]]; then BENCHMARK_KIND="saturation"; fi
API_STARTED=false
LOCUST_PREFLIGHT_STARTED=false
METRICS_STARTED=false
MAIN_RUN_STARTED=false
DATABASE_NEEDS_RESET=false
METRICS_STOP_FILE="$RESULT_DIR/.stop_docker_stats"
METRICS_PID=""

cleanup() {
  if [ "$LOCUST_PREFLIGHT_STARTED" = true ]; then
    docker compose stop locust >/dev/null 2>&1 || true
  fi
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
  echo "Dockerfile ausente para a linguagem '$LANGUAGE': $API_DIR/Dockerfile." >&2
  exit 2
fi

mkdir -p "$RESULT_DIR"

START_TIME="$(date -Iseconds)"
PYTHON_BIN="$(python_bin)"
PREFLIGHT_PATH="$RESULT_DIR/preflight.json"
MONITORING_PREFLIGHT_PATH="$RESULT_DIR/monitoring-preflight.json"

docker compose --profile monitoring up -d postgres-exporter benchmark-results-exporter prometheus grafana cadvisor
"$SCRIPT_DIR/reset_db.sh"

docker compose --profile "$LANGUAGE" up -d --build "$API_SERVICE"
API_STARTED=true
wait_for_api "$API_BASE_URL"
docker compose --profile load up -d locust
LOCUST_PREFLIGHT_STARTED=true
"$PYTHON_BIN" "$SCRIPT_DIR/preflight.py" --mode "$RUN_MODE" --output "$PREFLIGHT_PATH"
"$PYTHON_BIN" "$SCRIPT_DIR/validate_monitoring.py" \
  --prometheus-url "http://127.0.0.1:${PROMETHEUS_PORT:-9090}" \
  --grafana-url "http://127.0.0.1:${GRAFANA_PORT:-3000}" \
  --api-service "$API_SERVICE" --mode "$RUN_MODE" --output "$MONITORING_PREFLIGHT_PATH"
docker compose stop locust
LOCUST_PREFLIGHT_STARTED=false

IFS='|' read -r LANGUAGE_VERSION DRIVER_VERSION HTTP_FRAMEWORK DRIVER_NOTES COMMIT_SHA GIT_DIRTY TRACKED_DIFF_SHA UNTRACKED_FILES_SHA <<EOF
$("$PYTHON_BIN" - "$PREFLIGHT_PATH" "$LANGUAGE" <<'PY'
import json, sys
p=json.load(open(sys.argv[1], encoding="utf-8")); lang=sys.argv[2]
libs=p["libraries"][lang]["libraries"]
runtime=p["runtimes"][lang].get("version_output") or "unavailable"
if lang == "python":
    driver=f"psycopg {libs.get('psycopg')}"; framework=f"FastAPI {libs.get('fastapi')} + Uvicorn {libs.get('uvicorn')}"; pool=f"psycopg_pool {libs.get('psycopg-pool')}"
elif lang == "node":
    driver=f"pg {libs.get('pg')}"; framework=f"Express {libs.get('express')}"; pool="pg.Pool; min does not pre-open connections"
elif lang == "java":
    driver=f"PostgreSQL JDBC {libs.get('postgresql')}"; framework=f"JDK HttpServer + Jackson {libs.get('jackson-databind')}"; pool=f"HikariCP {libs.get('HikariCP')}"
elif lang == "go":
    driver=f"lib/pq {libs.get('github.com/lib/pq')}"; framework="net/http"; pool="database/sql; minimum pre-opened and context timeout"
else:
    driver=f"Npgsql {libs.get('Npgsql')}"; framework=f"ASP.NET Core Minimal API ({runtime})"; pool="Npgsql native pooling"
git=p["git"]
print("|".join((runtime,driver,framework,pool,git.get("commit_sha","unknown"),str(bool(git.get("git_dirty"))).lower(),git.get("tracked_diff_sha256","unknown"),git.get("untracked_files_sha256","unknown"))))
PY
)
EOF
PREFLIGHT_JSON="$(cat "$PREFLIGHT_PATH")"
MONITORING_PREFLIGHT_JSON="$(cat "$MONITORING_PREFLIGHT_PATH")"
UNTRACKED_FILES_JSON="$("$PYTHON_BIN" -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1], encoding="utf-8"))["git"].get("untracked_files", []), ensure_ascii=True))' "$PREFLIGHT_PATH")"

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
BOUNDS_FILE="$RESULT_DIR/locust_measurement_bounds.json"
"$SCRIPT_DIR/collect_docker_stats.sh" "$RESULT_DIR" "$METRICS_STOP_FILE" "$METRICS_SAMPLE_INTERVAL_SECONDS" "$BOUNDS_FILE" \
  > "$RESULT_DIR/docker_stats_collector.log" 2>&1 &
METRICS_PID=$!
METRICS_STARTED=true
MAIN_RUN_STARTED=true
DATABASE_NEEDS_RESET=true

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
RUNNER_ELAPSED_SECONDS=$((TEST_FINISHED_EPOCH - TEST_STARTED_EPOCH))

IFS='|' read -r TEST_STARTED_AT TEST_FINISHED_AT TEST_ELAPSED_SECONDS METRICS_START_EPOCH METRICS_END_EPOCH <<EOF
$($PYTHON_BIN -c 'import datetime,json,sys; b=json.load(open(sys.argv[1], encoding="utf-8")); iso=lambda v: datetime.datetime.fromtimestamp(float(v), datetime.timezone.utc).isoformat().replace("+00:00", "Z"); print("{}|{}|{:.3f}|{:.6f}|{:.6f}".format(iso(b["started_epoch"]), iso(b["finished_epoch"]), float(b["elapsed_seconds"]), float(b["started_epoch"]), float(b["finished_epoch"])))' "$BOUNDS_FILE")
EOF

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
MEASUREMENT_STABLE="$($PYTHON_BIN -c 'import json,sys; print(str(bool(json.load(open(sys.argv[1], encoding="utf-8"))["stable"])).lower())' "$RESULT_DIR/measurement_stability.json")"

# Nos perfis de taxa fixa a vazao e imposta, nao medida. Se a implementacao nao
# entregou a taxa pedida, ela esta saturada e a latencia dela nao e comparavel
# com a das outras: a rodada deixa de ser elegivel a oficial.
RATE_TARGET_MET=true
ACHIEVED_RPS=null
if [ -n "$LOAD_TARGET_RPS" ]; then
  ACHIEVED_RPS="$($PYTHON_BIN -c '
import csv, sys
for row in csv.DictReader(open(sys.argv[1], encoding="utf-8-sig")):
    if row["Name"] == "Aggregated":
        print(row["Requests/s"]); break
else:
    print("0")
' "$RESULT_DIR/locust_stats.csv")"
  RATE_TARGET_MET="$($PYTHON_BIN -c '
import sys
achieved, target = float(sys.argv[1]), float(sys.argv[2])
print(str(achieved >= target * 0.975).lower())
' "$ACHIEVED_RPS" "$LOAD_TARGET_RPS")"
  if [ "$RATE_TARGET_MET" != true ]; then
    echo "AVISO: alvo de $LOAD_TARGET_RPS req/s nao atingido (obtido $ACHIEVED_RPS)." >&2
    echo "A implementacao saturou antes do alvo; a latencia nao e comparavel neste perfil." >&2
  fi
fi

RESULT_CLASSIFICATION=non_official
if [ "$RUN_MODE" = official ] && [ "$MEASUREMENT_STABLE" = true ] && [ "$RATE_TARGET_MET" = true ]; then RESULT_CLASSIFICATION=official; fi
"$SCRIPT_DIR/export_prometheus_data.sh" "$RESULT_DIR" "$METRICS_START_EPOCH" "$METRICS_END_EPOCH" "$API_SERVICE" "$RUN_MODE"
"$SCRIPT_DIR/reset_db.sh"
MAIN_RUN_STARTED=false
DATABASE_NEEDS_RESET=false

END_TIME="$(date -Iseconds)"
API_IMAGE="$(docker compose images -q "$API_SERVICE" 2>/dev/null || echo unknown)"
# Com pacing 0 a malha e fechada: o gerador nao impoe teto, entao registrar um
# numero aqui seria falso (e a divisao estouraria).
if [ "$(printf '%s' "$LOCUST_WAIT_SECONDS" | awk '{print ($1 > 0)}')" = "1" ]; then
  THEORETICAL_RPS_CEILING="$($PYTHON_BIN -c 'import sys; print(round(float(sys.argv[1]) / float(sys.argv[2]), 3))' "$LOCUST_USERS" "$LOCUST_WAIT_SECONDS")"
else
  THEORETICAL_RPS_CEILING=null
fi
NOTES="Carga controlada; nao representa a capacidade maxima da API."
if [ "$BENCHMARK_KIND" = capacity ]; then
  NOTES="Teste extra de escalabilidade; representa o limite pratico observado neste ambiente."
fi
if [ "$BENCHMARK_KIND" = fixed_rate ]; then
  NOTES="Taxa fixa de $LOAD_TARGET_RPS req/s imposta a todas as linguagens; a vazao e variavel controlada e a comparacao e de latencia e recursos."
fi
if [ "$BENCHMARK_KIND" = saturation ]; then
  NOTES="Malha fechada sem pacing; a vazao e variavel de resposta e representa o limite observado com a CPU alocada a este container."
fi

cat > "$RESULT_DIR/metadata.json" <<JSON
{
  "result_classification": "$RESULT_CLASSIFICATION",
  "requested_run_mode": "$RUN_MODE",
  "official_run": $([ "$RUN_MODE" = official ] && echo true || echo false),
  "language": "$LANGUAGE",
  "scenario": "$RESULT_SCENARIO",
  "workload_scenario": "$SCENARIO_NAME",
  "load_profile": "$LOAD_PROFILE",
  "methodology_version": 6,
  "benchmark_kind": "$BENCHMARK_KIND",
  "run_number": $RUN_NUMBER,
  "execution_order": {
    "sequence_id": "${BENCHMARK_SEQUENCE_ID:-manual}",
    "position": ${BENCHMARK_ORDER_POSITION:-0}
  },
  "started_at": "$START_TIME",
  "finished_at": "$END_TIME",
  "git_commit": "$COMMIT_SHA",
  "commit_sha": "$COMMIT_SHA",
  "git_dirty": $GIT_DIRTY,
  "tracked_diff_sha256": "$TRACKED_DIFF_SHA",
  "untracked_files": $UNTRACKED_FILES_JSON,
  "untracked_files_sha256": "$UNTRACKED_FILES_SHA",
  "docker_image": "$API_IMAGE",
  "language_version": "$LANGUAGE_VERSION",
  "postgres_driver_version": "$DRIVER_VERSION",
  "http_library_or_framework": "$HTTP_FRAMEWORK",
  "environment": $PREFLIGHT_JSON,
  "monitoring_preflight": $MONITORING_PREFLIGHT_JSON,
  "framework_justification": "Somente HTTP, JSON, SQL explicito e pool de conexoes; nenhum ORM e utilizado.",
  "database_initial_state": "Seed deterministico carregado por database/reset/reset_database.sql.",
  "warmup": {
    "enabled": true,
    "scenario": "$SCENARIO_NAME",
    "users": $LOCUST_USERS,
    "spawn_rate": $LOCUST_SPAWN_RATE,
    "requested_duration_seconds": $WARMUP_DURATION_SECONDS,
    "retry_duration_seconds": 0,
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
  "resource_policy": {
    "api_containers": 1,
    "application_processes": 1,
    "replicas": 1,
    "cpu_limit": "Docker Desktop host allocation",
    "interpretation": "single application instance; not an intrinsic language ranking"
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
    "target_rps": ${LOAD_TARGET_RPS:-null},
    "achieved_rps": $ACHIEVED_RPS,
    "rate_target_met": $RATE_TARGET_MET,
    "host": "$LOCUST_HOST"
  },
  "test_phase": {
    "started_at": "$TEST_STARTED_AT",
    "finished_at": "$TEST_FINISHED_AT",
    "elapsed_seconds": $TEST_ELAPSED_SECONDS,
    "runner_elapsed_seconds": $RUNNER_ELAPSED_SECONDS,
    "excludes_warmup": true
  },
  "measurement_stability": $MEASUREMENT_STABILITY,
  "metrics": {
    "window_source": "locust_test_start_stop",
    "response_time_source": "Locust locust_stats.csv",
    "percentile_source": "Locust locust_stats.csv",
    "throughput_source": "Locust locust_stats.csv",
    "request_count_source": "Locust locust_stats.csv",
    "failure_and_error_rate_source": "Locust locust_stats.csv",
    "total_test_time_source": "Locust test_start/test_stop events",
    "sample_interval_seconds": $METRICS_SAMPLE_INTERVAL_SECONDS,
    "container_primary_source": "cAdvisor via Prometheus",
    "container_cpu_source": "cAdvisor via Prometheus",
    "container_memory_source": "cAdvisor via Prometheus",
    "cadvisor_summary_file": "cadvisor_summary.csv",
    "docker_stats_source": "continuous docker stats (complementary or contingency)",
    "docker_stats_summary_file": "docker_stats_summary.csv",
    "postgresql_metrics_source": "postgres-exporter via Prometheus query_range",
    "postgresql_summary_file": "postgres_summary.csv",
    "prometheus_series_file": "prometheus_series.json",
    "started_epoch": $METRICS_START_EPOCH,
    "finished_epoch": $METRICS_END_EPOCH
  },
  "notes": "$NOTES"
}
JSON

if [ "$RUN_MODE" = official ] && [ "$MEASUREMENT_STABLE" != true ]; then
  echo "A medicao oficial ficou instavel e foi registrada como non_official." >&2
  exit 2
fi

docker compose stop "$API_SERVICE"
API_STARTED=false

echo "Rodada concluida: $RESULT_DIR"
