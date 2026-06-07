#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

require_command docker

docker compose up -d postgres
wait_for_postgres
run_psql_file /benchmark/database/reset/reset_database.sql

echo "Banco restaurado para o estado inicial conhecido."
