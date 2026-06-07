CREATE INDEX IF NOT EXISTS idx_customers_created_id ON customers (created_at, id);
CREATE INDEX IF NOT EXISTS idx_customers_status ON customers (status);
CREATE INDEX IF NOT EXISTS idx_addresses_customer_default ON addresses (customer_id, is_default);
CREATE INDEX IF NOT EXISTS idx_products_category_active ON products (category_id, active, id);
CREATE INDEX IF NOT EXISTS idx_orders_customer_created ON orders (customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product ON order_items (product_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON payments (order_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity ON audit_logs (entity_type, entity_id, created_at DESC);
