# Exportadores

O `docker-compose.yml` inclui:

- `postgres-exporter` para métricas do PostgreSQL.
- `cadvisor` para métricas de containers.

Em Windows com Docker Desktop, o cAdvisor pode exigir ajustes de permissões ou caminhos de volumes. Se não funcionar no seu ambiente, mantenha os dados brutos do Locust e registre a limitação em `metadata.json`.
