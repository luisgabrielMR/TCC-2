# Notas metodológicas

## Justificativa para uso mínimo de frameworks

A escolha por uso mínimo de frameworks busca reduzir interferências de frameworks completos, ORMs e abstrações automáticas, mantendo a análise concentrada na interação entre linguagem, runtime, servidor HTTP, driver PostgreSQL, pool de conexões e execução das operações.

O objetivo não é eliminar toda biblioteca. O experimento permite bibliotecas necessárias para expor HTTP, serializar JSON, configurar rotas simples, acessar PostgreSQL e gerenciar pool de conexões. O que deve ser evitado são camadas que escondam a lógica principal, como geração automática de endpoints, persistência por ORM, validações mágicas, scaffolding pesado ou estruturas MVC complexas sem necessidade experimental.

## Bibliotecas planejadas

- Python: FastAPI em uso mínimo, Uvicorn, psycopg3 e psycopg_pool.
- Node.js: Express em uso mínimo e `pg`.
- Java: Javalin ou HTTP simples, JDBC e HikariCP.
- Go: `net/http`, roteador mínimo se necessário, `database/sql` e driver PostgreSQL.
- C#/.NET: ASP.NET Core Minimal API e Npgsql.

Essas escolhas devem ser revisadas quando cada API for implementada e registradas em `docs/environment-versions.md`.

## Política de pool de conexões

Configuração base:

```env
DB_POOL_MIN=1
DB_POOL_MAX=20
DB_POOL_ACQUIRE_TIMEOUT_SECONDS=10
DB_POOL_IDLE_TIMEOUT_SECONDS=60
DB_POOL_MAX_LIFETIME_SECONDS=300
```

Como cada ecossistema implementa pooling de forma diferente, o objetivo não é tornar os drivers internamente idênticos. O objetivo é garantir intenção equivalente: mesmo limite máximo de conexões, tempos próximos de espera, política semelhante de ociosidade e registro explícito das diferenças.

Diferenças inevitáveis devem ser registradas no `metadata.json` de cada rodada.

## Warmup

O warmup deve ser igual para todas as linguagens:

- duração: 180 segundos
- usuários: 20
- spawn rate: 5
- resultado não entra na coleta principal
- API não deve ser reiniciada entre warmup e teste principal
- banco deve ser resetado depois do warmup sem derrubar a API

## Controle de geração de payloads

O Locust não deve gerar payloads aleatórios pesados durante a coleta principal. Os arquivos JSONL em `common/payloads/` devem ser gerados antes da coleta e lidos sequencialmente pelos cenários de carga.

## Execução separada por linguagem

A coleta principal deve executar apenas uma API por vez. Scripts sequenciais podem percorrer as linguagens, mas devem subir uma, coletar, derrubar e só então iniciar a próxima.
