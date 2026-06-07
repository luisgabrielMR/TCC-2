BEGIN;

INSERT INTO categories (id, name)
VALUES
    (1, 'Books'),
    (2, 'Electronics'),
    (3, 'Home'),
    (4, 'Office'),
    (5, 'Sports')
ON CONFLICT (id) DO NOTHING;

INSERT INTO customers (id, full_name, email, document_number, phone, status, created_at, updated_at)
SELECT
    gs,
    'Cliente Base ' || lpad(gs::text, 4, '0'),
    'cliente.base.' || lpad(gs::text, 4, '0') || '@example.com',
    '100' || lpad(gs::text, 8, '0'),
    '+55 11 9' || lpad(gs::text, 8, '0'),
    'active',
    timestamp '2026-01-01 08:00:00+00' + (gs || ' minutes')::interval,
    timestamp '2026-01-01 08:00:00+00' + (gs || ' minutes')::interval
FROM generate_series(1, 200) AS gs
ON CONFLICT (id) DO NOTHING;

INSERT INTO addresses (
    id,
    customer_id,
    label,
    street,
    number,
    complement,
    district,
    city,
    state,
    postal_code,
    is_default,
    created_at
)
SELECT
    gs,
    gs,
    'main',
    'Rua Experimental ' || gs,
    (100 + gs)::text,
    CASE WHEN gs % 3 = 0 THEN 'Apto ' || gs ELSE NULL END,
    'Bairro ' || ((gs - 1) % 20 + 1),
    'Sao Paulo',
    'SP',
    '010' || lpad(gs::text, 5, '0'),
    true,
    timestamp '2026-01-01 08:00:00+00' + (gs || ' minutes')::interval
FROM generate_series(1, 200) AS gs
ON CONFLICT (id) DO NOTHING;

INSERT INTO products (id, category_id, sku, name, unit_price, stock_quantity, active, created_at)
SELECT
    gs,
    ((gs - 1) % 5) + 1,
    'SKU-' || lpad(gs::text, 5, '0'),
    'Produto Base ' || lpad(gs::text, 4, '0'),
    (10 + (gs % 50) + ((gs % 7) * 0.11))::numeric(12, 2),
    1000 + (gs % 100),
    true,
    timestamp '2026-01-01 09:00:00+00' + (gs || ' minutes')::interval
FROM generate_series(1, 100) AS gs
ON CONFLICT (id) DO NOTHING;

INSERT INTO orders (id, customer_id, address_id, status, total_amount, created_at, updated_at)
SELECT
    gs,
    ((gs - 1) % 200) + 1,
    ((gs - 1) % 200) + 1,
    'paid',
    0,
    timestamp '2026-01-02 10:00:00+00' + (gs || ' minutes')::interval,
    timestamp '2026-01-02 10:00:00+00' + (gs || ' minutes')::interval
FROM generate_series(1, 300) AS gs
ON CONFLICT (id) DO NOTHING;

WITH item_source AS (
    SELECT
        row_number() OVER (ORDER BY o.id, line_no) AS item_id,
        o.id AS order_id,
        (((o.id * line_no) + 7) % 100) + 1 AS product_id,
        1 + ((o.id + line_no) % 3) AS quantity
    FROM orders o
    CROSS JOIN generate_series(1, 2) AS line_no
    WHERE o.id BETWEEN 1 AND 300
)
INSERT INTO order_items (id, order_id, product_id, quantity, unit_price)
SELECT
    item_source.item_id,
    item_source.order_id,
    item_source.product_id,
    item_source.quantity,
    products.unit_price
FROM item_source
JOIN products ON products.id = item_source.product_id
ON CONFLICT (id) DO NOTHING;

UPDATE orders
SET total_amount = totals.total_amount
FROM (
    SELECT order_id, sum(total_price)::numeric(12, 2) AS total_amount
    FROM order_items
    GROUP BY order_id
) AS totals
WHERE orders.id = totals.order_id;

INSERT INTO payments (id, order_id, method, status, amount, paid_at)
SELECT
    o.id,
    o.id,
    CASE
        WHEN o.id % 4 = 0 THEN 'pix'
        WHEN o.id % 4 = 1 THEN 'credit_card'
        WHEN o.id % 4 = 2 THEN 'debit_card'
        ELSE 'boleto'
    END,
    'paid',
    o.total_amount,
    o.created_at + interval '3 minutes'
FROM orders o
WHERE o.id BETWEEN 1 AND 300
ON CONFLICT (id) DO NOTHING;

INSERT INTO audit_logs (id, entity_type, entity_id, action, payload, created_at)
SELECT
    gs,
    'customer',
    gs,
    'seed_customer',
    jsonb_build_object('source', 'deterministic_seed'),
    timestamp '2026-01-01 08:00:00+00' + (gs || ' minutes')::interval
FROM generate_series(1, 200) AS gs
ON CONFLICT (id) DO NOTHING;

INSERT INTO audit_logs (id, entity_type, entity_id, action, payload, created_at)
SELECT
    200 + gs,
    'order',
    gs,
    'seed_order',
    jsonb_build_object('source', 'deterministic_seed'),
    timestamp '2026-01-02 10:00:00+00' + (gs || ' minutes')::interval
FROM generate_series(1, 300) AS gs
ON CONFLICT (id) DO NOTHING;

SELECT setval(pg_get_serial_sequence('categories', 'id'), (SELECT max(id) FROM categories));
SELECT setval(pg_get_serial_sequence('customers', 'id'), (SELECT max(id) FROM customers));
SELECT setval(pg_get_serial_sequence('addresses', 'id'), (SELECT max(id) FROM addresses));
SELECT setval(pg_get_serial_sequence('products', 'id'), (SELECT max(id) FROM products));
SELECT setval(pg_get_serial_sequence('orders', 'id'), (SELECT max(id) FROM orders));
SELECT setval(pg_get_serial_sequence('order_items', 'id'), (SELECT max(id) FROM order_items));
SELECT setval(pg_get_serial_sequence('payments', 'id'), (SELECT max(id) FROM payments));
SELECT setval(pg_get_serial_sequence('audit_logs', 'id'), (SELECT max(id) FROM audit_logs));

COMMIT;
