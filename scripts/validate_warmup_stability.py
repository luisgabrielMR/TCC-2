#!/usr/bin/env python3
"""Validate warmup coverage, failures and throughput stability."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / "load-tests" / "locust" / "config" / "scenarios.json"


def number(value: str | None) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def data_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _row in csv.DictReader(handle))


def load_expected_endpoints(config_path: Path, scenario: str) -> list[str]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    workload = config.get("aliases", {}).get(scenario, scenario)
    entries = config.get("scenarios", {}).get(workload)
    if not entries:
        raise ValueError(f"Unknown scenario: {scenario}")
    return [entry["endpoint"] for entry in entries]


def load_stats(path: Path) -> tuple[dict[str, int], int]:
    endpoints: dict[str, int] = {}
    total_failures = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row.get("Name", "")
            if name == "Aggregated":
                total_failures = int(number(row.get("Failure Count")))
            elif name:
                endpoints[name] = int(number(row.get("Request Count")))
    return endpoints, total_failures


def load_history(path: Path) -> list[tuple[int, int, int]]:
    samples: list[tuple[int, int, int]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("Name") != "Aggregated":
                continue
            timestamp = int(number(row.get("Timestamp")))
            requests = int(number(row.get("Total Request Count")))
            users = int(number(row.get("User Count")))
            if timestamp:
                samples.append((timestamp, requests, users))
    return sorted(set(samples))


def at_or_before(samples: list[tuple[int, int, int]], target: int) -> tuple[int, int, int]:
    eligible = [sample for sample in samples if sample[0] <= target]
    return eligible[-1] if eligible else samples[0]


def steady_history(samples: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    max_users = max(sample[2] for sample in samples)
    return [sample for sample in samples if sample[2] == max_users]


def throughput_windows(
    samples: list[tuple[int, int, int]], window_seconds: int
) -> tuple[float, float, float, float]:
    if len(samples) < 3:
        raise ValueError("Warmup history does not contain enough aggregate samples")

    samples = steady_history(samples)
    end = samples[-1]
    boundaries = [
        at_or_before(samples, end[0] - (offset * window_seconds))
        for offset in (3, 2, 1)
    ] + [end]
    rates: list[float] = []
    for start, finish in zip(boundaries, boundaries[1:]):
        seconds = finish[0] - start[0]
        if seconds < window_seconds * 0.8:
            raise ValueError("Warmup history is shorter than the three stability windows")
        rates.append((finish[1] - start[1]) / seconds)

    drifts = [
        abs(current - previous) / previous * 100 if previous else 100.0
        for previous, current in zip(rates, rates[1:])
    ]
    return rates[0], rates[1], rates[2], max(drifts)


def first_last_windows(
    samples: list[tuple[int, int, int]], window_seconds: int
) -> tuple[float, float, float, float]:
    if len(samples) < 3:
        raise ValueError("Warmup history does not contain enough aggregate samples")

    samples = steady_history(samples)
    first_start = samples[0]
    first_end = at_or_before(samples, first_start[0] + window_seconds)
    last_end = samples[-1]
    last_start = next(
        (sample for sample in samples if sample[0] >= last_end[0] - window_seconds),
        samples[0],
    )
    first_seconds = first_end[0] - first_start[0]
    last_seconds = last_end[0] - last_start[0]
    total_seconds = last_end[0] - first_start[0]
    if (
        first_seconds < window_seconds * 0.8
        or last_seconds < window_seconds * 0.8
        or total_seconds < window_seconds * 2
    ):
        raise ValueError("Warmup history is too short for first-to-last stability windows")

    first_rps = (first_end[1] - first_start[1]) / first_seconds
    last_rps = (last_end[1] - last_start[1]) / last_seconds
    change = (last_rps / first_rps - 1) * 100 if first_rps else 100.0
    return first_rps, last_rps, abs(change), change


def validate(
    stats_path: Path,
    history_path: Path,
    scenario: str,
    config_path: Path,
    window_seconds: int,
    max_drift_percent: float,
    expected_users: int = 0,
    require_first_last_stability: bool = False,
) -> dict:
    endpoints, failures = load_stats(stats_path)
    expected = load_expected_endpoints(config_path, scenario)
    missing = [endpoint for endpoint in expected if endpoints.get(endpoint, 0) <= 0]
    exceptions_path = stats_path.with_name(stats_path.name.replace("_stats.csv", "_exceptions.csv"))
    exceptions = data_row_count(exceptions_path)

    reasons: list[str] = []
    history = load_history(history_path)
    observed_peak_users = max((sample[2] for sample in history), default=0)
    if expected_users > 0 and observed_peak_users != expected_users:
        reasons.append(
            f"peak user count {observed_peak_users} does not match expected {expected_users}"
        )
    try:
        earliest_rps, previous_rps, recent_rps, drift = throughput_windows(history, window_seconds)
    except ValueError as exc:
        earliest_rps, previous_rps, recent_rps, drift = 0.0, 0.0, 0.0, 100.0
        reasons.append(str(exc))
    try:
        first_rps, last_rps, first_last_drift, first_last_change = first_last_windows(
            history, window_seconds
        )
    except ValueError as exc:
        first_rps, last_rps, first_last_drift, first_last_change = 0.0, 0.0, 100.0, 100.0
        reasons.append(str(exc))

    if failures:
        reasons.append(f"{failures} HTTP failures")
    if exceptions:
        reasons.append(f"{exceptions} Locust task exceptions")
    if missing:
        reasons.append(f"endpoints without requests: {', '.join(missing)}")
    if drift > max_drift_percent:
        reasons.append(f"final-window RPS drift {drift:.2f}% exceeds {max_drift_percent:.2f}%")
    if require_first_last_stability and first_last_drift > max_drift_percent:
        reasons.append(
            f"first-to-last RPS drift {first_last_drift:.2f}% exceeds "
            f"{max_drift_percent:.2f}% during measurement"
        )

    return {
        "stable": not reasons,
        "scenario": scenario,
        "expected_users": expected_users,
        "observed_peak_users": observed_peak_users,
        "window_seconds": window_seconds,
        "max_rps_drift_percent": max_drift_percent,
        "first_last_stability_required": require_first_last_stability,
        "earliest_stability_window_rps": round(earliest_rps, 3),
        "previous_window_rps": round(previous_rps, 3),
        "recent_window_rps": round(recent_rps, 3),
        "rps_drift_percent": round(drift, 3),
        "first_window_rps": round(first_rps, 3),
        "last_window_rps": round(last_rps, 3),
        "first_last_rps_drift_percent": round(first_last_drift, 3),
        "first_last_rps_change_percent": round(first_last_change, 3),
        "http_failures": failures,
        "task_exceptions": exceptions,
        "endpoint_requests": endpoints,
        "missing_endpoints": missing,
        "reasons": reasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--scenario", default="mixed")
    parser.add_argument("--scenario-config", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--window-seconds", type=int, default=45)
    parser.add_argument("--max-rps-drift-percent", type=float, default=10.0)
    parser.add_argument("--expected-users", type=int, default=0)
    parser.add_argument("--require-first-last-stability", action="store_true")
    parser.add_argument("--phase-label", default="Warmup")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = validate(
        args.stats,
        args.history,
        args.scenario,
        args.scenario_config,
        args.window_seconds,
        args.max_rps_drift_percent,
        args.expected_users,
        args.require_first_last_stability,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    status = "stable" if result["stable"] else "unstable"
    print(
        f"{args.phase_label} {status}: final_drift={result['rps_drift_percent']:.2f}% "
        f"first_last_drift={result['first_last_rps_drift_percent']:.2f}% "
        f"failures={result['http_failures']} exceptions={result['task_exceptions']}"
    )


if __name__ == "__main__":
    main()
