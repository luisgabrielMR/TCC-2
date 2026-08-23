# Guia de execucao facil

## Windows

Abra `launchers/windows/00_MENU_TESTES.bat` e escolha uma opcao pelo numero. Os atalhos PowerShell sao nativos do Windows e nao dependem de Bash ou WSL.

- `01_SUBIR_POSTGRES.bat`: sobe o PostgreSQL.
- `02_PREPARAR_BANCO.bat`: executa schema, seed e indices.
- `03_GERAR_PAYLOADS.bat`: gera os arquivos JSONL.
- `04_VALIDAR_BANCO.bat`: valida tabelas, indices e contagens.
- `05_TESTAR_PAYLOADS_API_ATIVA.bat`: testa os oito endpoints.
- `06_RODAR_WARMUP_API_ATIVA.bat`: executa warmup.
- `07` a `11`: pilotos de uma linguagem no cenario mixed.
- `12_TESTAR_TODAS_SEQUENCIALMENTE.bat`: piloto com uma linguagem por vez.
- `13_RESUMIR_RESULTADOS.bat`: gera resumos.
- `14_VERIFICAR_PROJETO_COMPLETO.bat`: compila e valida banco, cinco APIs, monitoramento e Locust.
- `15_GERAR_GRAFICOS.bat`: gera o painel comparativo e abre no navegador.
- `16_CAPACIDADE_100_USUARIOS.bat`: piloto das cinco APIs com 100 usuarios.
- `17_CAPACIDADE_200_USUARIOS.bat`: piloto das cinco APIs com 200 usuarios.
- `18_BATERIA_50_100_200.bat`: solicita bateria oficial, tres repeticoes, rotacao e preflight estrito.

Os atalhos `07` a `12`, `16` e `17` gravam `non_official`. O atalho `18` so inicia com Docker 29.5.2, Compose 5.1.4, Git limpo e cAdvisor validado. Todos selecionam uma nova pasta `run_N` automaticamente.

## WSL/Linux

Use `./launchers/linux-wsl/menu-testes.sh` ou os atalhos individuais:

```bash
./launchers/linux-wsl/subir-postgres.sh
./launchers/linux-wsl/preparar-banco.sh
./launchers/linux-wsl/gerar-payloads.sh
./launchers/linux-wsl/validar-banco.sh
./launchers/linux-wsl/testar-payloads-api-ativa.sh
./launchers/linux-wsl/rodar-linguagem.sh python mixed 0 controlled_50 pilot
./launchers/linux-wsl/testar-todas-sequencialmente.sh
./scripts/run_all_languages_sequentially.sh mixed 0 capacity_100
./scripts/run_all_languages_sequentially.sh mixed 0 capacity_200
./scripts/run_capacity_battery.sh
```

Abra o Docker Desktop antes dos atalhos Windows. O cAdvisor ja foi validado por ID real, mas o estado atual deste host ainda nao atende as versoes Docker/Compose nem o Git limpo exigidos para oficial; use pilotos ate corrigir o ambiente externamente e versionar as mudancas.
