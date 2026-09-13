# Exportador de resultados

Depois de uma rodada, este componente lê os CSVs e JSONs já salvos e os
apresenta como métricas para Prometheus e Grafana. Ele serve para visualizar
resultados; não executa carga e não instrumenta as APIs.

Assim, se ele estiver desligado, os dados brutos de uma rodada continuam nos
arquivos de resultados. Para entender os filtros, classificações e validações,
leia [TECHNICAL.md](TECHNICAL.md).
