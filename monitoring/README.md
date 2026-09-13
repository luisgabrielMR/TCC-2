# Monitoramento

O monitoramento observa o experimento sem adicionar uma rota de métricas às
cinco APIs. Isso evita dar uma vantagem ou desvantagem de instrumentação a uma
linguagem.

| Ferramenta | Em linguagem simples | Documentação |
| --- | --- | --- |
| Prometheus | junta as métricas periodicamente | [README](prometheus/README.md) |
| Grafana | mostra painéis para leitura humana | [README](grafana/README.md) |
| cAdvisor | mede CPU e memória dos containers | [README](cadvisor/README.md) |
| PostgreSQL exporter | lê informações internas do banco | [README](exporters/README.md) |
| Results exporter | transforma resultados salvos em métricas | [README](results-exporter/README.md) |

Durante uma rodada, Prometheus coleta os dados; Grafana apenas os apresenta.
Os CSVs e JSONs em `../results/` continuam sendo os artefatos que devem ser
preservados. O dashboard não é uma segunda medição independente.

Veja o fluxo e os limites de interpretação em [TECHNICAL.md](TECHNICAL.md).
