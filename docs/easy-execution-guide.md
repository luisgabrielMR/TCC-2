# Guia de execucao facil

Na metodologia 17, `OFFICIAL_MINIMUM_CADVISOR_COVERAGE_PERCENT=95` define a
cobertura mínima de CPU e memória do cAdvisor para API, PostgreSQL e Locust.
Séries com lacunas maiores que 1,5 s são rejeitadas mesmo com cobertura
suficiente. O scrape permanece em 1 s; o housekeeping interno usa base de
200 ms para acomodar o jitter do cAdvisor 0.49.1. O preflight confere também
os intervalos reais antes da carga, conforme o [diagnóstico da correção](monitoring-cadvisor-20261006.md).

Use verificação e preflight do novo protocolo/commit. A calibração health-only
permanece opcional no preflight atual; se usada, deve corresponder à metodologia
17 e ao mesmo commit. Referências à calibração obrigatória abaixo descrevem o
fluxo histórico; consulte [as notas atuais](methodological-notes.md).

## Windows

Abra o Docker Desktop manualmente e aguarde `Docker Engine running`. Depois use somente um destes atalhos em `launchers/windows/`:

- `00_MENU_TESTES.bat`: menu inicial com verificacao, calibracao, rodada oficial, Grafana e opcoes avancadas.
- `01_VERIFICAR_PROJETO.bat`: verificacao completa sem gerar resultado oficial.
- `02_PROXIMA_RODADA_OFICIAL.bat`: próxima etapa da campanha oficial; alterna
  os perfis `fixed_50` e `fixed_100` conforme o plano de rodadas.
- `03_ABRIR_GRAFANA.bat`: abre os dois dashboards.
- `04_MENU_AVANCADO.bat`: preparacao, pilotos e capacidade.

O fluxo oficial possui cinco rodadas completas. Cada rodada executa Python, Node.js, Java, Go e .NET sequencialmente, com ordem rotacionada, warmup de 300 segundos e medicao de 5 minutos por API. O atalho detecta a proxima rodada incompleta, ignora linguagens ja concluidas como `official` e nunca sobrescreve `run_N` existente.

Antes da primeira rodada, o Git deve estar limpo, `01_VERIFICAR_PROJETO.bat` deve ter sido executado no mesmo commit e a opcao `Calibrar gerador de carga` deve concluir no mesmo ambiente. O atalho oficial realiza um preflight estrito antes da confirmacao e nao inicia carga quando Docker, Git, verificacao, calibracao, cotas, imagens ou monitoramento estiverem divergentes.

Os pilotos e a escada de saturacao ficam no menu avancado e sao gravados como `non_official` por padrao.

## WSL/Linux

Use `./launchers/linux-wsl/menu-testes.sh` ou os scripts individuais para diagnosticos e pilotos:

```bash
./launchers/linux-wsl/subir-postgres.sh
./launchers/linux-wsl/preparar-banco.sh
./launchers/linux-wsl/gerar-payloads.sh
./launchers/linux-wsl/validar-banco.sh
./launchers/linux-wsl/rodar-linguagem.sh python mixed 0 fixed_100 pilot
./launchers/linux-wsl/testar-todas-sequencialmente.sh
```

O procedimento oficial simplificado e retomavel descrito acima e o fluxo Windows usado neste ambiente experimental.
