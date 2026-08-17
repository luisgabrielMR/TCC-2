# Versoes do ambiente

Estado verificado em 15 de agosto de 2026. Os runtimes foram coletados das imagens construidas e as bibliotecas vieram dos manifestos versionados.

## Host e infraestrutura

| Item | Versao utilizada |
| --- | --- |
| Sistema operacional | Microsoft Windows 11 Pro 10.0.26200, build 26200 |
| Docker Engine | 29.7.2, build a7dcaa6 |
| Docker Compose | v5.3.1 |
| PostgreSQL | 17.10 (`postgres:17`) |
| Locust | 2.32.6 (`locustio/locust:2.32.6`) |
| Prometheus | 2.55.1 (`prom/prometheus:v2.55.1`) |
| Grafana | 11.3.0 (`grafana/grafana:11.3.0`) |
| postgres-exporter | 0.15.0 (`prometheuscommunity/postgres-exporter:v0.15.0`) |
| cAdvisor | 0.49.1 (`gcr.io/cadvisor/cadvisor:v0.49.1`) |

## APIs e dependencias diretas

| Linguagem/runtime | HTTP/JSON | PostgreSQL | Pool | Motivo do componente HTTP |
| --- | --- | --- | --- | --- |
| Python 3.12.14 | FastAPI 0.115.6 + Uvicorn 0.34.0 | psycopg 3.2.3 | psycopg_pool 3.2.4 | Roteamento e serializacao JSON minimos; SQL explicito |
| Node.js 22.23.2 | Express 4.22.2 | pg 8.13.1 | `pg.Pool` | Roteamento HTTP leve; SQL explicito |
| Java Temurin 21.0.11+10 LTS | JDK HttpServer + Jackson 2.17.2 | PostgreSQL JDBC 42.7.4 | HikariCP 5.1.0 | Servidor HTTP do JDK; Jackson somente para JSON |
| Go 1.23.12 | `net/http` | lib/pq 1.10.9 | `database/sql` | Bibliotecas padrao para HTTP e pool |
| .NET 8.0.30 | ASP.NET Core Minimal API | Npgsql 8.0.5 | pooling do Npgsql | API HTTP nativa e minima do runtime; SQL explicito |

Nenhuma API usa ORM. As imagens base de todos os servicos estao fixadas por digest SHA-256 nos Dockerfiles, no `docker-compose.yml` e no `.env.example`. Python usa `requirements.lock`, Node.js usa `package-lock.json` com `npm ci`, Go usa `go.sum` e .NET usa `packages.lock.json` com restore em modo bloqueado.

## Pool equivalente

| Variavel | Valor base |
| --- | --- |
| `DB_POOL_MIN` | 1 |
| `DB_POOL_MAX` | 20 |
| `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` | 10 |
| `DB_POOL_IDLE_TIMEOUT_SECONDS` | 60 |
| `DB_POOL_MAX_LIFETIME_SECONDS` | 1800 |

As diferencas inevitaveis entre drivers sao registradas no `metadata.json` de cada rodada: `pg` nao preabre o minimo configurado e `database/sql` nao oferece um timeout global por aquisicao equivalente aos demais drivers.
