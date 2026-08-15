#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

mkdir -p results/summaries

first_line_or_missing() {
  if command -v "$1" >/dev/null 2>&1; then
    shift
    "$@" 2>&1 | head -n 1
  else
    echo "not_found"
  fi
}

OS_VERSION="$(uname -a 2>/dev/null || echo unknown)"
DOCKER_VERSION="$(first_line_or_missing docker docker --version)"
COMPOSE_VERSION="$(docker compose version 2>/dev/null | head -n 1 || echo not_found)"
POSTGRES_VERSION="$(docker compose exec -T postgres postgres --version 2>/dev/null | head -n 1 || echo "${POSTGRES_IMAGE:-postgres:17}")"

PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" - "$OS_VERSION" "$DOCKER_VERSION" "$COMPOSE_VERSION" "$POSTGRES_VERSION" > results/summaries/environment-versions.json <<'PY'
import json
import sys

data = {
    "collected": {
        "os": sys.argv[1],
        "docker": sys.argv[2],
        "docker_compose": sys.argv[3],
        "postgres": sys.argv[4],
    },
    "configured": {
        "python": "3.12.14; FastAPI 0.115.6; Uvicorn 0.34.0; psycopg 3.2.3; psycopg_pool 3.2.4",
        "node": "22.23.2; Express 4.22.2; pg 8.13.1",
        "java": "Temurin 21.0.11+10 LTS; Jackson 2.17.2; PostgreSQL JDBC 42.7.4; HikariCP 5.1.0",
        "go": "1.23.12; lib/pq 1.10.9",
        "dotnet": "8.0.30; Npgsql 8.0.5",
        "locust": "2.32.6",
        "prometheus": "2.55.1",
        "grafana": "11.3.0",
        "postgres_exporter": "0.15.0",
        "cadvisor": "0.49.1",
    },
}
print(json.dumps(data, indent=2, ensure_ascii=True))
PY

echo "Versoes registradas em results/summaries/environment-versions.json."
echo "O catalogo versionado esta em docs/environment-versions.md."
