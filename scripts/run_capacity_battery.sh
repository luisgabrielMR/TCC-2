#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

# fixed_200 pertence exclusivamente a bateria oficial de cinco rodadas. Esta
# bateria separada responde apenas "qual o limite observado de cada API" e nao
# pode introduzir repeticoes extras na coorte de taxa fixa.
IFS=' ' read -r -a profiles <<< "${BENCHMARK_PROFILES:-saturation_25 saturation_50 saturation_100 saturation_200 saturation_400}"
for profile in "${profiles[@]}"; do
  if [[ "$profile" != saturation_* ]]; then
    echo "BENCHMARK_PROFILES aceita somente perfis saturation_* nesta bateria." >&2
    exit 2
  fi
done
CAPACITY_RUN_MODE="${CAPACITY_RUN_MODE:-pilot}"
if [ "$CAPACITY_RUN_MODE" != pilot ] && [ "$CAPACITY_RUN_MODE" != official ]; then
  echo "CAPACITY_RUN_MODE deve ser pilot ou official." >&2
  exit 2
fi
for round in $(seq 1 "$BENCHMARK_REPETITIONS"); do
  for profile_index in "${!profiles[@]}"; do
    profile="${profiles[$profile_index]}"
    offset=$(((round - 1 + profile_index * 2) % 5))
    echo "Iniciando perfil $profile, repeticao $round/$BENCHMARK_REPETITIONS, ordem deslocada $offset."
    "$SCRIPT_DIR/run_all_languages_sequentially.sh" mixed 0 "$profile" "$offset" "${profile}_round_${round}" "$CAPACITY_RUN_MODE"
  done
done

PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" "$SCRIPT_DIR/summarize_results.py"
"$PYTHON_BIN" "$SCRIPT_DIR/generate_results_dashboard.py"
