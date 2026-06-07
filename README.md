# TCC PostgreSQL Backend Benchmark

Projeto experimental para comparar o desempenho de APIs backend equivalentes em Python, Node.js, Java, Go e C#/.NET acessando a mesma base PostgreSQL com SQL direto, pool de conexoes configurado explicitamente e sem ORM.

Esta primeira base prepara o banco, contratos, payloads, scripts de validacao, warmup documentado e atalhos de execucao facil. As cinco APIs serao implementadas depois que essa base comum estiver validada.

## Execucao rapida da base

Requisitos:

- Docker e Docker Compose
- Python 3 para gerar payloads e resumir resultados
- `curl` para testes manuais
- Git

Passos principais:

```bash
cp .env.example .env
docker compose up -d postgres
./scripts/setup_database.sh
./scripts/generate_payloads.sh
./scripts/validate_database.sh
```

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

## Como testar manualmente os payloads

Primeiro deixe uma API ativa respondendo em `http://localhost:8000`. A porta externa padrao do experimento e sempre essa, para facilitar a comparacao.

Testar `GET /health`:

```bash
curl http://localhost:8000/health
```

Testar `GET /customers/{id}` usando um ID pronto:

```bash
CUSTOMER_ID=$(head -n 1 common/payloads/ids_customers.jsonl)
curl "http://localhost:8000/customers/$CUSTOMER_ID"
```

Testar pagina de clientes:

```bash
curl "http://localhost:8000/customers?page=1&pageSize=50"
```

Testar `POST /customers`:

```bash
head -n 1 common/payloads/customers_create.jsonl > /tmp/customer_payload.json
curl -X POST http://localhost:8000/customers \
  -H "Content-Type: application/json" \
  --data @/tmp/customer_payload.json
```

Testar `PUT /customers/{id}`:

```bash
CUSTOMER_ID=$(head -n 1 common/payloads/ids_customers.jsonl)
head -n 1 common/payloads/customers_update.jsonl > /tmp/customer_update_payload.json
curl -X PUT "http://localhost:8000/customers/$CUSTOMER_ID" \
  -H "Content-Type: application/json" \
  --data @/tmp/customer_update_payload.json
```

Testar `GET /products?categoryId={id}`:

```bash
CATEGORY_ID=$(head -n 1 common/payloads/ids_categories.jsonl)
curl "http://localhost:8000/products?categoryId=$CATEGORY_ID"
```

Testar `POST /orders`:

```bash
head -n 1 common/payloads/orders_create.jsonl > /tmp/order_payload.json
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  --data @/tmp/order_payload.json
```

Testar `GET /orders/{id}`:

```bash
ORDER_ID=$(head -n 1 common/payloads/ids_orders.jsonl)
curl "http://localhost:8000/orders/$ORDER_ID"
```

Tambem existe um script para validar todos os endpoints principais de uma API ativa:

```bash
./scripts/test_payloads_manually.sh http://localhost:8000
```

Esse script nao executa carga pesada. Ele apenas le exemplos dos arquivos JSONL, envia chamadas simples e mostra o status HTTP de cada endpoint.

## Fluxo experimental esperado

1. Subir PostgreSQL e monitoramento.
2. Resetar o banco para um estado conhecido.
3. Subir apenas uma API.
4. Rodar smoke test.
5. Rodar warmup.
6. Resetar o banco sem reiniciar a API.
7. Rodar o teste principal.
8. Coletar metricas.
9. Salvar resultados com linguagem, cenario, data e rodada.
10. Derrubar a API.
11. Repetir para a proxima linguagem.

Comandos planejados por linguagem:

```bash
./scripts/run_one_language.sh python mixed 1
./scripts/run_one_language.sh node mixed 1
./scripts/run_one_language.sh java mixed 1
./scripts/run_one_language.sh go mixed 1
./scripts/run_one_language.sh dotnet mixed 1
```

Cada comando reseta o banco, sobe somente a API escolhida, executa smoke test, warmup, novo reset sem reiniciar a API, teste principal, coleta de metricas e encerra a API.

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

As pastas das cinco linguagens ja existem em `apps/`, mas a implementacao das APIs sera feita em uma etapa posterior. Esta ordem evita que cada linguagem avance com interpretacoes diferentes do banco, dos endpoints, do SQL, do warmup e da politica de frameworks minimos.
