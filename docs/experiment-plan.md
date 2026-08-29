# Plano do experimento

## Escopo

O estudo compara Python, Node.js, Java, Go e C#/.NET no mesmo PostgreSQL, com SQL direto, sem ORM e com os oito endpoints de `docs/api-contract.md`. A interpretacao vale somente para o workload, hardware, alocacao Docker, versoes e configuracao registrados.

## Equivalencia antes da carga

1. Resetar apenas `benchmark_db` ao seed deterministico.
2. Validar OpenAPI, schema, indices e contagens.
3. Executar o contrato canonico na API Python validada.
4. Repetir a mesma sequencia nas outras quatro APIs.
5. Comparar JSON estruturalmente e comparar o estado final, inclusive estoque, pagamentos e `audit_logs`.
6. Bloquear a coleta se houver diferenca.

## Workloads

Os cenarios `smoke`, `read_heavy`, `write_heavy` e `mixed` usam os mesmos pesos e payloads JSONL pre-processados em todas as linguagens.

Os perfis de carga respondem a duas perguntas distintas, e por isso sao dois conjuntos separados. Um perfil unico com pacing nao responde nenhuma das duas: o pacing impoe um teto de `usuarios / wait_seconds` requisicoes por segundo, e uma implementacao mais rapida que esse teto apenas espera.

- `fixed_200`: 50 usuarios, spawn rate 10 e pacing de 0,25 s, o que fixa 200 req/s. A vazao e variavel controlada, igual para as cinco, e a comparacao e de latencia e consumo de recursos. Se uma implementacao entregar menos de 97,5% do alvo, ela saturou, a latencia dela deixa de ser comparavel e a rodada nao e elegivel a oficial.
- `saturation_25`, `saturation_50`, `saturation_100`, `saturation_200` e `saturation_400`: sem pacing, em malha fechada. Cada usuario dispara a proxima requisicao assim que a anterior responde, entao o teto passa a ser da propria API. A vazao volta a ser variavel de resposta. O ponto de saturacao e o degrau em que o ganho de RPS ao dobrar a concorrencia cai abaixo de 5%, ou em que a taxa de erro passa de 1%, ou em que a deriva de RPS passa de 10%.

Os perfis `controlled_50`, `capacity_100` e `capacity_200` continuam definidos apenas para releitura do historico.

A carga percorre a rede interna do Docker. Pelo caminho anterior, atraves da porta publicada no host, o `GET /health` custava de 6 a 7 ms sem consultar o banco, e esse piso entrava em toda medicao de leitura.

## Aquecimento e medicao

- aquecimento fixo de 300 segundos;
- mesmos usuarios, spawn rate, espera de 0,1 segundo e workload da medicao;
- leituras e escritas exercitadas;
- tres janelas finais de 45 segundos, deriva maxima de 10%;
- reset do banco apos aquecimento sem reiniciar a API;
- medicao principal de 5 minutos;
- tempo util entre eventos Locust `test_start` e `test_stop`, sem aquecimento;
- reset depois da medicao.

## Metricas

Locust: requisicoes, falhas, taxa de erro, media, P50, P95, P99 e RPS por metodo/endpoint. cAdvisor: CPU e memoria identificaveis da API ativa, PostgreSQL e Locust. postgres-exporter: disponibilidade continua, conexoes, commits, rollbacks, blocos lidos/encontrados em cache, cache hit ratio e tamanho do banco. `postgres_summary.csv` preserva esses valores por rodada. A janela de Prometheus e dos recursos usa exatamente os limites da medicao.

`docker stats` e preservado como coleta complementar/contingencial. Pela especificacao atual do TCC, ele nao torna uma rodada oficial quando o cAdvisor falha.

## Repeticoes e ordem

O perfil oficial `controlled_50` executa cinco rodadas completas. Cada rodada mede as cinco linguagens sequencialmente, totalizando 25 medicoes de API. A ordem e rotacionada, e `execution_order.position` e `sequence_id` ficam nos metadados. Uma unica rodada permanece preliminar ate a bateria ser concluida.

## Classificacao

Metodologia atual: `6`.

- `pilot`: permitido com ambiente divergente ou Git sujo; resultado `non_official`.
- `official`: exige Docker 29.7.2, Compose 5.3.1, arvore Git limpa, imagens fixadas, cAdvisor por container, targets saudaveis e `project-verification.json` aprovado no mesmo commit.

Os consolidadores agrupam por linguagem, endpoint quando aplicavel, cenario, perfil e metodologia. `legacy`, `non_official` e `official` nunca entram no mesmo agregado. O dashboard oficial aplica os mesmos filtros e so publica recursos quando cAdvisor e postgres-exporter forneceram a janela completa.
