#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
./scripts/run_one_language.sh "${1:-python}" "${2:-mixed}" "${3:-1}"
