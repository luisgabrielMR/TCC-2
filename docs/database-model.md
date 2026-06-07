# Modelo de banco de dados

O banco usa identificadores `BIGSERIAL` de forma consistente em todas as tabelas principais.

## Tabelas

### customers

Clientes do experimento.

Campos principais:

- `id`
- `full_name`
- `email`
- `document_number`
- `phone`
- `status`
- `created_at`
- `updated_at`

### addresses

Endereços vinculados a clientes.

Relacionamento:

- `addresses.customer_id` referencia `customers.id`.

### categories

Categorias de produtos.

### products

Produtos disponíveis para leitura por categoria e criação de pedidos.

Relacionamento:

- `products.category_id` referencia `categories.id`.

### orders

Pedidos criados por cliente e endereço.

Relacionamentos:

- `orders.customer_id` referencia `customers.id`.
- `orders.address_id` referencia `addresses.id`.

### order_items

Itens de pedido.

Relacionamentos:

- `order_items.order_id` referencia `orders.id`.
- `order_items.product_id` referencia `products.id`.

### payments

Pagamento de pedido.

Relacionamento:

- `payments.order_id` referencia `orders.id`.

### audit_logs

Registros de auditoria para operações relevantes.

Campos principais:

- `entity_type`
- `entity_id`
- `action`
- `payload`
- `created_at`

## Índices

- `idx_customers_created_id`: paginação ordenada de clientes.
- `idx_customers_status`: filtros futuros por status.
- `idx_addresses_customer_default`: busca do endereço principal.
- `idx_products_category_active`: busca de produtos por categoria.
- `idx_orders_customer_created`: histórico de pedidos por cliente.
- `idx_order_items_order`: itens de um pedido.
- `idx_order_items_product`: atualização e consulta por produto.
- `idx_payments_order`: pagamento por pedido.
- `idx_audit_logs_entity`: auditoria por entidade.

## Volume inicial

O seed determinístico cria:

- 5 categorias
- 100 produtos
- 200 clientes
- 200 endereços
- 300 pedidos
- 600 itens de pedido
- 300 pagamentos
- 500 registros de auditoria

## Seed

O seed principal fica em `database/init/002_seed_base_data.sql`. Ele usa `generate_series` e valores determinísticos, sem dependência de Faker ou aleatoriedade externa.

O script `database/scripts/generate_seed_data.py` reescreve o arquivo de seed de forma reprodutível.

## Reset

O reset fica em `database/reset/reset_database.sql`. Ele executa `TRUNCATE ... RESTART IDENTITY CASCADE` nas tabelas do experimento e recarrega o seed determinístico. Após cada rodada com escrita, o reset deve ser executado antes da próxima rodada oficial.

## Validação

O arquivo `database/scripts/validate_database.sql` confere se tabelas, índices e contagens mínimas existem. Ele deve ser executado depois do preparo inicial e depois de resets quando houver dúvida sobre o estado do banco.
