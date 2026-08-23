-- Remove indexes from earlier revisions that have no matching benchmark query.
DROP INDEX IF EXISTS idx_customers_status;
DROP INDEX IF EXISTS idx_orders_customer_created;
DROP INDEX IF EXISTS idx_order_items_product;
DROP INDEX IF EXISTS idx_payments_order;
DROP INDEX IF EXISTS idx_audit_logs_entity;

CREATE INDEX IF NOT EXISTS idx_customers_created_id ON customers (created_at, id);
CREATE INDEX IF NOT EXISTS idx_addresses_customer_default ON addresses (customer_id, is_default);
CREATE INDEX IF NOT EXISTS idx_products_category_active ON products (category_id, active, id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);

-- Background maintenance would run at different moments as the write workload
-- grows these small seed tables. Resets reclaim all tuples and ANALYZE explicitly.
ALTER TABLE customers SET (autovacuum_enabled = false);
ALTER TABLE addresses SET (autovacuum_enabled = false);
ALTER TABLE categories SET (autovacuum_enabled = false);
ALTER TABLE products SET (autovacuum_enabled = false);
ALTER TABLE orders SET (autovacuum_enabled = false);
ALTER TABLE order_items SET (autovacuum_enabled = false);
ALTER TABLE payments SET (autovacuum_enabled = false);
ALTER TABLE audit_logs SET (autovacuum_enabled = false);
