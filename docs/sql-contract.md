# Contrato SQL

Todas as APIs devem usar SQL direto, parametrizado e logicamente equivalente. A referência principal fica em `common/sql/queries_reference.sql`.

## Regras de equivalência

- Não usar ORM.
- Não montar SQL com concatenação de entrada do usuário.
- Usar parâmetros do driver em todos os valores externos.
- Preservar filtros, joins, ordenação e limites documentados.
- Não adicionar cache de aplicação durante a coleta principal.
- Não mudar o estado do banco fora dos endpoints definidos.
- Implementar `POST /orders` em transação.
- Implementar `POST /customers` e `PUT /customers/{id}` em transacao.
- Executar as leituras em autocommit, uma transacao implicita por consulta, sem
  agrupar consultas de um mesmo endpoint em transacao explicita. `GET /customers`
  e `GET /products` fazem duas consultas e, portanto, duas transacoes.
- Reverter a transacao em qualquer erro, inclusive `404`, `409` e falha do driver.
- Registrar diferenças inevitáveis de sintaxe no README da API correspondente.

## GET /customers/{id}

Consulta cliente e endereço principal por `customers.id`.

Parâmetros:

- `$1`: id do cliente.

Índices usados:

- chave primária de `customers`.
- `idx_addresses_customer_default`.

## GET /customers

Consulta paginada com ordenação estável e o mesmo `LEFT JOIN` do endereco padrao
usado na consulta individual. Cliente sem endereco padrao retorna `address: null`.

Parâmetros:

- `$1`: page size.
- `$2`: offset calculado por `(page - 1) * pageSize`.

Índices usados:

- `idx_customers_created_id`.

## POST /customers

Transação obrigatória:

1. Inserir cliente.
2. Inserir endereço.
3. Inserir audit log.
4. Retornar cliente criado.

Erros de unicidade devem ser convertidos para `409 CONFLICT`.

## PUT /customers/{id}

Transação obrigatória:

1. Atualizar cliente.
2. Atualizar endereço principal; inserir o endereco recebido se nenhum endereco
   padrao existir.
3. Inserir audit log.
4. Retornar cliente atualizado.

Cliente inexistente deve retornar `404 NOT_FOUND`.

## GET /products?categoryId={id}

Consulta produtos ativos por categoria.

Parâmetros:

- `$1`: id da categoria.

Índice usado:

- `idx_products_category_active`.

## POST /orders

Transação obrigatória:

1. Validar cliente.
2. Validar endereço do cliente.
3. Criar pedido.
4. Para cada item, bloquear produto com `FOR UPDATE`.
5. Validar estoque.
6. Baixar estoque.
7. Inserir item.
8. Calcular total.
9. Inserir pagamento.
10. Inserir audit log.
11. Retornar pedido completo.

Estoque insuficiente deve retornar `409 CONFLICT`.

Indice usado:

- `idx_order_items_order` no calculo do total do pedido.

## GET /orders/{id}

Consulta pedido completo com joins entre:

- `orders`
- `customers`
- `addresses`
- `order_items`
- `products`
- `categories`
- `payments`

O formato JSON final pode ser montado na aplicação para manter equivalência entre linguagens.
A consulta deve selecionar todos os campos usados nos objetos de pedido, cliente,
endereco, item, produto, categoria e pagamento.

## Estado final e auditoria

`database/scripts/capture_contract_state.sql` produz o snapshot canonico usado
pelos testes entre linguagens. Ele compara contagens, registros alterados, estoque,
sequencias e payloads JSONB de `audit_logs`; apenas timestamps gerados durante a
execucao sao excluidos. Os payloads de criacao de cliente, atualizacao de cliente
e criacao de pedido usam as mesmas chaves `camelCase` nas cinco APIs.

Indices usados:

- chave primaria de `orders`.
- `idx_order_items_order`.
- indice `UNIQUE` de `payments.order_id`.
