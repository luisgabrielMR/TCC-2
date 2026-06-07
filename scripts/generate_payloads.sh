#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" database/scripts/generate_test_payloads.py
