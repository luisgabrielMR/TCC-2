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

`scripts/export_prometheus_data.py` calcula médias temporais e picos na janela
da medição. CPU é normalizada pela quota do container; memória é working set.
Uma série ausente, com gap excessivo ou reset de contador invalida evidência
oficial. `docker stats` permanece diagnóstico complementar de piloto.
