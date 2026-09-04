#!/usr/bin/env python3
"""Expose benchmark CSV and JSON artifacts as Prometheus metrics."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Iterable


LIVE_FRESHNESS_SECONDS = 30


def number(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def integer(value: object) -> int:
    return int(number(value))


def median(rows: Iterable[dict], key: str) -> float:
    values = [number(row.get(key)) for row in rows if row.get(key) not in (None, "")]
    return statistics.median(values) if values else 0.0


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def resource(rows: list[dict[str, str]], predicate: Callable[[str], bool]) -> dict[str, str]:
    return next((row for row in rows if predicate(row.get("container_name", ""))), {})


def use_cadvisor_resources(metadata: dict) -> bool:
    methodology = integer(metadata.get("methodology_version")) or 1
    return methodology >= 6 and metadata.get("result_classification") == "official"


def read_resources(run_directory: Path, metadata: dict) -> tuple[list[dict[str, str]], str]:
    if use_cadvisor_resources(metadata):
        return read_csv(run_directory / "cadvisor_summary.csv"), "cadvisor_via_prometheus"
    return read_csv(run_directory / "docker_stats_summary.csv"), "docker_stats_complementary"


def elapsed_seconds(metadata: dict) -> float:
    elapsed = number(metadata.get("test_phase", {}).get("elapsed_seconds"))
    if elapsed > 0:
        return elapsed
    metrics = metadata.get("metrics", {})
    started = number(metrics.get("started_epoch"))
    finished = number(metrics.get("finished_epoch"))
    return finished - started if finished > started > 0 else 0.0


def throughput_rps(requests: object, elapsed: float, reported: object, use_exact: bool) -> float:
    return number(requests) / elapsed if use_exact and elapsed > 0 else number(reported)


def measurement_status(metadata: dict) -> str:
    measurement = metadata.get("measurement_stability", {})
    if not measurement:
        return "unavailable"
    if not measurement.get("stable"):
        return "fluctuating"
    change = number(measurement.get("first_last_rps_change_percent"))
    if change > 10:
        return "possible_late_warmup"
    if change < -10:
        return "decreasing_throughput"
    return "stable"


def collect_completed_runs(results_root: Path) -> tuple[list[dict], list[dict]]:
    runs: list[dict] = []
    endpoints: list[dict] = []
    raw_root = results_root / "raw"
    for stats_path in sorted(raw_root.glob("*/*/run_*/locust_stats.csv")):
        relative = stats_path.relative_to(raw_root).parts
        if len(relative) < 4:
            continue
        language, scenario, run_name = relative[:3]
        stats = read_csv(stats_path)
        aggregate = next((row for row in stats if row.get("Name") == "Aggregated"), None)
        if aggregate is None:
            continue

        run_directory = stats_path.parent
        metadata = read_json(run_directory / "metadata.json")
        resources, resource_source = read_resources(run_directory, metadata)
        postgres_summary = next(iter(read_csv(run_directory / "postgres_summary.csv")), {})
        cadvisor_rows = read_csv(run_directory / "cadvisor_summary.csv")
        api = resource(resources, lambda name: name == f"tcc_benchmark_{language}_api")
        locust = resource(resources, lambda name: "locust-run-" in name or name == "tcc_benchmark_locust")
        postgres = resource(resources, lambda name: name == "tcc_benchmark_postgres")
        cadvisor_api = resource(cadvisor_rows, lambda name: name == f"tcc_benchmark_{language}_api")
        cadvisor_locust = resource(cadvisor_rows, lambda name: name == "tcc_benchmark_locust")
        cadvisor_postgres = resource(cadvisor_rows, lambda name: name == "tcc_benchmark_postgres")
        measurement = metadata.get("measurement_stability", {})
        methodology = integer(metadata.get("methodology_version")) or 1
        classification = metadata.get("result_classification", "legacy")
        commit_sha = metadata.get("commit_sha") or metadata.get("git_commit") or "legacy"
        declared_campaign = metadata.get("execution_order", {}).get("campaign_fingerprint")
        campaign = declared_campaign if declared_campaign not in (None, "", "manual") else commit_sha
        duration = elapsed_seconds(metadata)
        bounds_valid = bool(metadata.get("test_phase", {}).get("bounds_validation", {}).get("valid"))
        window_source = metadata.get("metrics", {}).get("window_source")
        exact_window = (
            methodology >= 7 and bounds_valid and window_source == "locust_test_start_stop"
        ) or (
            5 <= methodology < 7 and window_source == "locust_test_start_stop"
        )
        use_exact_rps = methodology >= 7 and exact_window
        cadvisor_available = bool(cadvisor_api and cadvisor_locust and cadvisor_postgres)
        locust_metadata = metadata.get("locust", {})
        run_number = integer(run_name.removeprefix("run_"))
        run = {
            "language": language,
            "scenario": scenario,
            "run": run_number,
            "load_profile": metadata.get("load_profile", "legacy"),
            "methodology": methodology,
            "classification": classification,
            "campaign": campaign,
            "users": integer(locust_metadata.get("users")),
            "order_position": integer(metadata.get("execution_order", {}).get("position")),
            "sequence_id": metadata.get("execution_order", {}).get("sequence_id", "manual"),
            "requests": integer(aggregate.get("Request Count")),
            "failures": integer(aggregate.get("Failure Count")),
            "rps": throughput_rps(aggregate.get("Request Count"), duration, aggregate.get("Requests/s"), use_exact_rps),
            "locust_reported_rps": number(aggregate.get("Requests/s")),
            "throughput_source": "request_count / monotonic elapsed_seconds" if use_exact_rps else "locust_reported_rps",
            "avg_ms": number(aggregate.get("Average Response Time")),
            "p50_ms": number(aggregate.get("50%")),
            "p95_ms": number(aggregate.get("95%")),
            "p99_ms": number(aggregate.get("99%")),
            "duration_seconds": duration,
            "warmup_seconds": number(metadata.get("warmup", {}).get("total_duration_seconds")),
            "measurement_change_percent": number(measurement.get("first_last_rps_change_percent")),
            "measurement_status": measurement_status(metadata),
            "exact_window": exact_window,
            "cadvisor_available": cadvisor_available,
            "postgres_metrics_available": bool(postgres_summary),
            "postgres_metric_source": postgres_summary.get("metric_source", "unavailable"),
            "resource_source": resource_source,
            "resources_available": bool(api and locust and postgres and postgres_summary) and (
                not use_cadvisor_resources(metadata)
                or bool(metadata.get("monitoring_preflight", {}).get("official_eligible"))
            ),
            "api_cpu_avg": number(api.get("cpu_average_percent")),
            "api_cpu_max": number(api.get("cpu_max_percent")),
            "api_memory_avg": number(api.get("memory_average_bytes")),
            "api_memory_max": number(api.get("memory_max_bytes")),
            "api_cadvisor_coverage": number(api.get("coverage_percent")),
            "api_network_rx": number(api.get("network_rx_delta_bytes")),
            "api_network_tx": number(api.get("network_tx_delta_bytes")),
            "locust_cpu_avg": number(locust.get("cpu_average_percent")),
            "locust_cpu_max": number(locust.get("cpu_max_percent")),
            "locust_cpu_quota_avg": (
                number(locust.get("cpu_average_percent")) / number(locust_metadata.get("locust_cpu_quota"))
                if number(locust_metadata.get("locust_cpu_quota")) > 0 else None
            ),
            "locust_cadvisor_coverage": number(locust.get("coverage_percent")),
            "postgres_cpu_avg": number(postgres.get("cpu_average_percent")),
            "postgres_cpu_max": number(postgres.get("cpu_max_percent")),
            "postgres_cadvisor_coverage": number(postgres.get("coverage_percent")),
            "postgres_exporter_coverage": number(postgres_summary.get("coverage_percent")),
            "postgres_connections_avg": number(postgres_summary.get("connections_average")),
            "postgres_connections_max": number(postgres_summary.get("connections_max")),
            "postgres_commits_total": number(postgres_summary.get("commits_total")),
            "postgres_rollbacks_total": number(postgres_summary.get("rollbacks_total")),
            "postgres_commits_per_second": number(postgres_summary.get("commits_per_second")),
            "postgres_rollbacks_per_second": number(postgres_summary.get("rollbacks_per_second")),
            "postgres_blocks_read_total": number(postgres_summary.get("blocks_read_total")),
            "postgres_blocks_hit_total": number(postgres_summary.get("blocks_hit_total")),
            "postgres_cache_hit_ratio": number(postgres_summary.get("cache_hit_ratio")),
            "postgres_database_size_avg": number(postgres_summary.get("database_size_average_bytes")),
            "postgres_database_size_max": number(postgres_summary.get("database_size_max_bytes")),
        }
        runs.append(run)

        for row in stats:
            if row.get("Name") == "Aggregated":
                continue
            endpoints.append({
                "language": language,
                "scenario": scenario,
                "load_profile": run["load_profile"],
                "methodology": methodology,
                "classification": classification,
                "campaign": campaign,
                "users": run["users"],
                "run": run_number,
                "method": row.get("Type", ""),
                "endpoint": row.get("Name", ""),
                "requests": integer(row.get("Request Count")),
                "failures": integer(row.get("Failure Count")),
                "rps": throughput_rps(row.get("Request Count"), duration, row.get("Requests/s"), use_exact_rps),
                "avg_ms": number(row.get("Average Response Time")),
                "p50_ms": number(row.get("50%")),
                "p95_ms": number(row.get("95%")),
                "p99_ms": number(row.get("99%")),
            })
    return runs, endpoints


def confidence(rows: list[dict]) -> str:
    if any(row.get("classification") in {"non_official", "legacy"} for row in rows):
        return "non_official"
    if any(row["failures"] > 0 for row in rows):
        return "invalid_failures"
    if any(not row["resources_available"] for row in rows):
        return "invalid_missing_resources"
    if any(not row["exact_window"] for row in rows):
        return "invalid_measurement_window"
    # Methodology 7 gates on window-average CPU normalized by container quota.
    if any(
        (row.get("locust_cpu_quota_avg") is None or row["locust_cpu_quota_avg"] >= 90)
        if integer(row.get("methodology")) >= 7 else row["locust_cpu_max"] >= 90
        for row in rows
    ):
        return "invalid_load_generator"
    if any(row["measurement_status"] != "stable" for row in rows):
        return "invalid_instability"
    required_runs = 5 if any(
        integer(row.get("methodology")) >= 7 and row.get("load_profile") == "fixed_200"
        for row in rows
    ) else 3
    if len(rows) < required_runs:
        return f"preliminary_fewer_than_{required_runs}_runs"
    positions = {row["order_position"] for row in rows}
    if 0 in positions or len(positions) < required_runs:
        return "invalid_order_bias"
    values = [row["rps"] for row in rows]
    middle = statistics.median(values) if values else 0
    if middle <= 0 or (max(values) - min(values)) / middle * 100 > 10:
        return "invalid_run_variability"
    return "adequate"


def latest_methodology_groups(rows: list[dict], keys: tuple[str, ...]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    for key, group in list(groups.items()):
        latest = max(row["methodology"] for row in group)
        groups[key] = [row for row in group if row["methodology"] == latest]
    return groups


def label_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class Metrics:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.declared: set[str] = set()

    def add(self, name: str, value: float, labels: dict[str, object] | None = None, help_text: str = "") -> None:
        if name not in self.declared:
            self.lines.append(f"# HELP {name} {help_text or name}")
            self.lines.append(f"# TYPE {name} gauge")
            self.declared.add(name)
        label_text = ""
        if labels:
            pairs = ",".join(f'{key}="{label_value(item)}"' for key, item in sorted(labels.items()))
            label_text = "{" + pairs + "}"
        self.lines.append(f"{name}{label_text} {number(value):.9g}")

    def render(self) -> str:
        return "\n".join(self.lines) + "\n"


def add_result_metrics(metrics: Metrics, runs: list[dict], endpoints: list[dict]) -> None:
    for row in runs:
        labels = {
            "language": row["language"],
            "scenario": row["scenario"],
            "load_profile": row["load_profile"],
            "methodology": row["methodology"],
            "classification": row["classification"],
            "campaign": row["campaign"],
            "users": row["users"],
            "run": row["run"],
        }
        metrics.add("benchmark_run_throughput_rps", row["rps"], labels, "Throughput for one benchmark run")
        metrics.add("benchmark_run_requests", row["requests"], labels, "Requests for one benchmark run")
        metrics.add("benchmark_run_failures", row["failures"], labels, "Failures for one benchmark run")
        metrics.add("benchmark_run_duration_seconds", row["duration_seconds"], labels, "Measured duration for one benchmark run")
        if row["resources_available"] and row["methodology"] >= 7:
            for component, key_name in (
                ("api", "api_cadvisor_coverage"),
                ("locust", "locust_cadvisor_coverage"),
                ("postgresql", "postgres_cadvisor_coverage"),
            ):
                metrics.add(
                    "benchmark_run_cadvisor_coverage_percent", row[key_name],
                    {**labels, "component": component}, "cAdvisor coverage of the measurement window",
                )
        if row["postgres_metrics_available"] and row["methodology"] >= 7:
            metrics.add(
                "benchmark_run_postgres_exporter_coverage_percent", row["postgres_exporter_coverage"],
                labels, "postgres-exporter coverage of the measurement window",
            )
        for quantile, key_name in (("avg", "avg_ms"), ("p50", "p50_ms"), ("p95", "p95_ms"), ("p99", "p99_ms")):
            metrics.add("benchmark_run_latency_ms", row[key_name], {**labels, "quantile": quantile}, "Latency for one benchmark run")
        if row["postgres_metrics_available"]:
            postgres_labels = {**labels, "metric_source": row["postgres_metric_source"]}
            for stat, key_name in (("average", "postgres_connections_avg"), ("max", "postgres_connections_max")):
                metrics.add("benchmark_run_postgres_connections", row[key_name], {**postgres_labels, "stat": stat}, "PostgreSQL connections for one run")
            for transaction, total_key, rate_key in (
                ("commit", "postgres_commits_total", "postgres_commits_per_second"),
                ("rollback", "postgres_rollbacks_total", "postgres_rollbacks_per_second"),
            ):
                metrics.add("benchmark_run_postgres_transactions_total", row[total_key], {**postgres_labels, "transaction": transaction}, "PostgreSQL transactions for one run")
                metrics.add("benchmark_run_postgres_transactions_per_second", row[rate_key], {**postgres_labels, "transaction": transaction}, "PostgreSQL transaction rate for one run")
            metrics.add("benchmark_run_postgres_blocks_total", row["postgres_blocks_read_total"], {**postgres_labels, "operation": "read"}, "PostgreSQL blocks for one run")
            metrics.add("benchmark_run_postgres_blocks_total", row["postgres_blocks_hit_total"], {**postgres_labels, "operation": "hit"}, "PostgreSQL blocks for one run")
            metrics.add("benchmark_run_postgres_cache_hit_ratio", row["postgres_cache_hit_ratio"], postgres_labels, "PostgreSQL cache hit ratio for one run")
            metrics.add("benchmark_run_postgres_database_size_bytes", row["postgres_database_size_avg"], {**postgres_labels, "stat": "average"}, "PostgreSQL database size for one run")
            metrics.add("benchmark_run_postgres_database_size_bytes", row["postgres_database_size_max"], {**postgres_labels, "stat": "max"}, "PostgreSQL database size for one run")

    for row in endpoints:
        labels = {
            "language": row["language"],
            "scenario": row["scenario"],
            "load_profile": row["load_profile"],
            "methodology": row["methodology"],
            "classification": row["classification"],
            "campaign": row["campaign"],
            "users": row["users"],
            "run": row["run"],
            "method": row["method"],
            "endpoint": row["endpoint"],
        }
        metrics.add("benchmark_endpoint_run_throughput_rps", row["rps"], labels, "Endpoint throughput for one run")
        metrics.add("benchmark_endpoint_run_requests", row["requests"], labels, "Endpoint requests for one run")
        metrics.add("benchmark_endpoint_run_failures", row["failures"], labels, "Endpoint failures for one run")
        for quantile, key_name in (("avg", "avg_ms"), ("p50", "p50_ms"), ("p95", "p95_ms"), ("p99", "p99_ms")):
            metrics.add("benchmark_endpoint_run_latency_ms", row[key_name], {**labels, "quantile": quantile}, "Endpoint latency for one run")

    group_keys = ("campaign", "language", "scenario", "load_profile", "users", "classification")
    for key, group in sorted(latest_methodology_groups(runs, group_keys).items()):
        campaign, language, scenario, load_profile, users, classification = key
        labels = {
            "language": language,
            "scenario": scenario,
            "load_profile": load_profile,
            "methodology": group[0]["methodology"],
            "classification": classification,
            "campaign": campaign,
            "users": users,
        }
        rps_values = [row["rps"] for row in group]
        requests = sum(row["requests"] for row in group)
        failures = sum(row["failures"] for row in group)
        rps_median = statistics.median(rps_values) if rps_values else 0
        variability = (max(rps_values) - min(rps_values)) / rps_median * 100 if rps_median else 0
        metrics.add("benchmark_result_runs", len(group), labels, "Number of comparable benchmark runs")
        metrics.add("benchmark_result_confidence", 1, {**labels, "status": confidence(group)}, "Result confidence classification")
        for stat, value in (("median", rps_median), ("min", min(rps_values)), ("max", max(rps_values))):
            metrics.add("benchmark_result_throughput_rps", value, {**labels, "stat": stat}, "Benchmark throughput")
        metrics.add("benchmark_result_rps_variability_percent", variability, labels, "RPS min-max range relative to median")
        metrics.add("benchmark_result_requests", statistics.median(row["requests"] for row in group), labels, "Median requests per run")
        metrics.add("benchmark_result_failures", failures, labels, "Total failures in comparable runs")
        metrics.add("benchmark_result_error_rate", failures / requests if requests else 0, labels, "HTTP error ratio")
        metrics.add("benchmark_result_duration_seconds", median(group, "duration_seconds"), labels, "Median measured test duration")
        metrics.add("benchmark_result_warmup_seconds", median(group, "warmup_seconds"), labels, "Median warmup duration")
        metrics.add("benchmark_result_measurement_rps_change_percent", median(group, "measurement_change_percent"), labels, "Median RPS change during measurement")
        for quantile, key_name in (("avg", "avg_ms"), ("p50", "p50_ms"), ("p95", "p95_ms"), ("p99", "p99_ms")):
            metrics.add("benchmark_result_latency_ms", median(group, key_name), {**labels, "quantile": quantile}, "Benchmark response latency")
        if all(row["resources_available"] for row in group):
            source = group[0]["resource_source"]
            resource_labels = {**labels, "metric_source": source}
            for component, average_key, peak_key in (
                ("api", "api_cpu_avg", "api_cpu_max"),
                ("locust", "locust_cpu_avg", "locust_cpu_max"),
                ("postgres", "postgres_cpu_avg", "postgres_cpu_max"),
            ):
                metrics.add("benchmark_result_cpu_percent", median(group, average_key), {**resource_labels, "component": component, "stat": "average"}, "Median component CPU")
                metrics.add("benchmark_result_cpu_percent", max(row[peak_key] for row in group), {**resource_labels, "component": component, "stat": "peak"}, "Peak component CPU")
            metrics.add("benchmark_result_memory_bytes", median(group, "api_memory_avg"), {**resource_labels, "stat": "average"}, "Median API memory")
            metrics.add("benchmark_result_memory_bytes", max(row["api_memory_max"] for row in group), {**resource_labels, "stat": "peak"}, "Peak API memory")
            if source != "cadvisor_via_prometheus":
                metrics.add("benchmark_result_network_bytes", median(group, "api_network_rx"), {**resource_labels, "direction": "rx"}, "Median API network bytes")
                metrics.add("benchmark_result_network_bytes", median(group, "api_network_tx"), {**resource_labels, "direction": "tx"}, "Median API network bytes")
        if all(row["postgres_metrics_available"] for row in group):
            postgres_labels = {**labels, "metric_source": group[0]["postgres_metric_source"]}
            for stat, key_name in (("average", "postgres_connections_avg"), ("max", "postgres_connections_max")):
                metrics.add("benchmark_result_postgres_connections", median(group, key_name), {**postgres_labels, "stat": stat}, "Median PostgreSQL connections")
            for transaction, total_key, rate_key in (
                ("commit", "postgres_commits_total", "postgres_commits_per_second"),
                ("rollback", "postgres_rollbacks_total", "postgres_rollbacks_per_second"),
            ):
                metrics.add("benchmark_result_postgres_transactions_total", median(group, total_key), {**postgres_labels, "transaction": transaction}, "Median PostgreSQL transactions")
                metrics.add("benchmark_result_postgres_transactions_per_second", median(group, rate_key), {**postgres_labels, "transaction": transaction}, "Median PostgreSQL transaction rate")
            metrics.add("benchmark_result_postgres_blocks_total", median(group, "postgres_blocks_read_total"), {**postgres_labels, "operation": "read"}, "Median PostgreSQL blocks")
            metrics.add("benchmark_result_postgres_blocks_total", median(group, "postgres_blocks_hit_total"), {**postgres_labels, "operation": "hit"}, "Median PostgreSQL blocks")
            metrics.add("benchmark_result_postgres_cache_hit_ratio", median(group, "postgres_cache_hit_ratio"), postgres_labels, "Median PostgreSQL cache hit ratio")
            metrics.add("benchmark_result_postgres_database_size_bytes", median(group, "postgres_database_size_avg"), {**postgres_labels, "stat": "average"}, "Median PostgreSQL database size")
            metrics.add("benchmark_result_postgres_database_size_bytes", max(row["postgres_database_size_max"] for row in group), {**postgres_labels, "stat": "max"}, "Peak PostgreSQL database size")

    endpoint_keys = ("campaign", "language", "scenario", "load_profile", "users", "method", "endpoint", "classification")
    for key, group in sorted(latest_methodology_groups(endpoints, endpoint_keys).items()):
        campaign, language, scenario, load_profile, users, method, endpoint, classification = key
        labels = {
            "language": language,
            "scenario": scenario,
            "load_profile": load_profile,
            "methodology": group[0]["methodology"],
            "classification": classification,
            "campaign": campaign,
            "users": users,
            "method": method,
            "endpoint": endpoint,
        }
        metrics.add("benchmark_endpoint_throughput_rps", median(group, "rps"), labels, "Median endpoint throughput")
        metrics.add("benchmark_endpoint_requests", median(group, "requests"), labels, "Median endpoint requests")
        metrics.add("benchmark_endpoint_failures", sum(row["failures"] for row in group), labels, "Endpoint failures")
        for quantile, key_name in (("avg", "avg_ms"), ("p50", "p50_ms"), ("p95", "p95_ms"), ("p99", "p99_ms")):
            metrics.add("benchmark_endpoint_latency_ms", median(group, key_name), {**labels, "quantile": quantile}, "Median endpoint latency")


def freshest_run_directory(results_root: Path) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for run_directory in (results_root / "raw").glob("*/*/run_*"):
        paths = [
            run_directory / "locust_stats_history.csv",
            run_directory / "docker_stats_raw.csv",
            run_directory / "locust_stats.csv",
        ]
        modified = max((path.stat().st_mtime for path in paths if path.exists()), default=0)
        if modified:
            candidates.append((modified, run_directory))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def add_live_metrics(metrics: Metrics, results_root: Path) -> None:
    run_directory = freshest_run_directory(results_root)
    if run_directory is None:
        return
    now = time.time()
    relative = run_directory.relative_to(results_root / "raw").parts
    language, scenario, run_name = relative[:3]
    base_labels = {"language": language, "scenario": scenario, "run": run_name.removeprefix("run_")}

    history_path = run_directory / "locust_stats_history.csv"
    if history_path.exists() and now - history_path.stat().st_mtime <= LIVE_FRESHNESS_SECONDS:
        history = read_csv(history_path)
        aggregate = next((row for row in reversed(history) if row.get("Name") == "Aggregated"), None)
        if aggregate:
            metrics.add("benchmark_live_info", 1, base_labels, "Current benchmark run")
            metrics.add("benchmark_live_locust_users", number(aggregate.get("User Count")), base_labels, "Current Locust users")
            metrics.add("benchmark_live_locust_rps", number(aggregate.get("Requests/s")), base_labels, "Current Locust throughput")
            metrics.add("benchmark_live_locust_failures_per_second", number(aggregate.get("Failures/s")), base_labels, "Current Locust failures per second")
            metrics.add("benchmark_live_locust_requests", number(aggregate.get("Total Request Count")), base_labels, "Current Locust requests")
            metrics.add("benchmark_live_locust_failures", number(aggregate.get("Total Failure Count")), base_labels, "Current Locust failures")
            for quantile, column in (("p50", "50%"), ("p95", "95%"), ("p99", "99%"), ("avg", "Total Average Response Time")):
                metrics.add("benchmark_live_locust_latency_ms", number(aggregate.get(column)), {**base_labels, "quantile": quantile}, "Current Locust latency")

    docker_path = run_directory / "docker_stats_raw.csv"
    if docker_path.exists() and now - docker_path.stat().st_mtime <= LIVE_FRESHNESS_SECONDS:
        latest: dict[str, dict[str, str]] = {}
        for row in read_csv(docker_path):
            name = row.get("container_name", "")
            if name:
                latest[name] = row
        for container, row in latest.items():
            labels = {**base_labels, "container": container}
            metrics.add("benchmark_live_container_cpu_percent", number(row.get("cpu_percent")), labels, "Current container CPU")
            metrics.add("benchmark_live_container_memory_bytes", number(row.get("memory_usage_bytes")), labels, "Current container memory")
            metrics.add("benchmark_live_container_network_bytes", number(row.get("network_rx_bytes")), {**labels, "direction": "rx"}, "Current container network bytes")
            metrics.add("benchmark_live_container_network_bytes", number(row.get("network_tx_bytes")), {**labels, "direction": "tx"}, "Current container network bytes")
            metrics.add("benchmark_live_container_pids", number(row.get("pids")), labels, "Current container process count")


def render_metrics(results_root: Path) -> str:
    metrics = Metrics()
    try:
        runs, endpoints = collect_completed_runs(results_root)
        metrics.add("benchmark_results_exporter_up", 1, help_text="Benchmark results exporter status")
        metrics.add("benchmark_results_completed_runs", len(runs), help_text="Completed benchmark runs found")
        add_result_metrics(metrics, runs, endpoints)
        add_live_metrics(metrics, results_root)
    except Exception:
        metrics.add("benchmark_results_exporter_up", 0, help_text="Benchmark results exporter status")
    return metrics.render()


class Handler(BaseHTTPRequestHandler):
    results_root = Path("/results")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            payload = b"ok\n"
            status = 200
            content_type = "text/plain; charset=utf-8"
        elif self.path == "/metrics":
            payload = render_metrics(self.results_root).encode("utf-8")
            status = 200
            content_type = "text/plain; version=0.0.4; charset=utf-8"
        else:
            payload = b"not found\n"
            status = 404
            content_type = "text/plain; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=Path("/results"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9101)
    args = parser.parse_args()
    Handler.results_root = args.results
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Benchmark results exporter listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
