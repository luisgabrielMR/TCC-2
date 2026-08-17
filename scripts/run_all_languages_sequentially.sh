#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_NAME="${1:-mixed}"
RUN_NUMBER="${2:-0}"
LOAD_PROFILE="${3:-controlled_50}"

for language in python node java go dotnet; do
  echo "Executando $language, cenario $SCENARIO_NAME, perfil $LOAD_PROFILE, rodada $RUN_NUMBER"
  "$SCRIPT_DIR/run_one_language.sh" "$language" "$SCENARIO_NAME" "$RUN_NUMBER" "$LOAD_PROFILE"
done
