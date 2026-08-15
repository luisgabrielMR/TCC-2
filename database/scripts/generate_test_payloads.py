#!/usr/bin/env python3
"""Generate deterministic JSONL payloads for manual and Locust tests."""

from __future__ import annotations

import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_DIR = ROOT / "common" / "payloads"
SEED = 20260607

BASE_CUSTOMERS = 200
BASE_CATEGORIES = 5
BASE_PRODUCTS = 100
BASE_ORDERS = 300
CREATE_CUSTOMERS = 50_000
UPDATE_CUSTOMERS = 200
CREATE_ORDERS = 250


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_id_file(path: Path, values) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(f"{value}\n")


def customer_create_payloads():
    for idx in range(1, CREATE_CUSTOMERS + 1):
        yield {
            "fullName": f"Cliente Carga {idx:08d}",
            "email": f"cliente.carga.{idx:08d}@example.com",
            "documentNumber": f"900{idx:08d}",
            "phone": f"+55 11 98{idx:07d}",
            "address": {
                "label": "main",
                "street": f"Rua Carga {idx}",
                "number": str(500 + idx),
                "complement": f"Bloco {idx % 10}" if idx % 4 == 0 else None,
                "district": f"Bairro Carga {(idx % 20) + 1}",
                "city": "Sao Paulo",
                "state": "SP",
                "postalCode": f"020{idx:05d}",
                "isDefault": True,
            },
        }


def customer_update_payloads():
    for idx in range(1, UPDATE_CUSTOMERS + 1):
        yield {
            "fullName": f"Cliente Atualizado {idx:04d}",
            "phone": f"+55 11 97{idx:07d}",
            "status": "active",
            "address": {
                "label": "main",
                "street": f"Rua Atualizada {idx}",
                "number": str(900 + idx),
                "complement": None,
                "district": f"Bairro Atualizado {(idx % 20) + 1}",
                "city": "Sao Paulo",
                "state": "SP",
                "postalCode": f"030{idx:05d}",
                "isDefault": True,
            },
        }


def order_create_payloads():
    rng = random.Random(SEED)
    for idx in range(1, CREATE_ORDERS + 1):
        customer_id = ((idx - 1) % BASE_CUSTOMERS) + 1
        first_product = rng.randint(1, BASE_PRODUCTS)
        second_product = ((first_product + 17) % BASE_PRODUCTS) + 1
        yield {
            "customerId": customer_id,
            "addressId": customer_id,
            "items": [
                {"productId": first_product, "quantity": 1 + (idx % 3)},
                {"productId": second_product, "quantity": 1 + ((idx + 1) % 2)},
            ],
            "payment": {
                "method": ["credit_card", "debit_card", "pix", "boleto"][idx % 4]
            },
        }


def main() -> None:
    PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

    write_jsonl(PAYLOAD_DIR / "customers_create.jsonl", customer_create_payloads())
    write_jsonl(PAYLOAD_DIR / "customers_update.jsonl", customer_update_payloads())
    write_jsonl(PAYLOAD_DIR / "orders_create.jsonl", order_create_payloads())

    write_id_file(PAYLOAD_DIR / "ids_customers.jsonl", range(1, BASE_CUSTOMERS + 1))
    write_id_file(PAYLOAD_DIR / "ids_products.jsonl", range(1, BASE_PRODUCTS + 1))
    write_id_file(PAYLOAD_DIR / "ids_categories.jsonl", range(1, BASE_CATEGORIES + 1))
    write_id_file(PAYLOAD_DIR / "ids_orders.jsonl", range(1, BASE_ORDERS + 1))

    print(f"Payloads generated in {PAYLOAD_DIR}")


if __name__ == "__main__":
    main()
