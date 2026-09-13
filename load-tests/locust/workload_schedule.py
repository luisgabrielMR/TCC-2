"""Seeded workload selection shared by Locust and the protocol manifest."""

from __future__ import annotations

import hashlib
import json
import math
import random
import threading
from pathlib import Path
from typing import Any


DEFAULT_SCHEDULE_SEED = 20260913
SELECTION_MODE = "seeded_shuffled_weighted_cycle_v1"
WORKER_STREAM_SEED_DERIVATION = "sha256(base_seed:workload_scenario:worker_index)_first_16_bytes"


def schedule_seed(raw: int | str = DEFAULT_SCHEDULE_SEED) -> int:
    """Return a positive, explicit seed accepted by both the runner and Locust."""
    if isinstance(raw, bool):
        raise ValueError("WORKLOAD_SCHEDULE_SEED must be a positive integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("WORKLOAD_SCHEDULE_SEED must be a positive integer") from exc
    if value <= 0 or str(raw).strip() not in {str(value), f"+{value}"}:
        raise ValueError("WORKLOAD_SCHEDULE_SEED must be a positive integer")
    return value


def worker_stream_seed(base_seed: int, workload_scenario: str, worker_index: int) -> int:
    """Derive one reproducible random stream per Locust worker."""
    if worker_index < 0:
        raise ValueError("worker_index must be non-negative")
    material = f"{base_seed}:{workload_scenario}:{worker_index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:16], "big")


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
    """Shuffle exact weighted cycles with independent, reproducible worker streams."""

    def __init__(
        self,
        workload_scenario: str,
        actions: list[dict[str, Any]],
        seed: int | str = DEFAULT_SCHEDULE_SEED,
    ) -> None:
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

        if len({item["action"] for item in normalized}) != len(normalized):
            raise ValueError("Workload action names must be unique")
        self._base_seed = schedule_seed(seed)
        self._workload_scenario = workload_scenario
        self._weighted_actions = tuple(
            item["action"] for item in normalized for _ in range(item["weight"])
        )
        payload = {
            "selection": SELECTION_MODE,
            "workload_scenario": workload_scenario,
            "actions": normalized,
            "schedule_seed": self._base_seed,
            "worker_stream_seed_derivation": WORKER_STREAM_SEED_DERIVATION,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

        self._cycle: tuple[str, ...] = ()
        self._index = 0
        self._rng: random.Random | None = None
        self._lock = threading.Lock()
        self._manifest = {
            "selection": SELECTION_MODE,
            "workload_scenario": workload_scenario,
            "actions": normalized,
            "cycle_length": len(self._weighted_actions),
            "schedule_seed": self._base_seed,
            "worker_stream_seed_derivation": WORKER_STREAM_SEED_DERIVATION,
            "schedule_sha256": hashlib.sha256(canonical).hexdigest(),
        }
        self.configure_worker_stream(0, 1)

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)

    def configure_worker_stream(self, worker_index: int, worker_count: int) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be positive")
        if worker_index < 0 or worker_index >= worker_count:
            raise ValueError("worker_index must identify a configured worker")
        with self._lock:
            self._rng = random.Random(worker_stream_seed(
                self._base_seed, self._workload_scenario, worker_index
            ))
            self._cycle = ()
            self._index = 0

    def _next_cycle_locked(self) -> None:
        if self._rng is None:
            raise RuntimeError("Worker stream was not configured")
        cycle = list(self._weighted_actions)
        # random.Random.shuffle implements Fisher-Yates; every position receives
        # every weighted action with the same probability, while each full cycle
        # still contains the configured number of each action exactly.
        self._rng.shuffle(cycle)
        self._cycle = tuple(cycle)
        self._index = 0

    def next_action(self) -> str:
        with self._lock:
            if self._index >= len(self._cycle):
                self._next_cycle_locked()
            action = self._cycle[self._index]
            self._index += 1
            return action
