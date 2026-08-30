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
- Go/database/sql: aplica o maximo a conexoes abertas e ociosas, preabre o minimo e limita cada operacao de banco por contexto; isso evita churn de conexoes e cobre a espera por aquisicao.
- .NET/Npgsql: aplica todos os cinco parametros na connection string.

## Tipos numericos e formatacao monetaria

Valores `numeric` chegam como texto nos drivers `lib/pq` (Go) e `pg` (Node.js), e como tipo decimal em psycopg (`Decimal`), JDBC (`BigDecimal`) e Npgsql (`decimal`). Essa diferenca e do driver, nao do SQL: as cinco APIs enviam exatamente o mesmo texto de consulta ao PostgreSQL, sem cast de conversao, e normalizam o valor para string de duas casas na camada de aplicacao antes de serializar o JSON. Nenhuma implementacao delega a formatacao decimal ao banco.

## Warmup

O warmup reproduz o mesmo workload e o mesmo nivel de concorrencia da rodada principal:

- duracao fixa: 300 segundos para todas as linguagens
- usuarios e spawn rate: iguais aos da medicao (50/10, 100/20 ou 200/40)
- cobertura: mesmas leituras, escritas e pesos do cenario medido
- estabilidade: variacao maxima de 10% entre cada par das tres ultimas janelas de 45 segundos com a concorrencia completa
- concorrencia: o pico observado deve ser exatamente o numero de usuarios configurado para o perfil
- falha de estabilidade: interrompe a rodada; nao existe duracao especial ou repeticao automatica por linguagem
- resultado fora da coleta principal
- API nao reiniciada entre warmup e teste principal
- banco resetado depois do warmup sem derrubar a API
- banco resetado novamente depois da coleta principal
- `VACUUM (ANALYZE)`, `CHECKPOINT` e `pg_stat_reset()` executados em cada reset para iniciar a medicao com planos, tuplas mortas, escrita pendente e contadores cumulativos estabilizados

Se o aquecimento estiver instavel ou alguma rota esperada nao for chamada, a medicao principal nao comeca. Isso evita que o JIT do Java ou caminhos de escrita ainda frios sejam medidos como estado estacionario sem favorecer uma implementacao com tempo adicional.

## Payloads e estoque

Os arquivos JSONL em `common/payloads/` sao gerados antes da coleta e lidos sequencialmente, sem gerar, copiar ou alterar JSON durante o teste. `customers_create.jsonl` contem 200.000 clientes unicos e deterministas. Em cinco minutos a 5.000 requisicoes totais por segundo, o peso de 10% do cenario misto produz 150.000 criacoes em expectativa; a massa mantem 50.000 registros adicionais, ou 33,3% de margem, para a variacao da selecao ponderada. Os registros unicos sao repartidos entre os workers do Locust; fluxos ciclicos recebem deslocamentos diferentes para evitar que todos comecem no mesmo registro. A rodada falha de forma explicita se consumir todo o arquivo.

O seed reserva mais estoque do que uma rodada de cinco minutos consegue consumir. Assim, esgotamento de produto nao favorece APIs mais lentas nem penaliza APIs mais rapidas.

O PostgreSQL nao executa autovacuum ou autoanalyze nas tabelas do benchmark durante a carga. Cada reset usa `TRUNCATE`, repoe o seed, executa `VACUUM (ANALYZE)` e `CHECKPOINT` e zera as estatisticas cumulativas do banco. Isso evita que manutencao em segundo plano, a escrita inicial do seed ou contadores herdados ocorram em instantes diferentes para cada linguagem.

## Metricas comparaveis

Latencia e falhas HTTP sao medidas pelo Locust. No encerramento, o `locustfile.py` grava uma fotografia final e o runner a promove para `locust_stats.csv`; isso impede que o consolidado use apenas a ultima fotografia periodica anterior ao shutdown. Os limites UTC usam `time.time_ns`, enquanto a duracao usa `time.monotonic_ns` e passa por validacao de deriva. A vazao canonica e `Request Count / elapsed_seconds`; `Requests/s` do Locust permanece armazenado como valor informado pelo instrumento. Prometheus coleta series do PostgreSQL pelo `postgres-exporter`; disponibilidade, conexoes, transacoes, blocos, cache hit ratio e tamanho do banco sao reduzidos para `postgres_summary.csv` na mesma janela. Pela especificacao do TCC, cAdvisor e a fonte primaria de CPU e memoria da API, PostgreSQL e Locust. `docker stats` e coletado na mesma janela apenas como evidencia complementar ou contingencial.

Para CPU oficial, o exportador consulta o contador bruto `container_cpu_usage_seconds_total` com a margem de um scrape antes e depois. Cada delta e ponderado somente pela parte que intercepta `test_start`/`test_stop`; gauges usam media trapezoidal ponderada pelo tempo. Isso reduz a perda nas bordas sem incorporar aquecimento. Como o cAdvisor pode manter um valor em um scrape e publicar o incremento acumulado no seguinte, o maximo bruto por intervalo e preservado para diagnostico, mas o gate do gerador usa a media ponderada da janela normalizada pela cota. A cobertura e registrada e deve ser de pelo menos 90% para cAdvisor; PostgreSQL exige cobertura integral interpolavel. IDs observados pelo coletor continuo identificam inclusive o container Locust transitorio; labels/nome sao apenas fallback.

O `benchmark-results-exporter` e um componente proprio em Python, sem framework web ou dependencias externas. Ele le os CSVs e JSONs ja produzidos por Locust, cAdvisor/Prometheus, postgres-exporter e `docker stats` e os publica em `/metrics` para os dashboards do Grafana. Em resultados oficiais atuais, CPU e memoria sao aceitas somente de `cadvisor_summary.csv`, e recursos so ficam disponiveis quando `postgres_summary.csv` tambem existe; `docker_stats_summary.csv` permanece diagnostico de pilotos e legado. Ele nao instrumenta as APIs, nao substitui os arquivos oficiais e permanece ativo sob a mesma configuracao em todas as linguagens.

`test_phase.elapsed_seconds` e calculado exclusivamente entre `test_start` e `test_stop`. O tempo total do processo Locust e preservado separadamente como `runner_elapsed_seconds`. Build, contrato, warmup, resets, inicializacao do runner e exportacao posterior ficam fora da duracao oficial.

Cada rodada tambem registra `measurement_stability`: RPS da primeira e da ultima janela, mudanca percentual assinada e variacao entre as tres janelas finais. Na medicao principal, tanto a variacao entre janelas finais quanto a variacao absoluta entre a primeira e a ultima janela devem permanecer em ate 10%; ultrapassar qualquer limite torna a rodada `non_official`. No aquecimento, somente as tres janelas finais precisam estabilizar, permitindo que a transicao inicial aconteca antes da medicao. Assim, uma melhoria tardia como a observada anteriormente no Java nao pode ser aceita como estado estacionario.

Se o target cAdvisor responder sem publicar series identificaveis por container, a limitacao nao e mascarada: `scripts/validate_monitoring.py` bloqueia `official` e registra separadamente API, PostgreSQL e Locust ausentes. O resultado de `docker stats` pode ser analisado em pilotos, mas nao recebe classificacao oficial enquanto o TCC mantiver cAdvisor como requisito. As APIs nao expoem `/metrics`, evitando instrumentacao e custo diferentes entre linguagens.

O percentual de CPU do `docker stats` e expresso por nucleo logico: aproximadamente 100% representa um nucleo totalmente utilizado. Em uma maquina com varios nucleos, um container multithread pode ultrapassar 100% sem exceder a capacidade total disponivel.

## Execucao separada

A coleta principal executa apenas uma API por vez. O fluxo sequencial sobe uma linguagem, aquece, coleta, encerra e somente entao inicia a proxima.

O perfil oficial `fixed_200` executa cinco rodadas completas. A ordem das linguagens e rotacionada entre rodadas para distribuir efeitos de temperatura, cache e atividade residual do host. O relatorio apresenta mediana e intervalo minimo-maximo; na metodologia 7, uma combinacao `fixed_200` com menos de cinco rodadas continua marcada como preliminar. Falhas HTTP, metricas ausentes, janela inexata, entrega abaixo de 97,5% do alvo, ordem nao rotacionada nas cinco posicoes, variacao de RPS acima de 10%, instabilidade interna ou falta de folga do gerador invalidam a combinacao. Metodologias historicas e a bateria separada de saturacao preservam o criterio de repeticoes configurado para elas.

O `campaign_fingerprint` vincula os agregados ao commit, metodologia e artefato de calibracao. CSVs, exportador Prometheus e dashboards carregam essa dimensao; rodadas de campanhas diferentes permanecem visiveis, mas nunca compoem a mesma mediana ou classificacao de confianca.

## Proveniencia e classificacao

A metodologia atual e `7`, pois rede de carga, fronteiras transacionais de leitura, cotas de CPU, perfis e calculo temporal mudaram a linha de base. Cada `metadata.json` registra commit completo, arvore suja, hash do diff rastreado, arquivos nao rastreados e seus hashes, imagens e digests, runtimes, bibliotecas, hardware, alocacao Docker, cotas configuradas/efetivas, pool, Locust, cenario, perfil, rodada, ordem e origem de cada metrica. `official` exige Docker 29.5.2, Compose 5.1.4, Git limpo, cAdvisor validado e calibracao quando aplicavel. `pilot` permanece executavel, mas e sempre `non_official`.

## Carga controlada e capacidade

- Quando houver rodadas antigas e atuais para o mesmo nivel de carga, os relatorios usam apenas o maior `methodology_version` dentro da mesma familia, linguagem e classificacao. `legacy_capacity` e `saturation` nunca compartilham baseline.

O perfil `fixed_200` compara latencia e recursos com alvo de 200 req/s; ele nao representa capacidade maxima. Os perfis `saturation_25` a `saturation_400` usam malha fechada e formam uma bateria separada. Antes deles, a calibracao health-only demonstra a capacidade do instrumento; durante cada rodada, a CPU media do Locust na janela, normalizada pela cota, deve ficar abaixo de 90% e a vazao deve permanecer no maximo em 80% da capacidade calibrada. A media e o maximo brutos do cAdvisor tambem sao preservados. Saturacao significa apenas o limite pratico observado neste workload e ambiente.
