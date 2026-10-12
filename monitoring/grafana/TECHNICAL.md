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

O dashboard oficial filtra uma metodologia, campanha, cenário e perfil por
vez, em variáveis ocultas com os valores da campanha publicada. Linguagem e
métrica por operação ficam visíveis. As consultas são instantâneas: refletem
os artefatos salvos republicados pelo exporter. A janela de tempo do Grafana
não corresponde à duração da execução original.

`python scripts/build_grafana_overview.py` gera a definição oficial. Os seis
painéis usam `barchart`, sem tabelas, gauges ou rolagem interna: latência média,
P95 por execução, CPU, memória, leituras e escritas. Os gráficos por linguagem
usam mediana; o P95 por execução preserva as observações individuais.

Eixos começam em zero e compartilham escala dentro de cada gráfico. CPU usa
100% por núcleo e máximo suave de 30%, que pode crescer se houver valores
maiores. A memória é convertida para MiB. As execuções são categorias numéricas
sem unidade; leituras e escritas têm escalas independentes. Cores e ordem das
linguagens são consistentes com as imagens publicadas.

O dashboard de diagnóstico apresenta somente saúde dos serviços, atividade
atual do PostgreSQL e Locust ao vivo em uma seção recolhida. Uma ausência de
carga atual não significa perda das evidências históricas.

Alterar a visualização após uma coleta não altera o protocolo registrado nos
resultados publicados. Uma nova campanha deve passar pelas verificações do
novo commit, pois os arquivos de monitoramento integram o fingerprint.
