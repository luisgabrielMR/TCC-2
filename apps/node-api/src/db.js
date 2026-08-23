import pg from "pg";

const { Pool } = pg;

export function createPool(config) {
  const pool = new Pool({
    connectionString: config.databaseUrl,
    min: config.pool.min,
    max: config.pool.max,
    connectionTimeoutMillis: config.pool.acquireTimeoutSeconds * 1000,
    idleTimeoutMillis: config.pool.idleTimeoutSeconds * 1000,
    maxLifetimeSeconds: config.pool.maxLifetimeSeconds
  });
  pool.on("error", (error) => {
    console.error(`PostgreSQL idle connection error: ${error.code || error.message}`);
  });
  return pool;
}
