# Versões do ambiente

Este arquivo é atualizado pelo script `scripts/collect_versions.sh`. A tabela abaixo registra também as escolhas mínimas planejadas por linguagem.

## Versões coletadas

> Execute `./scripts/collect_versions.sh` para preencher os dados atuais em `results/summaries/environment-versions.json`.

| Item | Versão |
| --- | --- |
| Sistema operacional | A coletar |
| Docker | A coletar |
| Docker Compose | A coletar |
| PostgreSQL | A coletar |
| Python | A coletar |
| Node.js | A coletar |
| Java/JDK | A coletar |
| Go | A coletar |
| .NET SDK | A coletar |
| Locust | A coletar |
| Prometheus | A coletar |
| Grafana | A coletar |

## Bibliotecas mínimas planejadas

| Linguagem | HTTP | PostgreSQL | Pool | Justificativa |
| --- | --- | --- | --- | --- |
| Python | FastAPI + Uvicorn | psycopg3 | psycopg_pool | Expor HTTP e JSON com pouco código, mantendo SQL explícito. |
| Node.js | Express | pg | pg.Pool | Roteamento simples e driver PostgreSQL direto. |
| Java | Javalin ou HTTP simples | JDBC | HikariCP | Evita Spring Data/JPA e mantém controle direto do SQL. |
| Go | net/http | database/sql + driver PostgreSQL | database/sql | Biblioteca padrão para HTTP e pooling configurado no próprio `sql.DB`. |
| C#/.NET | Minimal API | Npgsql | NpgsqlDataSource/pooling Npgsql | Estrutura mínima do ASP.NET Core sem Entity Framework. |

## Variáveis de pool

| Variável | Valor base |
| --- | --- |
| `DB_POOL_MIN` | 1 |
| `DB_POOL_MAX` | 20 |
| `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` | 10 |
| `DB_POOL_IDLE_TIMEOUT_SECONDS` | 60 |
| `DB_POOL_MAX_LIFETIME_SECONDS` | 300 |
