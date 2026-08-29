from __future__ import annotations

import csv
import json
import os
import random
import threading
import time
from itertools import cycle
from pathlib import Path

from locust import HttpUser, constant, constant_pacing, events, task
from locust.stats import PERCENTILES_TO_REPORT, StatsCSV


SCENARIO = os.getenv("SCENARIO", "mixed")
LOCAL_PAYLOAD_DIR = Path(__file__).resolve().parents[2] / "common" / "payloads"
PAYLOAD_DIR = Path(os.getenv("PAYLOAD_DIR", str(LOCAL_PAYLOAD_DIR)))
WAIT_SECONDS = float(os.getenv("LOCUST_WAIT_SECONDS", "0.1"))
SCENARIO_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "scenarios.json"

with SCENARIO_CONFIG_PATH.open("r", encoding="utf-8") as scenario_handle:
    SCENARIO_CONFIG = json.load(scenario_handle)

WORKLOAD_SCENARIO = SCENARIO_CONFIG.get("aliases", {}).get(SCENARIO, SCENARIO)
SCENARIO_ACTIONS = SCENARIO_CONFIG.get("scenarios", {}).get(WORKLOAD_SCENARIO)
if SCENARIO != "smoke" and not SCENARIO_ACTIONS:
    raise RuntimeError(f"Unknown Locust scenario: {SCENARIO}")

measurement_started_epoch: float | None = None


def measurement_bounds_path(environment) -> Path | None:
    options = environment.parsed_options
    prefix = getattr(options, "csv_prefix", None) if options else None
    return Path(f"{prefix}_measurement_bounds.json") if prefix else None


@events.test_start.add_listener
def record_measurement_start(environment, **_kwargs) -> None:
    global measurement_started_epoch
    measurement_started_epoch = time.time()
    path = measurement_bounds_path(environment)
    if path:
        path.write_text(json.dumps({"started_epoch": measurement_started_epoch, "finished_epoch": None}), encoding="utf-8")


@events.test_stop.add_listener
def record_measurement_stop(environment, **_kwargs) -> None:
    finished_epoch = time.time()
    path = measurement_bounds_path(environment)
    if not path or measurement_started_epoch is None:
        return
    path.write_text(
        json.dumps({
            "started_epoch": measurement_started_epoch,
            "finished_epoch": finished_epoch,
            "elapsed_seconds": finished_epoch - measurement_started_epoch,
        }, separators=(",", ":")),
        encoding="utf-8",
    )


@events.quitting.add_listener
def write_final_csv_snapshot(environment, **_kwargs) -> None:
    options = environment.parsed_options
    prefix = getattr(options, "csv_prefix", None) if options else None
    if not prefix:
        return

    exporter = StatsCSV(environment, PERCENTILES_TO_REPORT)
    outputs = (
        ("stats", exporter.requests_csv_columns, exporter._requests_data_rows),
        ("failures", exporter.failures_columns, exporter._failures_data_rows),
        ("exceptions", exporter.exceptions_columns, exporter._exceptions_data_rows),
    )
    for kind, columns, write_rows in outputs:
        with Path(f"{prefix}_final_{kind}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            write_rows(writer)


class PayloadCycle:
    def __init__(self, path: Path, parse_json: bool = True) -> None:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"Payload file is empty: {path}")
        values = [json.loads(line) if parse_json else line for line in lines]
        self._cycle = cycle(values)
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            return next(self._cycle)


class PayloadSequence:
    def __init__(self, path: Path) -> None:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"Payload file is empty: {path}")
        self._values = [json.loads(line) for line in lines]
        self._index = 0
        self._lock = threading.Lock()

    def next(self):
        with self._lock:
            if self._index >= len(self._values):
                raise RuntimeError("customers_create.jsonl exhausted; generate more payloads before the benchmark")
            value = self._values[self._index]
            self._index += 1
            return value


customers_create = PayloadSequence(PAYLOAD_DIR / "customers_create.jsonl")
customers_update = PayloadCycle(PAYLOAD_DIR / "customers_update.jsonl")
orders_create = PayloadCycle(PAYLOAD_DIR / "orders_create.jsonl")
customer_ids = PayloadCycle(PAYLOAD_DIR / "ids_customers.jsonl", parse_json=False)
category_ids = PayloadCycle(PAYLOAD_DIR / "ids_categories.jsonl", parse_json=False)
order_ids = PayloadCycle(PAYLOAD_DIR / "ids_orders.jsonl", parse_json=False)


# Com WAIT_SECONDS > 0 o pacing impoe um teto de usuarios/WAIT_SECONDS req/s ao
# gerador. Com WAIT_SECONDS = 0 a malha e fechada: cada usuario dispara a proxima
# requisicao assim que a anterior responde, e o teto passa a ser da propria API.
WAIT_STRATEGY = constant(0) if WAIT_SECONDS <= 0 else constant_pacing(WAIT_SECONDS)


class BenchmarkUser(HttpUser):
    wait_time = WAIT_STRATEGY

    def get_health(self) -> None:
        self.client.get("/health", name="GET /health")

    def get_customer(self) -> None:
        customer_id = customer_ids.next()
        self.client.get(f"/customers/{customer_id}", name="GET /customers/{id}")

    def list_customers(self) -> None:
        self.client.get("/customers?page=1&pageSize=50", name="GET /customers")

    def create_customer(self) -> None:
        payload = customers_create.next()
        self.client.post("/customers", json=payload, name="POST /customers")

    def update_customer(self) -> None:
        customer_id = customer_ids.next()
        payload = customers_update.next()
        self.client.put(f"/customers/{customer_id}", json=payload, name="PUT /customers/{id}")

    def list_products(self) -> None:
        category_id = category_ids.next()
        self.client.get(f"/products?categoryId={category_id}", name="GET /products")

    def create_order(self) -> None:
        payload = orders_create.next()
        self.client.post("/orders", json=payload, name="POST /orders")

    def get_order(self) -> None:
        order_id = order_ids.next()
        self.client.get(f"/orders/{order_id}", name="GET /orders/{id}")

    @task
    def run_selected_scenario(self) -> None:
        if SCENARIO == "smoke":
            for action in (
                self.get_health,
                self.get_customer,
                self.list_customers,
                self.list_products,
                self.get_order,
            ):
                action()
            return

        actions = [getattr(self, item["action"]) for item in SCENARIO_ACTIONS]
        weights = [item["weight"] for item in SCENARIO_ACTIONS]
        random.choices(actions, weights=weights, k=1)[0]()
