# Python API

API Python do experimento, implementada com uso minimo de framework.

## Escolhas

- HTTP/rotas: FastAPI em uso minimo.
- Servidor ASGI: Uvicorn.
- PostgreSQL: psycopg3.
- Pool: psycopg_pool.
- ORM: nao usado.

## Estrutura

```text
app/
  config.py       variaveis de ambiente e pool
  db.py           criacao e ciclo de vida do pool
  errors.py       erro JSON padronizado
  main.py         rotas HTTP
  queries.py      SQL direto parametrizado
  repository.py   operacoes de banco e transacoes
  serializers.py  conversao para JSON do contrato
  validation.py   validacoes explicitas
```

## Executar via Docker Compose

Na raiz do projeto:

```bash
docker compose --profile python up -d --build python-api
```

A API fica em:

```text
http://localhost:8000
```

## Teste manual rapido

```bash
curl http://localhost:8000/health
./scripts/test_payloads_manually.sh http://localhost:8000
```

## Pool

Variaveis usadas:

```env
DB_POOL_MIN=1
DB_POOL_MAX=20
DB_POOL_ACQUIRE_TIMEOUT_SECONDS=10
DB_POOL_IDLE_TIMEOUT_SECONDS=60
DB_POOL_MAX_LIFETIME_SECONDS=300
```

Mapeamento:

- `DB_POOL_MIN` -> `ConnectionPool(min_size=...)`
- `DB_POOL_MAX` -> `ConnectionPool(max_size=...)`
- `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` -> `ConnectionPool(timeout=...)`
- `DB_POOL_IDLE_TIMEOUT_SECONDS` -> `ConnectionPool(max_idle=...)`
- `DB_POOL_MAX_LIFETIME_SECONDS` -> `ConnectionPool(max_lifetime=...)`

## Observacoes metodologicas

Esta API nao usa ORM. Todas as operacoes de banco usam SQL direto com parametros do driver. `POST /orders` usa transacao explicita e bloqueio de produto com `FOR UPDATE`.
