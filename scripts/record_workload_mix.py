#!/usr/bin/env python3
"""Publish the planned and completed endpoint mix for one Locust execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOCUST_ROOT = ROOT / "load-tests" / "locust"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LOCUST_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCUST_ROOT))

from scripts.snapshot_integrity import verified_stats
from workload_schedule import load_scenario, schedule_seed


STATIC_ACTIONS = {
    "health_only": [
        {"action": "get_health", "endpoint": "GET /health", "weight": 1},
    ],
    "smoke": [
        {"action": "get_health", "endpoint": "GET /health", "weight": 1},
        {"action": "get_customer", "endpoint": "GET /customers/{id}", "weight": 1},
        {"action": "list_customers", "endpoint": "GET /customers", "weight": 1},
        {"action": "list_products", "endpoint": "GET /products", "weight": 1},
        {"action": "get_order", "endpoint": "GET /orders/{id}", "weight": 1},
    ],
}


def planned_actions(
    requested_scenario: str, config_path: Path = LOCUST_ROOT / "config" / "scenarios.json"
) -> tuple[str, list[dict[str, Any]]]:
    if requested_scenario in STATIC_ACTIONS:
        return requested_scenario, STATIC_ACTIONS[requested_scenario]
    return load_scenario(config_path, requested_scenario)


def build_workload_mix(
    requested_scenario: str,
    seed: int | str,
    stats: list[dict[str, str]],
    config_path: Path = LOCUST_ROOT / "config" / "scenarios.json",
) -> dict[str, Any]:
    """Convert the validated final CSV rows into endpoint counts and proportions."""
    workload_scenario, actions = planned_actions(requested_scenario, config_path)
    normalized_seed = schedule_seed(seed)
    planned_endpoints = [item["endpoint"] for item in actions]
    if len(set(planned_endpoints)) != len(planned_endpoints):
        raise ValueError("Workload endpoints must be unique")

    observed: dict[str, int] = {}
    aggregate = None
    for row in stats:
        name = row.get("Name", "")
        if name == "Aggregated":
            aggregate = int(row["Request Count"])
        elif name:
            observed[name] = int(row["Request Count"])
    if aggregate is None:
        raise ValueError("Final Locust stats do not contain the Aggregated row")
    unexpected = sorted(set(observed).difference(planned_endpoints))
    if unexpected:
        raise ValueError("Final Locust stats contain endpoints outside the workload: " + ", ".join(unexpected))

    endpoint_counts = [
        {
            "action": item["action"],
            "endpoint": item["endpoint"],
            "planned_weight": item["weight"],
            "completed_requests": observed.get(item["endpoint"], 0),
            "completed_proportion": (
                observed.get(item["endpoint"], 0) / aggregate if aggregate else 0.0
            ),
        }
        for item in actions
    ]
    completed_total = sum(item["completed_requests"] for item in endpoint_counts)
    if completed_total != aggregate:
        raise ValueError("Final Locust endpoint counts do not match the aggregate")
    total_weight = sum(item["weight"] for item in actions)
    reads = [item for item in actions if item["endpoint"].startswith("GET ") and item["endpoint"] != "GET /health"]
    writes = [item for item in actions if item["endpoint"].startswith(("POST ", "PUT ", "PATCH ", "DELETE "))]
    return {
        "schema_version": 1,
        "requested_scenario": requested_scenario,
        "workload_scenario": workload_scenario,
        "schedule_seed": normalized_seed,
        "source": "locust_stats.csv verified by locust_snapshot_validation.json",
        "planned": {
            "actions": actions,
            "total_weight": total_weight,
            "read_operation_count": len(reads),
            "write_operation_count": len(writes),
            "read_weight_proportion": sum(item["weight"] for item in reads) / total_weight,
            "write_weight_proportion": sum(item["weight"] for item in writes) / total_weight,
        },
        "realized": {
            "completed_requests": aggregate,
            "endpoints": endpoint_counts,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--schedule-seed", required=True)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path(f"{args.prefix}_workload_mix.json")
    try:
        artifact = build_workload_mix(args.scenario, args.schedule_seed, verified_stats(args.prefix))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
