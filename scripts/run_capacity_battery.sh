#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

# fixed_200 responde "qual a latencia sob carga igual para todas"; a escada de
# saturacao responde "qual o limite de cada uma". Um perfil so nao responde as
# duas perguntas: com pacing, a vazao e do gerador, nao da API.
IFS=' ' read -r -a profiles <<< "${BENCHMARK_PROFILES:-fixed_200 saturation_50 saturation_100 saturation_200}"
for round in $(seq 1 "$BENCHMARK_REPETITIONS"); do
  for profile_index in "${!profiles[@]}"; do
    profile="${profiles[$profile_index]}"
    offset=$(((round - 1 + profile_index * 2) % 5))
    echo "Iniciando perfil $profile, repeticao $round/$BENCHMARK_REPETITIONS, ordem deslocada $offset."
    "$SCRIPT_DIR/run_all_languages_sequentially.sh" mixed 0 "$profile" "$offset" "${profile}_round_${round}" official
  done
done

PYTHON_BIN="$(python_bin)"
"$PYTHON_BIN" "$SCRIPT_DIR/summarize_results.py"
"$PYTHON_BIN" "$SCRIPT_DIR/generate_results_dashboard.py"
