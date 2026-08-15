# Java API

API Java do experimento, implementada com HTTP nativo do JDK, JDBC direto e HikariCP.

## Escolhas

- HTTP/rotas: `com.sun.net.httpserver.HttpServer`.
- JSON: Jackson.
- PostgreSQL: JDBC driver oficial.
- Pool: HikariCP.
- ORM: nao usado.

## Executar via Docker Compose

Na raiz do projeto:

```bash
docker compose --profile java up -d --build java-api
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

Mapeamento:

- `DB_POOL_MIN` -> `minimumIdle`
- `DB_POOL_MAX` -> `maximumPoolSize`
- `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` -> `connectionTimeout`
- `DB_POOL_IDLE_TIMEOUT_SECONDS` -> `idleTimeout`
- `DB_POOL_MAX_LIFETIME_SECONDS` -> `maxLifetime`

## Observacoes metodologicas

Esta API nao usa Spring, JPA, Hibernate ou Spring Data. Todas as operacoes de banco usam SQL direto parametrizado. `POST /orders` usa transacao explicita e bloqueio de produto com `FOR UPDATE`.
