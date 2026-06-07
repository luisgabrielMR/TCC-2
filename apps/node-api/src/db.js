import pg from "pg";

const { Pool } = pg;

export function createPool(config) {
  return new Pool({
    connectionString: config.databaseUrl,
    min: config.pool.min,
    max: config.pool.max,
    connectionTimeoutMillis: config.pool.acquireTimeoutSeconds * 1000,
    idleTimeoutMillis: config.pool.idleTimeoutSeconds * 1000,
    maxLifetimeSeconds: config.pool.maxLifetimeSeconds
  });
}
