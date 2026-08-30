---
name: auditar-rodada
description: Checar se os numeros de uma rodada do benchmark fazem sentido antes de usar como resultado. Cobre teto do gerador, piso de latencia, trabalho transacional por linguagem, validacao cruzada de CPU e memoria, e o que cada metrica realmente mede. Use ao analisar results/, comparar linguagens, interpretar RPS ou latencia, ou antes de escrever qualquer conclusao no TCC.
when_to_use: Pedidos como "analisa os resultados", "esses numeros fazem sentido", "por que o Go ficou na frente", "compara as linguagens", "auditar a rodada", "o que esses dados dizem", "posso usar isso no TCC"
paths: results/**, scripts/summarize_results.py, scripts/generate_results_dashboard.py
allowed-tools: Read, Grep, Bash
---

# Auditar uma rodada antes de acreditar nela

Ler `metadata.json` sempre com `encoding="utf-8-sig"` — o runner PowerShell grava com BOM e `utf-8` puro estoura.

## Os cinco testes, nesta ordem

**1. A vazao e da API ou do gerador?**
Compare `locust.achieved_rps` com `locust.theoretical_rps_ceiling`. Acima de 90% do teto, a vazao medida e do pacing do Locust, nao da aplicacao — e diferencas entre linguagens nessa faixa sao ruido. Confira tambem `generator_headroom_met` e `locust.locust_cpu_quota_percent`: esse valor divide a CPU bruta do cAdvisor pela cota de quatro CPUs, e precisa ficar abaixo de 90%.

**2. Quanto da latencia e piso fixo?**
Pegue o p50 do `GET /health` no `locust_stats.csv`. Esse endpoint nao consulta o banco e oferece uma referencia do piso de HTTP, runtime e rede. Use-o para contextualizar as demais latencias, mas nao o subtraia aritmeticamente: filas, conexoes e escalonamento nao tornam essas duracoes aditivas.

**3. As cinco fazem o mesmo trabalho no banco?**
Divida `commits_total` do `postgres_summary.csv` pelas requisicoes que tocam o banco (total menos `GET /health`). Pelo contrato — leituras em autocommit, `GET /customers` e `GET /products` com duas consultas, tres escritas transacionais — o esperado e **~1,31 commit por requisicao**. Desvio grande significa fronteira de transacao diferente e quebra a premissa de SQL equivalente.

Compare tambem `blocks_hit` por requisicao. Valores muito distintos com o mesmo SQL costumam indicar plano generico por prepared statement no lado servidor (psycopg3 e JDBC promovem sozinhos; `pg`, `lib/pq` e Npgsql nao).

**4. As metricas de recurso batem entre si?**
`cadvisor_summary.csv` e a fonte oficial. `docker_stats_summary.csv` e diagnostico complementar de pilotos e pode divergir por janela e amostragem; nunca invalide nem substitua o cAdvisor apenas comparando os dois arquivos. Confira cobertura da janela e identificacao dos IDs reais.

**5. A rodada conta como resultado?**
`result_classification` tem que ser `official`. Confira `measurement_stability.stable`, `rate_target_met` e `generator_headroom_met`. E confira `execution_order.sequence_id` e o numero de rodadas: na metodologia 7, menos de cinco por linguagem no perfil `fixed_200`, ou ordem nao rotacionada, e preliminar.

## O que nao medir

`rollbacks_total` vem do healthcheck do container e do proprio exporter, nao das APIs — nas rodadas piloto deu 59 em todas as cinco. Nunca apresentar como metrica de aplicacao.

## Como falar do resultado

Vale por linguagem, endpoint, cenario, perfil e rodada, e so para o workload, hardware, alocacao Docker e versoes registrados naquele `metadata.json`. Ranking fino entre implementacoes que ficaram dentro do intervalo das repeticoes nao se sustenta — dizer que ficaram agrupadas e mais honesto e mais defensavel.
