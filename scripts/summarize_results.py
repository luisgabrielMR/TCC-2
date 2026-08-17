#!/usr/bin/env python3
"""Summarize benchmark runs, resources, duration and scalability."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
PROCESSED = ROOT / "results" / "processed"
SUMMARIES = ROOT / "results" / "summaries"
LANGUAGE_ORDER = {name: index for index, name in enumerate(("python", "node", "java", "go", "dotnet"))}


def number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def median(rows: list[dict], key: str) -> float:
    values = [number(row.get(key)) for row in rows if row.get(key) not in (None, "")]
    return statistics.median(values) if values else 0.0


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


def read_resource_rows(run_directory: Path) -> list[dict[str, str]]:
    path = run_directory / "docker_stats_summary.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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


def collect_runs() -> tuple[list[dict], list[dict]]:
    runs: list[dict] = []
    endpoint_rows: list[dict] = []
    for stats_file in RAW.glob("*/*/run_*/locust_stats.csv"):
        language, scenario, run_dir = stats_file.relative_to(RAW).parts[:3]
        run_number = run_dir.removeprefix("run_")
        with stats_file.open("r", encoding="utf-8-sig", newline="") as handle:
            stats = list(csv.DictReader(handle))
        aggregate = next((row for row in stats if row.get("Name") == "Aggregated"), None)
        if aggregate is None:
            continue

        run_directory = stats_file.parent
        metadata = read_json(run_directory / "metadata.json")
        resources = read_resource_rows(run_directory)
        api = find_resource(resources, lambda name: name == f"tcc_benchmark_{language}_api")
        locust = find_resource(resources, lambda name: "locust-run-" in name or name == "tcc_benchmark_locust")
        postgres = find_resource(resources, lambda name: name == "tcc_benchmark_postgres")
        elapsed, duration_source = duration_from_metadata(metadata)
        locust_meta = metadata.get("locust", {})
        measurement = metadata.get("measurement_stability", {})
        measurement_available = bool(measurement)
        measurement_change = number(measurement.get("first_last_rps_change_percent"))
        final_windows_stable = bool(measurement.get("stable")) if measurement_available else False

        run = {
            "language": language,
            "scenario": scenario,
            "run": run_number,
            "load_profile": metadata.get("load_profile", "legacy"),
            "methodology_version": int(number(metadata.get("methodology_version"), 1)),
            "benchmark_kind": metadata.get("benchmark_kind", "controlled_load"),
            "users": int(number(locust_meta.get("users"))),
            "spawn_rate": int(number(locust_meta.get("spawn_rate"))),
            "configured_duration": locust_meta.get("duration", ""),
            "wait_seconds": number(locust_meta.get("wait_seconds"), 0.1),
            "test_elapsed_seconds": elapsed,
            "duration_source": duration_source,
            "requests": int(number(aggregate.get("Request Count"))),
            "failures": int(number(aggregate.get("Failure Count"))),
            "avg_ms": number(aggregate.get("Average Response Time")),
            "p50_ms": number(aggregate.get("50%")),
            "p95_ms": number(aggregate.get("95%")),
            "p99_ms": number(aggregate.get("99%")),
            "throughput_rps": number(aggregate.get("Requests/s")),
            "cpu_average_percent": number(api.get("cpu_average_percent")),
            "cpu_max_percent": number(api.get("cpu_max_percent")),
            "memory_average_bytes": number(api.get("memory_average_bytes")),
            "memory_max_bytes": number(api.get("memory_max_bytes")),
            "network_rx_delta_bytes": number(api.get("network_rx_delta_bytes")),
            "network_tx_delta_bytes": number(api.get("network_tx_delta_bytes")),
            "locust_cpu_average_percent": number(locust.get("cpu_average_percent")),
            "locust_cpu_max_percent": number(locust.get("cpu_max_percent")),
            "postgres_cpu_average_percent": number(postgres.get("cpu_average_percent")),
            "postgres_cpu_max_percent": number(postgres.get("cpu_max_percent")),
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
                "users": run["users"],
                "method": row.get("Type", ""),
                "endpoint": row.get("Name", ""),
                "requests": int(number(row.get("Request Count"))),
                "failures": int(number(row.get("Failure Count"))),
                "avg_ms": row.get("Average Response Time", ""),
                "p50_ms": row.get("50%", ""),
                "p95_ms": row.get("95%", ""),
                "p99_ms": row.get("99%", ""),
                "throughput_rps": row.get("Requests/s", ""),
            })
    return runs, endpoint_rows


def scalability_rows(runs: list[dict]) -> list[dict]:
    mixed = [row for row in runs if row["scenario"] == "mixed" or row["scenario"].startswith("mixed_capacity_")]
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in mixed:
        if row["users"] > 0:
            groups[(row["language"], int(row["users"]))].append(row)

    groups = {key: comparable_rows(group) for key, group in groups.items()}

    output: list[dict] = []
    by_language: dict[str, list[tuple[int, list[dict]]]] = defaultdict(list)
    for (language, users), group in groups.items():
        by_language[language].append((users, group))

    for language, levels in by_language.items():
        levels.sort(key=lambda item: item[0])
        baseline_group = next((group for users, group in levels if users == 50), levels[0][1])
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

            if users == baseline_users:
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
                "users": users,
                "runs": len(group),
                "throughput_rps": f"{rps:.3f}",
                "p95_ms": f"{p95:.3f}",
                "error_rate": f"{(failures / requests) if requests else 0:.6f}",
                "test_elapsed_seconds": f"{median(group, 'test_elapsed_seconds'):.3f}",
                "api_cpu_average_percent": f"{median(group, 'cpu_average_percent'):.3f}",
                "locust_cpu_average_percent": f"{locust_cpu:.3f}",
                "postgres_cpu_average_percent": f"{median(group, 'postgres_cpu_average_percent'):.3f}",
                "rps_gain_vs_50_percent": f"{gain_baseline:.3f}",
                "linear_scaling_efficiency_percent": f"{linear_efficiency:.3f}",
                "rps_gain_vs_previous_percent": f"{gain_previous:.3f}",
                "p95_change_vs_previous_percent": f"{p95_change:.3f}",
                "measurement_rps_change_percent": f"{measurement_change:.3f}",
                "measurement_stability_status": trend_status,
                "capacity_status": status,
            })
            previous_rps, previous_p95 = rps, p95
    return sorted(output, key=lambda row: (LANGUAGE_ORDER.get(row["language"], 99), row["users"]))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    SUMMARIES.mkdir(parents=True, exist_ok=True)
    runs, endpoints = collect_runs()
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
            "measurement_first_window_rps", "measurement_last_window_rps",
            "measurement_rps_change_percent", "measurement_final_window_drift_percent",
        ):
            row[key] = f"{number(row[key]):.3f}"

    endpoint_path = PROCESSED / "summary_by_endpoint.csv"
    endpoint_fields = [
        "language", "scenario", "run", "users", "method", "endpoint", "requests", "failures",
        "avg_ms", "p50_ms", "p95_ms", "p99_ms", "throughput_rps",
    ]
    write_csv(endpoint_path, endpoints, endpoint_fields)

    language_path = PROCESSED / "summary_by_language.csv"
    language_fields = [
        "language", "scenario", "run", "load_profile", "methodology_version", "benchmark_kind", "users", "spawn_rate",
        "configured_duration", "wait_seconds", "test_elapsed_seconds", "duration_source", "requests",
        "failures", "error_rate", "throughput_rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms",
        "cpu_average_percent", "cpu_max_percent", "memory_average_bytes", "memory_max_bytes",
        "network_rx_delta_bytes", "network_tx_delta_bytes", "locust_cpu_average_percent",
        "locust_cpu_max_percent", "postgres_cpu_average_percent", "postgres_cpu_max_percent",
        "measurement_first_window_rps", "measurement_last_window_rps",
        "measurement_rps_change_percent", "measurement_final_window_drift_percent",
        "measurement_final_windows_stable", "measurement_stability_status",
    ]
    write_csv(language_path, runs, language_fields)

    scalability_path = PROCESSED / "summary_scalability.csv"
    scalability_fields = [
        "language", "scenario", "users", "runs", "throughput_rps", "p95_ms", "error_rate",
        "test_elapsed_seconds", "api_cpu_average_percent", "locust_cpu_average_percent",
        "postgres_cpu_average_percent", "rps_gain_vs_50_percent", "linear_scaling_efficiency_percent",
        "rps_gain_vs_previous_percent", "p95_change_vs_previous_percent",
        "measurement_rps_change_percent", "measurement_stability_status", "capacity_status",
    ]
    write_csv(scalability_path, scaling, scalability_fields)

    final_summary = SUMMARIES / "final_summary.md"
    with final_summary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Resumo final\n\n")
        if not runs:
            handle.write("Nenhum arquivo `locust_stats.csv` foi encontrado em `results/raw`.\n")
        else:
            handle.write(f"- Rodadas consolidadas: {len(runs)}\n")
            handle.write(f"- Rodadas com duracao util: {sum(number(row['test_elapsed_seconds']) > 0 for row in runs)}/{len(runs)}\n")
            handle.write("- O cenario de 50 usuarios mede carga controlada, nao capacidade maxima.\n")
            handle.write(f"- Arquivo por linguagem: `{language_path}`\n")
            handle.write(f"- Arquivo por endpoint: `{endpoint_path}`\n")
            handle.write(f"- Arquivo de escalabilidade: `{scalability_path}`\n\n")
            if scaling:
                handle.write("## Escalabilidade\n\n")
                handle.write("| Linguagem | Usuarios | RPS | P95 (ms) | Tempo (s) | Tendencia RPS | Estabilidade | Capacidade |\n")
                handle.write("|---|---:|---:|---:|---:|---:|---|---|\n")
                for row in scaling:
                    handle.write(
                        f"| {row['language']} | {row['users']} | {row['throughput_rps']} | "
                        f"{row['p95_ms']} | {row['test_elapsed_seconds']} | "
                        f"{row['measurement_rps_change_percent']}% | "
                        f"{row['measurement_stability_status']} | {row['capacity_status']} |\n"
                    )

    for path in (language_path, endpoint_path, scalability_path, final_summary):
        print(f"Generated {path}")


if __name__ == "__main__":
    main()
