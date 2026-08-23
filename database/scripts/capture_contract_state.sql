-- One canonical JSON value used to compare database effects across APIs.
-- Dynamic timestamps are intentionally excluded; values and sequence effects are not.
SELECT jsonb_build_object(
    'counts', jsonb_build_object(
        'customers', (SELECT count(*) FROM customers),
        'addresses', (SELECT count(*) FROM addresses),
        'orders', (SELECT count(*) FROM orders),
        'orderItems', (SELECT count(*) FROM order_items),
        'payments', (SELECT count(*) FROM payments),
        'auditLogs', (SELECT count(*) FROM audit_logs)
    ),
    'customers', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'fullName', full_name, 'email', email,
            'documentNumber', document_number, 'phone', phone, 'status', status
        ) ORDER BY id)
        FROM customers WHERE id = 1 OR id > 200
    ), '[]'::jsonb),
    'addresses', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'customerId', customer_id, 'label', label, 'street', street,
            'number', number, 'complement', complement, 'district', district,
            'city', city, 'state', state, 'postalCode', postal_code,
            'isDefault', is_default
        ) ORDER BY id)
        FROM addresses WHERE id = 1 OR id > 200
    ), '[]'::jsonb),
    'orders', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'customerId', customer_id, 'addressId', address_id,
            'status', status, 'totalAmount', total_amount::text
        ) ORDER BY id)
        FROM orders WHERE id > 300
    ), '[]'::jsonb),
    'orderItems', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'orderId', order_id, 'productId', product_id,
            'quantity', quantity, 'unitPrice', unit_price::text,
            'totalPrice', total_price::text
        ) ORDER BY id)
        FROM order_items WHERE id > 600
    ), '[]'::jsonb),
    'payments', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'orderId', order_id, 'method', method,
            'status', status, 'amount', amount::text
        ) ORDER BY id)
        FROM payments WHERE id > 300
    ), '[]'::jsonb),
    'products', (
        SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'stockQuantity', stock_quantity, 'active', active
        ) ORDER BY id)
        FROM products
    ),
    'auditLogs', COALESCE((
        SELECT jsonb_agg(jsonb_build_object(
            'id', id, 'entityType', entity_type, 'entityId', entity_id,
            'action', action, 'payload', payload
        ) ORDER BY id)
        FROM audit_logs WHERE id > 500
    ), '[]'::jsonb),
    'sequences', (
        SELECT jsonb_object_agg(sequencename, last_value ORDER BY sequencename)
        FROM pg_sequences
        WHERE schemaname = 'public'
    )
);
