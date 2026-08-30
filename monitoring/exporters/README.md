# Exportadores

- `postgres-exporter`: metricas internas do PostgreSQL para Prometheus.
- `cadvisor`: fonte exigida pelo TCC para CPU e memoria dos containers.
- `benchmark-results-exporter`: publica CSV/JSON ja gerados como series para Grafana, sem instrumentar as APIs. Em metodologias oficiais atuais, aceita CPU e memoria somente de `cadvisor_summary.csv`, exige `postgres_summary.csv` para os recursos da rodada e mantem `docker_stats_summary.csv` restrito a pilotos e legado. A vazao da metodologia 7 usa contagem de requisicoes dividida pela duracao monotonica validada.

`scripts/validate_monitoring.py` exige tres targets operacionais saudaveis (`postgres-exporter`, `benchmark-results-exporter` e Prometheus), `benchmark_results_exporter_up=1`, Grafana com os dois dashboards provisionados e, separadamente, o target e as series cAdvisor identificaveis para API ativa, PostgreSQL e Locust. Uma falha operacional interrompe qualquer teste; uma falha exclusiva do cAdvisor ainda permite piloto, mas bloqueia qualquer rodada `official`. `docker stats` permanece complementar para pilotos.

No Docker Desktop com image store containerd, o cAdvisor 0.49.1 e iniciado com `--containerd-namespace=moby` e com o factory Docker desativado por um socket inexistente. Isso evita a dependencia do `layerdb` legado e preserva as series de CPU/memoria por ID real. O validador nao aceita cgroups agregados como `/`, `/docker` ou `/restricted`.
