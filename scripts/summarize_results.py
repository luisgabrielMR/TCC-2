#!/usr/bin/env python3
"""Summarize Locust CSV files into processed benchmark tables."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
PROCESSED = ROOT / "results" / "processed"
SUMMARIES = ROOT / "results" / "summaries"


def read_locust_rows():
    for stats_file in RAW.glob("*/*/run_*/locust_stats.csv"):
        parts = stats_file.relative_to(RAW).parts
        language, scenario, run_dir = parts[0], parts[1], parts[2]
        run_number = run_dir.replace("run_", "")
        with stats_file.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("Name") == "Aggregated":
                    continue
                yield language, scenario, run_number, stats_file.parent, row


def read_api_resources(language: str, run_directory: Path) -> dict[str, str]:
    summary = run_directory / "docker_stats_summary.csv"
    if not summary.exists():
        return {}
    expected = f"tcc_benchmark_{language}_api"
    with summary.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("container_name") == expected:
                return row
    return {}


def read_locust_aggregate(run_directory: Path) -> dict[str, str]:
    with (run_directory / "locust_stats.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("Name") == "Aggregated":
                return row
    return {}


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    SUMMARIES.mkdir(parents=True, exist_ok=True)

    endpoint_rows = []
    language_totals = {}

    for language, scenario, run_number, run_directory, row in read_locust_rows():
        endpoint = row.get("Name", "")
        method = row.get("Type", "")
        requests = int(float(row.get("Request Count", "0") or 0))
        failures = int(float(row.get("Failure Count", "0") or 0))
        p50 = row.get("50%", "")
        p95 = row.get("95%", "")
        p99 = row.get("99%", "")
        avg = row.get("Average Response Time", "")
        rps = row.get("Requests/s", "")

        endpoint_rows.append({
            "language": language,
            "scenario": scenario,
            "run": run_number,
            "method": method,
            "endpoint": endpoint,
            "requests": requests,
            "failures": failures,
            "avg_ms": avg,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "throughput_rps": rps,
        })

        key = (language, scenario, run_number)
        if key not in language_totals:
            aggregate = read_locust_aggregate(run_directory)
            language_totals[key] = {
                "requests": int(float(aggregate.get("Request Count", "0") or 0)),
                "failures": int(float(aggregate.get("Failure Count", "0") or 0)),
                "rps": float(aggregate.get("Requests/s", "0") or 0),
                "resources": read_api_resources(language, run_directory),
            }

    endpoint_path = PROCESSED / "summary_by_endpoint.csv"
    with endpoint_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "language",
            "scenario",
            "run",
            "method",
            "endpoint",
            "requests",
            "failures",
            "avg_ms",
            "p50_ms",
            "p95_ms",
            "p99_ms",
            "throughput_rps",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(endpoint_rows)

    language_path = PROCESSED / "summary_by_language.csv"
    with language_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "language", "scenario", "run", "requests", "failures", "error_rate", "throughput_rps",
            "cpu_average_percent", "cpu_max_percent", "memory_average_bytes", "memory_max_bytes",
            "network_rx_delta_bytes", "network_tx_delta_bytes",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for (language, scenario, run_number), total in sorted(language_totals.items()):
            requests = total["requests"]
            failures = total["failures"]
            resources = total["resources"]
            writer.writerow({
                "language": language,
                "scenario": scenario,
                "run": run_number,
                "requests": requests,
                "failures": failures,
                "error_rate": f"{(failures / requests) if requests else 0:.6f}",
                "throughput_rps": f"{total['rps']:.3f}",
                "cpu_average_percent": resources.get("cpu_average_percent", ""),
                "cpu_max_percent": resources.get("cpu_max_percent", ""),
                "memory_average_bytes": resources.get("memory_average_bytes", ""),
                "memory_max_bytes": resources.get("memory_max_bytes", ""),
                "network_rx_delta_bytes": resources.get("network_rx_delta_bytes", ""),
                "network_tx_delta_bytes": resources.get("network_tx_delta_bytes", ""),
            })

    final_summary = SUMMARIES / "final_summary.md"
    with final_summary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Resumo final\n\n")
        if not endpoint_rows:
            handle.write("Nenhum arquivo `locust_stats.csv` foi encontrado em `results/raw`.\n")
        else:
            handle.write(f"- Linhas por endpoint: {len(endpoint_rows)}\n")
            handle.write(f"- Rodadas consolidadas: {len(language_totals)}\n")
            measured = sum(1 for total in language_totals.values() if total["resources"])
            handle.write(f"- Rodadas com CPU e memoria: {measured}/{len(language_totals)}\n")
            handle.write(f"- Arquivo por linguagem: `{language_path}`\n")
            handle.write(f"- Arquivo por endpoint: `{endpoint_path}`\n")

    print(f"Generated {language_path}")
    print(f"Generated {endpoint_path}")
    print(f"Generated {final_summary}")


if __name__ == "__main__":
    main()
