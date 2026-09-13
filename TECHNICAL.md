# Referência técnica do projeto

## Arquitetura

```text
  Locust --> uma API ativa --> PostgreSQL
   |              |              |
   +---- métricas +--> coletores +--> Prometheus --> Grafana
Resultados CSV/JSON --> exporter de resultados --+
```

O Docker Compose cria uma rede `tcc_benchmark_network`. O Locust conversa com a
API pela rede interna durante o benchmark. A porta `8000` existe para testes
locais; ela não é o caminho de medição oficial.

| Componente | Serviço Compose | Perfil | Limite de CPU | Porta no host |
| --- | --- | --- | ---: | --- |
| Banco | `postgres` | sempre ativo | 1 | 5432 |
| API | uma entre cinco | linguagem correspondente | 2 | 8000 |
| Gerador | `locust` | `load` | 4 | 8089 |
| Banco → métricas | `postgres-exporter` | `monitoring` | sem quota declarada | 9187 |
| Coleta | `prometheus` | `monitoring` | sem quota declarada | 9090 |
| Visualização | `grafana` | `monitoring` | sem quota declarada | 3000 |
| CPU e memória | `cadvisor` | `monitoring` | sem quota declarada | 8080 |
| Resultados → métricas | `benchmark-results-exporter` | `monitoring` | sem quota declarada | 9101 local |

As quotas são limites, não reservas exclusivas do computador. O preflight exige
o Docker configurado com pelo menos oito processadores lógicos para acomodar a
soma das quotas principais e o monitoramento.

## Fontes de configuração

- `docker-compose.yml`: serviços, rede, volumes, portas e quotas.
- `.env.example`: valores padrão versionados. `.env` é a cópia local ignorada.
- `scripts/benchmark_protocol.py`: manifesto, perfis e fingerprint.
- `scripts/preflight.py`: versões e condições exigidas para modo oficial.

Imagens e digests ficam em `.env.example`; o preflight registra as imagens
efetivamente usadas em cada execução.

## Protocolo vigente

| Item | `fixed_50` | `fixed_100` |
| --- | ---: | ---: |
| Usuários | 100 | 100 |
| Spawn rate | 20/s | 20/s |
| Pacing por usuário | 2 s | 1 s |
| Teto nominal | 50 req/s | 100 req/s |
| Repetições oficiais | 5 | 5 |

O aquecimento e a medição oficiais duram 300 segundos cada. O Locust usa quatro
processos. O menu alterna a ordem das linguagens e dos perfis entre rodadas.

Os serviços compartilham o mesmo PostgreSQL, o mesmo seed, o mesmo contrato
HTTP, SQL equivalente e pool máximo de 20 conexões. O que se compara é a
implementação completa (linguagem, runtime, servidor e driver), não uma
propriedade isolada da linguagem.

## Navegação técnica por componente

- [Infraestrutura Docker](infrastructure/TECHNICAL.md)
- [APIs e pools](apps/TECHNICAL.md)
- [Banco e reset](database/TECHNICAL.md)
- [Locust e distribuição da carga](load-tests/locust/TECHNICAL.md)
- [Monitoramento](monitoring/TECHNICAL.md)
- [Execução](launchers/TECHNICAL.md)
- [Resultados e consolidação](results/TECHNICAL.md)
- [Scripts](scripts/TECHNICAL.md)

Documentos metodológicos e de contrato permanecem em `docs/`. Alguns arquivos
históricos citam perfis antigos; o protocolo vigente é definido por
`scripts/benchmark_protocol.py`, `.env.example` e
`docs/methodological-notes.md`.
