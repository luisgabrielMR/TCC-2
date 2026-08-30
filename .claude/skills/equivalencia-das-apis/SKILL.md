---
name: equivalencia-das-apis
description: Contrato que as cinco implementacoes backend (Python, Node.js, Java, Go, C#/.NET) tem que obedecer para continuarem comparaveis. Use ao criar, editar ou revisar qualquer codigo em apps/, ao mexer em SQL, endpoint, validacao, serializacao ou tratamento de erro, e antes de aceitar qualquer mudanca em uma API sem replicar nas outras quatro.
when_to_use: Pedidos como "mexer na API Go", "mudar a query do /orders", "adicionar um campo na resposta", "corrigir o endpoint de clientes", "por que as linguagens estao diferentes", "revisar apps/", "a implementacao X nao bate com as outras"
paths: apps/**, common/openapi/**, common/sql/**, docs/api-contract.md, docs/sql-contract.md
---

# Equivalencia entre as cinco APIs

O experimento compara ecossistemas, nao implementacoes. Qualquer assimetria entre as cinco vira ruido atribuido a linguagem errada. **Mudanca em uma API exige a mesma mudanca nas outras quatro, no mesmo commit.**

## Regras invioláveis

1. **Sem ORM, sem query builder.** So drivers de acesso direto: psycopg3 + psycopg_pool, `pg`, JDBC + HikariCP, `lib/pq`, Npgsql. Todo SQL escrito a mao e parametrizado pelo driver.
2. **SQL semanticamente equivalente nas cinco.** Tabelas, filtros, joins, locks, ordenacao, paginacao e efeitos precisam coincidir. Diferencas inevitaveis do driver, como `RETURNING stock_quantity` versus contagem de linhas afetadas, sao aceitas somente quando preservam o mesmo comportamento e estao documentadas.
3. **Formatacao monetaria na aplicacao, nunca no banco.** `NUMERIC` sai do driver e vira string de duas casas no codigo: `f"{Decimal:.2f}"`, `Number(v).toFixed(2)`, `money(BigDecimal)`, `Money(decimal)`, `big.Rat.FloatString(2)`. Empurrar isso para o SQL desloca custo da aplicacao para o PostgreSQL em uma linguagem so.
4. **Fronteira de transacao.** Leituras em autocommit, uma transacao implicita por consulta — `GET /customers` e `GET /products` fazem duas consultas, logo duas transacoes. As tres escritas (`POST /customers`, `PUT /customers/{id}`, `POST /orders`) em transacao explicita, com a releitura dentro dela. No Python isso depende de `autocommit=True` no pool (`apps/python-api/app/db.py`); psycopg3 sem isso abre transacao implicita por requisicao.
5. **Oito endpoints, sem sobra nem falta:** `GET /health`, `GET /customers/{id}`, `GET /customers`, `POST /customers`, `PUT /customers/{id}`, `GET /products`, `POST /orders`, `GET /orders/{id}`.
6. **Resposta JSON estruturalmente equivalente.** camelCase, datas `YYYY-MM-DDTHH:MM:SSZ` sem fracao, dinheiro como string de duas casas e os mesmos valores nulos e objetos aninhados. Ordem textual das propriedades e espacos de serializacao nao fazem parte do contrato.
7. **Erro sempre no envelope unico** `{"error":{"code","message","details"}}` com os codigos `VALIDATION_ERROR`, `NOT_FOUND`, `METHOD_NOT_ALLOWED`, `CONFLICT`, `DATABASE_ERROR`, `INTERNAL_ERROR`. Nunca vazar SQLSTATE, stack trace ou HTML do framework.
8. **Diferenca inevitavel de driver se documenta** no README da API e em `docs/methodological-notes.md`. Se nao da para documentar, nao da para aceitar.

## Antes de dar por pronto

```bash
grep -rn "::text" apps/            # tem que ser vazio
grep -rho "count(\*)[:i]*n*t*" apps/*/src/queries.js apps/*/app/queries.py apps/*-api/main.go apps/*-api/Program.cs apps/java-api/src/main/java/benchmark/Main.java | sort | uniq -c
```

Depois, no Windows com Docker no ar:

```
powershell -NoProfile -ExecutionPolicy Bypass -File launchers/windows/powershell/verificar-projeto.ps1
```

O teste que importa: os cinco `database-state-*.json` da pasta nova em `results/raw/verification/<timestamp>/` tem que sair com **hash SHA-256 identico**. Hash diferente significa que as implementacoes deixaram de ser equivalentes — nao rode bateria nenhuma ate resolver.

## Referencia

Campo a campo em `docs/api-contract.md`. Regras de SQL e transacao em `docs/sql-contract.md`. Consultas canonicas em `common/sql/queries_reference.sql`.
