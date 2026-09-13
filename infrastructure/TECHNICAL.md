# Infraestrutura Docker — referência técnica

## Serviços, perfis e comunicação

`docker-compose.yml` define uma rede única, `tcc_benchmark_network`. Todos os
containers usam essa rede. Durante uma rodada, o Locust acessa
`http://{api-service}:8000`; isso evita introduzir a porta do host no caminho
de medição.

| Grupo | Serviços | Como são iniciados |
| --- | --- | --- |
| Base | `postgres` | sem perfil, sempre necessário |
| APIs | `python-api`, `node-api`, `java-api`, `go-api`, `dotnet-api` | perfil da linguagem; uma por vez |
| Carga | `locust` | perfil `load` |
| Monitoramento | exporter PostgreSQL, Prometheus, Grafana, cAdvisor e exporter de resultados | perfil `monitoring` |

As APIs dependem do healthcheck de PostgreSQL. O exporter PostgreSQL também
espera o banco saudável. Não há dependência Compose entre Locust e API porque
o runner controla a sequência da rodada.

## Recursos, rede e armazenamento

- API: `cpus: 2.0`; Go também recebe `GOMAXPROCS=2`.
- PostgreSQL: `cpus: 1.0`.
- Locust: `cpus: 4.0`.
- Volumes persistentes: `postgres-data`, `prometheus-data`, `grafana-data`.
- Montagens somente leitura: banco, configurações de monitoramento, código
  do Locust, scripts e payloads.
- Resultados são montados como escrita apenas onde o runner/Locust precisa
  criá-los; monitoramento os lê sem modificá-los.

Portas externas principais: PostgreSQL `5432`, APIs `8000`, Locust `8089`,
Prometheus `9090`, Grafana `3000`, cAdvisor `8080`, PostgreSQL exporter `9187`
e results exporter `9101` limitado a `127.0.0.1`.

## Imagens e imutabilidade

As imagens são declaradas com tags e digests em `.env.example`. O preflight
registra as imagens efetivamente usadas e bloqueia Docker Engine diferente de
29.5.2 ou Compose diferente de 5.1.4 no modo oficial. Não altere esses valores
para fazer uma máquina divergente passar.

O manifesto de cada execução inclui hash da configuração Compose efetiva. A
alteração de `docker-compose.yml`, de variáveis relevantes ou de arquivos de
carga muda a identidade da campanha.
