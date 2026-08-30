# TCC PostgreSQL Backend Benchmark

Projeto experimental para comparar o desempenho de APIs backend equivalentes em Python, Node.js, Java, Go e C#/.NET acessando a mesma base PostgreSQL com SQL direto, pool de conexoes configurado explicitamente e sem ORM.

Esta base prepara o banco, contratos, payloads, scripts de validacao, warmup documentado, atalhos de execucao facil e as cinco APIs equivalentes.

## Execucao rapida da base

Requisitos para uso local:

- Docker e Docker Compose
- Python 3 para gerar payloads e resumir resultados
- `curl` para testes manuais
- Git

Para uma rodada oficial, a versao mais recente do TCC exige Docker Engine `29.5.2` e Docker Compose `5.1.4`. O preflight bloqueia qualquer diferenca; as versoes atualmente detectadas neste host devem ser ajustadas manualmente e a atualizacao automatica deve permanecer desligada durante a bateria.

## Configurar ambiente

Copie o arquivo de exemplo:

```bash
cp .env.example .env
```

O `.env.example` ja traz valores locais para estudo. Ajuste apenas se precisar mudar portas, usuario, senha local de laboratorio ou parametros de pool. Nao versionar `.env`.

## Subir apenas o PostgreSQL

```bash
docker compose up -d postgres
```

O servico usa a imagem definida em `.env.example` e expoe a porta `5432` por padrao.

## Criar banco, carregar seed e indices

```bash
./scripts/setup_database.sh
```

Esse script executa:

- `database/init/001_schema.sql`
- `database/init/002_seed_base_data.sql`
- `database/init/003_indexes.sql`

No Windows, abra `launchers/windows/04_MENU_AVANCADO.bat` e escolha `Preparar banco`.

## Gerar payloads prontos

```bash
./scripts/generate_payloads.sh
```

Arquivos gerados em `common/payloads/`:

- `customers_create.jsonl`
- `customers_update.jsonl`
- `orders_create.jsonl`
- `ids_customers.jsonl`
- `ids_products.jsonl`
- `ids_categories.jsonl`
- `ids_orders.jsonl`

No Windows, abra `launchers/windows/04_MENU_AVANCADO.bat` e escolha `Gerar payloads`.

## Validar banco

```bash
./scripts/validate_database.sh
```

O script confere tabelas, indices e contagens minimas. No Windows, use a opcao `Validar banco` do menu avancado.

## Resetar banco entre rodadas

```bash
./scripts/reset_db.sh
```

O reset volta o banco para o estado inicial conhecido, com seed deterministico e sequencias reiniciadas.

## Subir uma API especifica

As cinco APIs ja possuem implementacao inicial e `Dockerfile`. Os perfis do `docker-compose.yml` permitem subir uma linguagem por vez:

```bash
docker compose --profile python up -d --build python-api
docker compose --profile node up -d --build node-api
docker compose --profile java up -d --build java-api
docker compose --profile go up -d --build go-api
docker compose --profile dotnet up -d --build dotnet-api
```

Durante os testes, mantenha apenas uma API ativa por vez. A porta externa padrao e:

```text
http://127.0.0.1:8000
```

## Smoke test

Com uma API ativa:

```bash
./scripts/smoke_test_api.sh http://127.0.0.1:8000
```

O smoke test chama os endpoints principais com payloads pequenos. `scripts/contract_test_api.py` tambem compara corpos, erros, tipos e timestamps entre as cinco implementacoes. Esses testes nao substituem o warmup.

## Warmup

```bash
./scripts/run_warmup.sh
```

Configuracao padrao:

```text
WARMUP_DURATION_SECONDS=300
WARMUP_STABILITY_WINDOW_SECONDS=45
WARMUP_MAX_RPS_DRIFT_PERCENT=10
BENCHMARK_REPETITIONS=3
OFFICIAL_PROFILE=fixed_200
OFFICIAL_ROUNDS=5
METHODOLOGY_VERSION=7
```

`BENCHMARK_REPETITIONS` controla somente a bateria separada de saturacao. O atalho oficial usa `OFFICIAL_ROUNDS` e executa cinco rodadas completas do perfil `fixed_200`. Agregadores e dashboards tambem separam `campaign_fingerprint`, derivado de metodologia, commit e calibracao, para impedir mistura entre campanhas.

O warmup usa o mesmo cenario, usuarios, spawn rate e duracao para todas as linguagens, incluindo as rotas de escrita. As tres janelas finais sao comparadas e, se a variacao de RPS ultrapassar 10%, a rodada e interrompida em vez de alterar apenas uma linguagem. O warmup nao entra nos resultados principais e o banco e resetado sem reiniciar a API.

Os scripts no host usam `API_BASE_URL=http://127.0.0.1:8000`. Durante a medicao, o Locust acessa diretamente `http://{api-service}:8000` pela rede interna do Compose. `LOCUST_HOST_OVERRIDE` existe somente para pilotos comparativos pelo proxy do host.

## Rodada principal por linguagem

```bash
./scripts/run_one_language.sh python mixed 0 fixed_200 pilot
./scripts/run_one_language.sh node mixed 0 fixed_200 pilot
./scripts/run_one_language.sh java mixed 0 fixed_200 pilot
./scripts/run_one_language.sh go mixed 0 fixed_200 pilot
./scripts/run_one_language.sh dotnet mixed 0 fixed_200 pilot
```

Cada comando deve:

1. Resetar o banco.
2. Subir somente a API escolhida.
3. Executar smoke test.
4. Executar warmup.
5. Resetar o banco sem reiniciar a API.
6. Executar o teste principal.
7. Coletar metricas continuamente e finalizar os CSVs do Locust.
8. Salvar resultados e resetar novamente o banco.
9. Encerrar a API.

Na base atual, os comandos das cinco APIs ja podem ser usados quando o Docker estiver disponivel.

## Executar todas sequencialmente

```bash
./scripts/run_all_languages_sequentially.sh mixed 0 fixed_200 0 manual_pilot pilot
```

Esse script chama uma linguagem por vez. Ele nunca sobe as cinco APIs simultaneamente.

O perfil `fixed_200` tem alvo de 200 req/s e compara latencia e recursos sob a mesma taxa; nao representa capacidade maxima. A entrega minima e 97,5% do alvo. Os perfis `saturation_25` a `saturation_400` formam uma bateria separada, sem pacing. Perfis `controlled_*` e `capacity_*` existem apenas para releitura do historico e nunca entram na mesma coorte dos perfis de saturacao.

```bash
./scripts/calibrate_load_generator.sh go
./scripts/run_capacity_battery.sh
```

A calibracao usa somente `GET /health`, pacing zero e degraus de 25, 50, 100, 200 e 400 usuarios durante 60 s. Ela e `non_official_calibration`, usa CPU do cAdvisor e fica vinculada ao commit, imagens, numero de workers, cota do Locust e alocacao Docker. A escada deve levar a CPU media do Locust na janela a pelo menos 90% da cota para demonstrar seu teto, registrar pico de pelo menos 250 req/s e cobrir 80% da janela curta. Cada rodada oficial permanece limitada a 80% desse pico, CPU media do Locust abaixo de 90% da cota e 90% de cobertura na janela principal. O pico bruto por scrape e preservado apenas para diagnostico, pois atualizacoes irregulares do contador do cAdvisor podem concentra-lo artificialmente em um intervalo.

No Windows, calibre pelo menu e depois use `02_PROXIMA_RODADA_OFICIAL.bat`. Cada duplo clique executa a proxima rodada `fixed_200` ainda incompleta. O menu avancado preserva pilotos e a bateria de saturacao separadamente.

## Monitoramento

Subir Prometheus, Grafana e exportadores:

```bash
docker compose --profile monitoring up -d postgres postgres-exporter benchmark-results-exporter prometheus grafana cadvisor
```

Prometheus:

```text
http://localhost:9090
```

Grafana:

```text
http://localhost:3000
```

Credenciais locais padrao:

```text
admin / admin
```

A visualizacao local abre sem login e possui permissao somente de leitura. Use `admin / admin` apenas quando precisar editar o dashboard.

Grafana e apoio visual. Os dados brutos e consolidados devem ser preservados em `results/`.

O Grafana possui dois dashboards provisionados:

- `TCC Benchmark - Resultados Oficiais`, pagina inicial filtravel por metodologia e classificacao `official`, com requisicoes, falhas, taxa de erro, throughput, media, P50, P95, P99, duracao sem aquecimento, variacao, confianca, CPU, memoria e o resumo do PostgreSQL por linguagem.
- `TCC Benchmark - Monitoramento e Diagnostico`, com execucao ao vivo, detalhamento por endpoint e metricas internas do PostgreSQL.

Os dashboards possuem links no topo para alternar entre eles. O `benchmark-results-exporter` converte somente os CSVs e JSONs ja produzidos pelo teste em metricas Prometheus; ele nao instrumenta nem altera as APIs comparadas.

Prometheus coleta o PostgreSQL pelo `postgres-exporter`; cada rodada preserva `postgres_summary.csv` com conexoes, commits, rollbacks, blocos, cache hit ratio e tamanho do banco na janela exata da medicao. O cAdvisor e a fonte de CPU e memoria exigida pelo TCC e identifica API, PostgreSQL e Locust pelos IDs reais do containerd. O servico usa o namespace `moby` porque o factory Docker do cAdvisor 0.49.1 nao reconhece o image store containerd do Docker Desktop atual. Se essas series deixarem de existir, a rodada oficial volta a ser bloqueada. `docker stats` continua sendo coletado como diagnostico complementar de pilotos. As APIs nao expoem `/metrics`, mantendo o mesmo custo de instrumentacao nas cinco linguagens.

## Coletar versoes

```bash
./scripts/collect_versions.sh
```

Catalogo versionado e snapshot local:

```text
docs/environment-versions.md
results/summaries/environment-versions.json
```

O script chama `scripts/preflight.py` e consulta versoes reais, imagens, digests, hardware, alocacao Docker, manifestos e Git. Nao usa uma tabela hardcoded como evidencia da rodada.

## Encerrar containers

```bash
docker compose down
```

Para restaurar o banco do benchmark, use:

```bash
./scripts/reset_db.sh
```

Entre rodadas, encerre os containers sem remover volumes. O reset suportado atua somente em `benchmark_db`.

No Windows, voce tambem pode usar o menu por duplo clique:

```text
launchers/windows/00_MENU_TESTES.bat
```

## Execucao facil por duplo clique

Abra a pasta `launchers/windows/` e execute `00_MENU_TESTES.bat` com duplo clique. O menu principal mostra apenas verificacao, proxima rodada oficial, Grafana e acesso ao menu avancado.

Os principais atalhos sao:

- `00_MENU_TESTES.bat`
- `01_VERIFICAR_PROJETO.bat`
- `02_PROXIMA_RODADA_OFICIAL.bat`
- `03_ABRIR_GRAFANA.bat`
- `04_MENU_AVANCADO.bat`

O fluxo PowerShell do Windows e nativo e nao depende de Bash ou WSL. A proxima rodada oficial so inicia depois do preflight estrito e exige confirmacao `SIM`.

## Como testar manualmente os payloads

Primeiro deixe uma API ativa respondendo em `http://127.0.0.1:8000`. A porta externa padrao do experimento e sempre essa, para facilitar a comparacao.

Testar `GET /health`:

```bash
curl http://127.0.0.1:8000/health
```

Testar `GET /customers/{id}` usando um ID pronto:

```bash
CUSTOMER_ID=$(head -n 1 common/payloads/ids_customers.jsonl)
curl "http://127.0.0.1:8000/customers/$CUSTOMER_ID"
```

Testar pagina de clientes:

```bash
curl "http://127.0.0.1:8000/customers?page=1&pageSize=50"
```

Testar `POST /customers`:

```bash
head -n 1 common/payloads/customers_create.jsonl > /tmp/customer_payload.json
curl -X POST http://127.0.0.1:8000/customers \
  -H "Content-Type: application/json" \
  --data @/tmp/customer_payload.json
```

Testar `PUT /customers/{id}`:

```bash
CUSTOMER_ID=$(head -n 1 common/payloads/ids_customers.jsonl)
head -n 1 common/payloads/customers_update.jsonl > /tmp/customer_update_payload.json
curl -X PUT "http://127.0.0.1:8000/customers/$CUSTOMER_ID" \
  -H "Content-Type: application/json" \
  --data @/tmp/customer_update_payload.json
```

Testar `GET /products?categoryId={id}`:

```bash
CATEGORY_ID=$(head -n 1 common/payloads/ids_categories.jsonl)
curl "http://127.0.0.1:8000/products?categoryId=$CATEGORY_ID"
```

Testar `POST /orders`:

```bash
head -n 1 common/payloads/orders_create.jsonl > /tmp/order_payload.json
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  --data @/tmp/order_payload.json
```

Testar `GET /orders/{id}`:

```bash
ORDER_ID=$(head -n 1 common/payloads/ids_orders.jsonl)
curl "http://127.0.0.1:8000/orders/$ORDER_ID"
```

Tambem existe um script para validar todos os endpoints principais de uma API ativa:

```bash
./scripts/test_payloads_manually.sh http://127.0.0.1:8000
```

Esse script nao executa carga pesada. Ele apenas le exemplos dos arquivos JSONL, envia chamadas simples e mostra o status HTTP de cada endpoint.

## Testar payloads por duplo clique

No Windows:

Abra `launchers/windows/04_MENU_AVANCADO.bat` e escolha `Testar payloads da API ativa`. A opcao chama `launchers/windows/powershell/testar-payloads.ps1` e espera a API em `http://127.0.0.1:8000`.

No WSL/Linux:

```bash
./launchers/linux-wsl/testar-payloads-api-ativa.sh
```

## Fluxo experimental esperado

1. Subir PostgreSQL e monitoramento.
2. Resetar o banco para um estado conhecido.
3. Subir apenas uma API.
4. Rodar smoke test.
5. Rodar warmup.
6. Resetar o banco sem reiniciar a API.
7. Rodar o teste principal.
8. Coletar metricas continuamente.
9. Salvar resultados com linguagem, cenario, data e rodada.
10. Resetar novamente o banco.
11. Derrubar a API.
12. Repetir para a proxima linguagem.

## Checklist antes de coleta oficial

```text
[ ] Docker esta rodando
[ ] Docker Engine e 29.5.2 e Compose e 5.1.4
[ ] Git esta limpo e o commit foi revisado
[ ] A verificacao completa gerou project-verification.json para esse mesmo commit limpo
[ ] A calibracao do Locust corresponde ao mesmo commit e ambiente
[ ] PostgreSQL subiu corretamente
[ ] Banco foi criado
[ ] Seed foi carregado
[ ] Payloads foram gerados
[ ] API escolhida esta ativa
[ ] GET /health respondeu
[ ] scripts/test_payloads_manually.sh passou
[ ] Warmup esta habilitado
[ ] Pool de conexoes esta configurado
[ ] Prometheus esta coletando
[ ] cAdvisor possui CPU e memoria identificaveis para API, PostgreSQL e Locust
[ ] Grafana abre corretamente
[ ] O runner selecionara uma nova pasta run_N sem sobrescrever historicos
```

O proprio runner executa essas verificacoes. Um piloto pode continuar com bloqueios registrados; `official` falha antes do workload.

## Onde estao os resultados

Os testes oficiais devem salvar arquivos no padrao:

```text
results/raw/{language}/{scenario}/run_{number}/locust_stats.csv
results/raw/{language}/{scenario}/run_{number}/locust_failures.csv
results/raw/{language}/{scenario}/run_{number}/postgres_summary.csv
results/raw/{language}/{scenario}/run_{number}/cadvisor_summary.csv
results/raw/{language}/{scenario}/run_{number}/metadata.json
```

Os resumos ficam em:

```text
results/processed/summary_by_language.csv
results/processed/summary_by_endpoint.csv
results/processed/summary_scalability.csv
results/summaries/final_summary.md
results/summaries/benchmark_dashboard.html
```

Resultados retirados da comparacao oficial sao preservados localmente em `results/archive/`. Essa pasta nao entra nos relatorios nem no Git.

Gerar resumos:

```bash
python scripts/summarize_results.py
```

O consolidado final publica somente `official` por padrao. Para uma inspecao diagnostica separada, use `--classification non_official`, `--classification legacy` ou `--classification all`; esses modos nunca promovem suas linhas ao agregado oficial.

No Windows, a opcao `Gerar graficos e abrir painel` do menu avancado atualiza os resumos e o painel HTML comparativo.

No Windows, a opcao `Resumir resultados oficiais` fica no menu avancado.

## Documentacao principal

- `docs/experiment-plan.md`
- `docs/api-contract.md`
- `docs/database-model.md`
- `docs/sql-contract.md`
- `docs/methodological-notes.md`
- `docs/environment-versions.md`
- `docs/runbook.md`
- `docs/easy-execution-guide.md`

## Observacao sobre as APIs

As pastas das cinco linguagens existem em `apps/` e seguem a mesma logica de banco, endpoints, SQL, warmup e politica de frameworks minimos.

## Erros comuns

PostgreSQL nao sobe:

- Confirme se o Docker Desktop esta aberto.
- Verifique se a porta `5432` ja esta em uso.
- Tente `docker compose ps`.

Validacao do banco falha:

- Rode `./scripts/setup_database.sh` novamente.
- Use `scripts/reset_db.sh`, que restaura somente `benchmark_db` sem apagar historicos ou volumes de monitoramento.

Payloads nao existem:

- Rode `./scripts/generate_payloads.sh`.
- No Windows, use `Gerar payloads` no menu avancado.

API nao responde em `/health`:

- Confirme se apenas a API escolhida esta ativa.
- Confirme se ela expoe `http://127.0.0.1:8000`.
- Verifique logs com `docker compose logs <servico-da-api>`.

Script de linguagem informa que o `Dockerfile` esta ausente:

- Confirme se o `Dockerfile` e o codigo da API existem na pasta da linguagem escolhida.

WSL/Linux nao executa no Windows:

- Use os `.bat` em `launchers/windows/`.
- Os `.sh` dependem de WSL, Linux ou Git Bash.
