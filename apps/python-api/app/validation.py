from __future__ import annotations

from typing import Any

from .errors import ApiError


VALID_STATUSES = {"active", "inactive"}
VALID_PAYMENT_METHODS = {"credit_card", "debit_card", "pix", "boleto"}


def positive_int(value: Any, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", [{"field": field, "message": "Must be a positive integer"}])
    if parsed <= 0:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", [{"field": field, "message": "Must be a positive integer"}])
    return parsed


def pagination(page: Any, page_size: Any) -> tuple[int, int]:
    parsed_page = positive_int(page, "page")
    parsed_page_size = positive_int(page_size, "pageSize")
    if parsed_page_size > 100:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", [{"field": "pageSize", "message": "Must be between 1 and 100"}])
    return parsed_page, parsed_page_size


def _require_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request payload", [{"field": "$", "message": "Must be a JSON object"}])
    return payload


def _required_string(payload: dict[str, Any], key: str, details: list[dict[str, str]]) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        details.append({"field": key, "message": "Required non-empty string"})
        return ""
    return value.strip()


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return str(value).strip()


def _required_bool(payload: dict[str, Any], key: str, details: list[dict[str, str]]) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        details.append({"field": key, "message": "Required boolean"})
        return False
    return value


def _address(payload: Any, prefix: str, details: list[dict[str, str]]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        details.append({"field": prefix, "message": "Required object"})
        return {}
    return {
        "label": _required_string(payload, "label", details),
        "street": _required_string(payload, "street", details),
        "number": _required_string(payload, "number", details),
        "complement": _optional_string(payload, "complement"),
        "district": _required_string(payload, "district", details),
        "city": _required_string(payload, "city", details),
        "state": _required_string(payload, "state", details),
        "postalCode": _required_string(payload, "postalCode", details),
        "isDefault": _required_bool(payload, "isDefault", details),
    }


def create_customer(payload: Any) -> dict[str, Any]:
    payload = _require_object(payload)
    details: list[dict[str, str]] = []
    result = {
        "fullName": _required_string(payload, "fullName", details),
        "email": _required_string(payload, "email", details),
        "documentNumber": _required_string(payload, "documentNumber", details),
        "phone": _optional_string(payload, "phone"),
        "address": _address(payload.get("address"), "address", details),
    }
    if "@" not in result["email"]:
        details.append({"field": "email", "message": "Must be a valid email-like value"})
    if details:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details)
    return result


def update_customer(payload: Any) -> dict[str, Any]:
    payload = _require_object(payload)
    details: list[dict[str, str]] = []
    status = _required_string(payload, "status", details)
    if status and status not in VALID_STATUSES:
        details.append({"field": "status", "message": "Must be active or inactive"})
    result = {
        "fullName": _required_string(payload, "fullName", details),
        "phone": _optional_string(payload, "phone"),
        "status": status,
        "address": _address(payload.get("address"), "address", details),
    }
    if details:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details)
    return result


def create_order(payload: Any) -> dict[str, Any]:
    payload = _require_object(payload)
    details: list[dict[str, str]] = []
    customer_id = positive_int(payload.get("customerId"), "customerId")
    address_id = positive_int(payload.get("addressId"), "addressId")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        details.append({"field": "items", "message": "Must contain at least one item"})
        raw_items = []

    items = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            details.append({"field": f"items[{index}]", "message": "Must be an object"})
            continue
        items.append(
            {
                "productId": positive_int(item.get("productId"), f"items[{index}].productId"),
                "quantity": positive_int(item.get("quantity"), f"items[{index}].quantity"),
            }
        )

    payment = payload.get("payment")
    if not isinstance(payment, dict):
        details.append({"field": "payment", "message": "Required object"})
        method = ""
    else:
        method = _required_string(payment, "method", details)
        if method and method not in VALID_PAYMENT_METHODS:
            details.append({"field": "payment.method", "message": "Invalid payment method"})

    if details:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details)

    return {
        "customerId": customer_id,
        "addressId": address_id,
        "items": items,
        "payment": {"method": method},
    }
