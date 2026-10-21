# Matriz de aderencia ao TCC — metodologia 17

Esta matriz registra o protocolo implementado e sua visualização. A revisão
TCC_Luis_Gabriel_Mendonça_Reos (28), páginas 11 a 14, foi conferida em
12/10/2026: um perfil `fixed_100`, cinco rodadas e 25 execuções. A campanha
concluída está em `results/official/2026-10-12_fixed_100_m17`, com evidências
e hashes. O PDF acadêmico não está versionado neste repositório.

| Aspecto | Implementacao / evidencia | Limite de interpretacao |
| --- | --- | --- |
| Cinco ecossistemas, oito APIs e sete operacoes no mixed | Contrato HTTP preserva `/health`; `config/scenarios.json` e testes de workload definem as sete operacoes PostgreSQL | Nao isola linguagem de runtime, servidor e driver |
| SQL direto e dataset comum | SQL parametrizado, mesmo schema/seed, testes de estado final | Custo comum do SQL pode dominar a latencia |
| Pool maximo20 | Compose e drivers; configuracao comum 1/20/10s/60s/1800s | Minimo persistente e escopo de timeout variam por driver |
| Perfil oficial de carga | Apenas fixed_100; 100 usuarios, subida20/s, pacing1s, teto nominal100req/s | Carga fechada, nao aberta; registrar taxa efetivamente entregue |
| Workload reproduzivel | Ciclos ponderados embaralhados por semente/worker; manifesto, `locust_workload_mix.json` e payloads particionados | Intercalacao concorrente e prefixo final podem diferir; analisar contagens realizadas |
| Recursos | PG1 CPU, API2, gerador4; Go GOMAXPROCS2 | Quotas nao sao reservas; registrar host e memoria Docker efetiva |
| Software | Imagens por digest e inventario preflight; Docker29.5.2 / Compose5.1.4 exigidos | Nao substituir versoes aprovadas pelo PDF para contornar divergencias |
| Preparacao | Reset logico, seed200k, VACUUM ANALYZE, CHECKPOINT; warmup300s | Nao limpa cache do SO ou do runtime |
| Janela de medicao | 300s apos spawn; reconciliacao dos workers, drenagem5s | Percentis em histogramas arredondados; duracao de pilotos e distinta |
| Recursos por container | cAdvisor -> Prometheus; recorte temporal, cobertura minima95% e lacuna maxima1,5s | Nao atribuir CPU/memoria a endpoints; cobertura nao equivale a entrega de carga |
| Diagnostico do banco | postgres-exporter: sessoes ativas/esperas nao Client, Lock, IO | Snapshots1s nao medem tempo total de espera nem provam ausencia de gargalo |
| Compatibilidade PG17 | Coletor legado stat_bgwriter desativado; query estendida no exporter0.15 | Query estendida e deprecated nessa versao fixada; nao atualizada implicitamente |
| Gerador | CPU cAdvisor e entrega efetiva; calibracao health-only opcional | CPU media abaixo do limite nao prova capacidade sob toda carga |
| Repeticoes e ordem | Menu Windows:5 rodadas de fixed_100; rotacao das linguagens; 25 execucoes | Preparado nao significa executado |
| Separacao dos dados | classification + campaign_fingerprint + protocol_sha256; filtro --campaign | Piloto abreviado permanece non_official; historicos nao sao promovidos |
| Analise (TCC 28, p. 14) | Grafana: media, P50/P95/P99, vazao, erro, CPU e memoria; mediana (padrao) ou media entre execucoes, alternavel no filtro Consolidacao, e min-max entre execucoes | Sem teste de significancia; adequate nao e confianca estatistica |
| Prontidao cientifica | Verificacao funcional + pilotos + congelamento + campanha completa | Nenhum desses passos substitui os outros |

## Evidencia de execucao

A verificacao integrada gera results/raw/verification/<timestamp>/ e
results/summaries/project-verification.json. Os pilotos ficam nas pastas
de linguagem/perfil/run_N, com classificacao non_official e tempos registrados.
A evidencia da campanha oficial publicada esta preservada no pacote de resultados,
medida no commit d2716c1. Alteracoes posteriores de visualizacao nao modificam
essa origem; novas coletas precisam de nova verificacao do codigo/configuracao.

## Criterio de encerramento

Finalizar implementacao e testes, revisar o perfil fixed_100 nos pilotos, versionar
o protocolo com autorizacao do autor, e so entao executar as cinco rodadas
completas desse perfil. Relatar falhas e exclusoes em vez de selecionar apenas
as rodadas favoraveis. Nao existe garantia absoluta de ausencia de gargalos ou
de erros futuros; as conclusoes precisam ser sustentadas pelas series coletadas.

Detalhes e procedimento: [Notas metodologicas](methodological-notes.md).
