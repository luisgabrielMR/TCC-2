#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_NAME="${1:-mixed}"
RUN_NUMBER="${2:-0}"
LOAD_PROFILE="${3:-fixed_200}"
ORDER_OFFSET="${4:-0}"
SEQUENCE_ID="${5:-manual}"
RUN_MODE="${6:-pilot}"
CAMPAIGN_FINGERPRINT="${7:-manual}"

languages=(python node java go dotnet)
for index in 0 1 2 3 4; do
  language="${languages[$(((index + ORDER_OFFSET) % 5))]}"
  echo "Executando $language, cenario $SCENARIO_NAME, perfil $LOAD_PROFILE, rodada $RUN_NUMBER"
  BENCHMARK_SEQUENCE_ID="$SEQUENCE_ID" BENCHMARK_CAMPAIGN_FINGERPRINT="$CAMPAIGN_FINGERPRINT" BENCHMARK_ORDER_POSITION=$((index + 1)) \
    "$SCRIPT_DIR/run_one_language.sh" "$language" "$SCENARIO_NAME" "$RUN_NUMBER" "$LOAD_PROFILE" "$RUN_MODE"
done
