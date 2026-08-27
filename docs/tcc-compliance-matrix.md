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
| cAdvisor 0.49.1 por container | OK | Factory containerd/moby; CPU e memoria encontradas pelos IDs reais de API, PostgreSQL e Locust. |
| Rejeitar cgroups genericos | OK | Teste automatizado rejeita `/`, `/docker` e `/restricted`. |
| P50, P95, P99, media, RPS, requisicoes, falhas e erro | OK | Locust e tres CSVs processados usam o esquema metodologico atual. |
| CPU e memoria oficiais vindas do cAdvisor | OK | `--require-cadvisor`; `docker stats` permanece apenas complementar. |
| Metricas PostgreSQL na janela exata | OK | `postgres_summary.csv` usa postgres-exporter e deltas dentro da janela Locust. |
| Docker Engine 29.7.2 | OK | Versao instalada, verificada pelo preflight e declarada na Tabela 1 do TCC. |
| Docker Compose 5.3.1 | OK | Versao instalada, verificada pelo preflight e declarada na Tabela 1 do TCC. |
| Hardware registrado | OK | Ryzen 5 3600, 6 nucleos/12 threads, 31,93 GiB fisicos e NVMe registrados. |
| Alocacao efetiva dos containers | OK | Docker registra 4 CPUs e 8.328.429.568 bytes; nao e declarada como 32 GB. |
| Git limpo e verificacao no mesmo commit | Pendente | Arvore limpa no commit anterior; as correcoes deste bloco precisam de novo commit e nova verificacao completa. |
| Imagens fixadas por digest | OK | Infraestrutura e `FROM` das APIs usam SHA-256. |
| Separacao `legacy`/`non_official`/`official` | OK | Consolidador final usa somente `official` por padrao. |
| Cinco rodadas e ordem rotacionada | Preparado | Runner retomavel implementado; bateria ainda nao iniciada. |
| Preflight oficial sem bloqueios | Pendente | Os bloqueios de Docker/Compose foram removidos; falta reexecutar `preflight.py --mode official` apos o commit e a verificacao completa. |

## Interpretacao

O projeto esta funcionalmente preparado. Os bloqueios de versao do Docker deixaram de existir, porque a Tabela 1 do TCC passou a registrar as versoes efetivamente instaladas. Restam tres passos operacionais antes da coleta: commitar as correcoes de equivalencia de SQL e de documentacao, reexecutar a verificacao completa nesse commit limpo e reexecutar o preflight oficial sem bloqueios. Qualquer conclusao futura deve permanecer limitada ao workload, a alocacao Docker e ao hardware registrados em cada rodada.
