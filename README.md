# TCC PostgreSQL Backend Benchmark

Projeto experimental para comparar o desempenho de APIs backend equivalentes em Python, Node.js, Java, Go e C#/.NET acessando a mesma base PostgreSQL com SQL direto, pool de conexoes configurado explicitamente e sem ORM.

Esta base prepara o banco, contratos, payloads, scripts de validacao, warmup documentado, atalhos de execucao facil e as cinco APIs equivalentes.

## Execucao rapida da base

Requisitos para uso local:

- Docker e Docker Compose
- Python 3 para gerar payloads e resumir resultados
- `curl` para testes manuais
- Git

Para uma rodada oficial, o TCC exige Docker Engine 29.5.2 e Docker Compose 5.1.4. O host atualmente verificado usa 29.7.2/5.3.1; portanto, ele permite pilotos, mas o preflight bloqueia oficial. A troca do Docker Desktop deve ser manual.

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

No Windows, use `launchers/windows/02_PREPARAR_BANCO.bat`.

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

No Windows, use `launchers/windows/03_GERAR_PAYLOADS.bat`.

## Validar banco

```bash
./scripts/validate_database.sh
```

O script confere tabelas, indices e contagens minimas. No Windows, use `launchers/windows/04_VALIDAR_BANCO.bat`.

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
```

O warmup usa o mesmo cenario, usuarios, spawn rate e duracao para todas as linguagens, incluindo as rotas de escrita. As tres janelas finais sao comparadas e, se a variacao de RPS ultrapassar 10%, a rodada e interrompida em vez de alterar apenas uma linguagem. O warmup nao entra nos resultados principais e o banco e resetado sem reiniciar a API.

Os scripts no host usam `API_BASE_URL=http://127.0.0.1:8000`. O Locust roda em container e usa `LOCUST_HOST=http://host.docker.internal:8000`.

## Rodada principal por linguagem

```bash
./scripts/run_one_language.sh python mixed 0 controlled_50 pilot
./scripts/run_one_language.sh node mixed 0 controlled_50 pilot
./scripts/run_one_language.sh java mixed 0 controlled_50 pilot
./scripts/run_one_language.sh go mixed 0 controlled_50 pilot
./scripts/run_one_language.sh dotnet mixed 0 controlled_50 pilot
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
./scripts/run_all_languages_sequentially.sh mixed 0 controlled_50 0 manual_pilot pilot
```

Esse script chama uma linguagem por vez. Ele nunca sobe as cinco APIs simultaneamente.

O cenario `controlled_50` mede uma carga controlada e nao a capacidade maxima. Os testes extras usam os perfis `capacity_100` e `capacity_200`. A bateria completa executa, por padrao, tres repeticoes de cada nivel, alterna a ordem inicial das linguagens e nao sobrescreve rodadas anteriores:

```bash
./scripts/run_capacity_battery.sh
```

`run_capacity_battery.sh` e o atalho Windows 18 solicitam modo `official`: tres repeticoes, rotacao e bloqueio estrito. Os atalhos 07 a 12, 16 e 17 sao pilotos `non_official`.

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

- `TCC Benchmark - Resultados Oficiais`, pagina inicial restrita a metodologia 6 e classificacao `official`, com requisicoes, falhas, taxa de erro, throughput, media, P50, P95, P99, duracao sem aquecimento, variacao, confianca, CPU, memoria e o resumo do PostgreSQL por linguagem.
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

Abra a pasta `launchers/windows/` e execute `00_MENU_TESTES.bat` com duplo clique. O menu chama os scripts equivalentes para subir PostgreSQL, preparar banco, gerar payloads, validar banco, testar uma API ativa, rodar warmup e preparar rodadas por linguagem.

Os principais atalhos sao:

- `01_SUBIR_POSTGRES.bat`
- `02_PREPARAR_BANCO.bat`
- `03_GERAR_PAYLOADS.bat`
- `04_VALIDAR_BANCO.bat`
- `05_TESTAR_PAYLOADS_API_ATIVA.bat`
- `06_RODAR_WARMUP_API_ATIVA.bat`
- `07_TESTE_PYTHON_MIXED.bat`
- `08_TESTE_NODE_MIXED.bat`
- `09_TESTE_JAVA_MIXED.bat`
- `10_TESTE_GO_MIXED.bat`
- `11_TESTE_DOTNET_MIXED.bat`
- `12_TESTAR_TODAS_SEQUENCIALMENTE.bat`
- `13_RESUMIR_RESULTADOS.bat`
- `14_VERIFICAR_PROJETO_COMPLETO.bat`
- `15_GERAR_GRAFICOS.bat`
- `16_CAPACIDADE_100_USUARIOS.bat`
- `17_CAPACIDADE_200_USUARIOS.bat`
- `18_BATERIA_50_100_200.bat`
- `19_ABRIR_GRAFANA.bat`

O fluxo PowerShell do Windows e nativo e nao depende de Bash ou WSL.

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

```text
launchers/windows/05_TESTAR_PAYLOADS_API_ATIVA.bat
```

Esse atalho chama `launchers/windows/powershell/testar-payloads.ps1` e espera a API ativa em `http://127.0.0.1:8000`.

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

No Windows, `launchers/windows/15_GERAR_GRAFICOS.bat` atualiza os resumos, gera o painel HTML comparativo e o abre no navegador.

No Windows:

```text
launchers/windows/13_RESUMIR_RESULTADOS.bat
```

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
- No Windows, use `03_GERAR_PAYLOADS.bat`.

API nao responde em `/health`:

- Confirme se apenas a API escolhida esta ativa.
- Confirme se ela expoe `http://127.0.0.1:8000`.
- Verifique logs com `docker compose logs <servico-da-api>`.

Script de linguagem informa que o `Dockerfile` esta ausente:

- Confirme se o `Dockerfile` e o codigo da API existem na pasta da linguagem escolhida.

WSL/Linux nao executa no Windows:

- Use os `.bat` em `launchers/windows/`.
- Os `.sh` dependem de WSL, Linux ou Git Bash.
