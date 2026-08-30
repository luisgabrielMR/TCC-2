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


def clean_samples(row: dict) -> list[tuple[float, float]]:
    return sorted(
        (float(timestamp), float(value))
        for timestamp, value in row.get("values", [])
        if value not in ("NaN", "+Inf", "-Inf")
    )


def clipped_samples(samples: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    if end <= start or len(samples) < 2:
        return []

    def interpolate(boundary: float) -> tuple[float, float] | None:
        for left, right in zip(samples, samples[1:]):
            if left[0] <= boundary <= right[0] and right[0] > left[0]:
                ratio = (boundary - left[0]) / (right[0] - left[0])
                return boundary, left[1] + (right[1] - left[1]) * ratio
        return None

    observed_start = max(start, samples[0][0])
    observed_end = min(end, samples[-1][0])
    if observed_end <= observed_start:
        return []
    first = interpolate(observed_start)
    last = interpolate(observed_end)
    if first is None or last is None:
        return []
    inside = [(timestamp, value) for timestamp, value in samples if observed_start < timestamp < observed_end]
    return [first, *inside, last]


def time_weighted_gauge(
    samples: list[tuple[float, float]], start: float, end: float
) -> tuple[float, float, int, float]:
    clipped = clipped_samples(samples, start, end)
    if len(clipped) < 2:
        return 0.0, 0.0, 0, 0.0
    area = 0.0
    for (left_time, left_value), (right_time, right_value) in zip(clipped, clipped[1:]):
        area += (left_value + right_value) / 2 * (right_time - left_time)
    observed = clipped[-1][0] - clipped[0][0]
    return area / observed if observed else 0.0, max(value for _, value in clipped), len(clipped), observed


def counter_window_delta_samples(samples: list[tuple[float, float]], start: float, end: float) -> float:
    total = 0.0
    for (left_time, left_value), (right_time, right_value) in zip(samples, samples[1:]):
        interval = right_time - left_time
        overlap = min(right_time, end) - max(left_time, start)
        if interval <= 0 or overlap <= 0:
            continue
        delta = right_value - left_value if right_value >= left_value else right_value
        total += max(delta, 0.0) * overlap / interval
    return total


def series_cpu_observations(
    series: list[dict], service: str, name_pattern: str, identifiers: str | list[str] | None,
    start: float, end: float,
) -> list[tuple[float, float]]:
    observations: list[tuple[float, float]] = []
    for row in matching_series(series, service, name_pattern, identifiers):
        values = clean_samples(row)
        for (previous_time, previous_value), (current_time, current_value) in zip(values, values[1:]):
            elapsed = current_time - previous_time
            overlap = min(current_time, end) - max(previous_time, start)
            delta = current_value - previous_value
            if elapsed > 0 and overlap > 0 and delta >= 0:
                observations.append((delta / elapsed * 100, overlap))
    return observations


def series_gauge_summary(
    series: list[dict], service: str, name_pattern: str, identifiers: str | list[str] | None,
    start: float, end: float,
) -> tuple[float, float, int, float]:
    summaries = [
        time_weighted_gauge(clean_samples(row), start, end)
        for row in matching_series(series, service, name_pattern, identifiers)
    ]
    return max(summaries, key=lambda item: item[3], default=(0.0, 0.0, 0, 0.0))


def series_cpu_rates(
    series: list[dict], service: str, name_pattern: str, identifiers: str | list[str] | None = None,
    start: float = float("-inf"), end: float = float("inf"),
) -> list[float]:
    return [rate for rate, _ in series_cpu_observations(series, service, name_pattern, identifiers, start, end)]


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


def query_samples(result: dict, key: str) -> list[tuple[float, float]]:
    series = result["queries"][key]["response"].get("data", {}).get("result", [])
    return clean_samples(series[0]) if series else []


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
    samples = {key: query_samples(result, key) for key in keys}
    missing = [key for key, series in samples.items() if not series]
    insufficient = [key for key, series in samples.items() if 0 < len(series) < 2]
    start = float(result["start_epoch"])
    end = float(result["end_epoch"])
    elapsed = max(end - start, 0.0)
    observed_by_metric = {}
    for key, series in samples.items():
        clipped = clipped_samples(series, start, end)
        observed_by_metric[key] = clipped[-1][0] - clipped[0][0] if len(clipped) >= 2 else 0.0
    clipped_up = clipped_samples(samples["postgres_up"], start, end)
    if clipped_up and any(value != 1 for _, value in clipped_up):
        missing.append("postgres_up_not_continuously_healthy")
    if require and (missing or insufficient):
        problems = missing + [f"{key}:insufficient_samples" for key in insufficient]
        raise RuntimeError("Invalid PostgreSQL measurement series: " + ", ".join(problems))
    incomplete_coverage = [
        f"{key}:{observed:.3f}/{elapsed:.3f}s"
        for key, observed in observed_by_metric.items()
        if elapsed and observed < elapsed * 0.99
    ]
    if require and incomplete_coverage:
        raise RuntimeError(
            "PostgreSQL measurement coverage is incomplete: " + ", ".join(incomplete_coverage)
        )
    connections_average, connections_max, connection_samples, connection_observed = time_weighted_gauge(
        samples["postgres_connections"], start, end
    )
    size_average, size_max, _, _ = time_weighted_gauge(samples["postgres_database_size_bytes"], start, end)
    commits = counter_window_delta_samples(samples["postgres_commits_total"], start, end)
    rollbacks = counter_window_delta_samples(samples["postgres_rollbacks_total"], start, end)
    blocks_read = counter_window_delta_samples(samples["postgres_blocks_read"], start, end)
    blocks_hit = counter_window_delta_samples(samples["postgres_blocks_hit"], start, end)
    minimum_observed = min(observed_by_metric.values(), default=0.0)
    cache_total = blocks_hit + blocks_read
    row = {
        "samples": connection_samples,
        "observed_seconds": f"{minimum_observed:.6f}",
        "coverage_percent": f"{(minimum_observed / elapsed * 100) if elapsed else 0:.6f}",
        "coverage_by_metric": json.dumps({
            key: round(observed / elapsed * 100, 6) if elapsed else 0.0
            for key, observed in observed_by_metric.items()
        }, sort_keys=True, separators=(",", ":")),
        "connections_average": f"{connections_average:.6f}",
        "connections_max": f"{connections_max:.6f}",
        "commits_total": f"{commits:.6f}",
        "rollbacks_total": f"{rollbacks:.6f}",
        "commits_per_second": f"{(commits / elapsed) if elapsed else 0:.6f}",
        "rollbacks_per_second": f"{(rollbacks / elapsed) if elapsed else 0:.6f}",
        "blocks_read_total": f"{blocks_read:.6f}",
        "blocks_hit_total": f"{blocks_hit:.6f}",
        "cache_hit_ratio": f"{(blocks_hit / cache_total) if cache_total else 0:.9f}",
        "database_size_average_bytes": f"{size_average:.3f}",
        "database_size_max_bytes": f"{size_max:.3f}",
        "boundary_method": "scrape-padded overlap clipping; time-weighted gauges",
        "metric_source": "postgres_exporter_via_prometheus",
    }
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def write_cadvisor_summary(
    path: Path, result: dict, components: list[str], require: bool, minimum_coverage_percent: float = 90
) -> None:
    cpu = result["queries"]["cadvisor_cpu_usage_seconds_total"]["response"].get("data", {}).get("result", [])
    memory = result["queries"]["cadvisor_memory_working_set_bytes"]["response"].get("data", {}).get("result", [])
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    start = float(result["start_epoch"])
    end = float(result["end_epoch"])
    elapsed = max(end - start, 0.0)
    for specification in components:
        component, target = specification.split("=", 1)
        service, name_pattern = target.split(",", 1)
        identifiers = sampled_container_ids(path, component, name_pattern)
        current_identifier = container_id(name_pattern)
        if current_identifier:
            identifiers.append(current_identifier)
        cpu_observations = series_cpu_observations(
            cpu, service, name_pattern, identifiers, start, end
        )
        memory_average, memory_max, memory_samples, memory_observed = series_gauge_summary(
            memory, service, name_pattern, identifiers, start, end
        )
        cpu_observed = sum(overlap for _, overlap in cpu_observations)
        cpu_average = (
            sum(rate * overlap for rate, overlap in cpu_observations) / cpu_observed
            if cpu_observed else 0.0
        )
        cpu_max = max((rate for rate, _ in cpu_observations), default=0.0)
        coverage = min(cpu_observed, memory_observed) / elapsed * 100 if elapsed else 0.0
        if not cpu_observations or not memory_samples:
            missing.append(component)
            continue
        if require and coverage < minimum_coverage_percent:
            missing.append(f"{component}:coverage_{coverage:.1f}_percent")
            continue
        canonical_name = {
            "api": "tcc_benchmark_" + service.replace("-", "_"),
            "postgresql": "tcc_benchmark_postgres",
            "locust": "tcc_benchmark_locust",
        }.get(component, name_pattern)
        rows.append({
            "component": component,
            "container_name": canonical_name,
            "samples": min(len(cpu_observations), memory_samples),
            "observed_seconds": f"{min(cpu_observed, memory_observed):.6f}",
            "coverage_percent": f"{coverage:.6f}",
            "cpu_average_percent": f"{cpu_average:.6f}",
            "cpu_max_percent": f"{cpu_max:.6f}",
            "memory_average_bytes": round(memory_average),
            "memory_max_bytes": round(memory_max),
            "boundary_method": "scrape-padded overlap clipping; time-weighted samples",
            "metric_source": "cadvisor_via_prometheus",
        })
    fields = [
        "component", "container_name", "samples", "observed_seconds", "coverage_percent",
        "cpu_average_percent", "cpu_max_percent", "memory_average_bytes", "memory_max_bytes",
        "boundary_method", "metric_source",
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
    parser.add_argument("--minimum-cadvisor-coverage-percent", type=float, default=90)
    args = parser.parse_args()
    query_start = args.start - args.step
    query_end = args.end + args.step
    result = {
        "start_epoch": args.start,
        "end_epoch": args.end,
        "query_start_epoch": query_start,
        "query_end_epoch": query_end,
        "step_seconds": args.step,
        "boundary_method": "one-scrape padding with overlap clipping to wall-clock boundaries; duration is monotonic",
        "queries": {},
    }
    for name, query in QUERIES.items():
        result["queries"][name] = {
            "query": query,
            "response": query_range(args.url, query, query_start, query_end, args.step),
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    write_postgres_summary(output.with_name("postgres_summary.csv"), result, args.require_postgres)
    write_cadvisor_summary(
        output.with_name("cadvisor_summary.csv"), result, args.component, args.require_cadvisor,
        args.minimum_cadvisor_coverage_percent,
    )
    print(f"Prometheus series exported to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
