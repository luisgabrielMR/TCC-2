from __future__ import annotations

import csv
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from locust import HttpUser, constant, constant_pacing, events, task
from locust.runners import MasterRunner, WorkerRunner
from locust.stats import PERCENTILES_TO_REPORT, StatsCSV
from payload_sequences import PayloadCycle, PayloadSequence


SCENARIO = os.getenv("SCENARIO", "mixed")
LOCAL_PAYLOAD_DIR = Path(__file__).resolve().parents[2] / "common" / "payloads"
PAYLOAD_DIR = Path(os.getenv("PAYLOAD_DIR", str(LOCAL_PAYLOAD_DIR)))
WAIT_SECONDS = float(os.getenv("LOCUST_WAIT_SECONDS", "0.1"))
LOCUST_PROCESSES = int(os.getenv("LOCUST_PROCESSES", "1"))
if LOCUST_PROCESSES < 1:
    raise RuntimeError("LOCUST_PROCESSES must be a positive integer")
SCENARIO_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "scenarios.json"

with SCENARIO_CONFIG_PATH.open("r", encoding="utf-8") as scenario_handle:
    SCENARIO_CONFIG = json.load(scenario_handle)

WORKLOAD_SCENARIO = SCENARIO_CONFIG.get("aliases", {}).get(SCENARIO, SCENARIO)
SCENARIO_ACTIONS = SCENARIO_CONFIG.get("scenarios", {}).get(WORKLOAD_SCENARIO)
if SCENARIO not in {"smoke", "health_only"} and not SCENARIO_ACTIONS:
    raise RuntimeError(f"Unknown Locust scenario: {SCENARIO}")

measurement_started_wall_ns: int | None = None
measurement_started_monotonic_ns: int | None = None


def utc_iso_from_ns(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")


def writes_files(environment) -> bool:
    """Somente master e runner local escrevem. Com --processes os workers herdam
    o mesmo --csv e sobrescreveriam os arquivos uns dos outros."""
    return not isinstance(environment.runner, WorkerRunner)


def measurement_bounds_path(environment) -> Path | None:
    if not writes_files(environment):
        return None
    options = environment.parsed_options
    prefix = getattr(options, "csv_prefix", None) if options else None
    return Path(f"{prefix}_measurement_bounds.json") if prefix else None


@events.test_start.add_listener
def record_measurement_start(environment, **_kwargs) -> None:
    global measurement_started_wall_ns, measurement_started_monotonic_ns
    measurement_started_wall_ns = time.time_ns()
    measurement_started_monotonic_ns = time.monotonic_ns()
    path = measurement_bounds_path(environment)
    if path:
        path.write_text(json.dumps({
            "schema_version": 2,
            "started_epoch": measurement_started_wall_ns / 1_000_000_000,
            "started_at_utc": utc_iso_from_ns(measurement_started_wall_ns),
            "finished_epoch": None,
            "elapsed_seconds": None,
            "duration_clock": "time.monotonic_ns",
            "boundary_clock": "time.time_ns",
        }, separators=(",", ":")), encoding="utf-8")


@events.test_stop.add_listener
def record_measurement_stop(environment, **_kwargs) -> None:
    finished_wall_ns = time.time_ns()
    finished_monotonic_ns = time.monotonic_ns()
    path = measurement_bounds_path(environment)
    if path is None or measurement_started_wall_ns is None or measurement_started_monotonic_ns is None:
        return
    elapsed_seconds = (finished_monotonic_ns - measurement_started_monotonic_ns) / 1_000_000_000
    wall_elapsed_seconds = (finished_wall_ns - measurement_started_wall_ns) / 1_000_000_000
    path.write_text(
        json.dumps({
            "schema_version": 2,
            "started_epoch": measurement_started_wall_ns / 1_000_000_000,
            "finished_epoch": finished_wall_ns / 1_000_000_000,
            "started_at_utc": utc_iso_from_ns(measurement_started_wall_ns),
            "finished_at_utc": utc_iso_from_ns(finished_wall_ns),
            "elapsed_seconds": elapsed_seconds,
            "wall_elapsed_seconds": wall_elapsed_seconds,
            "clock_drift_seconds": wall_elapsed_seconds - elapsed_seconds,
            "duration_clock": "time.monotonic_ns",
            "boundary_clock": "time.time_ns",
        }, separators=(",", ":")),
        encoding="utf-8",
    )


@events.quitting.add_listener
def write_final_csv_snapshot(environment, **_kwargs) -> None:
    if not writes_files(environment):
        return
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


customers_create = PayloadSequence(PAYLOAD_DIR / "customers_create.jsonl")
customers_update = PayloadCycle(PAYLOAD_DIR / "customers_update.jsonl")
orders_create = PayloadCycle(PAYLOAD_DIR / "orders_create.jsonl")
customer_ids = PayloadCycle(PAYLOAD_DIR / "ids_customers.jsonl", parse_json=False)
category_ids = PayloadCycle(PAYLOAD_DIR / "ids_categories.jsonl", parse_json=False)
order_ids = PayloadCycle(PAYLOAD_DIR / "ids_orders.jsonl", parse_json=False)


@events.test_start.add_listener
def configure_payload_streams(environment, **_kwargs) -> None:
    """Distribui payloads unicos e defasa os ciclos deterministas por worker."""
    runner = environment.runner
    if isinstance(runner, MasterRunner):
        if runner.worker_count != LOCUST_PROCESSES:
            raise RuntimeError(
                f"Locust connected {runner.worker_count} workers, expected {LOCUST_PROCESSES}"
            )
        return
    if isinstance(runner, WorkerRunner):
        worker_index = int(runner.worker_index)
        if worker_index < 0 or worker_index >= LOCUST_PROCESSES:
            raise RuntimeError(
                f"Locust worker index {worker_index} is outside LOCUST_PROCESSES={LOCUST_PROCESSES}"
            )
        stride = LOCUST_PROCESSES
    else:
        if LOCUST_PROCESSES != 1:
            raise RuntimeError(
                "LOCUST_PROCESSES is greater than one, but Locust is not running in distributed mode"
            )
        worker_index = 0
        stride = 1

    customers_create.configure_shard(worker_index, stride)
    for stream in (customers_update, orders_create, customer_ids, category_ids, order_ids):
        stream.configure_worker_offset(worker_index)


@events.init.add_listener
def validate_process_configuration(environment, **_kwargs) -> None:
    options = environment.parsed_options
    configured = int(getattr(options, "processes", 0) or 1) if options else 1
    if not isinstance(environment.runner, WorkerRunner) and configured != LOCUST_PROCESSES:
        raise RuntimeError(
            f"--processes={configured} differs from LOCUST_PROCESSES={LOCUST_PROCESSES}"
        )


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
        if SCENARIO == "health_only":
            self.get_health()
            return
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
