-- Canonical PostgreSQL operations shared by all five APIs.
-- Placeholder syntax varies by driver; numbering below documents data order.

-- GET /customers/{id} and transaction rereads
SELECT
    c.id, c.full_name, c.email, c.document_number, c.phone, c.status,
    c.created_at, c.updated_at,
    a.id AS address_id, a.label, a.street, a.number, a.complement,
    a.district, a.city, a.state, a.postal_code, a.is_default
FROM customers c
LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
WHERE c.id = $1;

-- GET /customers total
SELECT count(*)::int AS total FROM customers;

-- GET /customers?page={page}&pageSize={pageSize}
SELECT
    c.id, c.full_name, c.email, c.document_number, c.phone, c.status,
    c.created_at, c.updated_at,
    a.id AS address_id, a.label, a.street, a.number, a.complement,
    a.district, a.city, a.state, a.postal_code, a.is_default
FROM customers c
LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
ORDER BY c.created_at, c.id
LIMIT $1 OFFSET $2;

-- POST /customers: one transaction
INSERT INTO customers (full_name, email, document_number, phone, status)
VALUES ($1, $2, $3, $4, 'active')
RETURNING id;

INSERT INTO addresses (
    customer_id, label, street, number, complement, district, city, state,
    postal_code, is_default
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
RETURNING id;

INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES ($1, $2, $3, $4::jsonb);

-- PUT /customers/{id}: one transaction
UPDATE customers
SET full_name = $1, phone = $2, status = $3, updated_at = now()
WHERE id = $4
RETURNING id;

-- Drivers that use affected-row counts omit RETURNING; the existence decision is identical.

UPDATE addresses
SET
    label = $1,
    street = $2,
    number = $3,
    complement = $4,
    district = $5,
    city = $6,
    state = $7,
    postal_code = $8,
    is_default = $9
WHERE customer_id = $10 AND is_default = true
RETURNING id;

-- Executed only when the preceding UPDATE returns no row.
INSERT INTO addresses (
    customer_id, label, street, number, complement, district, city, state,
    postal_code, is_default
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
RETURNING id;

INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES ($1, $2, $3, $4::jsonb);

-- GET /products?categoryId={id}
SELECT id FROM categories WHERE id = $1;

SELECT id, category_id, sku, name, unit_price, stock_quantity, active
FROM products
WHERE category_id = $1 AND active = true
ORDER BY id;

-- POST /orders: all operations below run in one transaction.
SELECT id FROM customers WHERE id = $1 AND status = 'active';

SELECT id FROM addresses WHERE id = $1 AND customer_id = $2;

INSERT INTO orders (customer_id, address_id, status, total_amount)
VALUES ($1, $2, 'created', 0)
RETURNING id;

-- Repeated for each order item.
SELECT id, unit_price, stock_quantity
FROM products
WHERE id = $1 AND active = true
FOR UPDATE;

UPDATE products
SET stock_quantity = stock_quantity - $1
WHERE id = $2 AND stock_quantity >= $3;

-- Python and Node.js append RETURNING stock_quantity; Java, Go and .NET inspect
-- the affected-row count. Both forms reject a concurrent stock loss identically.

INSERT INTO order_items (order_id, product_id, quantity, unit_price)
VALUES ($1, $2, $3, $4);

UPDATE orders
SET
    total_amount = (
        SELECT sum(total_price)::numeric(12, 2)
        FROM order_items
        WHERE order_id = $1
    ),
    status = 'paid',
    updated_at = now()
WHERE id = $2
RETURNING total_amount;

INSERT INTO payments (order_id, method, status, amount, paid_at)
VALUES ($1, $2, 'paid', $3, now());

INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES ($1, $2, $3, $4::jsonb);

-- GET /orders/{id} and transaction rereads
SELECT
    o.id AS order_id,
    o.status AS order_status,
    o.total_amount,
    o.created_at AS order_created_at,
    o.updated_at AS order_updated_at,
    c.id AS customer_id,
    c.full_name,
    c.email,
    c.document_number,
    c.phone,
    c.status AS customer_status,
    c.created_at AS customer_created_at,
    c.updated_at AS customer_updated_at,
    a.id AS address_id,
    a.label,
    a.street,
    a.number,
    a.complement,
    a.district,
    a.city,
    a.state,
    a.postal_code,
    a.is_default,
    oi.id AS item_id,
    oi.quantity,
    oi.unit_price AS item_unit_price,
    oi.total_price AS item_total_price,
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
    p.unit_price AS product_unit_price,
    p.stock_quantity,
    p.active,
    cat.id AS category_id,
    cat.name AS category_name,
    pay.id AS payment_id,
    pay.method AS payment_method,
    pay.status AS payment_status,
    pay.amount AS payment_amount,
    pay.paid_at
FROM orders o
JOIN customers c ON c.id = o.customer_id
JOIN addresses a ON a.id = o.address_id
JOIN order_items oi ON oi.order_id = o.id
JOIN products p ON p.id = oi.product_id
JOIN categories cat ON cat.id = p.category_id
JOIN payments pay ON pay.order_id = o.id
WHERE o.id = $1
ORDER BY oi.id;
