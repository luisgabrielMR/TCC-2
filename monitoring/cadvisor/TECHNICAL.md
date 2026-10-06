# cAdvisor — referência técnica

O serviço `cadvisor` usa a imagem 0.49.1 fixada por digest no Compose e é
iniciado com privilégios e montagens somente leitura de `/`, `/var/run`, `/sys`
e `/var/lib/docker`. Isso é necessário para identificar containers.

Argumentos efetivos obrigatórios:

- `--allow_dynamic_housekeeping=false`;
- `--housekeeping_interval=200ms`;
- `--containerd-namespace=moby`;
- `--docker=unix:///var/run/cadvisor-disabled-docker.sock`.

Os dois últimos contornam a incompatibilidade do factory Docker legado com o
image store containerd do Docker Desktop. O validador exige séries associadas
aos IDs reais dos containers, não agregados como `/`, `/docker` ou
`/restricted`.

O Prometheus coleta o cAdvisor e o PostgreSQL exporter a cada 1 s. A atualização
interna do cAdvisor usa base de 200 ms: a versão 0.49.1 acrescenta jitter de até
100% mesmo com housekeeping dinâmico desabilitado. Uma base de 1 s produzia
intervalos de quase 2 s. A base menor deixa margem para o scrape de 1 s sem
trocar a imagem ou substituir os timestamps originais. Esse dimensionamento
não garante o escalonamento do sistema operacional; os gaps reais continuam
sendo verificados. Consulte o [diagnóstico e a fonte upstream](../../docs/monitoring-cadvisor-20261006.md).

O preflight examina uma janela de 30 s das amostras reais antes da carga;
presença de séries e target `up` são insuficientes. Durante a inicialização,
aguarda até 45 s pela janela. `scripts/export_prometheus_data.py` calcula médias temporais e picos
na janela da medição. CPU é normalizada pela quota do container; memória é
working set. Nas rodadas oficiais, CPU e memória de cada um dos três
componentes (API, PostgreSQL e Locust) devem cobrir ao menos 95% da janela.
Uma série ausente, com gap superior a 1,5 s ou reset de contador invalida a
evidência oficial, mesmo com cobertura total suficiente. `docker stats`
permanece diagnóstico complementar de piloto.

`cadvisor-validation.json` registra cobertura, gaps, resets e motivos por
componente mesmo quando a exportação é rejeitada. `prometheus-validation.json`
identifica a etapa e o erro. Os CSVs de resultados oficiais não recebem linhas
rejeitadas. O novo intervalo e o fator de jitter integram o manifesto e os
metadados; o fingerprint separa a campanha corrigida das tentativas anteriores.
