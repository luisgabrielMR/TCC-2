from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def money(value: Decimal | float | int | str) -> str:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return f"{Decimal(str(value)):.2f}"


def instant(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    text = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return text.replace("+00:00", "Z")


def address_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("address_id") is None:
        return None
    return {
        "id": row["address_id"],
        "label": row["label"],
        "street": row["street"],
        "number": row["number"],
        "complement": row["complement"],
        "district": row["district"],
        "city": row["city"],
        "state": row["state"],
        "postalCode": row["postal_code"],
        "isDefault": row["is_default"],
    }


def customer_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "fullName": row["full_name"],
        "email": row["email"],
        "documentNumber": row["document_number"],
        "phone": row["phone"],
        "status": row["status"],
        "address": address_from_row(row),
        "createdAt": instant(row["created_at"]),
        "updatedAt": instant(row["updated_at"]),
    }


def product_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "categoryId": row["category_id"],
        "sku": row["sku"],
        "name": row["name"],
        "unitPrice": money(row["unit_price"]),
        "stockQuantity": row["stock_quantity"],
        "active": row["active"],
    }


def order_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    first = rows[0]
    customer = {
        "id": first["customer_id"],
        "fullName": first["full_name"],
        "email": first["email"],
        "documentNumber": first["document_number"],
        "phone": first["phone"],
        "status": first["customer_status"],
        "address": address_from_row(first),
        "createdAt": instant(first["customer_created_at"]),
        "updatedAt": instant(first["customer_updated_at"]),
    }
    address = address_from_row(first)
    payment = {
        "id": first["payment_id"],
        "method": first["payment_method"],
        "status": first["payment_status"],
        "amount": money(first["payment_amount"]),
        "paidAt": instant(first["paid_at"]),
    }
    items = []
    for row in rows:
        items.append(
            {
                "id": row["item_id"],
                "quantity": row["quantity"],
                "unitPrice": money(row["item_unit_price"]),
                "totalPrice": money(row["item_total_price"]),
                "product": {
                    "id": row["product_id"],
                    "categoryId": row["category_id"],
                    "categoryName": row["category_name"],
                    "sku": row["sku"],
                    "name": row["product_name"],
                    "unitPrice": money(row["product_unit_price"]),
                    "stockQuantity": row["stock_quantity"],
                    "active": row["active"],
                },
            }
        )

    return {
        "id": first["order_id"],
        "status": first["order_status"],
        "totalAmount": money(first["total_amount"]),
        "customer": customer,
        "address": address,
        "items": items,
        "payment": payment,
        "createdAt": instant(first["order_created_at"]),
        "updatedAt": instant(first["order_updated_at"]),
    }
