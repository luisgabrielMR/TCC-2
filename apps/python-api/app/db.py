from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings


pool: ConnectionPool | None = None


def create_pool(settings: Settings) -> ConnectionPool:
    return ConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.pool_min,
        max_size=settings.pool_max,
        timeout=settings.pool_acquire_timeout_seconds,
        max_idle=settings.pool_idle_timeout_seconds,
        max_lifetime=settings.pool_max_lifetime_seconds,
        kwargs={
            "row_factory": dict_row,
            "connect_timeout": settings.pool_acquire_timeout_seconds,
        },
        open=False,
    )


def open_pool(settings: Settings) -> None:
    global pool
    pool = create_pool(settings)
    pool.open(wait=True, timeout=settings.pool_acquire_timeout_seconds)


def close_pool() -> None:
    global pool
    if pool is not None:
        pool.close()
        pool = None


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("Database pool is not open")
    return pool
