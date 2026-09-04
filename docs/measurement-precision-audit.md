# Auditoria de transacoes e precisao (2026-09-04)

## Evidencia executada

Diagnostico sem escrita, sem reset e sem rodadas oficiais:
`scripts/diagnose_transactions.py --output results/summaries/transaction-diagnostic-20260904.json`.
Foram executadas 201 requisicoes medidas por endpoint, apos precondicionamento,
em quatro leituras de cada uma das cinco APIs. A observacao de `benchmark_db`
foi feita por uma conexao ao banco administrativo `postgres`, evitando contar
a propria consulta diagnostica em `benchmark_db`. Os contadores continuam
assincronos e incluem monitoramento: estes valores nao sao contagens isoladas
por sessao nem medidas de desempenho.

| API | Cliente individual | Lista de clientes | Produtos por categoria | Pedido |
| --- | ---: | ---: | ---: | ---: |
| Python | 1.005 | 2.134 | 2.129 | 1.134 |
| Node | 1.134 | 2.134 | 2.134 | 1.134 |
| Java | 1.144 | 2.144 | 2.149 | 1.144 |
| Go | 2.134 | 3.134 | 4.134 | 2.129 |
| .NET | 2.134 | 3.134 | 3.144 | 2.005 |

Unidade: incremento de `xact_commit` dividido pelas requisicoes do diagnostico.

## Causa

- O contrato logico das leituras e 1, 2, 2 e 1 consultas, respectivamente.
- `lib/pq` 1.10.9 usa `prepareTo` e uma sincronizacao anterior a execucao nas
  consultas parametrizadas, quando `binary_parameters` nao esta ativado. Sem
  `BEGIN`, a sincronizacao pode fechar uma transacao implicita adicional.
  A contagem observada em Go acompanha exatamente esse padrao: a consulta
  `COUNT(*)` de clientes nao tem parametros, mas as duas de produtos tem.
- Npgsql reinicializa o estado da conexao reutilizada, normalmente com
  `DISCARD ALL`. Esse trabalho tambem aparece em `pg_stat_database`. O diagnostico
  mostra aproximadamente um commit adicional por requisicao de leitura.
- Os contadores sao do banco inteiro, nao apenas dos endpoints. Na captura
  `results/summaries/precision-check-20260904/`, sem API ativa, foram observados
  aproximadamente 5.43 commits/s e 0.20 rollback/s, com o monitoramento ativo.
  Nao se deve interpretar esses rollbacks automaticamente como falhas HTTP.

Nao foram alterados os drivers nem desativada a limpeza segura de conexoes.
A comparacao mede a pilha completa (runtime, servidor, driver, protocolo e pool),
nao o custo isolado da linguagem. Igualar transacoes fisicas exigiria uma decisao
metodologica explicita e nova campanha; nao adicionar consultas artificiais nem
subtrair uma taxa fixa de monitoramento dos resultados.

Na rodada de 02/09, a contagem logica calculada pelos endpoints fica entre
74,100 e 74,814. O overhead previsto do protocolo de Go soma 44,924 transacoes,
e o reset de conexoes .NET explica aproximadamente 56,500 adicionais. Isso
explica a ordem de grandeza de 119,419 e 130,701 commits observados. Nao e uma
reconciliacao exata: fronteiras amostradas, estatisticas assincronas, atividades
de pool e monitoramento deixam residuos, inclusive negativos nas estimativas.

## Correcoes de medicao

1. O coletor revisao 2 usa vetores de intervalo brutos via `/api/v1/query`, em
   vez de `/query_range`. Assim preserva os timestamps de scrape e nao transforma
   valores antigos mantidos por lookback em novas observacoes.
2. A janela tem padding de dois scrapes em cada extremidade. O coletor aguarda
   a extremidade posterior antes de consultar; os totais continuam estimados por
   interpolacao nos limites, nao contagens inteiras exatas.
3. Cobertura desconta lacunas superiores a 1.5 vezes o intervalo declarado.
   Exportacoes obrigatorias rejeitam essas lacunas e reinicios de contadores.
4. Um ID conhecido nunca recai numa serie de outro container. Cgroups genericos,
   multiplos targets PostgreSQL e series CPU/memoria ambiguas sao rejeitados.
5. CSV final HTTP e validado antes da promocao: total por endpoint, falhas,
   duplicatas, numeros finitos, latencias nao negativas e P50 <= P95 <= P99.
   Falha de validacao preserva o snapshot anterior.
6. Deriva entre relogio UTC e monotonico tem limite fixo de 50 ms. A tolerancia
   antiga crescia com a duracao e permitiria 1.5 s numa medicao de cinco minutos.
7. Metadados Bash/PowerShell distinguem intervalo Docker Stats do intervalo
   Prometheus, identificam revisao do coletor, percentis aproximados, picos
   amostrados e escopo das transacoes PostgreSQL.

## O que cada numero significa

| Medida | Interpretacao e limite |
| --- | --- |
| Requisicoes e falhas | Contadores finais do master reconciliados com registros independentes de todos os workers, incluindo falhas e soma dos tempos por endpoint. Cancelamentos, pendencias e workers ausentes rejeitam a execucao. |
| Duracao | Diferenca monotonica entre eventos de inicio/fim. UTC localiza a janela no Prometheus; nao mede sincronizacao absoluta entre maquinas. |
| RPS | Contagem final dividida pela duracao monotonica; nao media de taxas instantaneas. |
| Latencia media | Media dos tempos HTTP observados pelo Locust; inclui rede e servidor, nao apenas SQL. |
| P50/P95/P99 | Histograma arredondado do Locust 2.32.6: passos de 1 ms abaixo de 100 ms, 10 ms abaixo de 1 s, 100 ms abaixo de 10 s e 1 s acima. Casas decimais de exibicao nao aumentam a resolucao. |
| CPU media | Delta de tempo de CPU por tempo observado. 100% bruto representa um processador logico; a media do gerador e normalizada pela cota para o gate de folga. |
| CPU maxima | Maior media entre scrapes, nao pico instantaneo. |
| Memoria | Working set amostrado pelo cAdvisor, com media ponderada no tempo; picos entre scrapes podem nao ser vistos. |
| Commits/rollbacks/blocos | Deltas estimados de contadores assincronos do banco inteiro. Incluem atividade administrativa, de drivers e monitoramento. |
| Cache hit | Cache de blocos PostgreSQL, nao garantia de ausencia de I/O do host nem leitura de disco fisico. |
| Variacao entre rodadas | Uma unica repeticao nao permite inferir variabilidade populacional; 0% exibido com n=1 nao e evidencia de estabilidade entre repeticoes. |

## Pendencias e limites

- Nao houve coleta de latencias individuais de alta resolucao nem mudanca do
  histograma Locust. Isso exigiria avaliar o overhead do instrumento e recalibrar.
- O protocolo de encerramento revisao 2 reconcilia todos os workers e rejeita
  requisicoes canceladas/em transito. Isso foi validado em piloto de leituras;
  a bateria completa com escritas e carga alta ainda precisa ser revalidada.
- `fixed_200` continua sendo carga fechada com pacing e fase de subida de usuarios
  dentro da janela, nao um gerador aberto de exatamente 200 chegadas por segundo.
- Nao houve rastreamento de cada mensagem do protocolo em producao; os padroes
  medidos e o codigo dos drivers explicam a diferenca, mas nao cada commit residual.
- Nenhum artefato historico foi recalculado como se contivesse amostras originais.
  Resultados antigos nao podem receber retroativamente a garantia do coletor 2.
- Antes de nova oficial: revisar/versionar, renovar verificacao e calibracao
  vinculadas ao commit. O fingerprint da nova campanha deve permanecer separado
  da campanha anterior; nao completar cinco repeticoes misturando os commits.

## Fechamento distribuido revisao 2

O codigo instalado do Locust 2.32.6 confirmou que `MasterRunner.quit()` chama
`stop(send_stop_to_client=False)` antes de enviar `quit` aos workers e espera
somente 0.5 s por estatisticas finais. Dois pilotos reproduziram problemas reais:
uma janela encerrada antes do worker e um CSV com 2,916 requisicoes quando os
workers haviam concluido 3,000. Essas evidencias diagnosticas foram preservadas.

A integracao agora chama `stop(send_stop_to_client=True)` antes do `quit`
original. Cada worker envia `_send_stats()` antes de sua confirmacao de parada,
pelo mesmo canal RPC ordenado. O master fecha a janela depois das confirmacoes.
O uso dessas APIs e especifico da versao 2.32.6 fixada no projeto e precisa ser
revalidado em qualquer atualizacao do Locust.

`measurement_audit.py` observa inicio/fim das chamadas HTTP em memoria e grava
somente ao terminar: `locust_expected_workers.json` e
`locust_worker_<indice>_final.json`. A promocao de CSV verifica identidade,
frescor temporal, presenca de todos os workers, nenhuma requisicao cancelada ou
pendente, contagens por endpoint e soma dos tempos de resposta. A comparacao de
somas usa tolerancia numerica de ponto flutuante, nao tolerancia de contagens.

Ha ate 5 s de drenagem; ela e parte da duracao medida, junto com a coordenacao.
O manifesto registra o instante da solicitacao de parada e o relatorio registra
`drain_and_coordination_seconds`. Dez segundos iniciais de preparacao do
monitoramento ficam fora da janela. Isto nao transforma a carga fechada em
chegadas abertas nem garante exatamente 200 req/s.

O cAdvisor estava usando housekeeping dinamico e produziu uma lacuna de 8.096 s
nas amostras PostgreSQL. Agora usa `--allow_dynamic_housekeeping=false` e
`--housekeeping_interval=1s`; o validador consulta o comando do container real
e bloqueia elegibilidade oficial sem esses argumentos. Os timestamps preservados
sao os das amostras armazenadas no Prometheus, inclusive timestamps fornecidos
pelo proprio exportador, nao uma grade artificial de cinco segundos.

Piloto final: `results/summaries/worker-audit-pilot-20260904e/`.
Quatro workers, cinco endpoints GET, 3,000 requisicoes, zero falhas, cancelamentos
ou pendencias. Somatorios por endpoint reconciliados; cerca de 1.01 s de drenagem
e coordenacao; cobertura de CPU/memoria de 100% para os tres componentes e
PostgreSQL validado na mesma janela. Trata-se de diagnostico, nao rodada oficial.
Os 68 testes Python passaram. Instrumentacao adicional tem custo: renovar
calibracao e verificacao do commit antes de iniciar uma nova campanha final.
Nao mesclar as execucoes antigas com as novas, nem afirmar que os contadores
historicos foram reconciliados sem os arquivos independentes que nao existiam.

## Referencias primarias

- PostgreSQL 17, protocolo: https://www.postgresql.org/docs/17/protocol-flow.html
- PostgreSQL 17, estatisticas: https://www.postgresql.org/docs/17/monitoring-stats.html
- lib/pq 1.10.9: https://github.com/lib/pq/blob/v1.10.9/conn.go
- Npgsql, pooling/reset: https://www.npgsql.org/doc/performance.html
- Locust 2.32.6: https://docs.locust.io/en/2.32.6/_modules/locust/stats.html
