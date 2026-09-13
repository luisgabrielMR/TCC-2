# Monitoramento — referência técnica

## Fluxo de dados

```text
cAdvisor --------------------> Prometheus ----> Grafana
PostgreSQL exporter ---------> Prometheus ----> Grafana
CSV/JSON de uma rodada -> results exporter --> Prometheus -> Grafana
```

`monitoring/prometheus/prometheus.yml` usa scrape e avaliação de 5 segundos.
Os targets são Prometheus, PostgreSQL exporter, cAdvisor e results exporter.
Os serviços são ativados pelo perfil Compose `monitoring`.

## Fonte de cada categoria de métrica

| Métrica | Fonte principal | Limite importante |
| --- | --- | --- |
| Requisições, falhas, latências e taxa entregue | Locust e snapshots dos workers | é métrica HTTP, não transação do banco |
| CPU e memória dos containers | cAdvisor via Prometheus | não é métrica por endpoint |
| Sessões e esperas do PostgreSQL | PostgreSQL exporter | amostras instantâneas, não duração acumulada |
| Resultados por rodada | CSV/JSON validados | results exporter só republica artefatos existentes |

`docker stats` é coletado somente como diagnóstico complementar de pilotos.
Ele não substitui cAdvisor como fonte oficial de CPU ou memória.

Os validadores exigem os targets operacionais, séries identificáveis de API,
PostgreSQL e Locust, além dos dashboards provisionados. Falha de cAdvisor
pode deixar piloto registrável, mas bloqueia uma rodada `official`.

Leia os documentos específicos antes de interpretar uma métrica: [Prometheus]
NaN(cadvisor/TECHNICAL.md), [PostgreSQL exporter](exporters/TECHNICAL.md) e [results exporter](results-exporter/TECHNICAL.md).
