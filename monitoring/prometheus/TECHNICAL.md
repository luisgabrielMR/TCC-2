# Prometheus — referência técnica

`prometheus/prometheus.yml` fixa `scrape_interval: 5s` e
`evaluation_interval: 5s`. O Compose monta esse arquivo somente para leitura
em `/etc/prometheus/prometheus.yml` e preserva o banco temporal no volume
`prometheus-data`.

| Job | Target interno | Origem dos dados |
| --- | --- | --- |
| `prometheus` | `prometheus:9090` | saúde do próprio Prometheus |
| `postgres` | `postgres-exporter:9187` | métricas PostgreSQL e query estendida |
| `cadvisor` | `cadvisor:8080` | CPU e memória dos containers |
| `benchmark-results` | `benchmark-results-exporter:9101` | CSV/JSON já finalizados |

O Prometheus não acessa as APIs comparadas. O script
`scripts/export_prometheus_data.py` consulta séries por janela de medição e
salva resumos por rodada. Lacunas, resets e séries ambíguas podem invalidar
evidências obrigatórias; as regras estão no próprio script e nos metadados.
