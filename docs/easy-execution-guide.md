# Guia de execução fácil

## Windows

O caminho principal é:

```text
launchers/windows/00_MENU_TESTES.bat
```

Abra esse arquivo com duplo clique e escolha uma opção pelo número.

Atalhos diretos:

- `01_SUBIR_POSTGRES.bat`: sobe o PostgreSQL.
- `02_PREPARAR_BANCO.bat`: executa schema, seed e índices.
- `03_GERAR_PAYLOADS.bat`: gera arquivos JSONL.
- `04_VALIDAR_BANCO.bat`: valida tabelas, índices e contagens.
- `05_TESTAR_PAYLOADS_API_ATIVA.bat`: testa endpoints com payloads prontos.
- `06_RODAR_WARMUP_API_ATIVA.bat`: executa warmup.
- `07_TESTE_PYTHON_MIXED.bat`: prepara rodada Python.
- `08_TESTE_NODE_MIXED.bat`: prepara rodada Node.js.
- `09_TESTE_JAVA_MIXED.bat`: prepara rodada Java.
- `10_TESTE_GO_MIXED.bat`: prepara rodada Go.
- `11_TESTE_DOTNET_MIXED.bat`: prepara rodada .NET.
- `12_TESTAR_TODAS_SEQUENCIALMENTE.bat`: executa uma linguagem por vez.
- `13_RESUMIR_RESULTADOS.bat`: gera resumos.

## WSL/Linux

Use:

```bash
./launchers/linux-wsl/menu-testes.sh
```

Ou chame os atalhos individuais:

```bash
./launchers/linux-wsl/subir-postgres.sh
./launchers/linux-wsl/preparar-banco.sh
./launchers/linux-wsl/gerar-payloads.sh
./launchers/linux-wsl/validar-banco.sh
./launchers/linux-wsl/testar-payloads-api-ativa.sh
./launchers/linux-wsl/rodar-linguagem.sh python mixed 1
./launchers/linux-wsl/testar-todas-sequencialmente.sh
```
