#!/usr/bin/env python3
"""Validate the shared HTTP/JSON contract for one active API."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def request(base_url: str, method: str, path: str, payload: Any = None, raw: bytes | None = None) -> tuple[int, bytes, Any]:
    data = raw if raw is not None else (json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None)
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read()
            return response.status, body, json.loads(body)
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, body, json.loads(body)


def expect(base_url: str, method: str, path: str, status: int, body: Any, payload: Any = None, raw: bytes | None = None) -> bytes:
    actual_status, raw_body, actual_body = request(base_url, method, path, payload=payload, raw=raw)
    if actual_status != status or actual_body != body:
        raise AssertionError(
            f"{method} {path}: expected {status} {body!r}, got {actual_status} {actual_body!r}"
        )
    return raw_body


def error(code: str, message: str, details: list[dict[str, str]]) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def detail(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://host.docker.internal:8000")
    parser.add_argument("--snapshot")
    parser.add_argument("--compare")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    empty_customer = error("VALIDATION_ERROR", "Invalid request payload", [
        detail("fullName", "Required non-empty string"),
        detail("email", "Required non-empty string"),
        detail("documentNumber", "Required non-empty string"),
        detail("address", "Required object"),
    ])
    empty_update = error("VALIDATION_ERROR", "Invalid request payload", [
        detail("fullName", "Required non-empty string"),
        detail("status", "Required non-empty string"),
        detail("address", "Required object"),
    ])
    empty_order = error("VALIDATION_ERROR", "Invalid request payload", [
        detail("customerId", "Must be a positive integer"),
        detail("addressId", "Must be a positive integer"),
        detail("items", "Must contain at least one item"),
        detail("payment", "Required object"),
    ])
    empty_address = error("VALIDATION_ERROR", "Invalid request payload", [
        detail("address.label", "Required non-empty string"),
        detail("address.street", "Required non-empty string"),
        detail("address.number", "Required non-empty string"),
        detail("address.district", "Required non-empty string"),
        detail("address.city", "Required non-empty string"),
        detail("address.state", "Required non-empty string"),
        detail("address.postalCode", "Required non-empty string"),
        detail("address.isDefault", "Required boolean"),
    ])
    invalid_json = error("VALIDATION_ERROR", "Invalid request payload", [detail("$", "Invalid JSON")])
    non_object = error("VALIDATION_ERROR", "Invalid request payload", [detail("$", "Must be a JSON object")])

    expect(base_url, "POST", "/customers", 400, empty_customer, payload={})
    expect(base_url, "PUT", "/customers/1", 400, empty_update, payload={})
    expect(base_url, "POST", "/orders", 400, empty_order, payload={})
    expect(base_url, "POST", "/customers", 400, invalid_json, raw=b"{")
    expect(base_url, "POST", "/customers", 400, non_object, raw=b"null")
    expect(base_url, "POST", "/customers", 400, empty_address, payload={
        "fullName": "Contract Test",
        "email": "contract@example.com",
        "documentNumber": "contract-1",
        "address": {},
    })

    snapshot: dict[str, Any] = {}
    for name, path in (
        ("health", "/health"),
        ("customer", "/customers/1"),
        ("customers", "/customers?page=1&pageSize=2"),
        ("products", "/products?categoryId=1"),
        ("order", "/orders/1"),
    ):
        status, raw_body, body = request(base_url, "GET", path)
        if status != 200 or raw_body.endswith(b"\n"):
            raise AssertionError(f"GET {path}: invalid status or trailing newline")
        validate_response(body)
        snapshot[name] = body

    serialized = json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    if args.snapshot:
        Path(args.snapshot).write_text(serialized, encoding="utf-8", newline="\n")
    if args.compare:
        expected = Path(args.compare).read_text(encoding="utf-8")
        if serialized != expected:
            raise AssertionError(f"API snapshot differs from {args.compare}")

    print("contract validation ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"contract validation failed: {error}", file=sys.stderr)
        raise
