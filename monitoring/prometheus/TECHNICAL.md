# Prometheus — referência técnica

`prometheus/prometheus.yml` fixa `scrape_interval: 1s` e
`evaluation_interval: 1s`. O primeiro define a coleta dos targets, incluindo
cAdvisor e PostgreSQL exporter. O segundo só controla a avaliação de regras;
como o projeto não declara regras, ele foi mantido em 1 s para deixar uma
cadência global única. O Compose monta esse arquivo somente para leitura em
`/etc/prometheus/prometheus.yml` e preserva o banco temporal no volume
`prometheus-data`. Os runners recriam somente o container `prometheus` antes
de uma execução para que o processo carregue a configuração montada; o volume
não é removido.

| Job | Target interno | Origem dos dados |
| --- | --- | --- |
| `prometheus` | `prometheus:9090` | saúde do próprio Prometheus |
| `postgres` | `postgres-exporter:9187` | métricas PostgreSQL e query estendida |
| `cadvisor` | `cadvisor:8080` | CPU e memória dos containers |
| `benchmark-results` | `benchmark-results-exporter:9101` | CSV/JSON já finalizados |

O Prometheus não acessa as APIs comparadas. O script
`scripts/export_prometheus_data.py` consulta séries por janela de medição e
salva resumos por rodada. Lacunas, resets e séries ambíguas podem invalidar
evidências obrigatórias; o limite de lacuna é calculado como 1,5 vezes o
`step_seconds` registrado na exportação, portanto 1,5 s nas novas rodadas.
