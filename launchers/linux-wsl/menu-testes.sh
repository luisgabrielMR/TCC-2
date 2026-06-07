#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

while true; do
  clear
  cat <<'MENU'
Menu de testes - TCC PostgreSQL Backend Benchmark

1  Subir PostgreSQL
2  Preparar banco
3  Gerar payloads
4  Validar banco
5  Testar payloads da API ativa
6  Rodar warmup da API ativa
7  Rodar Python mixed
8  Rodar Node.js mixed
9  Rodar Java mixed
10 Rodar Go mixed
11 Rodar .NET mixed
12 Rodar todas sequencialmente
13 Resumir resultados
0  Sair
MENU
  read -r -p "Escolha: " choice
  case "$choice" in
    1) ./launchers/linux-wsl/subir-postgres.sh ;;
    2) ./launchers/linux-wsl/preparar-banco.sh ;;
    3) ./launchers/linux-wsl/gerar-payloads.sh ;;
    4) ./launchers/linux-wsl/validar-banco.sh ;;
    5) ./launchers/linux-wsl/testar-payloads-api-ativa.sh ;;
    6) ./scripts/run_warmup.sh http://localhost:8000 ;;
    7) ./launchers/linux-wsl/rodar-linguagem.sh python mixed 1 ;;
    8) ./launchers/linux-wsl/rodar-linguagem.sh node mixed 1 ;;
    9) ./launchers/linux-wsl/rodar-linguagem.sh java mixed 1 ;;
    10) ./launchers/linux-wsl/rodar-linguagem.sh go mixed 1 ;;
    11) ./launchers/linux-wsl/rodar-linguagem.sh dotnet mixed 1 ;;
    12) ./launchers/linux-wsl/testar-todas-sequencialmente.sh ;;
    13)
      if command -v python3 >/dev/null 2>&1; then
        python3 scripts/summarize_results.py
      elif command -v python >/dev/null 2>&1; then
        python scripts/summarize_results.py
      else
        echo "Python nao encontrado."
      fi
      ;;
    0) break ;;
    *) echo "Opcao invalida" ;;
  esac
  read -r -p "Pressione Enter para continuar..."
done
