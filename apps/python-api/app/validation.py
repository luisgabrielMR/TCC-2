from __future__ import annotations

from typing import Any

from .errors import ApiError


VALID_STATUSES = {"active", "inactive"}
VALID_PAYMENT_METHODS = {"credit_card", "debit_card", "pix", "boleto"}


def positive_int(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request parameter", [{"field": field, "message": "Must be a positive integer"}])
    parsed = int(value)
    if parsed <= 0 or parsed > 2_147_483_647:
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


def _required_string(payload: dict[str, Any], key: str, details: list[dict[str, str]], field: str | None = None) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        details.append({"field": field or key, "message": "Required non-empty string"})
        return ""
    return value.strip()


def _optional_string(
    payload: dict[str, Any],
    key: str,
    details: list[dict[str, str]],
    field: str | None = None,
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        details.append({"field": field or key, "message": "Must be a string or null"})
        return None
    return value.strip()


def _required_bool(payload: dict[str, Any], key: str, field: str, details: list[dict[str, str]]) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        details.append({"field": field, "message": "Required boolean"})
        return False
    return value


def _positive_int_field(payload: dict[str, Any], key: str, field: str, details: list[dict[str, str]]) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        details.append({"field": field, "message": "Must be a positive integer"})
        return 0
    if isinstance(value, float) and not value.is_integer():
        details.append({"field": field, "message": "Must be a positive integer"})
        return 0
    parsed = int(value)
    if parsed <= 0 or parsed > 2_147_483_647:
        details.append({"field": field, "message": "Must be a positive integer"})
        return 0
    return parsed


def _address(payload: Any, prefix: str, details: list[dict[str, str]]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        details.append({"field": prefix, "message": "Required object"})
        return {}
    result = {
        "label": _required_string(payload, "label", details, f"{prefix}.label"),
        "street": _required_string(payload, "street", details, f"{prefix}.street"),
        "number": _required_string(payload, "number", details, f"{prefix}.number"),
        "complement": _optional_string(payload, "complement", details, f"{prefix}.complement"),
        "district": _required_string(payload, "district", details, f"{prefix}.district"),
        "city": _required_string(payload, "city", details, f"{prefix}.city"),
        "state": _required_string(payload, "state", details, f"{prefix}.state"),
        "postalCode": _required_string(payload, "postalCode", details, f"{prefix}.postalCode"),
        "isDefault": _required_bool(payload, "isDefault", f"{prefix}.isDefault", details),
    }
    if result["state"] and (len(result["state"]) != 2 or not result["state"].isascii() or not result["state"].isalpha()):
        details.append({"field": f"{prefix}.state", "message": "Must contain exactly 2 ASCII letters"})
    elif result["state"]:
        result["state"] = result["state"].upper()
    return result


def create_customer(payload: Any) -> dict[str, Any]:
    payload = _require_object(payload)
    details: list[dict[str, str]] = []
    result = {
        "fullName": _required_string(payload, "fullName", details),
        "email": _required_string(payload, "email", details),
        "documentNumber": _required_string(payload, "documentNumber", details),
        "phone": _optional_string(payload, "phone", details),
        "address": _address(payload.get("address"), "address", details),
    }
    if result["email"] and "@" not in result["email"]:
        details.append({"field": "email", "message": "Must be a valid email-like value"})
    if details:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details)
    return result


def update_customer(payload: Any) -> dict[str, Any]:
    payload = _require_object(payload)
    details: list[dict[str, str]] = []
    full_name = _required_string(payload, "fullName", details)
    status = _required_string(payload, "status", details)
    if status and status not in VALID_STATUSES:
        details.append({"field": "status", "message": "Must be active or inactive"})
    result = {
        "fullName": full_name,
        "phone": _optional_string(payload, "phone", details),
        "status": status,
        "address": _address(payload.get("address"), "address", details),
    }
    if details:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid request payload", details)
    return result


def create_order(payload: Any) -> dict[str, Any]:
    payload = _require_object(payload)
    details: list[dict[str, str]] = []
    customer_id = _positive_int_field(payload, "customerId", "customerId", details)
    address_id = _positive_int_field(payload, "addressId", "addressId", details)

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
                "productId": _positive_int_field(item, "productId", f"items[{index}].productId", details),
                "quantity": _positive_int_field(item, "quantity", f"items[{index}].quantity", details),
            }
        )

    payment = payload.get("payment")
    if not isinstance(payment, dict):
        details.append({"field": "payment", "message": "Required object"})
        method = ""
    else:
        method = _required_string(payment, "method", details, "payment.method")
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
