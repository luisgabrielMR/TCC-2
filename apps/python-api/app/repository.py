from __future__ import annotations

import json
from typing import Any

from psycopg import Connection
from psycopg.errors import UniqueViolation
from psycopg_pool import ConnectionPool

from . import queries
from .errors import ApiError
from .serializers import customer_from_row, order_from_rows, product_from_row


def _fetch_customer(conn: Connection, customer_id: int) -> dict[str, Any] | None:
    row = conn.execute(queries.GET_CUSTOMER, (customer_id,)).fetchone()
    if row is None:
        return None
    return customer_from_row(row)


def get_customer(pool: ConnectionPool, customer_id: int) -> dict[str, Any]:
    with pool.connection() as conn:
        customer = _fetch_customer(conn, customer_id)
    if customer is None:
        raise ApiError(404, "NOT_FOUND", "Customer not found")
    return customer


def list_customers(pool: ConnectionPool, page: int, page_size: int) -> dict[str, Any]:
    offset = (page - 1) * page_size
    with pool.connection() as conn:
        total = conn.execute(queries.COUNT_CUSTOMERS).fetchone()["total"]
        rows = conn.execute(queries.LIST_CUSTOMERS, (page_size, offset)).fetchall()
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "items": [customer_from_row(row) for row in rows],
    }


def create_customer(pool: ConnectionPool, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with pool.connection() as conn:
            with conn.transaction():
                customer_id = conn.execute(
                    queries.INSERT_CUSTOMER,
                    (
                        payload["fullName"],
                        payload["email"],
                        payload["documentNumber"],
                        payload.get("phone"),
                    ),
                ).fetchone()["id"]
                address = payload["address"]
                conn.execute(
                    queries.INSERT_ADDRESS,
                    (
                        customer_id,
                        address["label"],
                        address["street"],
                        address["number"],
                        address.get("complement"),
                        address["district"],
                        address["city"],
                        address["state"],
                        address["postalCode"],
                        address["isDefault"],
                    ),
                )
                conn.execute(
                    queries.INSERT_AUDIT_LOG,
                    ("customer", customer_id, "create_customer", json.dumps(payload, ensure_ascii=False)),
                )
                customer = _fetch_customer(conn, customer_id)
    except UniqueViolation as exc:
        raise ApiError(409, "CONFLICT", "Customer email or document already exists") from exc
    if customer is None:
        raise ApiError(500, "DATABASE_ERROR", "Customer was created but could not be loaded")
    return customer


def update_customer(pool: ConnectionPool, customer_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with pool.connection() as conn:
        with conn.transaction():
            updated = conn.execute(
                queries.UPDATE_CUSTOMER,
                (
                    payload["fullName"],
                    payload.get("phone"),
                    payload["status"],
                    customer_id,
                ),
            ).fetchone()
            if updated is None:
                raise ApiError(404, "NOT_FOUND", "Customer not found")

            address = payload["address"]
            changed_address = conn.execute(
                queries.UPDATE_DEFAULT_ADDRESS,
                (
                    address["label"],
                    address["street"],
                    address["number"],
                    address.get("complement"),
                    address["district"],
                    address["city"],
                    address["state"],
                    address["postalCode"],
                    address["isDefault"],
                    customer_id,
                ),
            ).fetchone()
            if changed_address is None:
                conn.execute(
                    queries.INSERT_ADDRESS,
                    (
                        customer_id,
                        address["label"],
                        address["street"],
                        address["number"],
                        address.get("complement"),
                        address["district"],
                        address["city"],
                        address["state"],
                        address["postalCode"],
                        address["isDefault"],
                    ),
                )

            conn.execute(
                queries.INSERT_AUDIT_LOG,
                ("customer", customer_id, "update_customer", json.dumps(payload, ensure_ascii=False)),
            )
            customer = _fetch_customer(conn, customer_id)
    if customer is None:
        raise ApiError(500, "DATABASE_ERROR", "Customer was updated but could not be loaded")
    return customer


def list_products(pool: ConnectionPool, category_id: int) -> dict[str, Any]:
    with pool.connection() as conn:
        category = conn.execute(queries.CATEGORY_EXISTS, (category_id,)).fetchone()
        if category is None:
            raise ApiError(404, "NOT_FOUND", "Category not found")
        rows = conn.execute(queries.LIST_PRODUCTS_BY_CATEGORY, (category_id,)).fetchall()
    return {
        "categoryId": category_id,
        "items": [product_from_row(row) for row in rows],
    }


def _fetch_order(conn: Connection, order_id: int) -> dict[str, Any] | None:
    rows = conn.execute(queries.GET_ORDER, (order_id,)).fetchall()
    return order_from_rows(rows)


def get_order(pool: ConnectionPool, order_id: int) -> dict[str, Any]:
    with pool.connection() as conn:
        order = _fetch_order(conn, order_id)
    if order is None:
        raise ApiError(404, "NOT_FOUND", "Order not found")
    return order


def create_order(pool: ConnectionPool, payload: dict[str, Any]) -> dict[str, Any]:
    with pool.connection() as conn:
        with conn.transaction():
            customer = conn.execute(queries.ACTIVE_CUSTOMER_EXISTS, (payload["customerId"],)).fetchone()
            if customer is None:
                raise ApiError(404, "NOT_FOUND", "Customer not found")

            address = conn.execute(
                queries.ADDRESS_BELONGS_TO_CUSTOMER,
                (payload["addressId"], payload["customerId"]),
            ).fetchone()
            if address is None:
                raise ApiError(404, "NOT_FOUND", "Address not found")

            order_id = conn.execute(
                queries.INSERT_ORDER,
                (payload["customerId"], payload["addressId"]),
            ).fetchone()["id"]

            for item in payload["items"]:
                product = conn.execute(queries.LOCK_PRODUCT, (item["productId"],)).fetchone()
                if product is None:
                    raise ApiError(404, "NOT_FOUND", "Product not found")
                if product["stock_quantity"] < item["quantity"]:
                    raise ApiError(409, "CONFLICT", "Insufficient stock")

                updated_stock = conn.execute(
                    queries.UPDATE_PRODUCT_STOCK,
                    (item["quantity"], item["productId"], item["quantity"]),
                ).fetchone()
                if updated_stock is None:
                    raise ApiError(409, "CONFLICT", "Insufficient stock")

                conn.execute(
                    queries.INSERT_ORDER_ITEM,
                    (order_id, item["productId"], item["quantity"], product["unit_price"]),
                )

            total = conn.execute(queries.UPDATE_ORDER_TOTAL, (order_id, order_id)).fetchone()["total_amount"]
            conn.execute(queries.INSERT_PAYMENT, (order_id, payload["payment"]["method"], total))
            conn.execute(
                queries.INSERT_AUDIT_LOG,
                ("order", order_id, "create_order", json.dumps(payload, ensure_ascii=False)),
            )

            order = _fetch_order(conn, order_id)

    if order is None:
        raise ApiError(500, "DATABASE_ERROR", "Order was created but could not be loaded")
    return order
