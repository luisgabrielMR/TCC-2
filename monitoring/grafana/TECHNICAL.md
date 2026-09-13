# Grafana — referência técnica

O Compose usa Grafana 11.3.0 com imagem fixada por digest. O serviço recebe:

- volume `grafana-data` para estado local;
- `grafana/provisioning` montado somente para leitura;
- `grafana/dashboards` montado somente para leitura.

A fonte provisionada é Prometheus em `http://prometheus:9090`. O provedor
`provisioning/dashboards/default.yml` atualiza a pasta de dashboards a cada
10 segundos. O Compose define o dashboard de visão geral como página inicial.

Os arquivos provisionados incluem `benchmark-overview.json` e
`benchmark-extras.json`. Eles devem ser tratados como visualização: para a
análise acadêmica, preserve e consolide os CSVs/JSONs da rodada, filtrando
classificação, campanha, perfil e protocolo antes de comparar.
