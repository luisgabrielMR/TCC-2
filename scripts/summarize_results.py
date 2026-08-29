#!/usr/bin/env python3
"""Summarize benchmark runs, resources, duration and scalability."""

from __future__ import annotations

import csv
import json
import statistics
import argparse
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
PROCESSED = ROOT / "results" / "processed"
SUMMARIES = ROOT / "results" / "summaries"
LANGUAGE_ORDER = {name: index for index, name in enumerate(("python", "node", "java", "go", "dotnet"))}

ENDPOINT_FIELDS = [
    "language", "scenario", "load_profile", "methodology_version", "result_classification",
    "run", "users", "benchmark_kind", "execution_order_position", "method", "endpoint",
    "requests", "failures", "error_rate", "avg_ms", "p50_ms", "p95_ms", "p99_ms",
    "throughput_rps", "test_elapsed_seconds", "exact_measurement_window",
    "resource_metrics_available", "cadvisor_metrics_available", "postgres_metrics_available",
    "resource_metric_source", "cpu_average_percent", "cpu_max_percent",
    "memory_average_bytes", "memory_max_bytes", "locust_cpu_average_percent",
    "postgres_cpu_average_percent", "postgres_connections_average", "postgres_cache_hit_ratio",
]

LANGUAGE_FIELDS = [
    "language", "scenario", "run", "load_profile", "methodology_version", "result_classification",
    "benchmark_kind", "users", "spawn_rate", "configured_duration", "wait_seconds",
    "test_elapsed_seconds", "duration_source", "exact_measurement_window",
    "resource_metrics_available", "cadvisor_metrics_available", "postgres_metrics_available",
    "resource_metric_source", "execution_order_position", "requests", "failures", "error_rate",
    "throughput_rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "cpu_average_percent",
    "cpu_max_percent", "memory_average_bytes", "memory_max_bytes", "network_rx_delta_bytes",
    "network_tx_delta_bytes", "locust_cpu_average_percent", "locust_cpu_max_percent",
    "postgres_cpu_average_percent", "postgres_cpu_max_percent", "postgres_metric_source",
    "postgres_connections_average", "postgres_connections_max", "postgres_commits_total",
    "postgres_rollbacks_total", "postgres_commits_per_second", "postgres_rollbacks_per_second",
    "postgres_blocks_read_total", "postgres_blocks_hit_total", "postgres_cache_hit_ratio",
    "postgres_database_size_average_bytes", "postgres_database_size_max_bytes",
    "measurement_first_window_rps", "measurement_last_window_rps",
    "measurement_rps_change_percent", "measurement_final_window_drift_percent",
    "measurement_final_windows_stable", "measurement_stability_status",
]

SCALABILITY_FIELDS = [
    "language", "scenario", "load_profile", "methodology_version", "result_classification",
    "users", "runs", "requests", "failures", "error_rate", "avg_ms", "p50_ms", "p95_ms",
    "p99_ms", "throughput_rps", "throughput_min_rps", "throughput_max_rps",
    "throughput_relative_range_percent", "test_elapsed_seconds", "resource_metrics_available",
    "cadvisor_metrics_available", "resource_metric_source", "api_cpu_average_percent",
    "api_cpu_max_percent", "api_memory_average_bytes", "api_memory_max_bytes",
    "locust_cpu_average_percent", "postgres_cpu_average_percent", "rps_gain_vs_50_percent",
    "linear_scaling_efficiency_percent", "rps_gain_vs_previous_percent",
    "p95_change_vs_previous_percent", "measurement_rps_change_percent",
    "measurement_stability_status", "result_confidence", "capacity_status",
]


def number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def median(rows: list[dict], key: str) -> float:
    values = [number(row.get(key)) for row in rows if row.get(key) not in (None, "")]
    return statistics.median(values) if values else 0.0


def numeric_values(rows: list[dict], key: str) -> list[float]:
    return [number(row.get(key)) for row in rows if row.get(key) not in (None, "")]


def result_confidence(rows: list[dict]) -> str:
    if any(row.get("result_classification") in {"non_official", "legacy"} for row in rows):
        return "non_official"
    if any(int(row.get("failures", 0)) > 0 for row in rows):
        return "invalid_failures"
    if any(not row.get("resource_metrics_available", False) for row in rows):
        return "invalid_missing_resources"
    if any(not row.get("exact_measurement_window", False) for row in rows):
        return "invalid_measurement_window"
    if any(number(row.get("locust_cpu_max_percent")) >= 90 for row in rows):
        return "invalid_load_generator"
    if any(row.get("measurement_stability_status") != "stable" for row in rows):
        return "invalid_instability"
    if len(rows) < 3:
        return "preliminary_fewer_than_3_runs"
    order_positions = {int(number(row.get("execution_order_position"))) for row in rows}
    if 0 in order_positions or len(order_positions) < 3:
        return "invalid_order_bias"
    rps_values = numeric_values(rows, "throughput_rps")
    rps_median = statistics.median(rps_values) if rps_values else 0
    if rps_median <= 0 or (max(rps_values) - min(rps_values)) / rps_median * 100 > 10:
        return "invalid_run_variability"
    return "adequate"


def comparable_rows(rows: list[dict]) -> list[dict]:
    """Prefer runs produced by the current methodology over legacy results."""
    current = [row for row in rows if row.get("load_profile", "legacy") != "legacy"]
    candidates = current or rows
    latest_version = max(int(number(row.get("methodology_version"), 1)) for row in candidates)
    return [row for row in candidates if int(number(row.get("methodology_version"), 1)) == latest_version]


def measurement_status(change_percent: float, final_windows_stable: bool, available: bool = True) -> str:
    if not available:
        return "unavailable"
    if not final_windows_stable:
        return "fluctuating"
    if change_percent > 10:
        return "possible_late_warmup"
    if change_percent < -10:
        return "decreasing_throughput"
    return "stable"


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def use_cadvisor_resources(metadata: dict) -> bool:
    methodology = int(number(metadata.get("methodology_version"), 1))
    return methodology >= 6 and metadata.get("result_classification") == "official"


def read_resource_rows(run_directory: Path, metadata: dict) -> tuple[list[dict[str, str]], str]:
    if use_cadvisor_resources(metadata):
        return read_csv_rows(run_directory / "cadvisor_summary.csv"), "cadvisor_via_prometheus"
    return read_csv_rows(run_directory / "docker_stats_summary.csv"), "docker_stats_complementary"


def find_resource(rows: list[dict[str, str]], predicate) -> dict[str, str]:
    return next((row for row in rows if predicate(row.get("container_name", ""))), {})


def duration_from_metadata(metadata: dict) -> tuple[float, str]:
    test_phase = metadata.get("test_phase", {})
    elapsed = number(test_phase.get("elapsed_seconds"))
    if elapsed > 0:
        return elapsed, "test_phase"
    metrics = metadata.get("metrics", {})
    started = number(metrics.get("started_epoch"))
    finished = number(metrics.get("finished_epoch"))
    if finished > started > 0:
        return finished - started, "metrics_window_legacy"
    return 0.0, "unavailable"


def collect_runs(raw: Path | None = None) -> tuple[list[dict], list[dict]]:
    source = raw or RAW
    runs: list[dict] = []
    endpoint_rows: list[dict] = []
    for stats_file in source.glob("*/*/run_*/locust_stats.csv"):
        language, scenario, run_dir = stats_file.relative_to(source).parts[:3]
        run_number = run_dir.removeprefix("run_")
        with stats_file.open("r", encoding="utf-8-sig", newline="") as handle:
            stats = list(csv.DictReader(handle))
        aggregate = next((row for row in stats if row.get("Name") == "Aggregated"), None)
        if aggregate is None:
            continue

        run_directory = stats_file.parent
        metadata = read_json(run_directory / "metadata.json")
        resources, resource_source = read_resource_rows(run_directory, metadata)
        postgres_summary = next(iter(read_csv_rows(run_directory / "postgres_summary.csv")), {})
        cadvisor_rows = read_csv_rows(run_directory / "cadvisor_summary.csv")
        api = find_resource(resources, lambda name: name == f"tcc_benchmark_{language}_api")
        locust = find_resource(resources, lambda name: "locust-run-" in name or name == "tcc_benchmark_locust")
        postgres = find_resource(resources, lambda name: name == "tcc_benchmark_postgres")
        cadvisor_api = find_resource(cadvisor_rows, lambda name: name == f"tcc_benchmark_{language}_api")
        cadvisor_locust = find_resource(cadvisor_rows, lambda name: name == "tcc_benchmark_locust")
        cadvisor_postgres = find_resource(cadvisor_rows, lambda name: name == "tcc_benchmark_postgres")
        elapsed, duration_source = duration_from_metadata(metadata)
        locust_meta = metadata.get("locust", {})
        measurement = metadata.get("measurement_stability", {})
        measurement_available = bool(measurement)
        measurement_change = number(measurement.get("first_last_rps_change_percent"))
        final_windows_stable = bool(measurement.get("stable")) if measurement_available else False
        methodology_version = int(number(metadata.get("methodology_version"), 1))
        classification = metadata.get("result_classification", "legacy")
        monitoring = metadata.get("monitoring_preflight", {})
        cadvisor_available = bool(cadvisor_api and cadvisor_locust and cadvisor_postgres)
        resource_metrics_available = bool(api and locust and postgres and postgres_summary) and (
            not use_cadvisor_resources(metadata) or bool(monitoring.get("official_eligible"))
        )

        run = {
            "language": language,
            "scenario": scenario,
            "run": run_number,
            "load_profile": metadata.get("load_profile", "legacy"),
            "methodology_version": methodology_version,
            "result_classification": classification,
            "execution_order_position": int(number(metadata.get("execution_order", {}).get("position"))),
            "benchmark_kind": metadata.get("benchmark_kind", "controlled_load"),
            "users": int(number(locust_meta.get("users"))),
            "spawn_rate": int(number(locust_meta.get("spawn_rate"))),
            "configured_duration": locust_meta.get("duration", ""),
            "wait_seconds": number(locust_meta.get("wait_seconds"), 0.1),
            "test_elapsed_seconds": elapsed,
            "duration_source": duration_source,
            "exact_measurement_window": (
                methodology_version >= 5
                and metadata.get("metrics", {}).get("window_source") == "locust_test_start_stop"
            ),
            "cadvisor_metrics_available": cadvisor_available,
            "postgres_metrics_available": bool(postgres_summary),
            "resource_metric_source": resource_source,
            "resource_metrics_available": resource_metrics_available,
            "requests": int(number(aggregate.get("Request Count"))),
            "failures": int(number(aggregate.get("Failure Count"))),
            "avg_ms": number(aggregate.get("Average Response Time")),
            "p50_ms": number(aggregate.get("50%")),
            "p95_ms": number(aggregate.get("95%")),
            "p99_ms": number(aggregate.get("99%")),
            "throughput_rps": number(aggregate.get("Requests/s")),
            "cpu_average_percent": number(api.get("cpu_average_percent")) if api else None,
            "cpu_max_percent": number(api.get("cpu_max_percent")) if api else None,
            "memory_average_bytes": number(api.get("memory_average_bytes")) if api else None,
            "memory_max_bytes": number(api.get("memory_max_bytes")) if api else None,
            "network_rx_delta_bytes": number(api.get("network_rx_delta_bytes")) if api else None,
            "network_tx_delta_bytes": number(api.get("network_tx_delta_bytes")) if api else None,
            "locust_cpu_average_percent": number(locust.get("cpu_average_percent")) if locust else None,
            "locust_cpu_max_percent": number(locust.get("cpu_max_percent")) if locust else None,
            "postgres_cpu_average_percent": number(postgres.get("cpu_average_percent")) if postgres else None,
            "postgres_cpu_max_percent": number(postgres.get("cpu_max_percent")) if postgres else None,
            "postgres_metric_source": postgres_summary.get("metric_source", "unavailable"),
            "postgres_connections_average": number(postgres_summary.get("connections_average")) if postgres_summary else None,
            "postgres_connections_max": number(postgres_summary.get("connections_max")) if postgres_summary else None,
            "postgres_commits_total": number(postgres_summary.get("commits_total")) if postgres_summary else None,
            "postgres_rollbacks_total": number(postgres_summary.get("rollbacks_total")) if postgres_summary else None,
            "postgres_commits_per_second": number(postgres_summary.get("commits_per_second")) if postgres_summary else None,
            "postgres_rollbacks_per_second": number(postgres_summary.get("rollbacks_per_second")) if postgres_summary else None,
            "postgres_blocks_read_total": number(postgres_summary.get("blocks_read_total")) if postgres_summary else None,
            "postgres_blocks_hit_total": number(postgres_summary.get("blocks_hit_total")) if postgres_summary else None,
            "postgres_cache_hit_ratio": number(postgres_summary.get("cache_hit_ratio")) if postgres_summary else None,
            "postgres_database_size_average_bytes": number(postgres_summary.get("database_size_average_bytes")) if postgres_summary else None,
            "postgres_database_size_max_bytes": number(postgres_summary.get("database_size_max_bytes")) if postgres_summary else None,
            "measurement_first_window_rps": number(measurement.get("first_window_rps")),
            "measurement_last_window_rps": number(measurement.get("last_window_rps")),
            "measurement_rps_change_percent": measurement_change,
            "measurement_final_window_drift_percent": number(measurement.get("rps_drift_percent")),
            "measurement_final_windows_stable": final_windows_stable,
            "measurement_stability_status": measurement_status(
                measurement_change, final_windows_stable, measurement_available
            ),
        }
        runs.append(run)

        for row in stats:
            if row.get("Name") == "Aggregated":
                continue
            endpoint_rows.append({
                "language": language,
                "scenario": scenario,
                "run": run_number,
                "load_profile": run["load_profile"],
                "methodology_version": methodology_version,
                "result_classification": classification,
                "users": run["users"],
                "benchmark_kind": run["benchmark_kind"],
                "execution_order_position": run["execution_order_position"],
                "method": row.get("Type", ""),
                "endpoint": row.get("Name", ""),
                "requests": int(number(row.get("Request Count"))),
                "failures": int(number(row.get("Failure Count"))),
                "error_rate": f"{(number(row.get('Failure Count')) / number(row.get('Request Count'))) if number(row.get('Request Count')) else 0:.6f}",
                "avg_ms": row.get("Average Response Time", ""),
                "p50_ms": row.get("50%", ""),
                "p95_ms": row.get("95%", ""),
                "p99_ms": row.get("99%", ""),
                "throughput_rps": row.get("Requests/s", ""),
                "test_elapsed_seconds": run["test_elapsed_seconds"],
                "exact_measurement_window": run["exact_measurement_window"],
                "resource_metrics_available": run["resource_metrics_available"],
                "cadvisor_metrics_available": run["cadvisor_metrics_available"],
                "postgres_metrics_available": run["postgres_metrics_available"],
                "resource_metric_source": run["resource_metric_source"],
                "cpu_average_percent": run["cpu_average_percent"],
                "cpu_max_percent": run["cpu_max_percent"],
                "memory_average_bytes": run["memory_average_bytes"],
                "memory_max_bytes": run["memory_max_bytes"],
                "locust_cpu_average_percent": run["locust_cpu_average_percent"],
                "postgres_cpu_average_percent": run["postgres_cpu_average_percent"],
                "postgres_connections_average": run["postgres_connections_average"],
                "postgres_cache_hit_ratio": run["postgres_cache_hit_ratio"],
            })
    return runs, endpoint_rows


def scalability_rows(runs: list[dict]) -> list[dict]:
    scalable_prefixes = ("mixed_capacity_", "mixed_saturation_")
    mixed = [
        row for row in runs
        if row["scenario"] == "mixed" or row["scenario"].startswith(scalable_prefixes)
    ]
    current_cohorts = {
        (row["language"], row.get("result_classification", "legacy"))
        for row in mixed if row.get("load_profile", "legacy") != "legacy"
    }
    candidates = [
        row for row in mixed
        if row.get("load_profile", "legacy") != "legacy"
        or (row["language"], row.get("result_classification", "legacy")) not in current_cohorts
    ]
    latest_versions = {
        cohort: max(
            int(number(row.get("methodology_version"), 1))
            for row in candidates
            if (row["language"], row.get("result_classification", "legacy")) == cohort
        )
        for cohort in {
            (row["language"], row.get("result_classification", "legacy")) for row in candidates
        }
    }
    mixed = [
        row for row in candidates
        if int(number(row.get("methodology_version"), 1))
        == latest_versions[(row["language"], row.get("result_classification", "legacy"))]
    ]
    groups: dict[tuple[str, str, str, int, str, int], list[dict]] = defaultdict(list)
    for row in mixed:
        if row["users"] > 0:
            groups[(
                row["language"], row["scenario"], row.get("load_profile", "legacy"),
                int(number(row.get("methodology_version"), 1)),
                row.get("result_classification", "legacy"), int(row["users"]),
            )].append(row)

    output: list[dict] = []
    cohorts: dict[tuple[str, int, str], list[tuple[int, list[dict]]]] = defaultdict(list)
    for (language, _scenario, _profile, methodology, classification, users), group in groups.items():
        cohorts[(language, methodology, classification)].append((users, group))

    for (language, methodology, classification), levels in cohorts.items():
        levels.sort(key=lambda item: item[0])
        baseline_group = next(
            (group for users, group in levels if users == 50 and group[0]["scenario"] == "mixed"),
            levels[0][1],
        )
        baseline_users = int(baseline_group[0]["users"])
        baseline_rps = median(baseline_group, "throughput_rps")
        previous_rps = 0.0
        previous_p95 = 0.0

        for users, group in levels:
            rps = median(group, "throughput_rps")
            p95 = median(group, "p95_ms")
            failures = sum(int(row["failures"]) for row in group)
            requests = sum(int(row["requests"]) for row in group)
            locust_cpu = median(group, "locust_cpu_average_percent")
            gain_baseline = (rps / baseline_rps - 1) * 100 if baseline_rps else 0.0
            linear_efficiency = rps / (baseline_rps * users / baseline_users) * 100 if baseline_rps else 0.0
            gain_previous = (rps / previous_rps - 1) * 100 if previous_rps else 0.0
            p95_change = (p95 / previous_p95 - 1) * 100 if previous_p95 else 0.0
            trend_rows = [
                row for row in group
                if row.get("measurement_stability_status", "unavailable") != "unavailable"
            ]
            measurement_change = median(trend_rows, "measurement_rps_change_percent")
            trend_status = measurement_status(
                measurement_change,
                all(bool(row.get("measurement_final_windows_stable")) for row in trend_rows),
                bool(trend_rows),
            )
            rps_values = numeric_values(group, "throughput_rps")
            rps_min = min(rps_values) if rps_values else 0.0
            rps_max = max(rps_values) if rps_values else 0.0
            rps_spread = (rps_max - rps_min) / rps * 100 if rps else 0.0
            confidence = result_confidence(group)

            resources_available = all(bool(row.get("resource_metrics_available")) for row in group)
            if not resources_available:
                status = "missing_resources"
            elif users == baseline_users:
                status = "baseline"
            elif failures:
                status = "failures_detected"
            elif locust_cpu >= 90:
                status = "load_generator_limit"
            elif gain_previous < 10:
                status = "probable_saturation"
            elif p95_change >= 100 and gain_previous < 50:
                status = "under_pressure"
            else:
                status = "scaling"

            output.append({
                "language": language,
                "scenario": group[0]["scenario"],
                "load_profile": group[0].get("load_profile", "legacy"),
                "methodology_version": methodology,
                "result_classification": classification,
                "users": users,
                "runs": len(group),
                "requests": requests,
                "failures": failures,
                "avg_ms": f"{median(group, 'avg_ms'):.3f}",
                "p50_ms": f"{median(group, 'p50_ms'):.3f}",
                "throughput_rps": f"{rps:.3f}",
                "throughput_min_rps": f"{rps_min:.3f}",
                "throughput_max_rps": f"{rps_max:.3f}",
                "throughput_relative_range_percent": f"{rps_spread:.3f}",
                "p95_ms": f"{p95:.3f}",
                "p99_ms": f"{median(group, 'p99_ms'):.3f}",
                "error_rate": f"{(failures / requests) if requests else 0:.6f}",
                "test_elapsed_seconds": f"{median(group, 'test_elapsed_seconds'):.3f}",
                "resource_metrics_available": resources_available,
                "cadvisor_metrics_available": all(bool(row.get("cadvisor_metrics_available")) for row in group),
                "resource_metric_source": group[0].get("resource_metric_source", "unavailable"),
                "api_cpu_average_percent": f"{median(group, 'cpu_average_percent'):.3f}" if resources_available else "",
                "api_cpu_max_percent": f"{median(group, 'cpu_max_percent'):.3f}" if resources_available else "",
                "api_memory_average_bytes": f"{median(group, 'memory_average_bytes'):.3f}" if resources_available else "",
                "api_memory_max_bytes": f"{median(group, 'memory_max_bytes'):.3f}" if resources_available else "",
                "locust_cpu_average_percent": f"{locust_cpu:.3f}" if resources_available else "",
                "postgres_cpu_average_percent": f"{median(group, 'postgres_cpu_average_percent'):.3f}" if resources_available else "",
                "rps_gain_vs_50_percent": f"{gain_baseline:.3f}",
                "linear_scaling_efficiency_percent": f"{linear_efficiency:.3f}",
                "rps_gain_vs_previous_percent": f"{gain_previous:.3f}",
                "p95_change_vs_previous_percent": f"{p95_change:.3f}",
                "measurement_rps_change_percent": f"{measurement_change:.3f}",
                "measurement_stability_status": trend_status,
                "result_confidence": confidence,
                "capacity_status": status,
            })
            previous_rps, previous_p95 = rps, p95
    return sorted(output, key=lambda row: (
        LANGUAGE_ORDER.get(row["language"], 99), row["methodology_version"],
        row["result_classification"], row["users"],
    ))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_outputs(
    raw: Path,
    processed: Path,
    summaries: Path,
    classification: str = "official",
) -> tuple[Path, Path, Path, Path]:
    processed.mkdir(parents=True, exist_ok=True)
    summaries.mkdir(parents=True, exist_ok=True)
    runs, endpoints = collect_runs(raw)
    if classification != "all":
        runs = [row for row in runs if row.get("result_classification") == classification]
        endpoints = [row for row in endpoints if row.get("result_classification") == classification]
    runs.sort(key=lambda row: (row["scenario"], LANGUAGE_ORDER.get(row["language"], 99), int(row["run"])))
    endpoints.sort(key=lambda row: (row["scenario"], LANGUAGE_ORDER.get(row["language"], 99), int(row["run"]), row["endpoint"]))
    scaling = scalability_rows(runs)

    for row in runs:
        requests = row["requests"]
        row["error_rate"] = f"{(row['failures'] / requests) if requests else 0:.6f}"
        for key in (
            "throughput_rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "test_elapsed_seconds",
            "cpu_average_percent", "cpu_max_percent", "memory_average_bytes", "memory_max_bytes",
            "network_rx_delta_bytes", "network_tx_delta_bytes", "locust_cpu_average_percent",
            "locust_cpu_max_percent", "postgres_cpu_average_percent", "postgres_cpu_max_percent",
            "postgres_connections_average", "postgres_connections_max", "postgres_commits_total",
            "postgres_rollbacks_total", "postgres_commits_per_second", "postgres_rollbacks_per_second",
            "postgres_blocks_read_total", "postgres_blocks_hit_total", "postgres_cache_hit_ratio",
            "postgres_database_size_average_bytes", "postgres_database_size_max_bytes",
            "measurement_first_window_rps", "measurement_last_window_rps",
            "measurement_rps_change_percent", "measurement_final_window_drift_percent",
        ):
            row[key] = "" if row[key] in (None, "") else f"{number(row[key]):.3f}"

    for row in endpoints:
        for key in (
            "avg_ms", "p50_ms", "p95_ms", "p99_ms", "throughput_rps", "test_elapsed_seconds",
            "cpu_average_percent", "cpu_max_percent", "memory_average_bytes", "memory_max_bytes",
            "locust_cpu_average_percent", "postgres_cpu_average_percent",
            "postgres_connections_average", "postgres_cache_hit_ratio",
        ):
            row[key] = "" if row[key] in (None, "") else f"{number(row[key]):.3f}"

    endpoint_path = processed / "summary_by_endpoint.csv"
    language_path = processed / "summary_by_language.csv"
    scalability_path = processed / "summary_scalability.csv"
    write_csv(endpoint_path, endpoints, ENDPOINT_FIELDS)
    write_csv(language_path, runs, LANGUAGE_FIELDS)
    write_csv(scalability_path, scaling, SCALABILITY_FIELDS)

    final_summary = summaries / "final_summary.md"
    with final_summary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Resumo final\n\n")
        if not runs:
            requested = "qualquer classificacao" if classification == "all" else f"classificacao `{classification}`"
            handle.write(f"Nenhuma rodada com {requested} foi encontrada no diretorio de resultados informado.\n\n")
            handle.write("Os CSVs foram gerados sem linhas de dados e contem somente o cabecalho metodologico atual. ")
            handle.write("Resultados `legacy`, `non_official` e de verificacao nao foram promovidos para resultados oficiais.\n")
        else:
            handle.write(f"- Classificacao consolidada: `{classification}`\n")
            handle.write(f"- Rodadas consolidadas: {len(runs)}\n")
            handle.write(f"- Rodadas com duracao util: {sum(number(row['test_elapsed_seconds']) > 0 for row in runs)}/{len(runs)}\n")
            handle.write("- O cenario de 50 usuarios mede carga controlada, nao capacidade maxima.\n")
            handle.write(f"- Arquivo por linguagem: `{language_path}`\n")
            handle.write(f"- Arquivo por endpoint: `{endpoint_path}`\n")
            handle.write(f"- Arquivo de escalabilidade: `{scalability_path}`\n\n")
            if scaling:
                handle.write("## Escalabilidade\n\n")
                handle.write("| Linguagem | Usuarios | Rodadas | RPS mediano [min-max] | P95 (ms) | Tempo (s) | Estabilidade | Confianca |\n")
                handle.write("|---|---:|---:|---:|---:|---:|---|---|\n")
                for row in scaling:
                    handle.write(
                        f"| {row['language']} | {row['users']} | {row['runs']} | {row['throughput_rps']} "
                        f"[{row['throughput_min_rps']}-{row['throughput_max_rps']}] | "
                        f"{row['p95_ms']} | {row['test_elapsed_seconds']} | "
                        f"{row['measurement_stability_status']} | {row['result_confidence']} |\n"
                    )
    return language_path, endpoint_path, scalability_path, final_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate benchmark artifacts without mixing methodologies.")
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument("--processed", type=Path, default=PROCESSED)
    parser.add_argument("--summaries", type=Path, default=SUMMARIES)
    parser.add_argument(
        "--classification",
        choices=("official", "non_official", "legacy", "all"),
        default="official",
        help="Classification to publish; final TCC artifacts default to official only.",
    )
    args = parser.parse_args()
    paths = generate_outputs(args.raw, args.processed, args.summaries, args.classification)
    for path in paths:
        print(f"Generated {path}")


if __name__ == "__main__":
    main()
