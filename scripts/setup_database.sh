#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

require_command docker

docker compose up -d postgres
wait_for_postgres

run_psql_file /benchmark/database/init/001_schema.sql
run_psql_file /benchmark/database/init/002_seed_base_data.sql
run_psql_file /benchmark/database/init/003_indexes.sql

echo "Banco preparado com schema, seed deterministico e indices."
