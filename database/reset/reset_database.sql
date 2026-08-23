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

-- Reclaim tuples created by the deterministic total update, refresh planner
-- statistics, flush dirty buffers and clear cumulative database counters
-- before the measured phase begins.
VACUUM (ANALYZE);
CHECKPOINT;
SELECT pg_stat_reset();
