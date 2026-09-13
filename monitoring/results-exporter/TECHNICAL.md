# Exportador de resultados — referência técnica

`monitoring/results_exporter.py` roda em uma imagem Python 3.12-slim e escuta
em `127.0.0.1:9101`. Ele lê `results/raw` e publica somente artefatos que já
existem; seus volumes de scripts e resultados são somente leitura.

Para metodologias atuais, ele verifica snapshots finalizados por worker antes
de considerar uma rodada completa. Para execução `official`, CPU e memória vêm
de `cadvisor_summary.csv`; `docker_stats_summary.csv` fica como diagnóstico de
pilotos ou dados antigos.

O componente identifica campanha pelo fingerprint declarado no metadata; se
não houver, usa o commit como compatibilidade histórica. Métricas de taxa usam
`request_count / elapsed_seconds` apenas quando a janela exata foi validada.
Ele não promove `non_official` ou `legacy` a resultado oficial.

O serviço tem healthcheck em `/health`. `scripts/validate_monitoring.py` exige
que ele esteja disponível para uma rodada, juntamente com Prometheus e o
PostgreSQL exporter.
