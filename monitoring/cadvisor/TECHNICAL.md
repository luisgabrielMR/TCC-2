# cAdvisor — referência técnica

O serviço `cadvisor` usa a imagem 0.49.1 fixada por digest no Compose e é
iniciado com privilégios e montagens somente leitura de `/`, `/var/run`, `/sys`
e `/var/lib/docker`. Isso é necessário para identificar containers.

Argumentos efetivos obrigatórios:

- `--allow_dynamic_housekeeping=false`;
- `--housekeeping_interval=1s`;
- `--containerd-namespace=moby`;
- `--docker=unix:///var/run/cadvisor-disabled-docker.sock`.

Os dois últimos contornam a incompatibilidade do factory Docker legado com o
image store containerd do Docker Desktop. O validador exige séries associadas
aos IDs reais dos containers, não agregados como `/`, `/docker` ou
`/restricted`.

O Prometheus coleta o cAdvisor e o PostgreSQL exporter a cada 1 s, alinhado ao
`--housekeeping_interval=1s` acima; esse alinhamento não altera o argumento do
cAdvisor. `scripts/export_prometheus_data.py` calcula médias temporais e picos
na janela da medição. CPU é normalizada pela quota do container; memória é
working set. Nas rodadas oficiais, CPU e memória de cada um dos três
componentes (API, PostgreSQL e Locust) devem cobrir ao menos 95% da janela.
Uma série ausente, com gap superior a 1,5 s ou reset de contador invalida a
evidência oficial, mesmo com cobertura total suficiente. `docker stats`
permanece diagnóstico complementar de piloto.
