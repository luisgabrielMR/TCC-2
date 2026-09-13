# APIs — referência técnica

## Condições comuns

As cinco APIs expõem oito operações: health, leitura e lista de clientes,
criação e atualização de cliente, produtos, criação e consulta de pedido. O
contrato canônico está em `../common/openapi/openapi.yaml`; as respostas e
regras estão descritas em `../docs/api-contract.md` e `../docs/sql-contract.md`.

Todas usam SQL parametrizado, sem ORM. As escritas de pedido usam transação e
bloqueio `FOR UPDATE` de produto. A equivalência é verificada por testes de
contrato e pela comparação do estado final do banco.

| Implementação | HTTP | Driver/pool PostgreSQL | Runtime da imagem |
| --- | --- | --- | --- |
| Python | FastAPI + Uvicorn | psycopg 3 + psycopg_pool | Python 3.12 |
| Node.js | Express | pg / `Pool` | Node 22 |
| Java | `HttpServer` do JDK | JDBC + HikariCP 5.1.0 | Java 21 |
| Go | `net/http` | `database/sql` + lib/pq | Go 1.23 (build) |
| C#/.NET | ASP.NET Core Minimal API | Npgsql 8.0.5 | .NET 8 |

Os Dockerfiles são as fontes de verdade para runtime e build. As dependências
travadas estão em `requirements.lock`, `package-lock.json`, `pom.xml`,
`go.mod/go.sum` e `packages.lock.json`.

## Pool de conexões

Valores comuns entregues pelo Compose:

| Variável | Valor padrão | Finalidade |
| --- | ---: | --- |
| `DB_POOL_MIN` | 1 | mínimo, quando o driver oferece esse conceito |
| `DB_POOL_MAX` | 20 | máximo de conexões abertas |
| `DB_POOL_ACQUIRE_TIMEOUT_SECONDS` | 10 s | espera para obter conexão |
| `DB_POOL_IDLE_TIMEOUT_SECONDS` | 60 s | descarte de conexão ociosa |
| `DB_POOL_MAX_LIFETIME_SECONDS` | 1800 s | vida máxima da conexão |

| Implementação | Mapeamento efetivo | Diferença que deve ser preservada |
| --- | --- | --- |
| Python | `min_size`, `max_size`, `timeout`, `max_idle`, `max_lifetime` | abre o pool no startup e espera até 10 s |
| Node.js | `min`, `max`, `connectionTimeoutMillis`, `idleTimeoutMillis`, `maxLifetimeSeconds` | `pg` configura `min`, mas não pré-abre conexões ociosas |
| Java | `minimumIdle`, `maximumPoolSize`, `connectionTimeout`, `idleTimeout`, `maxLifetime` | tempos convertidos para milissegundos no HikariCP |
| Go | `SetMaxOpenConns`, `SetMaxIdleConns`, `SetConnMaxIdleTime`, `SetConnMaxLifetime` | não oferece mínimo persistente; `PingContext` só verifica a conexão; cada aquisição usa contexto de 10 s |
| .NET | `Minimum Pool Size`, `Maximum Pool Size`, `Timeout`, `Connection Idle Lifetime`, `Connection Lifetime` | `CommandTimeout=0`; o limite de SQL fica no PostgreSQL |

`DB_POOL_MAX=20` é comum e confirmado nas cinco implementações. O mínimo não
é idêntico em todos os ecossistemas; não force uma simulação de mínimo no Go ou
uma pré-abertura que o Node não executa naturalmente.

## Caminhos no código

- Python: `python-api/app/main.py`, `db.py`, `repository.py`, `queries.py`.
- Node.js: `node-api/src/server.js`, `db.js`, `repository.js`, `queries.js`.
- Java: `java-api/src/main/java/benchmark/Main.java`.
- Go: `go-api/main.go`.
- .NET: `dotnet-api/Program.cs`.

O PostgreSQL aplica `statement_timeout=30000`. Por isso, o timeout de aquisição
do pool e o limite de execução SQL são controles diferentes.
