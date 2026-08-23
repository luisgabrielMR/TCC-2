#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


EXPECTED_OPERATIONS = {
    ("/health", "get"): {"200", "500"},
    ("/customers/{id}", "get"): {"200", "400", "404", "500"},
    ("/customers", "get"): {"200", "400", "500"},
    ("/customers", "post"): {"201", "400", "409", "500"},
    ("/customers/{id}", "put"): {"200", "400", "404", "500"},
    ("/products", "get"): {"200", "400", "404", "500"},
    ("/orders", "post"): {"201", "400", "404", "409", "500"},
    ("/orders/{id}", "get"): {"200", "400", "404", "500"},
}
HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


def fail(message: str) -> None:
    raise ValueError(message)


def resolve_pointer(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        fail(f"external reference is not allowed: {reference}")
    current: Any = document
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            fail(f"unresolved reference: {reference}")
        current = current[part]
    return current


def validate_references(document: dict[str, Any], value: Any, location: str = "$") -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if reference is not None:
            if not isinstance(reference, str):
                fail(f"{location}.$ref must be a string")
            resolve_pointer(document, reference)
        for key, child in value.items():
            validate_references(document, child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_references(document, child, f"{location}[{index}]")


def schema(document: dict[str, Any], name: str) -> dict[str, Any]:
    result = document["components"]["schemas"].get(name)
    if not isinstance(result, dict):
        fail(f"missing schema: {name}")
    return result


def validate_contract(document: dict[str, Any]) -> None:
    if document.get("openapi") != "3.0.3":
        fail("openapi must be exactly 3.0.3")
    paths = document.get("paths")
    if not isinstance(paths, dict):
        fail("paths must be an object")

    actual: dict[tuple[str, str], set[str]] = {}
    operation_ids: set[str] = set()
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            fail(f"path item must be an object: {path}")
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                fail(f"operation must be an object: {method.upper()} {path}")
            operation_id = operation.get("operationId")
            if not operation_id or operation_id in operation_ids:
                fail(f"missing or duplicate operationId: {method.upper()} {path}")
            operation_ids.add(operation_id)
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                fail(f"responses missing: {method.upper()} {path}")
            actual[(path, method)] = {str(status) for status in responses}

    if set(actual) != set(EXPECTED_OPERATIONS):
        missing = sorted(set(EXPECTED_OPERATIONS) - set(actual))
        extra = sorted(set(actual) - set(EXPECTED_OPERATIONS))
        fail(f"operation set mismatch; missing={missing}; extra={extra}")
    for operation, expected_statuses in EXPECTED_OPERATIONS.items():
        if actual[operation] != expected_statuses:
            fail(
                f"response statuses differ for {operation[1].upper()} {operation[0]}: "
                f"expected {sorted(expected_statuses)}, got {sorted(actual[operation])}"
            )

    for path, method in (("/customers", "post"), ("/customers/{id}", "put"), ("/orders", "post")):
        request_body = paths[path][method].get("requestBody", {})
        if request_body.get("required") is not True:
            fail(f"request body must be required: {method.upper()} {path}")

    positive = schema(document, "PositiveInteger")
    if positive.get("format") != "int32" or positive.get("minimum") != 1 or positive.get("maximum") != 2147483647:
        fail("PositiveInteger must cover exactly 1..2147483647")
    if schema(document, "PageSize").get("maximum") != 100:
        fail("PageSize maximum must be 100")
    address = schema(document, "Customer").get("properties", {}).get("address", {})
    if address.get("nullable") is not True:
        fail("Customer.address must be nullable")
    state = schema(document, "AddressInput").get("properties", {}).get("state", {})
    if state.get("pattern") != r"^[ \t\r\n]*[A-Za-z]{2}[ \t\r\n]*$":
        fail("AddressInput.state must allow trimming around exactly two ASCII letters")
    email = schema(document, "EmailInput")
    email_parts = email.get("allOf", [])
    if not any(isinstance(part, dict) and part.get("pattern") == "@" for part in email_parts):
        fail("EmailInput must require an at sign")
    order_items = schema(document, "CreateOrderRequest").get("properties", {}).get("items", {})
    if order_items.get("minItems") != 1:
        fail("CreateOrderRequest.items must require at least one item")
    methods = schema(document, "PaymentInput").get("properties", {}).get("method", {}).get("enum")
    if methods != ["credit_card", "debit_card", "pix", "boleto"]:
        fail("PaymentInput.method enum differs from the canonical contract")
    paid_at = schema(document, "Payment").get("properties", {}).get("paidAt", {})
    paid_at_parts = paid_at.get("allOf", [])
    if (
        paid_at.get("nullable") is not True
        or paid_at_parts != [{"$ref": "#/components/schemas/Instant"}]
        or schema(document, "Instant").get("format") != "date-time"
    ):
        fail("Payment.paidAt must be a nullable date-time")
    error_detail = schema(document, "ErrorDetail")
    if error_detail.get("required") != ["field", "message"]:
        fail("ErrorDetail must require field and message")
    error_object = schema(document, "ErrorObject")
    if error_object.get("required") != ["code", "message", "details"]:
        fail("ErrorObject must require code, message and details")
    if error_object.get("properties", {}).get("details", {}).get("type") != "array":
        fail("ErrorObject.details must be an array")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the canonical benchmark OpenAPI document.")
    parser.add_argument("document", type=Path)
    args = parser.parse_args()
    loaded = yaml.safe_load(args.document.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        fail("OpenAPI root must be an object")
    validate_references(loaded, loaded)
    validate_contract(loaded)
    print(f"OpenAPI validation ok: {len(EXPECTED_OPERATIONS)} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
