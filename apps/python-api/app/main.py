from __future__ import annotations

from contextlib import asynccontextmanager
from json import JSONDecodeError, loads
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from psycopg import Error as PsycopgError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import repository, validation
from .config import load_settings
from .db import close_pool, get_pool, open_pool
from .errors import ApiError, api_error_handler, error_response, generic_error_handler


settings = load_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool(settings)
    try:
        yield
    finally:
        close_pool()


app = FastAPI(
    title="TCC PostgreSQL Benchmark Python API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(Exception, generic_error_handler)


async def framework_http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 405:
        return error_response(405, "METHOD_NOT_ALLOWED", "Method not allowed")
    return error_response(404, "NOT_FOUND", "Route not found")


async def database_error_handler(_: Request, __: PsycopgError) -> JSONResponse:
    return error_response(500, "DATABASE_ERROR", "Database error")


app.add_exception_handler(StarletteHTTPException, framework_http_error_handler)
app.add_exception_handler(PsycopgError, database_error_handler)


def reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant: {value}")


async def read_json(request: Request) -> Any:
    try:
        return loads(await request.body(), parse_constant=reject_nonstandard_json_constant)
    except (JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request payload", [{"field": "$", "message": "Invalid JSON"}]) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/customers")
def list_customers(page: str = "1", pageSize: str = "50"):
    parsed_page, parsed_page_size = validation.pagination(page, pageSize)
    try:
        return repository.list_customers(get_pool(), parsed_page, parsed_page_size)
    except PsycopgError as exc:
        raise ApiError(500, "DATABASE_ERROR", "Database error") from exc


@app.post("/customers")
async def create_customer(request: Request):
    payload = validation.create_customer(await read_json(request))
    try:
        customer = await run_in_threadpool(repository.create_customer, get_pool(), payload)
    except ApiError:
        raise
    except PsycopgError as exc:
        raise ApiError(500, "DATABASE_ERROR", "Database error") from exc
    return JSONResponse(status_code=201, content=customer)


@app.get("/customers/{customer_id}")
def get_customer(customer_id: str):
    parsed_id = validation.positive_int(customer_id, "id")
    try:
        return repository.get_customer(get_pool(), parsed_id)
    except ApiError:
        raise
    except PsycopgError as exc:
        raise ApiError(500, "DATABASE_ERROR", "Database error") from exc


@app.put("/customers/{customer_id}")
async def update_customer(customer_id: str, request: Request):
    parsed_id = validation.positive_int(customer_id, "id")
    payload = validation.update_customer(await read_json(request))
    try:
        return await run_in_threadpool(repository.update_customer, get_pool(), parsed_id, payload)
    except ApiError:
        raise
    except PsycopgError as exc:
        raise ApiError(500, "DATABASE_ERROR", "Database error") from exc


@app.get("/products")
def list_products(categoryId: str | None = None):
    category_id = validation.positive_int(categoryId, "categoryId")
    try:
        return repository.list_products(get_pool(), category_id)
    except ApiError:
        raise
    except PsycopgError as exc:
        raise ApiError(500, "DATABASE_ERROR", "Database error") from exc


@app.post("/orders")
async def create_order(request: Request):
    payload = validation.create_order(await read_json(request))
    try:
        order = await run_in_threadpool(repository.create_order, get_pool(), payload)
    except ApiError:
        raise
    except PsycopgError as exc:
        raise ApiError(500, "DATABASE_ERROR", "Database error") from exc
    return JSONResponse(status_code=201, content=order)


@app.get("/orders/{order_id}")
def get_order(order_id: str):
    parsed_id = validation.positive_int(order_id, "id")
    try:
        return repository.get_order(get_pool(), parsed_id)
    except ApiError:
        raise
    except PsycopgError as exc:
        raise ApiError(500, "DATABASE_ERROR", "Database error") from exc
