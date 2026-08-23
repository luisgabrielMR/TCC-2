#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

mkdir -p results/summaries
PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" "$SCRIPT_DIR/preflight.py" --mode pilot --output results/summaries/environment-versions.json

echo "Versoes registradas em results/summaries/environment-versions.json."
echo "O catalogo versionado esta em docs/environment-versions.md."
