# Plano do experimento

## Objetivo experimental

Comparar o comportamento de cinco implementações backend equivalentes ao acessar PostgreSQL em operações comuns de APIs: leitura simples, leitura paginada, filtro, escrita com relacionamento, atualização e transação com múltiplas tabelas.

O objetivo não é provar que uma linguagem é sempre superior. O estudo mede o comportamento dentro de um cenário controlado, com banco, endpoints, payloads, consultas SQL, regras de erro, warmup e coleta de métricas padronizados.

## Linguagens avaliadas

- Python
- JavaScript no ambiente Node.js
- Java
- Go
- C#/.NET

Cada linguagem será executada separadamente. A coleta principal nunca deve executar duas APIs ao mesmo tempo.

## PostgreSQL comum

Todas as APIs acessam a mesma instância PostgreSQL porque o banco precisa ser uma fonte comum de dados, índices, relacionamentos e custos de consulta. Isso reduz variações externas e mantém o foco na interação entre linguagem, runtime, servidor HTTP, driver PostgreSQL, pool de conexões e SQL executado.

## SQL direto

Todas as implementações devem usar SQL direto com comandos parametrizados. Não é permitido usar ORM. A consulta de referência para cada endpoint fica em `common/sql/queries_reference.sql` e o contrato metodológico fica em `docs/sql-contract.md`.

## Motivo de não usar ORM

ORMs adicionam geração automática de SQL, cache, rastreamento de entidades, lazy loading e abstrações que variam muito entre ecossistemas. Essas diferenças poderiam dominar a medição. O experimento usa SQL direto para tornar a lógica de acesso mais visível e equivalente.

## Uso mínimo de frameworks

Frameworks completos podem introduzir pipelines, middlewares, reflexão, injeção de dependência e camadas automáticas difíceis de comparar. O experimento permite apenas bibliotecas necessárias para HTTP, JSON, rotas simples, driver PostgreSQL e pool de conexões.

## Endpoints avaliados

- `GET /health`
- `GET /customers/{id}`
- `GET /customers?page=1&pageSize=50`
- `POST /customers`
- `PUT /customers/{id}`
- `GET /products?categoryId={id}`
- `POST /orders`
- `GET /orders/{id}`

## Métricas pretendidas

- Tempo médio de resposta
- P50
- P95
- P99
- Requisições por segundo
- Falhas
- Total de requisições por endpoint
- CPU média por container
- Memória média por container
- Métricas básicas do PostgreSQL
- Tempo total da fase principal, sem warmup
- CPU do gerador Locust
- Ganho de RPS e eficiência de escala entre 50, 100 e 200 usuários

## Fluxo geral

1. Preparar ambiente.
2. Coletar versões.
3. Subir PostgreSQL.
4. Criar schema, índices e seed determinístico.
5. Gerar payloads JSONL.
6. Validar banco.
7. Subir uma API.
8. Rodar smoke test.
9. Rodar warmup.
10. Resetar banco sem reiniciar a API.
11. Rodar teste principal.
12. Exportar métricas.
13. Encerrar a API.
14. Repetir para a próxima linguagem.

## Rodadas

Os scripts aceitam múltiplas rodadas por linguagem e cenário. O padrão sugerido é executar três rodadas por linguagem por cenário, sempre registrando ordem, commit, horários, parâmetros de Locust, parâmetros de warmup e configuração efetiva do pool.

## Niveis de carga

- `controlled_50`: 50 usuarios, spawn rate 10, comparacao controlada.
- `capacity_100`: 100 usuarios, spawn rate 20, teste extra de escalabilidade.
- `capacity_200`: 200 usuarios, spawn rate 40, teste extra de escalabilidade.

Cada nivel executa warmup, reset e medicao independentes. O limite encontrado e descrito como capacidade pratica observada no ambiente, sem generalizacao para outras maquinas.
