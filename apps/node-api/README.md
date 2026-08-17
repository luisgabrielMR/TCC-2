# Node.js API

API Node.js do experimento, implementada com uso minimo de framework.

## Escolhas

- HTTP/rotas: Express em uso minimo.
- PostgreSQL: `pg`.
- Pool: `pg.Pool`.
- ORM: nao usado.

## Estrutura

```text
src/
  config.js       variaveis de ambiente e pool
  db.js           criacao do pool
  errors.js       erro JSON padronizado
  queries.js      SQL direto parametrizado
  repository.js   operacoes de banco e transacoes
  serializers.js  conversao para JSON do contrato
  server.js       rotas HTTP
  validation.js   validacoes explicitas
```

## Executar via Docker Compose

Na raiz do projeto:

```bash
docker compose --profile node up -d --build node-api
```

A API fica em:

```text
http://127.0.0.1:8000
```

## Teste manual rapido

```bash
curl http://127.0.0.1:8000/health
./scripts/test_payloads_manually.sh http://127.0.0.1:8000
```

## Pool

Variaveis usadas:

```env
DB_POOL_MIN=1
DB_POOL_MAX=20
DB_POOL_ACQUIRE_TIMEOUT_SECONDS=10
DB_POOL_IDLE_TIMEOUT_SECONDS=60
DB_POOL_MAX_LIFETIME_SECONDS=1800
```

Mapeamento:

- `DB_POOL_MIN` -> `Pool({ min })`
- `DB_POOL_MAX` -> `Pool({ max })`
- `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` -> `connectionTimeoutMillis`
- `DB_POOL_IDLE_TIMEOUT_SECONDS` -> `idleTimeoutMillis`
- `DB_POOL_MAX_LIFETIME_SECONDS` -> `maxLifetimeSeconds`

## Observacoes metodologicas

Esta API nao usa ORM. Todas as operacoes de banco usam SQL direto com parametros do driver. `POST /orders` usa transacao explicita e bloqueio de produto com `FOR UPDATE`.
