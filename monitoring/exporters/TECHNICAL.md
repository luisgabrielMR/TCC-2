# Exportador do PostgreSQL — referência técnica

O serviço `postgres-exporter` usa `prometheuscommunity/postgres-exporter`
v0.15.0, imagem fixada por digest. Sua conexão aponta para `benchmark_db` com
`application_name=benchmark_exporter`, o que permite excluir a própria conexão
das métricas de atividade.

A query estendida está em `postgres-benchmark-queries.yaml`. Ela exporta gauges
para:

- sessões client backend ativas;
- sessões ativas esperando evento que não é Client;
- sessões ativas esperando `Lock`;
- sessões ativas esperando `IO`.

A query considera somente `current_database()`, `backend_type = 'client backend'`
e exclui `application_name = 'benchmark_exporter'`. Portanto, os valores são
contagens instantâneas de sessões, não percentual de queries bloqueadas nem
duração acumulada de espera.

O coletor legado `stat_bgwriter` é desabilitado porque esta versão consulta
colunas removidas no PostgreSQL 17. Estatísticas de checkpoint/bgwriter não
fazem parte das métricas do experimento. A query estendida é usada apesar de
estar marcada como deprecated no exporter fixado; a versão não foi atualizada
implicitamente durante o benchmark.
