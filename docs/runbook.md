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
python scripts/preflight.py --mode official --api-service python-api --load-profile fixed_200 --output results/summaries/preflight-official.json
```

`official` falha se Docker/Compose divergirem, Git estiver sujo, imagens nao estiverem fixadas, cotas efetivas divergirem, runtimes/hardware nao puderem ser confirmados, a calibracao do gerador estiver ausente ou `results/summaries/project-verification.json` nao comprovar a verificacao completa no mesmo commit limpo. Depois de iniciar monitoramento, API e Locust, `scripts/validate_monitoring.py` exige os tres targets operacionais, exporter de resultados ativo, os dois dashboards provisionados e, para classificacao oficial, target cAdvisor e series de CPU/memoria para os tres containers.

## Piloto

Linux/WSL:

```bash
./scripts/run_one_language.sh python mixed 0 fixed_200 pilot
```

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/rodar-linguagem.ps1 -Language python -Scenario mixed -RunNumber 0 -LoadProfile fixed_200 -RunMode pilot
```

Pilotos geram `result_classification=non_official`. Eles podem validar fluxo e observar valores, mas nao entram no dashboard oficial.

## Congelar o Docker

A versao mais recente do TCC exige Docker 29.5.2/Compose 5.1.4. O host auditado estava em 29.7.2/5.3.1; ajuste as versoes manualmente, desative as atualizacoes automaticas do Docker Desktop e confirme versoes, CPU, memoria, kernel e storage driver com comandos reais antes da bateria.

## Bateria oficial

Somente depois de revisar/versionar as mudancas, obter Git limpo, confirmar Docker 29.5.2/Compose 5.1.4, executar novamente a verificacao completa e calibrar o gerador nesse mesmo commit e ambiente.

No menu simples, execute primeiro `Calibrar gerador de carga`. O processo usa apenas `/health`, pacing zero, cinco degraus de 60 s e cAdvisor. O artefato e sempre nao oficial; ele apenas demonstra que o Locust tem folga suficiente para instrumentar as rodadas.

No Windows, use `02_PROXIMA_RODADA_OFICIAL.bat`. Cada duplo clique executa uma das cinco rodadas oficiais do perfil `fixed_200`. Uma rodada mede as cinco linguagens sequencialmente, com ordem rotacionada, e leva aproximadamente 55 a 75 minutos. O runner detecta a proxima rodada incompleta e retoma somente as linguagens ainda ausentes do mesmo commit, metodologia e calibracao; mudancas nesses elementos criam uma campanha distinta.

O preflight `official` ocorre antes da confirmacao. Cada linguagem repete o contrato, valida o monitoramento por container e so grava `result_classification=official` quando a medicao permanece estavel, entrega pelo menos 97,5% do alvo, mantem a CPU media do Locust na janela abaixo de 90% da cota e usa no maximo 80% da capacidade calibrada. A bateria de saturacao permanece separada e e piloto por padrao.

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
## Revisao de medicao 8

A configuracao atual usa `METHODOLOGY_VERSION=9`. Depois de atualizar o codigo,
refaca a verificacao completa e a calibracao do gerador para o commit limpo.
Nao reutilize a verificacao ou a calibracao da revisao 7. O verificador inclui
esperas controladas de 12 e 33 segundos por API para conferir o limite SQL;
essas esperas sao diagnostico, nao resultados oficiais.

O PostgreSQL deve reportar `SHOW statement_timeout` como `30s`. O Compose aplica
essa configuracao ao recriar o servico; o preflight bloqueia valores diferentes.
Os novos resultados exigem estabilidade de RPS e de latencia media por endpoint.
As falhas de publicacao de CSV interrompem a execucao; os arquivos `locust_final_*`
sao preservados para diagnostico. Nao promova resultados manualmente para `official`.
