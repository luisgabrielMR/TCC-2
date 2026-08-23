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
http://127.0.0.1:8000
```

## Teste manual rápido

```bash
curl http://127.0.0.1:8000/health
./scripts/test_payloads_manually.sh http://127.0.0.1:8000
```

## Pool

Mapeamento:

- `DB_POOL_MAX` -> `SetMaxOpenConns`
- `DB_POOL_MAX` -> `SetMaxIdleConns`
- `DB_POOL_MIN` -> numero de conexoes preabertas na inicializacao
- `DB_POOL_IDLE_TIMEOUT_SECONDS` -> `SetConnMaxIdleTime`
- `DB_POOL_MAX_LIFETIME_SECONDS` -> `SetConnMaxLifetime`

`database/sql` não possui timeout global de aquisição igual aos demais drivers. Cada operacao de banco recebe um contexto de 10 segundos, mantendo o limite tambem durante espera por conexao. O limite ocioso usa o maximo do pool para evitar descarte e recriacao de conexoes sob concorrencia.
