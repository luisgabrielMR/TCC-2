#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ".env"
  set +a
fi

POSTGRES_DB="${POSTGRES_DB:-benchmark_db}"
POSTGRES_USER="${POSTGRES_USER:-benchmark_user}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-benchmark_password}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
LOCUST_HOST="${LOCUST_HOST:-http://host.docker.internal:8000}"

DB_POOL_MIN="${DB_POOL_MIN:-1}"
DB_POOL_MAX="${DB_POOL_MAX:-20}"
DB_POOL_ACQUIRE_TIMEOUT_SECONDS="${DB_POOL_ACQUIRE_TIMEOUT_SECONDS:-10}"
DB_POOL_IDLE_TIMEOUT_SECONDS="${DB_POOL_IDLE_TIMEOUT_SECONDS:-60}"
DB_POOL_MAX_LIFETIME_SECONDS="${DB_POOL_MAX_LIFETIME_SECONDS:-1800}"

LOCUST_USERS="${LOCUST_USERS:-50}"
LOCUST_SPAWN_RATE="${LOCUST_SPAWN_RATE:-10}"
LOCUST_DURATION="${LOCUST_DURATION:-5m}"
LOCUST_WAIT_SECONDS="${LOCUST_WAIT_SECONDS:-0.1}"
# Um processo Locust satura um core (gevent). Sem varios processos o gerador
# vira o gargalo antes das APIs rapidas.
LOCUST_PROCESSES="${LOCUST_PROCESSES:-4}"
WARMUP_DURATION_SECONDS="${WARMUP_DURATION_SECONDS:-300}"
WARMUP_STABILITY_WINDOW_SECONDS="${WARMUP_STABILITY_WINDOW_SECONDS:-45}"
WARMUP_MAX_RPS_DRIFT_PERCENT="${WARMUP_MAX_RPS_DRIFT_PERCENT:-10}"
METRICS_SAMPLE_INTERVAL_SECONDS="${METRICS_SAMPLE_INTERVAL_SECONDS:-2}"
BENCHMARK_REPETITIONS="${BENCHMARK_REPETITIONS:-3}"
METHODOLOGY_VERSION="${METHODOLOGY_VERSION:-9}"
OFFICIAL_PROFILE="${OFFICIAL_PROFILE:-fixed_200}"
OFFICIAL_ROUNDS="${OFFICIAL_ROUNDS:-5}"
LOAD_GENERATOR_CALIBRATION_FILE="${LOAD_GENERATOR_CALIBRATION_FILE:-results/summaries/load-generator-calibration.json}"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Comando obrigatorio nao encontrado: $command_name" >&2
    exit 127
  fi
}

wait_for_postgres() {
  echo "Aguardando PostgreSQL ficar pronto..."
  for _ in $(seq 1 60); do
    if docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      echo "PostgreSQL pronto."
      return 0
    fi
    sleep 2
  done
  echo "PostgreSQL nao ficou pronto dentro do tempo esperado." >&2
  exit 1
}

run_psql_file() {
  local container_path="$1"
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$container_path"
}

python_bin() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    echo "Python nao encontrado. Instale Python 3 ou configure PATH." >&2
    exit 127
  fi
}

api_service_for_language() {
  case "$1" in
    python) echo "python-api" ;;
    node) echo "node-api" ;;
    java) echo "java-api" ;;
    go) echo "go-api" ;;
    dotnet) echo "dotnet-api" ;;
    *)
      echo "Linguagem invalida: $1" >&2
      echo "Use: python, node, java, go ou dotnet." >&2
      exit 2
      ;;
  esac
}

wait_for_api() {
  local base_url="${1:-$API_BASE_URL}"
  echo "Aguardando API em $base_url ..."
  for _ in $(seq 1 60); do
    if curl -fsS "$base_url/health" >/dev/null 2>&1; then
      echo "API pronta."
      return 0
    fi
    sleep 2
  done
  echo "API nao respondeu em $base_url dentro do tempo esperado." >&2
  exit 1
}
