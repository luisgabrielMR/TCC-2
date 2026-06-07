-- GET /customers/{id}
SELECT
    c.id,
    c.full_name,
    c.email,
    c.document_number,
    c.phone,
    c.status,
    c.created_at,
    c.updated_at,
    a.id AS address_id,
    a.label,
    a.street,
    a.number,
    a.complement,
    a.district,
    a.city,
    a.state,
    a.postal_code,
    a.is_default
FROM customers c
LEFT JOIN addresses a ON a.customer_id = c.id AND a.is_default = true
WHERE c.id = $1;

-- GET /customers?page=1&pageSize=50
SELECT
    c.id,
    c.full_name,
    c.email,
    c.document_number,
    c.phone,
    c.status,
    c.created_at,
    c.updated_at
FROM customers c
ORDER BY c.created_at, c.id
LIMIT $1 OFFSET $2;

-- GET /customers total
SELECT count(*) AS total FROM customers;

-- POST /customers step 1
INSERT INTO customers (full_name, email, document_number, phone, status)
VALUES ($1, $2, $3, $4, 'active')
RETURNING id, full_name, email, document_number, phone, status, created_at, updated_at;

-- POST /customers step 2
INSERT INTO addresses (
    customer_id,
    label,
    street,
    number,
    complement,
    district,
    city,
    state,
    postal_code,
    is_default
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
RETURNING id;

-- POST /customers step 3
INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES ('customer', $1, 'create_customer', $2::jsonb);

-- PUT /customers/{id} step 1
UPDATE customers
SET
    full_name = $2,
    phone = $3,
    status = $4,
    updated_at = now()
WHERE id = $1
RETURNING id, full_name, email, document_number, phone, status, created_at, updated_at;

-- PUT /customers/{id} step 2
UPDATE addresses
SET
    label = $2,
    street = $3,
    number = $4,
    complement = $5,
    district = $6,
    city = $7,
    state = $8,
    postal_code = $9,
    is_default = $10
WHERE customer_id = $1 AND is_default = true
RETURNING id;

-- PUT /customers/{id} step 3
INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES ('customer', $1, 'update_customer', $2::jsonb);

-- GET /products?categoryId={id}
SELECT
    p.id,
    p.category_id,
    p.sku,
    p.name,
    p.unit_price,
    p.stock_quantity,
    p.active
FROM products p
WHERE p.category_id = $1 AND p.active = true
ORDER BY p.id;

-- POST /orders step 1: validate customer
SELECT id FROM customers WHERE id = $1 AND status = 'active';

-- POST /orders step 2: validate address
SELECT id FROM addresses WHERE id = $1 AND customer_id = $2;

-- POST /orders step 3: create order
INSERT INTO orders (customer_id, address_id, status, total_amount)
VALUES ($1, $2, 'created', 0)
RETURNING id;

-- POST /orders step 4: lock product
SELECT id, unit_price, stock_quantity
FROM products
WHERE id = $1 AND active = true
FOR UPDATE;

-- POST /orders step 5: update stock
UPDATE products
SET stock_quantity = stock_quantity - $2
WHERE id = $1 AND stock_quantity >= $2;

-- POST /orders step 6: insert item
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
VALUES ($1, $2, $3, $4);

-- POST /orders step 7: update total
UPDATE orders
SET
    total_amount = (
        SELECT sum(total_price)::numeric(12, 2)
        FROM order_items
        WHERE order_id = $1
    ),
    status = 'paid',
    updated_at = now()
WHERE id = $1
RETURNING total_amount;

-- POST /orders step 8: insert payment
INSERT INTO payments (order_id, method, status, amount, paid_at)
VALUES ($1, $2, 'paid', $3, now());

-- POST /orders step 9: audit
INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES ('order', $1, 'create_order', $2::jsonb);

-- GET /orders/{id}
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
    a.id AS address_id,
    a.label,
    a.street,
    a.number,
    a.complement,
    a.district,
    a.city,
    a.state,
    a.postal_code,
    oi.id AS item_id,
    oi.quantity,
    oi.unit_price AS item_unit_price,
    oi.total_price AS item_total_price,
    p.id AS product_id,
    p.sku,
    p.name AS product_name,
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
