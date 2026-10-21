# Grafana — referência técnica

O Compose usa Grafana 11.3.0 com imagem fixada por digest. O serviço recebe:

- volume `grafana-data` para estado local;
- `grafana/provisioning` montado somente para leitura;
- `grafana/dashboards` montado somente para leitura.

A fonte provisionada é Prometheus em `http://prometheus:9090`. O provedor
`provisioning/dashboards/default.yml` atualiza a pasta de dashboards a cada
10 segundos. O Compose define o dashboard de visão geral como página inicial.

Os arquivos provisionados incluem `benchmark-overview.json`,
`benchmark-analysis.json` e `benchmark-extras.json`. Eles devem ser tratados como visualização: para a
análise acadêmica, preserve e consolide os CSVs/JSONs da rodada, filtrando
classificação, campanha, perfil e protocolo antes de comparar.

O dashboard oficial filtra uma metodologia, campanha, cenário e perfil por
vez, em variáveis ocultas com os valores da campanha publicada. Linguagem e
métrica por operação ficam visíveis. As consultas são instantâneas: refletem
os artefatos salvos republicados pelo exporter. A janela de tempo do Grafana
não corresponde à duração da execução original.

`python scripts/build_grafana_overview.py` gera duas definições:

- `benchmark-overview.json`: sete painéis consolidados por API (mediana ou
  média) — latência média, P50/P95/P99, CPU, memória, leituras, escritas e
  tabela de vazão/erro.
- `benchmark-analysis.json`: cinco painéis complementares — latência por
  execução, extremos da latência selecionada, extremos de CPU/memória e
  tabela com extremos da vazão/erro.

Os links entre as visões usam `includeVars` para preservar a campanha e os
filtros. No principal, o filtro de latência altera apenas as operações; no
complementar, altera latência por execução e o resumo dos extremos.

**Consolidação (mediana ou média).** A variável `consolidacao` (rótulo
Consolidação, valores `median`/`mean`, padrão `median`) aparece nos dois
dashboards e viaja pelos links. Cada consulta consolidada tem dois ramos e o
filtro mantém só um, sem alterar as demais variáveis:

```promql
(label_replace(<mediana>, "consolidacao", "median", "", "")
 or label_replace(<média>, "consolidacao", "mean", "", ""))
and on(consolidacao) label_replace(vector(1), "consolidacao", "$consolidacao", "", "")
```

No dashboard principal, o ramo da mediana é a consulta que já existia sobre as
séries `benchmark_result_*` e `benchmark_endpoint_*`, publicadas pelo exporter;
os valores com `Mediana` selecionada são, portanto, os mesmos de antes. O ramo
da média é `avg by(...)` sobre as séries por execução (`benchmark_run_*` e
`benchmark_endpoint_run_*`), com os mesmos filtros de campanha. A média
entre execuções de P50/P95/P99 também não é um percentil global. O exporter e
os arquivos publicados em `results/official` continuam consolidando só pela
mediana; a média existe apenas na visualização. O gráfico de latência por
execução não depende da consolidação.

No dashboard complementar, a série central dos extremos é `Consolidado` por
dentro e recebe o nome `Mediana` ou `Média` por `displayName`
(`${consolidacao:text}`). As colunas `Vazão · Consolidado` e
`Erro · Consolidado` seguem a mesma regra.

Os resumos mínimo/valor consolidado/máximo usam `min by(language)`,
`quantile by(language)(0.5, ...)` ou `avg by(language)(...)`, e
`max by(language)` sobre métricas de cada
execução. A latência usa `benchmark_run_latency_ms`. CPU e memória usam
`benchmark_run_cpu_percent{component="api",stat="average"}` e
`benchmark_run_memory_bytes{stat="average"}`, provenientes das médias
preservadas no cAdvisor. Recursos ausentes não são publicados como zero.
O máximo das médias não deve ser confundido com a métrica antiga `stat="peak"`.
A taxa de erro de cada execução é `100 * failures / requests`.

Os eixos começam em zero. CPU mantém 100% por núcleo e máximo suave de 30%,
que cresce quando necessário. Memória é convertida para MiB. Execuções são
categorias sem unidade; os percentis usam ms. Cores por linguagem ficam nos
painéis comparativos; nos gráficos de extremos, cinza indica mínimo, azul
mediana e laranja máximo. Leituras e escritas têm escalas independentes.

As duas visões cobrem a consolidação descrita na página 14 do TCC (28).
A separação altera a apresentação, sem retirar a evidência de variabilidade.
P66/P75/P80/P90/P98/P99,9/P99,99/P100 permanecem nos CSVs brutos, sem serem
confundidos com novos percentis globais ou incluídos na consolidação do TCC.

O dashboard de diagnóstico apresenta somente saúde dos serviços, atividade
atual do PostgreSQL e Locust ao vivo em uma seção recolhida. Uma ausência de
carga atual não significa perda das evidências históricas.

Alterar a visualização após uma coleta não altera o protocolo registrado nos
resultados publicados. Uma nova campanha deve passar pelas verificações do
novo commit, pois os arquivos de monitoramento integram o fingerprint.
