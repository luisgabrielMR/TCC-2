# Go API

API Go do experimento, implementada com uso mínimo de framework.

## Escolhas

- HTTP/rotas: `net/http` da biblioteca padrão.
- PostgreSQL: `database/sql` com driver `github.com/lib/pq`.
- Pool: configuração explícita do próprio `sql.DB`.
- ORM: não usado.
- Valores monetários: `numeric` chega como texto pelo `lib/pq` e é normalizado para duas casas na aplicação, sem cast no SQL.

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
- `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` -> contexto de `db.Conn`
- `DB_POOL_IDLE_TIMEOUT_SECONDS` -> `SetConnMaxIdleTime`
- `DB_POOL_MAX_LIFETIME_SECONDS` -> `SetConnMaxLifetime`

`database/sql` não possui configuração de mínimo de conexões persistente. Por isso, `DB_POOL_MIN` não é aplicado pela implementação Go; a inicialização apenas executa `PingContext` para verificar a conectividade. Também não há timeout global de aquisição: cada chamada a `db.Conn` recebe um contexto de 10 segundos, que limita a espera por uma conexão. O limite de conexões ociosas é configurado como 20 para manter reutilizáveis as conexões que já foram abertas, sem elevar o máximo de conexões abertas.
