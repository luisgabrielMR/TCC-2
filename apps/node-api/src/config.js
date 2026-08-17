function intEnv(name, fallback) {
  const value = process.env[name];
  if (value === undefined || value === "") {
    return fallback;
  }
  return Number.parseInt(value, 10);
}

export function loadConfig() {
  const databaseUrl =
    process.env.DATABASE_URL ||
    `postgresql://${process.env.POSTGRES_USER || "benchmark_user"}:${process.env.POSTGRES_PASSWORD || "benchmark_password"}@${process.env.POSTGRES_HOST || "localhost"}:${process.env.POSTGRES_PORT || "5432"}/${process.env.POSTGRES_DB || "benchmark_db"}`;

  return {
    port: intEnv("PORT", 8000),
    databaseUrl,
    pool: {
      min: intEnv("DB_POOL_MIN", 1),
      max: intEnv("DB_POOL_MAX", 20),
      acquireTimeoutSeconds: intEnv("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 10),
      idleTimeoutSeconds: intEnv("DB_POOL_IDLE_TIMEOUT_SECONDS", 60),
      maxLifetimeSeconds: intEnv("DB_POOL_MAX_LIFETIME_SECONDS", 1800)
    }
  };
}
