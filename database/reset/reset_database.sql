BEGIN;

TRUNCATE TABLE
    audit_logs,
    payments,
    order_items,
    orders,
    products,
    categories,
    addresses,
    customers
RESTART IDENTITY CASCADE;

COMMIT;

\ir ../init/002_seed_base_data.sql
\ir ../init/003_indexes.sql

-- Keep query plans deterministic instead of waiting for autovacuum to analyze
-- the freshly reloaded tables during the measured phase.
ANALYZE;
