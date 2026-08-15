# Guia de execucao facil

## Windows

Abra `launchers/windows/00_MENU_TESTES.bat` e escolha uma opcao pelo numero. Os atalhos PowerShell sao nativos do Windows e nao dependem de Bash ou WSL.

- `01_SUBIR_POSTGRES.bat`: sobe o PostgreSQL.
- `02_PREPARAR_BANCO.bat`: executa schema, seed e indices.
- `03_GERAR_PAYLOADS.bat`: gera os arquivos JSONL.
- `04_VALIDAR_BANCO.bat`: valida tabelas, indices e contagens.
- `05_TESTAR_PAYLOADS_API_ATIVA.bat`: testa os oito endpoints.
- `06_RODAR_WARMUP_API_ATIVA.bat`: executa warmup.
- `07` a `11`: executam uma linguagem no cenario mixed.
- `12_TESTAR_TODAS_SEQUENCIALMENTE.bat`: executa uma linguagem por vez.
- `13_RESUMIR_RESULTADOS.bat`: gera resumos.
- `14_VERIFICAR_PROJETO_COMPLETO.bat`: compila e valida banco, cinco APIs, monitoramento e Locust.

## WSL/Linux

Use `./launchers/linux-wsl/menu-testes.sh` ou os atalhos individuais:

```bash
./launchers/linux-wsl/subir-postgres.sh
./launchers/linux-wsl/preparar-banco.sh
./launchers/linux-wsl/gerar-payloads.sh
./launchers/linux-wsl/validar-banco.sh
./launchers/linux-wsl/testar-payloads-api-ativa.sh
./launchers/linux-wsl/rodar-linguagem.sh python mixed 1
./launchers/linux-wsl/testar-todas-sequencialmente.sh
```
