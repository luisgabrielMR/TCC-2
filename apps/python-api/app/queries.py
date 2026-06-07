GET_CUSTOMER = """
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
WHERE c.id = %s
"""

COUNT_CUSTOMERS = "SELECT count(*) AS total FROM customers"

LIST_CUSTOMERS = """
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
ORDER BY c.created_at, c.id
LIMIT %s OFFSET %s
"""

INSERT_CUSTOMER = """
INSERT INTO customers (full_name, email, document_number, phone, status)
VALUES (%s, %s, %s, %s, 'active')
RETURNING id
"""

INSERT_ADDRESS = """
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
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

INSERT_AUDIT_LOG = """
INSERT INTO audit_logs (entity_type, entity_id, action, payload)
VALUES (%s, %s, %s, %s::jsonb)
"""

UPDATE_CUSTOMER = """
UPDATE customers
SET
    full_name = %s,
    phone = %s,
    status = %s,
    updated_at = now()
WHERE id = %s
RETURNING id
"""

UPDATE_DEFAULT_ADDRESS = """
UPDATE addresses
SET
    label = %s,
    street = %s,
    number = %s,
    complement = %s,
    district = %s,
    city = %s,
    state = %s,
    postal_code = %s,
    is_default = %s
WHERE customer_id = %s AND is_default = true
RETURNING id
"""

CATEGORY_EXISTS = "SELECT id FROM categories WHERE id = %s"

LIST_PRODUCTS_BY_CATEGORY = """
SELECT
    p.id,
    p.category_id,
    p.sku,
    p.name,
    p.unit_price,
    p.stock_quantity,
    p.active
FROM products p
WHERE p.category_id = %s AND p.active = true
ORDER BY p.id
"""

ACTIVE_CUSTOMER_EXISTS = "SELECT id FROM customers WHERE id = %s AND status = 'active'"
ADDRESS_BELONGS_TO_CUSTOMER = "SELECT id FROM addresses WHERE id = %s AND customer_id = %s"

INSERT_ORDER = """
INSERT INTO orders (customer_id, address_id, status, total_amount)
VALUES (%s, %s, 'created', 0)
RETURNING id
"""

LOCK_PRODUCT = """
SELECT id, unit_price, stock_quantity
FROM products
WHERE id = %s AND active = true
FOR UPDATE
"""

UPDATE_PRODUCT_STOCK = """
UPDATE products
SET stock_quantity = stock_quantity - %s
WHERE id = %s AND stock_quantity >= %s
RETURNING stock_quantity
"""

INSERT_ORDER_ITEM = """
INSERT INTO order_items (order_id, product_id, quantity, unit_price)
VALUES (%s, %s, %s, %s)
"""

UPDATE_ORDER_TOTAL = """
UPDATE orders
SET
    total_amount = (
        SELECT sum(total_price)::numeric(12, 2)
        FROM order_items
        WHERE order_id = %s
    ),
    status = 'paid',
    updated_at = now()
WHERE id = %s
RETURNING total_amount
"""

INSERT_PAYMENT = """
INSERT INTO payments (order_id, method, status, amount, paid_at)
VALUES (%s, %s, 'paid', %s, now())
"""

GET_ORDER = """
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
WHERE o.id = %s
ORDER BY oi.id
"""
