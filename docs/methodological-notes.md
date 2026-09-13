# Protocolo experimental — metodologia 15

## Objetivo e alcance

Comparar cinco implementacoes backend (Python, Node.js, Java, Go e C#/.NET)
com o mesmo PostgreSQL, contrato HTTP, SQL, payloads e dataset. A unidade
comparada e o conjunto implementacao + runtime + servidor + driver; nao a
linguagem isolada. O resultado vale para o hardware, quotas e workload registrados.

Este documento descreve a implementacao atual; nao e a redacao academica final.
A matriz de aderencia referencia o PDF aprovado, que nao esta versionado aqui.
Conferir o texto final com esse PDF antes de entregar o TCC.

## Desenho principal

- Cenario: mixed, oito operacoes. Pesos: health 5%; cliente individual 15%;
  listagem de clientes 15%; produtos 15%; pedido individual 15%; criar cliente
  10%; atualizar cliente 10%; criar pedido 15%. Sao 60% leituras com banco,
  35% escritas e 5% health sem banco.
- Referencia principal: fixed_50; nivel complementar de maior pressao: fixed_100.
  Os pilotos de 13/09/2026 fundamentam essa distincao (ver relatorio abaixo).
  Ambos usam 100 usuarios,
  spawn rate 20/s, quatro processos Locust. Pacing: 2 s e 1 s respectivamente.
- Modelo FECHADO com pacing: usuarios aguardam respostas; 50/100 req/s sao
  taxas nominais, nao chegadas abertas independentes. Publicar a taxa efetiva.
  Nao usar esse desenho para inferir comportamento sob fila aberta/sobrecarga.
- A primeira requisicao de cada usuario recebe uma fase distribuida no periodo.
  O tempo de spawn nao e contado pelo pacing da primeira tarefa.
- Selecao suave e deterministica das operacoes por worker, com ciclo de 20
  operacoes no mixed e offsets distintos. Cada ciclo completo respeita os pesos.
  O prefixo incompleto no encerramento pode diferir; guardar contagens reais.
  Nao ha promessa de ordem global identica: respostas e escalonamento variam.
- Payloads de criacao de clientes usam faixas disjuntas por worker; outros
  payloads percorrem ciclos com offsets. Nao se garante identica intercalacao
  concorrente de atualizacoes, nem identico instante de acesso a cada registro.
- Cinco rodadas POR NIVEL, ordem das cinco linguagens rotacionada. O menu Windows
  percorre OFFICIAL_PROFILES, alternando tambem a ordem dos perfis por rodada.
  Uma chamada de proxima rodada executa cinco APIs de um nivel; sao dez chamadas
  para completar os dois niveis com cinco repeticoes.
- Warmup oficial: 300 s; medicao oficial: 300 s apos spawn completo.
  Pilotos abreviados sao sempre non_official e nao substituem essas repeticoes.

## Escolha e congelamento da carga

A avaliacao local das dez combinacoes esta em
[Validacao da metodologia 15](validation-methodology-15.md). O nivel50 manteve
CPU media PostgreSQL de 32,6% a 36,9% da cota, enquanto o nivel100 atingiu
63,3% a 73,3%, incluindo tres avisos de margem >=70%. Por isso, nivel50 e a
referencia principal; nivel100 permanece como comparacao complementar de
sensibilidade a carga. Nao misturar seus resultados nem apresentar o nivel100
como evidencia de banco sem pressao. Ambos exigem repeticoes oficiais separadas.
Foram observadas esperas de I/O mesmo no nivel50; a escolha nao elimina nem
isola o custo do banco e nao demonstra latencias estacionarias.

Antes da campanha, executar ambos os niveis em todas as APIs. Avaliar entrega
da carga, falhas, latencia por endpoint, CPU media E picos do banco/gerador,
sessoes ativas e esperas. O criterio operacional existente de CPU media abaixo
de 90% da cota NAO prova ausencia de gargalo. Preferir margem ampla e examinar
a mudanca entre os dois niveis. Esperas amostradas iguais a zero tambem nao
provam ausencia de esperas curtas.

O relatorio opcional assess_primary_pilots.py recebe uma sequence_id explicita
e confere as dez combinacoes, fontes executaveis iguais e um protocolo por
nivel, snapshots, estabilidade, CPU e cobertura. Para selecao dos pilotos,
sinaliza entrega fora de +/-2,5% do nominal, CPU media PostgreSQL >=70% como
aviso de margem, picos >=90% e esperas observadas. Esses avisos nao sao novos
preflights nem uma prova automatica de ausencia de gargalo. Eles devem ser
interpretados antes do congelamento, e nao ajustados apos ver um ranking.

Se um nivel comprometer o banco ou gerador em qualquer implementacao, rever
o nivel comum ou as quotas para TODAS e repetir os pilotos antes do congelamento.
Nao escolher parametros para ampliar diferencas entre linguagens. Nao remover
somente rodadas lentas para favorecer uma implementacao. Registrar falhas,
exclusoes e justificativas, mantendo os artefatos originais.

Aumentar pool para 100 nao equivale a oferecer 100 req/s. Pool20 e quotas
permanecem inalterados: API2 CPU, PostgreSQL1 CPU, Locust4 CPU. Sao limites,
nao reservas/afinidades exclusivas. Compartilham host e memoria Docker;
capturar a alocacao efetiva, nao apenas a memoria fisica do PC.

## Banco e condicoes controladas

PostgreSQL 17 com imagem por digest; shared_buffers=128MB, work_mem=4MB,
effective_cache_size=4GB, max_connections=100 e statement_timeout=30000ms.
effective_cache_size e estimativa do planejador, nao memoria reservada.

Seed deterministico: 200.000 clientes, enderecos, pedidos e pagamentos;
400.000 itens e registros de auditoria; 100 produtos e cinco categorias.
Reset logico antes do warmup e novamente antes da medicao; o runner tambem
restaura no final. O reset repoe sequences/dados, executa VACUUM ANALYZE,
CHECKPOINT e pg_stat_reset. Locust deve estar parado durante o reset.

O reset NAO limpa cache do SO, buffers, planos, JIT ou heap da aplicacao.
O runtime aquecido continua ativo. Registrar essa limitacao; nao chamar
o procedimento de cold cache. A rotacao reduz efeitos de ordem, nao os elimina.
A consulta COUNT(*) da listagem e parte do workload: seu custo comum nao
pode ser atribuido a linguagem, e seu plano/custo nao deve ser presumido.

## Aplicacoes e pools

Nenhum SQL, endpoint, payload ou regra de negocio foi alterado nesta revisao.
Minimo1, maximo20, aquisicao10s, idle60s, lifetime1800s, conforme suporte do driver.
Python: FastAPI/Uvicorn, psycopg/psycopg_pool; Node: Express/pg;
Java: HttpServer, Jackson/JDBC/HikariCP; Go: net/http, database/sql/lib/pq;
.NET: ASP.NET Core Minimal API/Npgsql. Sem ORM.

Node nao preabre o minimo; Go nao garante um minimo persistente de conexoes
ociosas. O escopo do timeout nao e identico entre drivers: registrar as notas
do metadata. Modelos de concorrencia tambem diferem: Python Uvicorn de processo
unico com tarefas sincronas, Node event loop, Java virtual threads, Go e .NET
com seus escalonadores. Go configura GOMAXPROCS=2. Nao igualar esses conceitos
ao numero de CPUs utilizado ou de conexoes simultaneamente ativas.

## Coleta e unidades

Locust 2.32.6 mede contagens, falhas e latencia HTTP. Vazao canonica =
requisicoes concluidas / segundos monotonicos da janela. P50/P95/P99 sao
recalculados dos histogramas arredondados dos workers. Janela inicia apos
spawn; encerra na ultima fronteira de parada dos workers, com drenagem limitada
a 5 s das requisicoes iniciadas antes da parada. Contagens/histogramas devem
reconciliar; requests cancelados ou pendentes nao sao promovidos.

Prometheus coleta a cada 5 s; cAdvisor usa housekeeping de 1 s. Revisao3 do
coletor exporta timestamps reais, margem de scrape e medias ponderadas pelo
tempo, rejeitando gaps/reset/ambiguidade quando a evidencia e obrigatoria.
CPU bruta100% equivale a um core; dividir pela quota para obter percentual
da cota. Working set de memoria e por container. CPU/memoria NAO sao
atribuicoes por endpoint. docker stats permanece complementar.

postgres-exporter v0.15.0 recebe consulta customizada pg_benchmark_activity:
sessoes client backend ativas, ativas esperando evento nao Client,
esperando Lock e esperando IO; todas no banco experimental, excluindo as
conexoes identificadas do exporter. Sao gauges instantaneos (sessoes),
nao tempo acumulado de espera nem percentual de queries bloqueadas.
Postgres_summary.csv fornece media ponderada e maximo de cada gauge; series
originais ficam em prometheus_series.json. Resultados antigos mostram vazio,
nao zero, quando essa instrumentacao nao existia.

A consulta estendida e suportada mas deprecated nessa imagem fixada. O coletor
stat_bgwriter legado foi desabilitado por consultar colunas removidas no PG17;
estatisticas de checkpoint/bgwriter nao integram as metricas do trabalho.
Os contadores de commits, rollbacks e blocos sao do BANCO INTEIRO, incluindo
monitoramento/drivers. Nao sao equivalentes a transacoes HTTP; cache_hit_ratio
e dos buffers PostgreSQL, nao evidencia de I/O fisico. Grafana visualiza;
o results-exporter republica resultados, nao e uma medicao independente.

## Proveniencia, analise e execucao

Metodologia15 e nova coorte. Manifesto registra modelo, ciclo/hash, fases,
carga, warmup, pool, quotas, seed, Compose e intervalos; fingerprint combina
protocolo e commit. Hashes dos arquivos executaveis/configuracoes/payloads
tambem entram no manifesto, inclusive arquivos ainda sem commit; documentos
e resultados ficam fora desse conjunto. A calibracao health-only e opcional e nao faz mais parte
do hash de um protocolo que nao a exige. Nao ha nova obrigacao de calibrar
para cada execucao. Preflight ainda verifica o ambiente/contrato oficial,
incluindo Docker29.5.2, Compose5.1.4 e Git limpo. Nao contornar esses controles.

Deriva da latencia no warmup e diagnostica, nao bloqueante isoladamente.
Erros operacionais/integridade permanecem erros, nao resultados cientificos.
Falha de criterios de comparabilidade deve permanecer documentada junto
aos dados non_official; nao presumir que ela identifica a causa do gargalo.

Os consolidadores separam campanha, protocolo, perfil e classificacao.
Use --campaign no summarize_results.py para uma coorte explicita. Divulgar
numero de rodadas, mediana e min-max por linguagem/endpoint/nivel.
Mediana de P95 entre rodadas nao e P95 global. Nao ha teste de significancia,
intervalo de confianca ou causalidade isolada implementados. A etiqueta
adequate do software e verificacao operacional, nao confianca estatistica.

Fluxo: ambiente -> reset -> API -> verificacoes/contrato -> reset -> warmup
-> reset -> medicao Locust em paralelo a cAdvisor/exporter/Prometheus
-> reconciliacao dos workers -> exportacao da janela -> metadata -> reset
-> parada da API -> consolidacao/visualizacao. So uma API e medida por vez.

Para reproduzir a validacao funcional no Windows:
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/verificar-projeto.ps1

Para um piloto:
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/rodar-linguagem.ps1 -Language python -Scenario mixed -LoadProfile fixed_50 -RunMode pilot

Para uma rodada oficial usar o menu existente, apos finalizar/versionar o
protocolo e revisar os pilotos. Nao transformar execucoes abreviadas em oficiais.
