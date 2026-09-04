#!/usr/bin/env python3
"""Validate the canonical HTTP/JSON contract for one active API."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from compare_json import first_difference


INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MONEY = re.compile(r"^\d+\.\d{2}$")
MAX_INT = 2_147_483_647


def request(
    base_url: str,
    method: str,
    path: str,
    payload: Any = None,
    raw: bytes | None = None,
) -> tuple[int, bytes, Any]:
    data = raw if raw is not None else (
        json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
    )
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                body = response.read()
                return response.status, body, json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                decoded = json.loads(body)
            except json.JSONDecodeError as json_error:
                raise AssertionError(f"{method} {path}: non-JSON error body {body!r}") from json_error
            return exc.code, body, decoded
        except urllib.error.URLError as exc:
            if attempt == 2:
                raise AssertionError(f"{method} {path}: API transport unavailable after 3 attempts: {exc}") from exc
            time.sleep(0.25 * (attempt + 1))
    raise AssertionError(f"{method} {path}: unreachable request state")


def expect(
    label: str,
    base_url: str,
    method: str,
    path: str,
    status: int,
    body: Any,
    payload: Any = None,
    raw: bytes | None = None,
) -> bytes:
    actual_status, raw_body, actual_body = request(base_url, method, path, payload=payload, raw=raw)
    difference = first_difference(body, actual_body)
    if actual_status != status or difference:
        raise AssertionError(
            f"{label} {method} {path}: expected HTTP {status}; got {actual_status}; "
            f"difference: {difference or 'status only'}"
        )
    if raw_body.endswith(b"\n"):
        raise AssertionError(f"{label} {method} {path}: response has a trailing newline")
    return raw_body


def error(code: str, message: str, details: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or []}}


def detail(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def validation_error(*details: dict[str, str]) -> dict[str, Any]:
    return error("VALIDATION_ERROR", "Invalid request payload", list(details))


def parameter_error(field: str, message: str = "Must be a positive integer") -> dict[str, Any]:
    return error("VALIDATION_ERROR", "Invalid request parameter", [detail(field, message)])


def validate_response(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key == "id" or key.endswith("Id"):
                if not isinstance(item, int) or isinstance(item, bool):
                    raise AssertionError(f"{item_path} must be an integer, got {item!r}")
            if key.endswith("At") and item is not None:
                if not isinstance(item, str) or not INSTANT.fullmatch(item):
                    raise AssertionError(f"{item_path} must use UTC seconds without fractions, got {item!r}")
            validate_response(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            validate_response(item, f"{path}[{index}]")


def exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise AssertionError(f"{path}: expected keys {sorted(expected)}, got {sorted(actual)}")


def validate_address(value: Any, path: str, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must be an object")
    exact_keys(value, {"id", "label", "street", "number", "complement", "district", "city", "state", "postalCode", "isDefault"}, path)
    if not isinstance(value["isDefault"], bool) or not isinstance(value["state"], str) or len(value["state"]) != 2:
        raise AssertionError(f"{path}: invalid isDefault or state")


def validate_customer(value: Any, path: str = "$") -> None:
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must be an object")
    exact_keys(value, {"id", "fullName", "email", "documentNumber", "phone", "status", "address", "createdAt", "updatedAt"}, path)
    validate_address(value["address"], f"{path}.address", nullable=True)
    validate_response(value, path)


def validate_product(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must be an object")
    exact_keys(value, {"id", "categoryId", "sku", "name", "unitPrice", "stockQuantity", "active"}, path)
    if not isinstance(value["unitPrice"], str) or not MONEY.fullmatch(value["unitPrice"]):
        raise AssertionError(f"{path}.unitPrice must be money")
    validate_response(value, path)


def validate_order(value: Any, path: str = "$") -> None:
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must be an object")
    exact_keys(value, {"id", "status", "totalAmount", "customer", "address", "items", "payment", "createdAt", "updatedAt"}, path)
    validate_customer(value["customer"], f"{path}.customer")
    validate_address(value["address"], f"{path}.address")
    if not isinstance(value["totalAmount"], str) or not MONEY.fullmatch(value["totalAmount"]):
        raise AssertionError(f"{path}.totalAmount must be money")
    if not isinstance(value["items"], list) or not value["items"]:
        raise AssertionError(f"{path}.items must be a non-empty array")
    for index, item in enumerate(value["items"]):
        item_path = f"{path}.items[{index}]"
        exact_keys(item, {"id", "quantity", "unitPrice", "totalPrice", "product"}, item_path)
        if not MONEY.fullmatch(item["unitPrice"]) or not MONEY.fullmatch(item["totalPrice"]):
            raise AssertionError(f"{item_path}: invalid money")
        product = item["product"]
        exact_keys(product, {"id", "categoryId", "categoryName", "sku", "name", "unitPrice", "stockQuantity", "active"}, f"{item_path}.product")
        if not MONEY.fullmatch(product["unitPrice"]):
            raise AssertionError(f"{item_path}.product.unitPrice must be money")
    payment = value["payment"]
    exact_keys(payment, {"id", "method", "status", "amount", "paidAt"}, f"{path}.payment")
    if not MONEY.fullmatch(payment["amount"]):
        raise AssertionError(f"{path}.payment.amount must be money")
    validate_response(value, path)


def normalize_dynamic(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<timestamp>" if key.endswith("At") and item is not None else normalize_dynamic(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_dynamic(item) for item in value]
    return value


def base_address(default: bool = True) -> dict[str, Any]:
    return {
        "label": "Principal", "street": "Rua Contrato", "number": "10", "complement": None,
        "district": "Centro", "city": "Sao Paulo", "state": "SP", "postalCode": "01001000",
        "isDefault": default,
    }


def base_customer() -> dict[str, Any]:
    return {
        "fullName": "Contract Customer", "email": "contract-write@example.com",
        "documentNumber": "contract-write-1", "phone": "+55 11 90000-0001",
        "address": base_address(),
    }


def base_update() -> dict[str, Any]:
    return {
        "fullName": "Customer 1 Contract", "phone": "+55 11 90000-0002", "status": "active",
        "address": {**base_address(), "street": "Rua Atualizada", "number": "101", "postalCode": "01001001"},
    }


def base_order() -> dict[str, Any]:
    return {
        "customerId": 1, "addressId": 1,
        "items": [{"productId": 1, "quantity": 1}],
        "payment": {"method": "pix"},
    }


def run_database_error_case(label: str, base_url: str) -> None:
    expect(label, base_url, "GET", "/customers/1", 500, error("DATABASE_ERROR", "Database error"))


def run_contract(label: str, base_url: str) -> dict[str, Any]:
    empty_customer = validation_error(
        detail("fullName", "Required non-empty string"), detail("email", "Required non-empty string"),
        detail("documentNumber", "Required non-empty string"), detail("address", "Required object"),
    )
    empty_update = validation_error(
        detail("fullName", "Required non-empty string"), detail("status", "Required non-empty string"),
        detail("address", "Required object"),
    )
    empty_order = validation_error(
        detail("customerId", "Must be a positive integer"), detail("addressId", "Must be a positive integer"),
        detail("items", "Must contain at least one item"), detail("payment", "Required object"),
    )
    invalid_json = validation_error(detail("$", "Invalid JSON"))
    non_object = validation_error(detail("$", "Must be a JSON object"))

    for method, path, empty in (
        ("POST", "/customers", empty_customer),
        ("PUT", "/customers/1", empty_update),
        ("POST", "/orders", empty_order),
    ):
        expect(label, base_url, method, path, 400, empty, payload={})
        for invalid_body in (b"", b"{", b"NaN", b"Infinity", b"-Infinity"):
            expect(label, base_url, method, path, 400, invalid_json, raw=invalid_body)
        for scalar in (b"null", b"[]", b'"text"', b"1", b"true"):
            expect(label, base_url, method, path, 400, non_object, raw=scalar)

    empty_address = validation_error(
        detail("address.label", "Required non-empty string"), detail("address.street", "Required non-empty string"),
        detail("address.number", "Required non-empty string"), detail("address.district", "Required non-empty string"),
        detail("address.city", "Required non-empty string"), detail("address.state", "Required non-empty string"),
        detail("address.postalCode", "Required non-empty string"), detail("address.isDefault", "Required boolean"),
    )
    customer = base_customer()
    expect(label, base_url, "POST", "/customers", 400, empty_address, payload={**customer, "address": {}})
    for value in (None, [], "address"):
        expect(label, base_url, "POST", "/customers", 400, validation_error(detail("address", "Required object")), payload={**customer, "address": value})
    for key in ("fullName", "email", "documentNumber"):
        expect(label, base_url, "POST", "/customers", 400, validation_error(detail(key, "Required non-empty string")), payload={**customer, key: "   "})
    expect(label, base_url, "POST", "/customers", 400, validation_error(detail("email", "Must be a valid email-like value")), payload={**customer, "email": "invalid-email"})
    expect(label, base_url, "POST", "/customers", 400, validation_error(detail("phone", "Must be a string or null")), payload={**customer, "phone": 123})
    expect(label, base_url, "POST", "/customers", 400, validation_error(detail("address.complement", "Must be a string or null")), payload={**customer, "address": {**customer["address"], "complement": False}})
    expect(label, base_url, "POST", "/customers", 400, validation_error(detail("address.isDefault", "Required boolean")), payload={**customer, "address": {**customer["address"], "isDefault": 1}})
    expect(label, base_url, "POST", "/customers", 400, validation_error(detail("address.state", "Must contain exactly 2 ASCII letters")), payload={**customer, "address": {**customer["address"], "state": "SPO"}})
    expect(label, base_url, "POST", "/customers", 400, validation_error(detail("address.state", "Must contain exactly 2 ASCII letters")), payload={**customer, "address": {**customer["address"], "state": "Sã"}})

    update = base_update()
    expect(label, base_url, "GET", "/customers?page=2147483647&pageSize=100", 200,
           {"page": 2147483647, "pageSize": 100, "total": 200, "items": []})
    expect(label, base_url, "PUT", "/customers/1", 400, validation_error(detail("status", "Must be active or inactive")), payload={**update, "status": "blocked"})
    expect(label, base_url, "PUT", "/customers/1", 400, validation_error(detail("phone", "Must be a string or null")), payload={**update, "phone": True})

    for path, field, message in (
        ("/customers/0", "id", None), ("/customers/1.5", "id", None),
        ("/customers/2147483648", "id", None), ("/orders/abc", "id", None),
        ("/customers?page=&pageSize=2", "page", None),
        ("/customers?page=1&pageSize=0", "pageSize", None),
        ("/customers?page=1&pageSize=101", "pageSize", "Must be between 1 and 100"),
        ("/products", "categoryId", None), ("/products?categoryId=true", "categoryId", None),
        ("/products?categoryId=2147483648", "categoryId", None),
    ):
        expected = parameter_error(field, message) if message else parameter_error(field)
        expect(label, base_url, "GET", path, 400, expected)

    order = base_order()
    expect(
        label,
        base_url,
        "POST",
        "/orders",
        400,
        validation_error(detail("customerId", "Must be a positive integer")),
        raw=b'{"customerId":1e400,"addressId":1,"items":[{"productId":1,"quantity":1}],"payment":{"method":"pix"}}',
    )
    for field in ("customerId", "addressId"):
        for value in ("1", True, 0, -1, 1.5, 2147483648):
            expect(label, base_url, "POST", "/orders", 400, validation_error(detail(field, "Must be a positive integer")), payload={**order, field: value})
    for field in ("productId", "quantity"):
        for value in ("1", True, 0, -1, 1.5, 2147483648):
            item = {**order["items"][0], field: value}
            expect(label, base_url, "POST", "/orders", 400, validation_error(detail(f"items[0].{field}", "Must be a positive integer")), payload={**order, "items": [item]})
    for value in (None, {}, [], "items"):
        expect(label, base_url, "POST", "/orders", 400, validation_error(detail("items", "Must contain at least one item")), payload={**order, "items": value})
    expect(label, base_url, "POST", "/orders", 400, validation_error(detail("items[0]", "Must be an object")), payload={**order, "items": [1]})
    for value in (None, [], "payment"):
        expect(label, base_url, "POST", "/orders", 400, validation_error(detail("payment", "Required object")), payload={**order, "payment": value})
    for payment in ({}, {"method": None}, {"method": "   "}, {"method": 1}):
        expect(label, base_url, "POST", "/orders", 400, validation_error(detail("payment.method", "Required non-empty string")), payload={**order, "payment": payment})
    expect(label, base_url, "POST", "/orders", 400, validation_error(detail("payment.method", "Invalid payment method")), payload={**order, "payment": {"method": "cash"}})

    expect(label, base_url, "GET", "/missing", 404, error("NOT_FOUND", "Route not found"))
    expect(label, base_url, "POST", "/missing", 404, error("NOT_FOUND", "Route not found"), raw=b"{")
    expect(label, base_url, "GET", "/customers/1/extra", 404, error("NOT_FOUND", "Route not found"))
    for method, path in (("POST", "/health"), ("DELETE", "/customers"), ("PATCH", "/customers/1"), ("GET", "/orders")):
        expect(label, base_url, method, path, 405, error("METHOD_NOT_ALLOWED", "Method not allowed"))
    expect(label, base_url, "PATCH", "/customers/1", 405, error("METHOD_NOT_ALLOWED", "Method not allowed"), raw=b"{")

    expect(label, base_url, "GET", f"/customers/{MAX_INT}", 404, error("NOT_FOUND", "Customer not found"))
    expect(label, base_url, "PUT", f"/customers/{MAX_INT}", 404, error("NOT_FOUND", "Customer not found"), payload=update)
    expect(label, base_url, "GET", f"/products?categoryId={MAX_INT}", 404, error("NOT_FOUND", "Category not found"))
    expect(label, base_url, "GET", f"/orders/{MAX_INT}", 404, error("NOT_FOUND", "Order not found"))
    expect(label, base_url, "POST", "/orders", 404, error("NOT_FOUND", "Customer not found"), payload={**order, "customerId": MAX_INT})
    expect(label, base_url, "POST", "/orders", 404, error("NOT_FOUND", "Address not found"), payload={**order, "addressId": MAX_INT})
    expect(label, base_url, "POST", "/orders", 404, error("NOT_FOUND", "Product not found"), payload={**order, "items": [{"productId": MAX_INT, "quantity": 1}]})

    duplicate_email = {**customer, "email": "cliente.base.0001@example.com", "documentNumber": "unique-contract-document"}
    duplicate_document = {**customer, "email": "unique-contract@example.com", "documentNumber": "10000000001"}
    conflict = error("CONFLICT", "Customer email or document already exists")
    expect(label, base_url, "POST", "/customers", 409, conflict, payload=duplicate_email)
    expect(label, base_url, "POST", "/customers", 409, conflict, payload=duplicate_document)

    status, _, product_list = request(base_url, "GET", "/products?categoryId=1")
    if status != 200:
        raise AssertionError(f"{label} GET /products baseline failed")
    encoded_status, _, encoded_product_list = request(base_url, "GET", "/products?categoryId=%31")
    if encoded_status != 200 or encoded_product_list != product_list:
        raise AssertionError(f"{label} percent-encoded query parameter differs")
    product_one_before = next(item for item in product_list["items"] if item["id"] == 1)["stockQuantity"]
    expect(label, base_url, "POST", "/orders", 409, error("CONFLICT", "Insufficient stock"), payload={**order, "items": [{"productId": 1, "quantity": MAX_INT}]})
    status, _, product_list_after = request(base_url, "GET", "/products?categoryId=1")
    product_one_after = next(item for item in product_list_after["items"] if item["id"] == 1)["stockQuantity"]
    if status != 200 or product_one_before != product_one_after:
        raise AssertionError(f"{label} stock changed after rolled-back order")

    snapshot: dict[str, Any] = {}
    for name, path, validator in (
        ("health", "/health", None),
        ("customer", "/customers/1", validate_customer),
        ("customers", "/customers?page=1&pageSize=2", None),
        ("products", "/products?categoryId=1", None),
        ("order", "/orders/1", validate_order),
    ):
        status, raw_body, body = request(base_url, "GET", path)
        if status != 200 or raw_body.endswith(b"\n"):
            raise AssertionError(f"{label} GET {path}: invalid status or trailing newline")
        if validator:
            validator(body)
        elif name == "customers":
            exact_keys(body, {"page", "pageSize", "total", "items"}, "$")
            for index, item in enumerate(body["items"]):
                validate_customer(item, f"$.items[{index}]")
        elif name == "products":
            exact_keys(body, {"categoryId", "items"}, "$")
            for index, item in enumerate(body["items"]):
                validate_product(item, f"$.items[{index}]")
        else:
            validate_response(body)
        snapshot[name] = body

    create_payload = {
        **customer,
        "fullName": "  Contract Customer  ",
        "phone": "  +55 11 90000-0001  ",
        "address": {**customer["address"], "street": "  Rua Contrato  ", "ignoredAddress": "ignored"},
        "ignoredRoot": "ignored",
    }
    status, _, created = request(base_url, "POST", "/customers", payload=create_payload)
    if status != 201 or created["fullName"] != "Contract Customer" or created["phone"] != "+55 11 90000-0001" or created["address"]["street"] != "Rua Contrato":
        raise AssertionError(f"{label} POST /customers normalization failed: {status} {created!r}")
    validate_customer(created)
    snapshot["createdCustomer"] = normalize_dynamic(created)
    status, _, fetched_created = request(base_url, "GET", f"/customers/{created['id']}")
    if status != 200 or fetched_created != created:
        raise AssertionError(f"{label} created customer reread differs")

    status, _, updated = request(base_url, "PUT", "/customers/1", payload={**update, "ignoredRoot": True})
    if status != 200:
        raise AssertionError(f"{label} PUT /customers/1 returned {status}: {updated!r}")
    validate_customer(updated)
    snapshot["updatedCustomer"] = normalize_dynamic(updated)

    integral_order = {
        **order,
        "customerId": 1.0,
        "addressId": 1.0,
        "items": [{"productId": 1.0, "quantity": 1.0, "ignoredItem": 1}],
        "payment": {"method": "  pix  ", "ignoredPayment": True},
        "ignoredRoot": True,
    }
    status, _, created_order = request(base_url, "POST", "/orders", payload=integral_order)
    if status != 201 or created_order["payment"]["method"] != "pix":
        raise AssertionError(f"{label} POST /orders integral/normalized write failed: {status} {created_order!r}")
    validate_order(created_order)
    snapshot["createdOrder"] = normalize_dynamic(created_order)
    status, _, fetched_order = request(base_url, "GET", f"/orders/{created_order['id']}")
    if status != 200 or fetched_order != created_order:
        raise AssertionError(f"{label} created order reread differs")

    no_default_payload = {
        **customer,
        "email": "contract-no-default@example.com",
        "documentNumber": "contract-no-default-1",
        "address": base_address(default=False),
    }
    status, _, no_default_customer = request(base_url, "POST", "/customers", payload=no_default_payload)
    if status != 201 or no_default_customer.get("address") is not None:
        raise AssertionError(f"{label} customer without default address differs: {status} {no_default_customer!r}")
    validate_customer(no_default_customer)
    snapshot["customerWithoutDefaultAddress"] = normalize_dynamic(no_default_customer)
    no_default_id = no_default_customer["id"]
    status, _, upserted = request(base_url, "PUT", f"/customers/{no_default_id}", payload=update)
    if status != 200 or not upserted.get("address") or upserted["address"].get("isDefault") is not True:
        raise AssertionError(f"{label} missing default address was not upserted: {status} {upserted!r}")
    validate_customer(upserted)
    snapshot["upsertedDefaultAddress"] = normalize_dynamic(upserted)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://host.docker.internal:8000")
    parser.add_argument("--label", default="api")
    parser.add_argument("--snapshot")
    parser.add_argument("--compare")
    parser.add_argument("--database-error-only", action="store_true")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    if args.database_error_only:
        run_database_error_case(args.label, base_url)
        print(f"{args.label} database error contract ok")
        return 0

    snapshot = run_contract(args.label, base_url)
    serialized = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    if args.snapshot:
        Path(args.snapshot).write_text(serialized, encoding="utf-8", newline="\n")
    if args.compare:
        expected = json.loads(Path(args.compare).read_text(encoding="utf-8-sig"))
        difference = first_difference(expected, snapshot)
        if difference:
            raise AssertionError(f"{args.label} API snapshot differs at {difference}")

    print(f"{args.label} contract validation ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"contract validation failed: {exc}", file=sys.stderr)
        raise
