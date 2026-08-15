# Notas metodologicas

## Justificativa para uso mínimo de frameworks

O experimento busca reduzir interferencias de frameworks completos, ORMs e abstracoes automaticas. Cada API usa apenas o necessario para HTTP, JSON, acesso PostgreSQL, pool de conexoes e execucao das operacoes.

- Python: FastAPI, Uvicorn, psycopg e psycopg_pool.
- Node.js: Express e pg.
- Java: JDK HttpServer, Jackson, JDBC e HikariCP.
- Go: net/http, database/sql e lib/pq.
- C#/.NET: ASP.NET Core Minimal API e Npgsql.

Nenhuma implementacao usa ORM, geracao automatica de entidades ou persistencia implicita. FastAPI, Express e ASP.NET Core Minimal API sao usados somente como camada HTTP/JSON; Java e Go usam os servidores HTTP das bibliotecas padrao. O SQL, as transacoes e o mapeamento das respostas permanecem explicitos em todas as linguagens.

## Pool de conexoes

Configuracao base:

```env
DB_POOL_MIN=1
DB_POOL_MAX=20
DB_POOL_ACQUIRE_TIMEOUT_SECONDS=10
DB_POOL_IDLE_TIMEOUT_SECONDS=60
DB_POOL_MAX_LIFETIME_SECONDS=300
```

Cada ecossistema implementa pooling de modo diferente. A comparacao preserva a mesma intencao e registra estas diferencas em `metadata.json`:

- Python/psycopg_pool: aplica minimo, maximo, espera de aquisicao, ociosidade e vida maxima.
- Node.js/pg: aplica maximo, espera, ociosidade e vida maxima; `min` nao preabre conexoes.
- Java/HikariCP: aplica todos os cinco parametros diretamente.
- Go/database/sql: aplica maximo, minimo ocioso, ociosidade e vida maxima; o tempo de aquisicao e usado no `PingContext` inicial porque nao ha opcao global equivalente por aquisicao.
- .NET/Npgsql: aplica todos os cinco parametros na connection string.

## Warmup

O warmup e igual para todas as linguagens:

- duracao: 180 segundos
- usuarios: 20
- spawn rate: 5
- resultado fora da coleta principal
- API nao reiniciada entre warmup e teste principal
- banco resetado depois do warmup sem derrubar a API
- banco resetado novamente depois da coleta principal

## Payloads e estoque

Os arquivos JSONL em `common/payloads/` sao gerados antes da coleta e lidos sequencialmente, sem gerar, copiar ou alterar JSON durante o teste. `customers_create.jsonl` contem 50.000 clientes unicos e deterministas. A rodada falha de forma explicita se consumir todo o arquivo, em vez de reutilizar registros e criar conflitos artificiais.

O seed reserva mais estoque do que uma rodada de cinco minutos consegue consumir. Assim, esgotamento de produto nao favorece APIs mais lentas nem penaliza APIs mais rapidas.

## Metricas comparaveis

Latencia, throughput e falhas HTTP sao medidos pelo Locust. Prometheus coleta series do PostgreSQL pelo `postgres-exporter`. CPU, memoria e rede dos containers sao amostradas continuamente por `docker stats` e preservadas em CSV bruto e consolidado.

O cAdvisor permanece disponivel para Linux. No Docker Desktop com armazenamento containerd, ele pode nao publicar series por container; por isso, o resultado oficial de recursos usa a coleta continua de `docker stats`, igual para as cinco APIs. As APIs nao expoem `/metrics`, evitando instrumentacao e custo diferentes entre linguagens.

## Execucao separada

A coleta principal executa apenas uma API por vez. O fluxo sequencial sobe uma linguagem, aquece, coleta, encerra e somente entao inicia a proxima.
