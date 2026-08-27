# Guia de execucao facil

## Windows

Abra o Docker Desktop manualmente e aguarde `Docker Engine running`. Depois use somente um destes atalhos em `launchers/windows/`:

- `00_MENU_TESTES.bat`: menu inicial com as quatro acoes principais.
- `01_VERIFICAR_PROJETO.bat`: verificacao completa sem gerar resultado oficial.
- `02_PROXIMA_RODADA_OFICIAL.bat`: proxima rodada oficial `controlled_50`.
- `03_ABRIR_GRAFANA.bat`: abre os dois dashboards.
- `04_MENU_AVANCADO.bat`: preparacao, pilotos e capacidade.

O fluxo oficial possui cinco rodadas completas. Cada rodada executa Python, Node.js, Java, Go e .NET sequencialmente, com ordem rotacionada, warmup de 300 segundos e medicao de 5 minutos por API. O atalho detecta a proxima rodada incompleta, ignora linguagens ja concluidas como `official` e nunca sobrescreve `run_N` existente.

Antes da primeira rodada, o Git deve estar limpo e `01_VERIFICAR_PROJETO.bat` deve ter sido executado no mesmo commit. O atalho oficial realiza um preflight estrito antes da confirmacao e nao inicia carga quando Docker, Git, verificacao, imagens ou monitoramento estiverem divergentes.

Os pilotos e testes de 100/200 usuarios ficam no menu avancado e sao gravados como `non_official`.

## WSL/Linux

Use `./launchers/linux-wsl/menu-testes.sh` ou os scripts individuais para diagnosticos e pilotos:

```bash
./launchers/linux-wsl/subir-postgres.sh
./launchers/linux-wsl/preparar-banco.sh
./launchers/linux-wsl/gerar-payloads.sh
./launchers/linux-wsl/validar-banco.sh
./launchers/linux-wsl/rodar-linguagem.sh python mixed 0 controlled_50 pilot
./launchers/linux-wsl/testar-todas-sequencialmente.sh
```

O procedimento oficial simplificado e retomavel descrito acima e o fluxo Windows usado neste ambiente experimental.
