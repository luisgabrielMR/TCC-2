---
name: perfil-de-carga
description: Como criar ou alterar um perfil de carga do benchmark (fixed_*, saturation_*, capacity_*) sem quebrar metade do projeto. Existem dois runners paralelos, Bash e PowerShell, que precisam ser espelhados, mais os consolidadores, o menu e o preflight. Use ao adicionar degrau de usuarios, mudar pacing, mudar alvo de RPS ou mexer no locustfile.
when_to_use: Pedidos como "criar um perfil novo", "adicionar degrau de 800 usuarios", "mudar o pacing", "mudar o alvo de req/s", "o perfil nao aparece", "a rodada nao foi detectada", "mexer no locustfile", "LOCUST_PROCESSES"
paths: scripts/run_one_language.sh, scripts/run_warmup.sh, scripts/run_capacity_battery.sh, scripts/calibrate_load_generator.sh, launchers/windows/powershell/*.ps1, load-tests/locust/**, docker-compose.yml
---

# Mexer em perfil de carga

**O runner existe duas vezes.** `scripts/run_one_language.sh` e `launchers/windows/powershell/rodar-linguagem.ps1` sao implementacoes paralelas completas, cada uma com seu proprio mapeamento de perfil, pasta de resultado e metadata. Mudar so um lado deixa o projeto silenciosamente inconsistente — o Windows e o caminho que roda de verdade.

## Checklist ao adicionar ou mudar um perfil

1. `scripts/run_one_language.sh`, bloco `case "$LOAD_PROFILE"`: usuarios, spawn rate, `LOCUST_WAIT_SECONDS` e `LOAD_TARGET_RPS` (vazio fora dos perfis de taxa fixa).
2. `rodar-linguagem.ps1`: o mesmo mapeamento **e** o `[ValidateSet(...)]` do parametro `-LoadProfile`. Perfil fora do ValidateSet e rejeitado antes de rodar.
3. Pasta de resultado: perfis `capacity_*`, `saturation_*` e `fixed_*` gravam em `mixed_<perfil>`; os demais em `mixed`. Vale nos dois runners.
4. `menu-testes.ps1`, `Get-ResultScenarioName`: a deteccao de rodada concluida le essa pasta. Se ficar desatualizada, o menu nunca acha as rodadas e repete a mesma para sempre.
5. `benchmark_kind`: `fixed_rate`, `saturation`, `capacity` ou `controlled_load`. Alimenta as notas do metadata e os relatorios.
6. Consolidadores, se o cenario for novo: `scripts/summarize_results.py` (`scalable_prefixes`) e `scripts/generate_results_dashboard.py`. Fora dos prefixos conhecidos, o cenario some do relatorio de escalabilidade.

## Armadilhas ja pagas

- **Divisao por zero.** `THEORETICAL_RPS_CEILING` divide usuarios por `wait_seconds`. Com pacing 0 tem que gravar `null`, nao calcular.
- **Aquecimento com pacing diferente.** `run_warmup.sh` e outro processo e leria o padrao do `.env`. `LOCUST_WAIT_SECONDS` precisa estar exportado.
- **Payload duplicado com `--processes`.** Cada processo Locust le `customers_create.jsonl` do inicio. Sem o sharding por faixa disjunta do `locustfile.py`, os `POST /customers` colidem em email e documento e viram 409 artificiais. `LOCUST_PROCESSES` tem que chegar ao container junto do `--processes`.
- **CSV sobrescrito com `--processes`.** Os workers herdam o mesmo `--csv`. Os listeners que escrevem arquivo so podem rodar no master — guarda `WorkerRunner` no `locustfile.py`.
- **Cota de CPU.** Mudou `cpus` no `docker-compose.yml`? Atualize `EXPECTED_CPU_LIMITS` em `scripts/preflight.py`, senao o preflight oficial bloqueia. As cotas sao limites maximos, nao reservas exclusivas; o Docker precisa expor capacidade agregada suficiente para API, PostgreSQL e Locust ativos ao mesmo tempo.

## Verificar antes de commitar

```bash
bash -n scripts/run_one_language.sh scripts/run_warmup.sh scripts/run_capacity_battery.sh scripts/calibrate_load_generator.sh
python3 -m py_compile scripts/preflight.py scripts/summarize_results.py scripts/generate_results_dashboard.py load-tests/locust/locustfile.py
python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"
PYTHONPATH=. python3 tests/test_benchmark_tools.py && PYTHONPATH=. python3 tests/test_results_exporter.py
```

Confira que os dois runners concordam perfil a perfil em usuarios, spawn rate e pacing.

Os `.ps1` sao CRLF por `.gitattributes`. Editor que salva LF gera diff do arquivo inteiro — verifique com `git diff --stat` que nao aparece aviso de conversao de fim de linha.
