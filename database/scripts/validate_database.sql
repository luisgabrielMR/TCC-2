DO $$
DECLARE
    missing_objects TEXT[] := ARRAY[]::TEXT[];
BEGIN
    IF to_regclass('public.customers') IS NULL THEN missing_objects := array_append(missing_objects, 'customers'); END IF;
    IF to_regclass('public.addresses') IS NULL THEN missing_objects := array_append(missing_objects, 'addresses'); END IF;
    IF to_regclass('public.categories') IS NULL THEN missing_objects := array_append(missing_objects, 'categories'); END IF;
    IF to_regclass('public.products') IS NULL THEN missing_objects := array_append(missing_objects, 'products'); END IF;
    IF to_regclass('public.orders') IS NULL THEN missing_objects := array_append(missing_objects, 'orders'); END IF;
    IF to_regclass('public.order_items') IS NULL THEN missing_objects := array_append(missing_objects, 'order_items'); END IF;
    IF to_regclass('public.payments') IS NULL THEN missing_objects := array_append(missing_objects, 'payments'); END IF;
    IF to_regclass('public.audit_logs') IS NULL THEN missing_objects := array_append(missing_objects, 'audit_logs'); END IF;

    IF array_length(missing_objects, 1) IS NOT NULL THEN
        RAISE EXCEPTION 'Missing database objects: %', array_to_string(missing_objects, ', ');
    END IF;

    IF (SELECT count(*) FROM customers) <> 200000 THEN RAISE EXCEPTION 'customers seed count must equal 200000'; END IF;
    IF (SELECT count(*) FROM addresses) <> 200000 THEN RAISE EXCEPTION 'addresses seed count must equal 200000'; END IF;
    IF (SELECT count(*) FROM categories) <> 5 THEN RAISE EXCEPTION 'categories seed count must equal 5'; END IF;
    IF (SELECT count(*) FROM products) <> 100 THEN RAISE EXCEPTION 'products seed count must equal 100'; END IF;
    IF (SELECT count(*) FROM orders) <> 200000 THEN RAISE EXCEPTION 'orders seed count must equal 200000'; END IF;
    IF (SELECT count(*) FROM order_items) <> 400000 THEN RAISE EXCEPTION 'order_items seed count must equal 400000'; END IF;
    IF (SELECT count(*) FROM payments) <> 200000 THEN RAISE EXCEPTION 'payments seed count must equal 200000'; END IF;
    IF (SELECT count(*) FROM audit_logs) <> 400000 THEN RAISE EXCEPTION 'audit_logs seed count must equal 400000'; END IF;

    IF to_regclass('public.idx_customers_created_id') IS NULL THEN RAISE EXCEPTION 'idx_customers_created_id is missing'; END IF;
    IF to_regclass('public.idx_addresses_customer_default') IS NULL THEN RAISE EXCEPTION 'idx_addresses_customer_default is missing'; END IF;
    IF to_regclass('public.idx_products_category_active') IS NULL THEN RAISE EXCEPTION 'idx_products_category_active is missing'; END IF;
    IF to_regclass('public.idx_order_items_order') IS NULL THEN RAISE EXCEPTION 'idx_order_items_order is missing'; END IF;

    IF to_regclass('public.idx_customers_status') IS NOT NULL THEN RAISE EXCEPTION 'obsolete index idx_customers_status is still present'; END IF;
    IF to_regclass('public.idx_orders_customer_created') IS NOT NULL THEN RAISE EXCEPTION 'obsolete index idx_orders_customer_created is still present'; END IF;
    IF to_regclass('public.idx_order_items_product') IS NOT NULL THEN RAISE EXCEPTION 'obsolete index idx_order_items_product is still present'; END IF;
    IF to_regclass('public.idx_payments_order') IS NOT NULL THEN RAISE EXCEPTION 'obsolete index idx_payments_order is still present'; END IF;
    IF to_regclass('public.idx_audit_logs_entity') IS NOT NULL THEN RAISE EXCEPTION 'obsolete index idx_audit_logs_entity is still present'; END IF;
END $$;

SELECT 'database validation ok' AS validation_result;
