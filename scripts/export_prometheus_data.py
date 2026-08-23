#!/usr/bin/env python3
"""Export PostgreSQL and target time series from Prometheus."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path


QUERIES = {
    "targets_up": "up",
    "postgres_up": "pg_up",
    "postgres_connections": 'pg_stat_database_numbackends{datname="benchmark_db"}',
    "postgres_commits_total": 'pg_stat_database_xact_commit{datname="benchmark_db"}',
    "postgres_rollbacks_total": 'pg_stat_database_xact_rollback{datname="benchmark_db"}',
    "postgres_blocks_read": 'pg_stat_database_blks_read{datname="benchmark_db"}',
    "postgres_blocks_hit": 'pg_stat_database_blks_hit{datname="benchmark_db"}',
    "postgres_database_size_bytes": 'pg_database_size_bytes{datname="benchmark_db"}',
    "cadvisor_cpu_usage_seconds_total": "sum by (id,name,container_label_com_docker_compose_service) (container_cpu_usage_seconds_total)",
    "cadvisor_memory_working_set_bytes": "max by (id,name,container_label_com_docker_compose_service) (container_memory_working_set_bytes)",
}


def query_range(base_url: str, query: str, start: float, end: float, step: int) -> dict:
    params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/v1/query_range?{params}", timeout=15) as response:
        return json.load(response)


def container_id(container_name: str) -> str | None:
    try:
        completed = subprocess.run(
            ["docker", "inspect", container_name, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    identifier = completed.stdout.strip()
    return identifier if completed.returncode == 0 and identifier else None


def metric_matches(
    metric: dict[str, str],
    service: str,
    name_pattern: str,
    identifiers: str | list[str] | None = None,
) -> bool:
    if metric.get("container_label_com_docker_compose_service") == service:
        return True
    name = metric.get("name", "")
    if name_pattern and name_pattern in name:
        return True
    cgroup = metric.get("id", "")
    values = [identifiers] if isinstance(identifiers, str) else (identifiers or [])
    return any(identifier in cgroup or identifier[:12] in cgroup for identifier in values)


def matching_series(
    series: list[dict], service: str, name_pattern: str, identifiers: str | list[str] | None = None
) -> list[dict]:
    values = [identifiers] if isinstance(identifiers, str) else (identifiers or [])
    if values:
        by_identifier = [
            row for row in series
            if any(
                identifier in row.get("metric", {}).get("id", "")
                or identifier[:12] in row.get("metric", {}).get("id", "")
                for identifier in values
            )
        ]
        if by_identifier:
            return by_identifier
    return [row for row in series if metric_matches(row.get("metric", {}), service, name_pattern)]


def series_values(
    series: list[dict], service: str, name_pattern: str, identifiers: str | list[str] | None = None
) -> list[float]:
    values: list[float] = []
    for row in matching_series(series, service, name_pattern, identifiers):
        values.extend(float(value) for _, value in row.get("values", []) if value not in ("NaN", "+Inf", "-Inf"))
    return values


def series_cpu_rates(
    series: list[dict], service: str, name_pattern: str, identifiers: str | list[str] | None = None
) -> list[float]:
    rates: list[float] = []
    for row in matching_series(series, service, name_pattern, identifiers):
        values = [
            (float(timestamp), float(value))
            for timestamp, value in row.get("values", [])
            if value not in ("NaN", "+Inf", "-Inf")
        ]
        for (previous_time, previous_value), (current_time, current_value) in zip(values, values[1:]):
            elapsed = current_time - previous_time
            delta = current_value - previous_value
            if elapsed > 0 and delta >= 0:
                rates.append(delta / elapsed * 100)
    return rates


def sampled_container_ids(path: Path, component: str, canonical_name: str) -> list[str]:
    raw_path = path.with_name("docker_stats_raw.csv")
    if not raw_path.exists():
        return []
    identifiers: set[str] = set()
    with raw_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row.get("container_name", "")
            matches = name == canonical_name or (component == "locust" and "locust-run-" in name)
            if matches and row.get("container_id"):
                identifiers.add(row["container_id"])
    return sorted(identifiers)


def query_values(result: dict, key: str) -> list[float]:
    series = result["queries"][key]["response"].get("data", {}).get("result", [])
    return [
        float(value)
        for row in series
        for _, value in row.get("values", [])
        if value not in ("NaN", "+Inf", "-Inf")
    ]


def counter_window_delta(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    total = 0.0
    for previous, current in zip(values, values[1:]):
        total += current - previous if current >= previous else current
    return max(total, 0.0)


def write_postgres_summary(path: Path, result: dict, require: bool) -> None:
    keys = (
        "postgres_up", "postgres_connections", "postgres_commits_total", "postgres_rollbacks_total",
        "postgres_blocks_read", "postgres_blocks_hit", "postgres_database_size_bytes",
    )
    values = {key: query_values(result, key) for key in keys}
    missing = [key for key, series in values.items() if not series]
    insufficient = [key for key, series in values.items() if 0 < len(series) < 2]
    if values["postgres_up"] and any(value != 1 for value in values["postgres_up"]):
        missing.append("postgres_up_not_continuously_healthy")
    if require and (missing or insufficient):
        problems = missing + [f"{key}:insufficient_samples" for key in insufficient]
        raise RuntimeError("Invalid PostgreSQL measurement series: " + ", ".join(problems))
    connections = values["postgres_connections"]
    commits = counter_window_delta(values["postgres_commits_total"])
    rollbacks = counter_window_delta(values["postgres_rollbacks_total"])
    blocks_read = counter_window_delta(values["postgres_blocks_read"])
    blocks_hit = counter_window_delta(values["postgres_blocks_hit"])
    sizes = values["postgres_database_size_bytes"]
    elapsed = max(float(result["end_epoch"]) - float(result["start_epoch"]), 0.0)
    cache_total = blocks_hit + blocks_read
    row = {
        "samples": len(connections),
        "connections_average": f"{(sum(connections) / len(connections)) if connections else 0:.6f}",
        "connections_max": f"{max(connections, default=0):.6f}",
        "commits_total": f"{commits:.6f}",
        "rollbacks_total": f"{rollbacks:.6f}",
        "commits_per_second": f"{(commits / elapsed) if elapsed else 0:.6f}",
        "rollbacks_per_second": f"{(rollbacks / elapsed) if elapsed else 0:.6f}",
        "blocks_read_total": f"{blocks_read:.6f}",
        "blocks_hit_total": f"{blocks_hit:.6f}",
        "cache_hit_ratio": f"{(blocks_hit / cache_total) if cache_total else 0:.9f}",
        "database_size_average_bytes": f"{(sum(sizes) / len(sizes)) if sizes else 0:.3f}",
        "database_size_max_bytes": f"{max(sizes, default=0):.3f}",
        "metric_source": "postgres_exporter_via_prometheus",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def write_cadvisor_summary(path: Path, result: dict, components: list[str], require: bool) -> None:
    cpu = result["queries"]["cadvisor_cpu_usage_seconds_total"]["response"].get("data", {}).get("result", [])
    memory = result["queries"]["cadvisor_memory_working_set_bytes"]["response"].get("data", {}).get("result", [])
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for specification in components:
        component, target = specification.split("=", 1)
        service, name_pattern = target.split(",", 1)
        identifiers = sampled_container_ids(path, component, name_pattern)
        current_identifier = container_id(name_pattern)
        if current_identifier:
            identifiers.append(current_identifier)
        cpu_values = series_cpu_rates(cpu, service, name_pattern, identifiers)
        memory_values = series_values(memory, service, name_pattern, identifiers)
        if not cpu_values or not memory_values:
            missing.append(component)
            continue
        canonical_name = {
            "api": "tcc_benchmark_" + service.replace("-", "_"),
            "postgresql": "tcc_benchmark_postgres",
            "locust": "tcc_benchmark_locust",
        }.get(component, name_pattern)
        rows.append({
            "component": component,
            "container_name": canonical_name,
            "samples": min(len(cpu_values), len(memory_values)),
            "cpu_average_percent": f"{sum(cpu_values) / len(cpu_values):.6f}",
            "cpu_max_percent": f"{max(cpu_values):.6f}",
            "memory_average_bytes": round(sum(memory_values) / len(memory_values)),
            "memory_max_bytes": round(max(memory_values)),
            "metric_source": "cadvisor_via_prometheus",
        })
    fields = [
        "component", "container_name", "samples", "cpu_average_percent", "cpu_max_percent",
        "memory_average_bytes", "memory_max_bytes", "metric_source",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    if require and missing:
        raise RuntimeError("Missing cAdvisor measurement series for: " + ", ".join(missing))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9090")
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", required=True, type=float)
    parser.add_argument("--end", required=True, type=float)
    parser.add_argument("--step", type=int, default=5)
    parser.add_argument("--component", action="append", default=[])
    parser.add_argument("--require-cadvisor", action="store_true")
    parser.add_argument("--require-postgres", action="store_true")
    args = parser.parse_args()
    result = {"start_epoch": args.start, "end_epoch": args.end, "step_seconds": args.step, "queries": {}}
    for name, query in QUERIES.items():
        result["queries"][name] = {"query": query, "response": query_range(args.url, query, args.start, args.end, args.step)}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    write_postgres_summary(output.with_name("postgres_summary.csv"), result, args.require_postgres)
    write_cadvisor_summary(
        output.with_name("cadvisor_summary.csv"), result, args.component, args.require_cadvisor
    )
    print(f"Prometheus series exported to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
