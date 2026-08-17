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
DB_POOL_MAX_LIFETIME_SECONDS=1800
```

Cada ecossistema implementa pooling de modo diferente. A comparacao preserva a mesma intencao e registra estas diferencas em `metadata.json`:

- Python/psycopg_pool: aplica minimo, maximo, espera de aquisicao, ociosidade e vida maxima.
- Node.js/pg: aplica maximo, espera, ociosidade e vida maxima; `min` nao preabre conexoes.
- Java/HikariCP: aplica todos os cinco parametros diretamente.
- Go/database/sql: aplica maximo, minimo ocioso, ociosidade e vida maxima; o tempo de aquisicao e usado no `PingContext` inicial porque nao ha opcao global equivalente por aquisicao.
- .NET/Npgsql: aplica todos os cinco parametros na connection string.

## Warmup

O warmup reproduz o mesmo workload e o mesmo nivel de concorrencia da rodada principal:

- duracao inicial: 180 segundos
- usuarios e spawn rate: iguais aos da medicao (50/10, 100/20 ou 200/40)
- cobertura: mesmas leituras, escritas e pesos do cenario medido
- estabilidade: variacao maxima de 10% entre cada par das tres ultimas janelas de 45 segundos com a concorrencia completa
- concorrencia: o pico observado deve ser exatamente o numero de usuarios configurado para o perfil
- tentativa adicional: 300 segundos, ou 600 segundos no Java, com banco resetado e API mantida ativa
- resultado fora da coleta principal
- API nao reiniciada entre warmup e teste principal
- banco resetado depois do warmup sem derrubar a API
- banco resetado novamente depois da coleta principal
- `ANALYZE` executado em cada reset para que o PostgreSQL nao atualize estatisticas do planejador no meio da medicao

Se o aquecimento continuar instavel ou alguma rota esperada nao for chamada, a medicao principal nao comeca. Isso evita que o JIT do Java ou caminhos de escrita ainda frios sejam medidos como estado estacionario.

## Payloads e estoque

Os arquivos JSONL em `common/payloads/` sao gerados antes da coleta e lidos sequencialmente, sem gerar, copiar ou alterar JSON durante o teste. `customers_create.jsonl` contem 75.000 clientes unicos e deterministas, quantidade superior ao maximo teorico de 60.000 criacoes em cinco minutos no perfil de 200 usuarios. A rodada falha de forma explicita se consumir todo o arquivo, em vez de reutilizar registros e criar conflitos artificiais.

O seed reserva mais estoque do que uma rodada de cinco minutos consegue consumir. Assim, esgotamento de produto nao favorece APIs mais lentas nem penaliza APIs mais rapidas.

O PostgreSQL nao executa autovacuum ou autoanalyze nas tabelas do benchmark durante a carga. Cada reset usa `TRUNCATE`, que remove tuplas mortas, e executa `ANALYZE` de forma explicita. Isso evita que manutencao em segundo plano ocorra em instantes diferentes para cada linguagem.

## Metricas comparaveis

Latencia, throughput e falhas HTTP sao medidos pelo Locust. No encerramento, o `locustfile.py` grava uma fotografia final e o runner a promove para `locust_stats.csv`; isso impede que o consolidado use apenas a ultima fotografia periodica anterior ao shutdown. Prometheus coleta series do PostgreSQL pelo `postgres-exporter`. CPU, memoria e rede dos containers sao amostradas continuamente por `docker stats` e preservadas em CSV bruto e consolidado.

O tempo total medido comeca imediatamente antes da preparacao da execucao principal do Locust e termina depois da fotografia final. Build, contrato, warmup, resets e exportacao posterior ficam fora de `test_phase.elapsed_seconds`. Rodadas antigas usam a janela da coleta de recursos como aproximacao e sao identificadas como `metrics_window_legacy`.

Cada rodada tambem registra `measurement_stability`: RPS da primeira e da ultima janela, mudanca percentual assinada e variacao entre as tres janelas finais. Janelas finais instaveis sao classificadas primeiro como oscilacao. Quando elas estao estaveis, crescimento acima de 10% durante a fase medida e marcado como possivel aquecimento tardio; queda acima de 10% permanece visivel para distinguir aquecimento, saturacao e instabilidade.

O cAdvisor permanece disponivel para Linux. No Docker Desktop com armazenamento containerd, ele pode nao publicar series por container; por isso, o resultado oficial de recursos usa a coleta continua de `docker stats`, igual para as cinco APIs. As APIs nao expoem `/metrics`, evitando instrumentacao e custo diferentes entre linguagens.

O percentual de CPU do `docker stats` e expresso por nucleo logico: aproximadamente 100% representa um nucleo totalmente utilizado. Em uma maquina com varios nucleos, um container multithread pode ultrapassar 100% sem exceder a capacidade total disponivel.

## Execucao separada

A coleta principal executa apenas uma API por vez. O fluxo sequencial sobe uma linguagem, aquece, coleta, encerra e somente entao inicia a proxima.

## Carga controlada e capacidade

- Quando houver rodadas antigas e atuais para o mesmo nivel de carga, os relatorios de escalabilidade usam apenas o maior `methodology_version` com `load_profile` atual. Resultados anteriores continuam preservados no historico, mas nao entram na comparacao 50/100/200.

O perfil oficial `controlled_50` usa 50 usuarios e mede comparacao sob carga controlada; ele nao representa a capacidade maxima. Os perfis extras `capacity_100` e `capacity_200` repetem o workload mixed com 100 e 200 usuarios. O relatorio compara ganho de RPS, P95, eficiencia de escala, falhas e CPU do Locust. Saturacao significa apenas o limite pratico observado neste computador.
