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

Os cenarios `smoke`, `read_heavy`, `write_heavy` e `mixed` usam os mesmos pesos e payloads JSONL pre-processados em todas as linguagens. O perfil principal `controlled_50` usa 50 usuarios e spawn rate 10; mede carga controlada, nao capacidade maxima. `capacity_100` usa 100/20 e `capacity_200` usa 200/40 como testes extras de escalabilidade.

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

Cada perfil oficial executa tres repeticoes. A ordem das cinco linguagens e rotacionada, e `execution_order.position` e `sequence_id` ficam nos metadados. Uma unica execucao e sempre preliminar.

## Classificacao

Metodologia atual: `6`.

- `pilot`: permitido com ambiente divergente ou Git sujo; resultado `non_official`.
- `official`: exige Docker 29.7.2, Compose 5.3.1, arvore Git limpa, imagens fixadas, cAdvisor por container, targets saudaveis e `project-verification.json` aprovado no mesmo commit.

Os consolidadores agrupam por linguagem, endpoint quando aplicavel, cenario, perfil e metodologia. `legacy`, `non_official` e `official` nunca entram no mesmo agregado. O dashboard oficial aplica os mesmos filtros e so publica recursos quando cAdvisor e postgres-exporter forneceram a janela completa.
