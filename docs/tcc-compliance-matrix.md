# Matriz de aderencia ao TCC

Fonte documental verificada: `TCC_Luis_Gabriel_Mendonca_Reos (27).pdf`, paginas 9 a 15. Esta matriz registra o estado executavel do projeto; nao substitui o preflight de cada rodada.

| Requisito do TCC | Estado atual | Evidencia ou gate |
| --- | --- | --- |
| Python, Node.js, Java, Go e C#/.NET | OK | Cinco imagens construidas e contrato comum aprovado. |
| Oito endpoints equivalentes | OK | OpenAPI possui oito operacoes; teste contratual cobre sucesso, validacao e erro de banco. |
| PostgreSQL 17 unico e compartilhado | OK | `postgres:17` fixado por digest; schema, seed e estado final comparados. |
| SQL direto, sem ORM | OK | Drivers nativos e SQL parametrizado nas cinco APIs; busca estatica sem ORM/query builder. |
| Locust 2.32.6 | OK | Imagem fixada por digest e workloads comuns por cenario/perfil. |
| Prometheus 2.55.1, Grafana 11.3.0 e postgres-exporter 0.15.0 | OK | Targets `up`, Grafana saudavel e dois dashboards provisionados. |
| cAdvisor 0.49.1 por container | OK | Factory containerd/moby; CPU e memoria encontradas pelos IDs reais de API, PostgreSQL e Locust. |
| Rejeitar cgroups genericos | OK | Teste automatizado rejeita `/`, `/docker` e `/restricted`. |
| P50, P95, P99, media, RPS, requisicoes, falhas e erro | OK | Locust e tres CSVs processados usam o esquema metodologico atual. |
| CPU e memoria oficiais vindas do cAdvisor | OK | `--require-cadvisor`; `docker stats` permanece apenas complementar. |
| Metricas PostgreSQL na janela exata | OK | `postgres_summary.csv` usa postgres-exporter e deltas dentro da janela Locust. |
| Docker Engine 29.5.2 | Pendente externo | Host usa 29.7.2; preflight oficial bloqueia. |
| Docker Compose 5.1.4 | Pendente externo | Host usa 5.3.1; preflight oficial bloqueia. |
| Hardware registrado | OK | Ryzen 5 3600, 6 nucleos/12 threads, 31,93 GiB fisicos e NVMe registrados. |
| Alocacao efetiva dos containers | OK | Docker registra 4 CPUs e 8.328.429.568 bytes; nao e declarada como 32 GB. |
| Git limpo e verificacao no mesmo commit | Pendente | Alteracoes aguardam revisao e autorizacao para commit. |
| Imagens fixadas por digest | OK | Infraestrutura e `FROM` das APIs usam SHA-256. |
| Separacao `legacy`/`non_official`/`official` | OK | Consolidador final usa somente `official` por padrao. |
| Tres repeticoes e ordem rotacionada | Preparado | Runner implementado; bateria nao iniciada porque os gates externos falham. |
| Preflight oficial sem bloqueios | Pendente | Bloqueado por Docker/Compose e Git; nenhuma rodada oficial autorizada. |

## Interpretacao

O projeto esta funcionalmente preparado, mas ainda nao e plenamente elegivel para experimentos oficiais. A aprovacao depende da troca manual das versoes Docker/Compose, revisao e commit das mudancas, nova verificacao completa no commit limpo e novo preflight sem bloqueios. Qualquer conclusao futura deve permanecer limitada ao workload, a alocacao Docker e ao hardware registrados em cada rodada.
