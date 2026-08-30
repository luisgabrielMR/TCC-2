# Matriz de aderencia ao TCC

Fonte documental verificada: `TCC_Luis_Gabriel_Mendonca_Reos (27).pdf`, paginas 9 a 15. Esta matriz registra o estado executavel do projeto; nao substitui o preflight de cada rodada.

| Requisito do TCC | Estado atual | Evidencia ou gate |
| --- | --- | --- |
| Python, Node.js, Java, Go e C#/.NET | OK | Cinco imagens construidas e contrato comum aprovado. |
| Oito endpoints equivalentes | OK | OpenAPI possui oito operacoes; teste contratual cobre sucesso, validacao e erro de banco. |
| PostgreSQL 17 unico e compartilhado | OK | `postgres:17` fixado por digest; schema, seed e estado final comparados. |
| SQL direto, sem ORM | OK | Drivers nativos e SQL parametrizado nas cinco APIs; busca estatica sem ORM/query builder. |
| Texto SQL equivalente entre as cinco | OK | Nenhum cast de conversao no SQL comparado; formatacao monetaria feita na aplicacao nas cinco linguagens. |
| Locust 2.32.6 | OK | Imagem fixada por digest e workloads comuns por cenario/perfil. |
| Prometheus 2.55.1, Grafana 11.3.0 e postgres-exporter 0.15.0 | OK | Targets `up`, Grafana saudavel e dois dashboards provisionados. |
| cAdvisor 0.49.1 por container | Pendente | Ja houve evidencia por ID real, mas precisa ser revalidado no ambiente e commit da proxima bateria. |
| Rejeitar cgroups genericos | OK | Teste automatizado rejeita `/`, `/docker` e `/restricted`. |
| P50, P95, P99, media, RPS, requisicoes, falhas e erro | OK | Locust e tres CSVs processados usam o esquema metodologico atual. |
| CPU e memoria oficiais vindas do cAdvisor | OK | `--require-cadvisor`; `docker stats` permanece apenas complementar. |
| Metricas PostgreSQL na janela da medicao | OK | Consulta com margem de scrape, recorte por sobreposicao e gauges ponderados pelo tempo. |
| Docker Engine 29.5.2 | Pendente | O TCC exige 29.5.2; o ultimo host auditado usava 29.7.2 e permanece bloqueado ate ajuste manual. |
| Docker Compose 5.1.4 | Pendente | O TCC exige 5.1.4; o ultimo host auditado usava 5.3.1 e permanece bloqueado ate ajuste manual. |
| Hardware registrado | OK | Ryzen 5 3600, 6 nucleos/12 threads, 31,93 GiB fisicos e NVMe registrados. |
| Alocacao efetiva dos containers | Parcial | Host e Docker sao registrados; cotas do Compose e `NanoCpus` ativos sao validados. Cotas nao sao reservas exclusivas. |
| Git limpo e verificacao no mesmo commit | Pendente | Arvore limpa no commit anterior; as correcoes deste bloco precisam de novo commit e nova verificacao completa. |
| Imagens fixadas por digest | OK | Infraestrutura e `FROM` das APIs usam SHA-256. |
| Separacao `legacy`/`non_official`/`official` | OK | Consolidador final usa somente `official` por padrao. |
| Cinco rodadas e ordem rotacionada | Preparado | Runner retomavel implementado; bateria ainda nao iniciada. |
| Calibracao do gerador | Pendente | Gate implementado; falta executar `/health` 25/50/100/200/400 no commit limpo e ambiente correto. |
| Preflight oficial sem bloqueios | Pendente | Docker/Compose, Git limpo, nova verificacao, cAdvisor e calibracao ainda precisam ser aprovados. |

## Interpretacao

O projeto permanece funcionalmente preparado, mas nao esta elegivel a rodada oficial neste estado. As versoes do PDF nao devem ser alteradas para acompanhar o host. Depois de revisar e versionar as correcoes, e necessario ajustar Docker/Compose manualmente, reexecutar a verificacao completa, calibrar o gerador e obter os dois gates de preflight/monitoramento sem bloqueios. Qualquer conclusao futura deve permanecer limitada ao workload, a alocacao Docker e ao hardware registrados em cada rodada.
