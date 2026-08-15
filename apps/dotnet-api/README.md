# .NET API

API C#/.NET do experimento, implementada com ASP.NET Core Minimal API e Npgsql direto.

## Escolhas

- HTTP/rotas: ASP.NET Core Minimal API.
- PostgreSQL: Npgsql.
- Pool: pool do Npgsql configurado explicitamente na connection string.
- ORM: não usado.
- Dependencias: restauradas em modo bloqueado por `packages.lock.json`.

## Executar via Docker Compose

Na raiz do projeto:

```bash
docker compose --profile dotnet up -d --build dotnet-api
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

- `DB_POOL_MIN` -> `Minimum Pool Size`
- `DB_POOL_MAX` -> `Maximum Pool Size`
- `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` -> `Timeout`
- `DB_POOL_IDLE_TIMEOUT_SECONDS` -> `Connection Idle Lifetime`
- `DB_POOL_MAX_LIFETIME_SECONDS` -> `Connection Lifetime`

## Observações metodológicas

Esta API não usa Entity Framework. Todas as operações de banco usam SQL direto parametrizado com Npgsql. `POST /orders` usa transação explícita e bloqueio de produto com `FOR UPDATE`.
