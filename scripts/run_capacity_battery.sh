#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

for profile in controlled_50 capacity_100 capacity_200; do
  echo "Iniciando perfil $profile para as cinco APIs."
  "$SCRIPT_DIR/run_all_languages_sequentially.sh" mixed 0 "$profile"
done

PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" "$SCRIPT_DIR/summarize_results.py"
"$PYTHON_BIN" "$SCRIPT_DIR/generate_results_dashboard.py"
