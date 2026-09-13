# Exportador do PostgreSQL

Este componente lê informações internas do PostgreSQL e as entrega ao
Prometheus. Ele não muda as consultas das APIs nem altera os dados do banco.

Ele ajuda a observar quantas conexões estão ativas e se há sessões esperando
por I/O ou lock. Esses números são amostras do instante de coleta; não são o
tempo total que uma consulta esperou.

Veja as consultas, filtros e limites em [TECHNICAL.md](TECHNICAL.md). O
exportador de resultados é outro componente, documentado em
[../results-exporter/README.md](../results-exporter/README.md).
