from __future__ import annotations

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    database_url: str
    pool_min: int
    pool_max: int
    pool_acquire_timeout_seconds: int
    pool_idle_timeout_seconds: int
    pool_max_lifetime_seconds: int


def load_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "benchmark_db")
        user = os.getenv("POSTGRES_USER", "benchmark_user")
        password = os.getenv("POSTGRES_PASSWORD", "benchmark_password")
        database_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"

    return Settings(
        database_url=database_url,
        pool_min=_int_env("DB_POOL_MIN", 1),
        pool_max=_int_env("DB_POOL_MAX", 20),
        pool_acquire_timeout_seconds=_int_env("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 10),
        pool_idle_timeout_seconds=_int_env("DB_POOL_IDLE_TIMEOUT_SECONDS", 60),
        pool_max_lifetime_seconds=_int_env("DB_POOL_MAX_LIFETIME_SECONDS", 300),
    )
