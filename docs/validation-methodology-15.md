# Validacao local da metodologia 15 — 13/09/2026

## Alcance da evidencia

Implementacao e validacao tecnica, nao campanha oficial nem ranking cientifico.
O PDF aprovado nao esta disponivel neste checkout: conferir a correspondencia
com sua revisao academica antes da entrega. Este relatorio usa codigo e artefatos
locais como evidencia, sem declarar que o texto aprovado foi relido.

Host registrado no preflight: AMD Ryzen 5 3600 (6 nucleos/12 threads);
Docker com 8 CPUs logicas e 8.327.397.376 bytes de memoria disponivel.
Docker Engine 29.5.2, Compose 5.1.4, kernel WSL
6.18.33.1-microsoft-standard-WSL2. As cotas nao sao reservas exclusivas:
API2 CPU, PostgreSQL1 CPU, Locust4 CPU. Pool maximo20 em todas as APIs.
O inventario detalhado de software/imagens esta no preflight de cada piloto.

## Verificacoes executadas

- Verificacao integrada: `results/raw/verification/20260913T134155649Z/`;
  resumo em `results/summaries/project-verification.json`.
- Builds das cinco APIs, contrato HTTP (oito operacoes), payloads, validacao
  do seed, equivalencia do estado final do banco e politica de espera SQL.
  Espera de 12s retornou HTTP200; espera de 33s encontrou o timeout SQL de 30s
  e retornou HTTP500 nas cinco implementacoes.
- Monitoramento, teste Go do pool, smoke/mixed Locust e 123 testes passaram
  nessa verificacao integrada, antes do fechamento do commit.
- A suite final passou com **124 testes**, incluindo uma regressao adicional
  do comando de avaliacao em processo Python isolado.
- Dez pilotos sequenciais, sem testes/builds concorrentes durante a medicao.
  Cenario mixed; 100 usuarios; quatro workers; spawn20/s; warmup60s;
  medicao90s; janelas de estabilidade15s; pacing2s/1s conforme o perfil.
- Todos os pilotos sao `non_official`. Padroes oficiais permanecem warmup300s
  e medicao300s, cinco repeticoes por linguagem e por nivel.

## Resultados operacionais dos pilotos

Sequencia: `primary_m15_pilot_20260913T111043`.
Relatorio completo: `results/summaries/primary_m15_pilot_20260913T111043.json`.
Os dez registros passaram nas verificacoes de snapshots, reconciliacao,
janela, cobertura, estabilidade operacional de vazao e margem CPU operacional.
Total da medicao: **67.499 requisicoes, zero falhas HTTP**.

| Implementacao | RPS efetivo 50 | CPU PG media 50 (% cota) | RPS efetivo 100 | CPU PG media 100 (% cota) |
| --- | ---: | ---: | ---: | ---: |
| Python | 49,959 | 32,625 | 99,891 | 65,136 |
| Node.js | 49,964 | 35,857 | 99,906 | 71,742 |
| Java | 49,960 | 32,643 | 99,907 | 63,283 |
| Go | 49,961 | 36,622 | 99,885 | 73,312 |
| .NET | 49,965 | 36,882 | 99,904 | 72,128 |

No nivel50, cada API concluiu 4.500 requisicoes com contagens identicas por
endpoint. No nivel100, foram 9.000 por API, exceto Go com 8.999: um POST /orders
a menos. A reconciliacao de Go confirmou os quatro workers, sem cancelamentos
nem requisicoes pendentes. Nao completar contagens artificialmente.

Cada consolidacao isolada tem cinco linhas de linguagem e quarenta de endpoint:

- `results/processed/primary_m15_pilot_20260913T111043/fixed_50/`
- `results/processed/primary_m15_pilot_20260913T111043/fixed_100/`

CSVs e resumos por campanha, consolidacao padrao e geracao do dashboard foram
executados com sucesso. Nenhum piloto foi promovido para official; nenhum
resultado historico foi removido.

## Decisao e limites

**fixed_50 e a referencia principal; fixed_100 e o nivel complementar de
maior pressao.** A decisao usa margem do banco e entrega da carga, nao a ordem
de desempenho das linguagens. No nivel100, Node, Go e .NET ultrapassaram o
aviso previamente definido de CPU media PG >=70%; nao ultrapassaram o criterio
operacional de 90%. A maior media foi73,3%; maior pico78,5%. No nivel50,
as medias ficaram abaixo37% e os picos abaixo41%. CPU Locust media ficou
abaixo5% da cota em todos os pilotos.

Isso NAO prova ausencia de gargalo: houve amostras de espera por I/O em todos
os pilotos e por lock em Python/Java no nivel100. Os gauges amostrados a cada
5s nao medem tempo total de espera. CPU baixa nao exclui dependencia de I/O,
locks, custo de SQL ou armazenamento. Nenhum parametro de durabilidade foi
relaxado e nenhum SQL foi alterado para obter numeros melhores.

`stable=true` nao significa latencia estacionaria: a deriva de latencia por
endpoint e diagnostica. Houve avisos, inclusive variacoes elevadas nas escritas.
No Java/nivel50, a comparacao de vazao entre primeira/ultima janela ficou em
9,97%, proxima do limite10%. Os JSONs de estabilidade preservam esses dados.
Os pilotos curtos nao demonstram que cinco minutos eliminarao essas variacoes.

Somente uma observacao por combinacao foi feita aqui, em ordem fixa de pilotos.
A campanha oficial usa rotacao de linguagens/alternancia de niveis. Nao ha
base aqui para significancia estatistica, causalidade exclusivamente da
linguagem ou exclusao seletiva de resultados lentos. Comparar implementacao,
runtime, servidor e driver, por endpoint/perfil, com as repeticoes previstas.

## Proveniencia e correcao no fechamento

Os dez manifestos registram o mesmo commit-base
`1e7c9a879d0dd77b5e686abf66ea27d6a22c41fc`, worktree em alteracao e o mesmo
mapa de 129 fontes executaveis. Um protocolo por nivel:

- 50: `m15_1e7c9a879d0d_f693778a8bd6`;
- 100: `m15_1e7c9a879d0d_c07b44af1b1f`.

A primeira chamada CLI do novo avaliador falhou ao importar snapshot_integrity
no Python isolado do pgAdmin. Foi corrigida a inicializacao de sys.path em
`scripts/assess_primary_pilots.py`, sem alterar os snapshots ou a carga.
O teste CLI demonstrou a falha antes da correcao e passou depois; o avaliador
foi reexecutado com sucesso sobre os mesmos dez pilotos.

A comparacao de hashes confirmou que esse avaliador de POS-PROCESSAMENTO e
a unica fonte executavel diferente desde as medicoes. Nao foi usado para
gerar carga ou coletar metricas. Testes/documentacao tambem foram atualizados.
Os pilotos nao foram reetiquetados como execucoes do commit final nem repetidos
para mascarar a falha do avaliador. Uma campanha oficial futura tera seu proprio
commit/fingerprint e seus proprios dados.

## O que ainda exige execucao cientifica

O projeto validado prepara a campanha, mas **as cinquenta medicoes oficiais
da metodologia15 ainda nao foram executadas**: cinco linguagens x dois niveis
x cinco repeticoes. Usar o atalho de proxima rodada, revisar o perfil exibido
e manter o ambiente congelado. Uma chamada completa mede cinco APIs de um
nivel. O preflight do commit limpo verifica prontidao operacional, nao substitui
a campanha nem elimina os limites acima.
