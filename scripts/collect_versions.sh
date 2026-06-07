#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

mkdir -p results/summaries

version_or_missing() {
  local label="$1"
  shift
  if command -v "$1" >/dev/null 2>&1; then
    "$@" 2>&1 | head -n 1
  else
    echo "not_found"
  fi
}

OS_VERSION="$(uname -a 2>/dev/null || ver 2>/dev/null || echo unknown)"
DOCKER_VERSION="$(version_or_missing Docker docker --version)"
COMPOSE_VERSION="$(docker compose version 2>/dev/null | head -n 1 || echo not_found)"
PYTHON_VERSION="$(version_or_missing Python python3 --version)"
if [ "$PYTHON_VERSION" = "not_found" ]; then PYTHON_VERSION="$(version_or_missing Python python --version)"; fi
NODE_VERSION="$(version_or_missing Node node --version)"
JAVA_VERSION="$(version_or_missing Java java -version)"
GO_VERSION="$(version_or_missing Go go version)"
DOTNET_VERSION="$(version_or_missing Dotnet dotnet --version)"
POSTGRES_IMAGE="${POSTGRES_IMAGE:-postgres:17}"
LOCUST_IMAGE="${LOCUST_IMAGE:-locustio/locust:2.32.6}"
PROMETHEUS_IMAGE="${PROMETHEUS_IMAGE:-prom/prometheus:v2.55.1}"
GRAFANA_IMAGE="${GRAFANA_IMAGE:-grafana/grafana:11.3.0}"

cat > docs/environment-versions.md <<MD
# Versões do ambiente

Arquivo atualizado por \`scripts/collect_versions.sh\`.

## Versões coletadas

| Item | Versão |
| --- | --- |
| Sistema operacional | \`$OS_VERSION\` |
| Docker | \`$DOCKER_VERSION\` |
| Docker Compose | \`$COMPOSE_VERSION\` |
| PostgreSQL | \`$POSTGRES_IMAGE\` |
| Python | \`$PYTHON_VERSION\` |
| Node.js | \`$NODE_VERSION\` |
| Java/JDK | \`$JAVA_VERSION\` |
| Go | \`$GO_VERSION\` |
| .NET SDK | \`$DOTNET_VERSION\` |
| Locust | \`$LOCUST_IMAGE\` |
| Prometheus | \`$PROMETHEUS_IMAGE\` |
| Grafana | \`$GRAFANA_IMAGE\` |

## Bibliotecas mínimas planejadas

| Linguagem | HTTP | PostgreSQL | Pool | Justificativa |
| --- | --- | --- | --- | --- |
| Python | FastAPI + Uvicorn | psycopg3 | psycopg_pool | Expor HTTP e JSON com pouco código, mantendo SQL explícito. |
| Node.js | Express | pg | pg.Pool | Roteamento simples e driver PostgreSQL direto. |
| Java | Javalin ou HTTP simples | JDBC | HikariCP | Evita Spring Data/JPA e mantém controle direto do SQL. |
| Go | net/http | database/sql + driver PostgreSQL | database/sql | Biblioteca padrão para HTTP e pooling configurado no próprio \`sql.DB\`. |
| C#/.NET | Minimal API | Npgsql | NpgsqlDataSource/pooling Npgsql | Estrutura mínima do ASP.NET Core sem Entity Framework. |

## Variáveis de pool

| Variável | Valor base |
| --- | --- |
| \`DB_POOL_MIN\` | $DB_POOL_MIN |
| \`DB_POOL_MAX\` | $DB_POOL_MAX |
| \`DB_POOL_ACQUIRE_TIMEOUT_SECONDS\` | $DB_POOL_ACQUIRE_TIMEOUT_SECONDS |
| \`DB_POOL_IDLE_TIMEOUT_SECONDS\` | $DB_POOL_IDLE_TIMEOUT_SECONDS |
| \`DB_POOL_MAX_LIFETIME_SECONDS\` | $DB_POOL_MAX_LIFETIME_SECONDS |
MD

PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" - "$OS_VERSION" "$DOCKER_VERSION" "$COMPOSE_VERSION" "$POSTGRES_IMAGE" "$PYTHON_VERSION" "$NODE_VERSION" "$JAVA_VERSION" "$GO_VERSION" "$DOTNET_VERSION" "$LOCUST_IMAGE" "$PROMETHEUS_IMAGE" "$GRAFANA_IMAGE" > results/summaries/environment-versions.json <<'PY'
import json
import sys

keys = [
    "os",
    "docker",
    "docker_compose",
    "postgres",
    "python",
    "node",
    "java",
    "go",
    "dotnet",
    "locust",
    "prometheus",
    "grafana",
]
print(json.dumps(dict(zip(keys, sys.argv[1:])), indent=2, ensure_ascii=False))
PY

echo "Versoes registradas em docs/environment-versions.md e results/summaries/environment-versions.json"
