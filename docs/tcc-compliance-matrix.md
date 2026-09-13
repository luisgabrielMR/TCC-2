# Matriz de aderencia ao TCC — metodologia 15

Esta matriz registra o protocolo implementado, nao declara uma campanha concluida.
A referencia documental anterior foi o PDF TCC_Luis_Gabriel_Mendonca_Reos (27),
paginas 9 a 15. O PDF nao esta versionado no repositorio; a correspondencia com
a revisao academica aprovada deve ser conferida antes da entrega.

| Aspecto | Implementacao / evidencia | Limite de interpretacao |
| --- | --- | --- |
| Cinco ecossistemas, oito APIs e sete operacoes no mixed | Contrato HTTP preserva `/health`; `config/scenarios.json` e testes de workload definem as sete operacoes PostgreSQL | Nao isola linguagem de runtime, servidor e driver |
| SQL direto e dataset comum | SQL parametrizado, mesmo schema/seed, testes de estado final | Custo comum do SQL pode dominar a latencia |
| Pool maximo20 | Compose e drivers; configuracao comum 1/20/10s/60s/1800s | Minimo persistente e escopo de timeout variam por driver |
| Perfis oficiais de carga | fixed_50 e fixed_100; mesmos100 usuarios, pacing2s/1s | Niveis devem ser analisados separadamente; carga fechada, nao aberta; campanha oficial ainda nao executada |
| Workload reproduzivel | Ciclos ponderados embaralhados por semente/worker; manifesto, `locust_workload_mix.json` e payloads particionados | Intercalacao concorrente e prefixo final podem diferir; analisar contagens realizadas |
| Recursos | PG1 CPU, API2, gerador4; Go GOMAXPROCS2 | Quotas nao sao reservas; registrar host e memoria Docker efetiva |
| Software | Imagens por digest e inventario preflight; Docker29.5.2 / Compose5.1.4 exigidos | Nao substituir versoes aprovadas pelo PDF para contornar divergencias |
| Preparacao | Reset logico, seed200k, VACUUM ANALYZE, CHECKPOINT; warmup300s | Nao limpa cache do SO ou do runtime |
| Janela de medicao | 300s apos spawn; reconciliacao dos workers, drenagem5s | Percentis em histogramas arredondados; duracao de pilotos e distinta |
| Recursos por container | cAdvisor -> Prometheus; recorte temporal e cobertura | Nao atribuir CPU/memoria a endpoints |
| Diagnostico do banco | postgres-exporter: sessoes ativas/esperas nao Client, Lock, IO | Snapshots1s nao medem tempo total de espera nem provam ausencia de gargalo |
| Compatibilidade PG17 | Coletor legado stat_bgwriter desativado; query estendida no exporter0.15 | Query estendida e deprecated nessa versao fixada; nao atualizada implicitamente |
| Gerador | CPU cAdvisor e entrega efetiva; calibracao health-only opcional | CPU media abaixo do limite nao prova capacidade sob toda carga |
| Repeticoes e ordem | Menu Windows:5 por nivel; rotacao das linguagens e alternancia dos niveis | Preparado nao significa executado |
| Separacao dos dados | classification + campaign_fingerprint + protocol_sha256; filtro --campaign | Piloto abreviado permanece non_official; historicos nao sao promovidos |
| Analise | Latencias, vazao, erros, recursos; medianas e min-max entre rodadas | Sem teste de significancia; adequate nao e confianca estatistica |
| Prontidao cientifica | Verificacao funcional + pilotos + congelamento + campanha completa | Nenhum desses passos substitui os outros |

## Evidencia de execucao

A verificacao integrada gera results/raw/verification/<timestamp>/ e
results/summaries/project-verification.json. Os pilotos ficam nas pastas
de linguagem/perfil/run_N, com classificacao non_official e tempos registrados.
Consultar os artefatos da execucao atual, nao inferir aprovacao a partir desta
matriz ou de registros de uma metodologia antiga.

## Criterio de encerramento

Finalizar implementacao e testes, revisar os dois niveis nos pilotos, versionar
o protocolo com autorizacao do autor, e so entao executar as cinco repeticoes
completas por nivel. Relatar falhas e exclusoes em vez de selecionar apenas
as rodadas favoraveis. Nao existe garantia absoluta de ausencia de gargalos ou
de erros futuros; as conclusoes precisam ser sustentadas pelas series coletadas.

Detalhes e procedimento: [Notas metodologicas](methodological-notes.md).
