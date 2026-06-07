# Go API

API Go do experimento, implementada com uso mínimo de framework.

## Escolhas

- HTTP/rotas: `net/http` da biblioteca padrão.
- PostgreSQL: `database/sql` com driver `github.com/lib/pq`.
- Pool: configuração explícita do próprio `sql.DB`.
- ORM: não usado.

## Executar via Docker Compose

Na raiz do projeto:

```bash
docker compose --profile go up -d --build go-api
```

A API fica em:

```text
http://localhost:8000
```

## Teste manual rápido

```bash
curl http://localhost:8000/health
./scripts/test_payloads_manually.sh http://localhost:8000
```

## Pool

Mapeamento:

- `DB_POOL_MAX` -> `SetMaxOpenConns`
- `DB_POOL_MIN` -> `SetMaxIdleConns`
- `DB_POOL_IDLE_TIMEOUT_SECONDS` -> `SetConnMaxIdleTime`
- `DB_POOL_MAX_LIFETIME_SECONDS` -> `SetConnMaxLifetime`

`database/sql` não possui timeout direto de aquisição igual aos demais drivers; o timeout de contexto das requisições é usado para manter intenção equivalente.
