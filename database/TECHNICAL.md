# Banco de dados — referência técnica

## Configuração do serviço

O serviço `postgres` usa PostgreSQL 17, imagem fixada por digest em
`.env.example`, banco `benchmark_db` e usuário `benchmark_user` por padrão.
O Compose declara `cpus: 1.0` e publica a porta 5432.

Parâmetros do servidor definidos em `docker-compose.yml` e validados pelo
preflight:

| Parâmetro | Valor |
| --- | --- |
| `statement_timeout` | 30000 ms |
| `shared_buffers` | 128 MB |
| `effective_cache_size` | 4 GB |
| `work_mem` | 4 MB |
| `max_connections` | 100 |

`effective_cache_size` é uma estimativa para o planejador, não memória reservada.

## Schema, seed e validação

- `init/001_schema.sql`: tabelas, chaves e constraints.
- `init/002_seed_base_data.sql`: dataset determinístico.
- `init/003_indexes.sql`: índices.
- `scripts/validate_database.sql`: contagens, objetos e índices esperados.
- `scripts/capture_contract_state.sql`: estado final usado na equivalência das APIs.

O modelo detalhado está em `../docs/database-model.md`; o SQL esperado pelas
APIs está em `../docs/sql-contract.md`.

## Reset entre etapas

`reset/reset_database.sql` restaura os dados e os índices, reinicia sequências,
executa `VACUUM (ANALYZE)`, `CHECKPOINT` e `pg_stat_reset`. O runner para o
Locust antes do reset para evitar concorrência com `TRUNCATE` e seed.

O runner restaura antes do warmup, antes da medição e ao final. Isso torna os
dados lógicos comparáveis, mas não limpa cache do sistema operacional, buffers
do PostgreSQL, planos, JIT ou heap de runtimes. Portanto, não descreva o
procedimento como *cold cache*.
