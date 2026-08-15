# TCC PostgreSQL Backend Benchmark

Projeto experimental para comparar o desempenho de APIs backend equivalentes em Python, Node.js, Java, Go e C#/.NET acessando a mesma base PostgreSQL com SQL direto, pool de conexoes configurado explicitamente e sem ORM.

Esta base prepara o banco, contratos, payloads, scripts de validacao, warmup documentado, atalhos de execucao facil e as cinco APIs equivalentes.

## Execucao rapida da base

Requisitos:

- Docker e Docker Compose
- Python 3 para gerar payloads e resumir resultados
- `curl` para testes manuais
- Git

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
WARMUP_DURATION_SECONDS=180
WARMUP_USERS=20
WARMUP_SPAWN_RATE=5
```

O warmup nao entra nos resultados principais. Depois do warmup, o banco deve ser resetado sem reiniciar a API.

Os scripts no host usam `API_BASE_URL=http://127.0.0.1:8000`. O Locust roda em container e usa `LOCUST_HOST=http://host.docker.internal:8000`.

## Rodada principal por linguagem

```bash
./scripts/run_one_language.sh python mixed 1
./scripts/run_one_language.sh node mixed 1
./scripts/run_one_language.sh java mixed 1
./scripts/run_one_language.sh go mixed 1
./scripts/run_one_language.sh dotnet mixed 1
```

Cada comando deve:

1. Resetar o banco.
2. Subir somente a API escolhida.
3. Executar smoke test.
4. Executar warmup.
5. Resetar o banco sem reiniciar a API.
6. Executar o teste principal.
7. Coletar metricas continuamente.
8. Salvar resultados e resetar novamente o banco.
9. Encerrar a API.

Na base atual, os comandos das cinco APIs ja podem ser usados quando o Docker estiver disponivel.

## Executar todas sequencialmente

```bash
./scripts/run_all_languages_sequentially.sh mixed 1
```

Esse script chama uma linguagem por vez. Ele nunca sobe as cinco APIs simultaneamente.

## Monitoramento

Subir Prometheus, Grafana e exportadores:

```bash
docker compose --profile monitoring up -d postgres postgres-exporter prometheus grafana cadvisor
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

Grafana e apoio visual. Os dados brutos e consolidados devem ser preservados em `results/`.

Prometheus coleta o PostgreSQL pelo `postgres-exporter`. O cAdvisor fornece visualizacao adicional em hosts compativeis. CPU, memoria e rede oficiais sao amostradas continuamente por `docker stats`, o que tambem funciona no Docker Desktop com containerd. As APIs nao expoem `/metrics`, mantendo o mesmo custo de instrumentacao nas cinco linguagens.

## Coletar versoes

```bash
./scripts/collect_versions.sh
```

Catalogo versionado e snapshot local:

```text
docs/environment-versions.md
results/summaries/environment-versions.json
```

O script atualiza o snapshot JSON; o catalogo Markdown registra as versoes verificadas das imagens e dependencias do projeto.

## Encerrar containers

```bash
docker compose down
```

Para apagar volumes locais do banco:

```bash
docker compose down -v
```

Use `-v` somente quando quiser remover o estado local do PostgreSQL.

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
[ ] Grafana abre corretamente
[ ] results/raw esta vazio ou preparado para nova rodada
```

## Onde estao os resultados

Os testes oficiais devem salvar arquivos no padrao:

```text
results/raw/{language}/{scenario}/run_{number}/locust_stats.csv
results/raw/{language}/{scenario}/run_{number}/locust_failures.csv
results/raw/{language}/{scenario}/run_{number}/metadata.json
```

Os resumos ficam em:

```text
results/processed/summary_by_language.csv
results/processed/summary_by_endpoint.csv
results/summaries/final_summary.md
```

Gerar resumos:

```bash
python scripts/summarize_results.py
```

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
- Se o volume antigo estiver inconsistente, use `docker compose down -v` e prepare o banco de novo.

Payloads nao existem:

- Rode `./scripts/generate_payloads.sh`.
- No Windows, use `03_GERAR_PAYLOADS.bat`.

API nao responde em `/health`:

- Confirme se apenas a API escolhida esta ativa.
- Confirme se ela expoe `http://127.0.0.1:8000`.
- Verifique logs com `docker compose logs <servico-da-api>`.

Script de linguagem diz que a API nao foi implementada:

- Confirme se o `Dockerfile` e o codigo da API existem na pasta da linguagem escolhida.

WSL/Linux nao executa no Windows:

- Use os `.bat` em `launchers/windows/`.
- Os `.sh` dependem de WSL, Linux ou Git Bash.
