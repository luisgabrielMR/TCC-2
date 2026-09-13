"""Deterministic workload selection shared by Locust and the protocol manifest."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from pathlib import Path
from typing import Any


SELECTION_MODE = "deterministic_smooth_weighted_cycle_v1"


def initial_user_phase(index: int, worker: int, workers: int, users: int, period: float,
                       local_users: int | None = None) -> float:
    """Spread forked workers' user slots across a pacing period, without randomness."""
    if users < 1 or workers < 1 or not 0 <= worker < workers or index < 0:
        raise ValueError("Invalid user/worker slot")
    if not math.isfinite(period) or period < 0:
        raise ValueError("Invalid pacing period")
    population = local_users if local_users is not None else users // workers + (worker < users % workers)
    if population < 1 or index >= population:
        raise ValueError("More users spawned than the configured population")
    return period * (worker + (index + 0.5) / population) / workers


def load_scenario(config_path: Path, requested_scenario: str) -> tuple[str, list[dict[str, Any]]]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    workload_scenario = config.get("aliases", {}).get(requested_scenario, requested_scenario)
    actions = config.get("scenarios", {}).get(workload_scenario)
    if not actions:
        raise ValueError(f"Unknown workload scenario: {requested_scenario}")
    return workload_scenario, actions


def static_workload_manifest(
    selection: str, workload_scenario: str, actions: list[dict[str, Any]]
) -> dict[str, Any]:
    normalized = [
        {"action": item["action"], "endpoint": item["endpoint"], "weight": item["weight"]}
        for item in actions
    ]
    payload = {
        "selection": selection,
        "workload_scenario": workload_scenario,
        "actions": normalized,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return {
        **payload,
        "cycle_length": len(normalized),
        "cycle_sha256": hashlib.sha256(canonical).hexdigest(),
    }


class DeterministicActionSchedule:
    """Cycles through the configured weighted actions without runtime randomness."""

    def __init__(self, workload_scenario: str, actions: list[dict[str, Any]]) -> None:
        if not actions:
            raise ValueError("A workload requires at least one action")
        normalized: list[dict[str, Any]] = []
        weights: list[int] = []
        for item in actions:
            action = item.get("action")
            endpoint = item.get("endpoint")
            weight = item.get("weight")
            if not isinstance(action, str) or not action:
                raise ValueError("Each workload action requires a non-empty action name")
            if not isinstance(endpoint, str) or not endpoint:
                raise ValueError("Each workload action requires a non-empty endpoint name")
            if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
                raise ValueError("Each workload action requires a positive integer weight")
            normalized.append({"action": action, "endpoint": endpoint, "weight": weight})
            weights.append(weight)

        divisor = math.gcd(*weights)
        if len({item["action"] for item in normalized}) != len(normalized):
            raise ValueError("Workload action names must be unique")
        # Smooth weighted round robin avoids grouping all writes in a single burst.
        reduced = [weight // divisor for weight in weights]
        total = sum(reduced)
        current = [0] * len(reduced)
        cycle = []
        for _ in range(total):
            current = [value + weight for value, weight in zip(current, reduced)]
            selected = max(range(len(current)), key=current.__getitem__)
            current[selected] -= total
            cycle.append(normalized[selected]["action"])
        payload = {
            "selection": SELECTION_MODE,
            "workload_scenario": workload_scenario,
            "actions": normalized,
            "cycle": cycle,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

        self._cycle = tuple(cycle)
        self._index = 0
        self._lock = threading.Lock()
        self._manifest = {
            "selection": SELECTION_MODE,
            "workload_scenario": workload_scenario,
            "actions": normalized,
            "cycle_length": len(self._cycle),
            "cycle_sha256": hashlib.sha256(canonical).hexdigest(),
        }

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    def configure_worker_offset(self, worker_index: int, worker_count: int) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be positive")
        if worker_index < 0 or worker_index >= worker_count:
            raise ValueError("worker_index must identify a configured worker")
        with self._lock:
            self._index = (worker_index * len(self._cycle)) // worker_count

    def next_action(self) -> str:
        with self._lock:
            action = self._cycle[self._index % len(self._cycle)]
            self._index += 1
            return action
