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

Uma única thread lê e valida os artefatos, publica um snapshot em memória e
aguarda cinco segundos antes de atualizar novamente. `/metrics` responde com
esse snapshot, sem acessar os arquivos durante o scrape. Isso evita que a
leitura dos resultados no volume Windows exceda o timeout de um segundo do
Prometheus e acumule leituras concorrentes. A coleta de cAdvisor e PostgreSQL
continua a cada segundo; o snapshot serve apenas à visualização dos resultados.

O healthcheck em `/health` retorna 503 até a primeira coleta bem-sucedida,
quando a atualização falha ou quando o snapshot fica sem atualização por mais de
30 segundos. Nesses casos, `/metrics` publica `benchmark_results_exporter_up=0`
sem reutilizar resultados antigos como se estivessem saudáveis. Erros de leitura
são registrados no log. A verificação dos hashes dos snapshots Locust permanece
obrigatória para incluir resultados das metodologias atuais.

`scripts/validate_monitoring.py` exige que ele esteja disponível para uma rodada,
juntamente com Prometheus e o PostgreSQL exporter, e grava os erros de scrape
no relatório. Os runners PowerShell e Bash recriam o exporter e o Prometheus
antes da preparação para carregar o código e a configuração montados por volume.
