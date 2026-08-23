# Runbook

## Antes de tudo

Abra o Docker Desktop manualmente e aguarde o Engine ficar ativo. A verificacao do projeto e os pilotos nao sao rodadas oficiais.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/verificar-projeto.ps1
```

Cada execucao preserva suas evidencias em uma nova pasta `results/raw/verification/<data-hora>/`; a verificacao nao remove diagnosticos anteriores nem regrava resultados experimentais.

Esse fluxo constroi as cinco APIs, reseta somente `benchmark_db`, valida banco/OpenAPI/Grafana, compara contrato e estado final, testa erro de banco, pool Go, monitoramento, warmup curto e consolidadores.

## Preflight

```bash
python scripts/preflight.py --mode pilot --output results/summaries/preflight.json
python scripts/preflight.py --mode official --output results/summaries/preflight-official.json
```

`official` falha se Docker/Compose divergirem, Git estiver sujo, imagens nao estiverem fixadas, runtimes/hardware nao puderem ser confirmados ou `results/summaries/project-verification.json` nao comprovar a verificacao completa no mesmo commit limpo. Depois de iniciar monitoramento, API e Locust, `scripts/validate_monitoring.py` exige os tres targets operacionais, exporter de resultados ativo, os dois dashboards provisionados e, para classificacao oficial, target cAdvisor e series de CPU/memoria para os tres containers.

## Piloto

Linux/WSL:

```bash
./scripts/run_one_language.sh python mixed 0 controlled_50 pilot
```

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/rodar-linguagem.ps1 -Language python -Scenario mixed -RunNumber 0 -LoadProfile controlled_50 -RunMode pilot
```

Pilotos geram `result_classification=non_official`. Eles podem validar fluxo e observar valores, mas nao entram no dashboard oficial.

## Congelar o Docker

O ambiente registrado usa Docker 29.7.2/Compose 5.3.1, que sao as versoes instaladas neste host e as declaradas na Tabela 1 do TCC. Nao ha troca a fazer. Antes da bateria, siga `docs/environment-versions.md`: desative a atualizacao automatica do Docker Desktop, preserve 4 CPUs/8 GB na VM WSL2 e confirme os valores com `docker version`, `docker compose version` e `docker info`. Nao execute a bateria se Engine e Compose nao forem exatamente 29.7.2/5.3.1.

## Bateria oficial

Somente depois de revisar/versionar as mudancas, obter Git limpo, confirmar Docker 29.7.2/Compose 5.3.1 com a atualizacao automatica desligada e executar novamente a verificacao completa nesse ambiente e no mesmo commit. Entao use:

```bash
./scripts/run_capacity_battery.sh
```

No Windows, use `18_BATERIA_50_100_200.bat`. A bateria executa tres repeticoes dos perfis 50, 100 e 200, rotaciona a ordem das cinco linguagens e bloqueia no primeiro requisito oficial ausente.

## Monitoramento

```bash
docker compose --profile monitoring up -d postgres postgres-exporter benchmark-results-exporter prometheus grafana cadvisor
```

- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`

O dashboard `Resultados Oficiais` filtra somente `official` e mostra carga, latencia, taxa de erro, CPU, memoria e o resumo historico do PostgreSQL. O dashboard `Monitoramento e Diagnostico` permite filtrar classificacao, metodologia, rodada, cenario, perfil, linguagem e endpoint. `docker stats` e complementar; cAdvisor e obrigatorio para oficial.

## Resultados

```bash
python scripts/summarize_results.py
python scripts/generate_results_dashboard.py
```

`summarize_results.py` publica somente `official` por padrao. Os CSVs mantem linguagem, metodo, endpoint, cenario, perfil, usuarios, rodada, metodologia, classificacao e metricas de recursos aplicaveis. Sem rodadas oficiais, eles contem apenas o cabecalho atual e `final_summary.md` declara a ausencia de dados. Cada rodada tambem preserva `postgres_summary.csv` e as origens das metricas no `metadata.json`. Historicos e `results/archive` nao sao apagados.

## Encerramento

```bash
docker compose down
```

Encerre os containers sem remover volumes. O reset oficial atua somente em `benchmark_db`.
