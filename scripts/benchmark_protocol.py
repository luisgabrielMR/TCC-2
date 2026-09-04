#!/usr/bin/env python3
"""Build and validate the canonical experimental protocol manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CURRENT_METHODOLOGY = 9
CPU_QUOTAS = {
    "postgres": 1.0,
    "locust": 4.0,
    "python-api": 2.0,
    "node-api": 2.0,
    "java-api": 2.0,
    "go-api": 2.0,
    "dotnet-api": 2.0,
}
PROFILE_OVERRIDES = {
    "fixed_200": (50, 10, 0.25, 200),
    "saturation_25": (25, 25, 0.0, None),
    "saturation_50": (50, 25, 0.0, None),
    "saturation_100": (100, 25, 0.0, None),
    "saturation_200": (200, 40, 0.0, None),
    "saturation_400": (400, 80, 0.0, None),
    "controlled_50": (50, 10, None, None),
    "capacity_100": (100, 20, None, None),
    "capacity_200": (200, 40, None, None),
}
_DURATION = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(ms|s|m|h)?$")


def load_environment() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (ROOT / ".env.example", ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def duration_seconds(raw: str | int | float) -> float:
    match = _DURATION.fullmatch(str(raw).strip().lower())
    if not match:
        raise ValueError(f"Invalid duration: {raw!r}")
    value = float(match.group(1))
    factor = {None: 1.0, "ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}[match.group(2)]
    result = value * factor
    if not math.isfinite(result) or result <= 0:
        raise ValueError("Duration must be finite and positive")
    return result


def _number(values: dict[str, str], key: str, default: str, cast: type = float) -> Any:
    value = cast(values.get(key, default))
    if isinstance(value, (int, float)) and (not math.isfinite(value) or value <= 0):
        raise ValueError(f"{key} must be finite and positive")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def _compose_digest() -> str:
    command = ["docker", "compose"]
    for profile in ("python", "node", "java", "go", "dotnet", "load", "monitoring"):
        command.extend(("--profile", profile))
    command.extend(("config", "--format", "json"))
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, check=False, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Cannot read effective Docker Compose configuration: {exc}") from exc
    if completed.returncode:
        raise RuntimeError(
            "Cannot read effective Docker Compose configuration: "
            + completed.stderr.decode(errors="replace").strip()
        )
    return hashlib.sha256(completed.stdout).hexdigest()


def build_protocol(load_profile: str, scenario: str, values: dict[str, str] | None = None) -> dict[str, Any]:
    environment = values or load_environment()
    host_override = environment.get("LOCUST_HOST_OVERRIDE", "").strip()
    methodology = int(environment.get("METHODOLOGY_VERSION", str(CURRENT_METHODOLOGY)))
    users = _number(environment, "LOCUST_USERS", "50", int)
    spawn_rate = _number(environment, "LOCUST_SPAWN_RATE", "10", int)
    wait_seconds = float(environment.get("LOCUST_WAIT_SECONDS", "0.1"))
    target_rps = None
    if load_profile in PROFILE_OVERRIDES:
        users, spawn_rate, profile_wait, target_rps = PROFILE_OVERRIDES[load_profile]
        if profile_wait is not None:
            wait_seconds = profile_wait
    elif load_profile != "environment":
        raise ValueError(f"Unknown load profile: {load_profile}")
    if not math.isfinite(wait_seconds) or wait_seconds < 0:
        raise ValueError("LOCUST_WAIT_SECONDS must be finite and non-negative")

    calibration_path = ROOT / environment.get(
        "LOAD_GENERATOR_CALIBRATION_FILE", "results/summaries/load-generator-calibration.json"
    )
    protocol = {
        "schema_version": 1,
        "methodology_version": methodology,
        "scenario": scenario,
        "load_profile": load_profile,
        "load": {
            "users": users,
            "spawn_rate": spawn_rate,
            "wait_seconds": wait_seconds,
            "measurement_duration_seconds": duration_seconds(environment.get("LOCUST_DURATION", "5m")),
            "processes": _number(environment, "LOCUST_PROCESSES", "4", int),
            "target_rps": target_rps,
            "target": {
                "network_mode": "host_override" if host_override else "docker_internal_compose_service",
                "url_template": host_override or "http://{api-service}:8000",
            },
        },
        "warmup": {
            "duration_seconds": _number(environment, "WARMUP_DURATION_SECONDS", "300", int),
            "users": users,
            "spawn_rate": spawn_rate,
            "stability_window_seconds": _number(environment, "WARMUP_STABILITY_WINDOW_SECONDS", "45", int),
            "max_rps_drift_percent": _number(environment, "WARMUP_MAX_RPS_DRIFT_PERCENT", "10"),
        },
        "database_pool": {
            "min": _number(environment, "DB_POOL_MIN", "1", int),
            "max": _number(environment, "DB_POOL_MAX", "20", int),
            "acquire_timeout_seconds": _number(environment, "DB_POOL_ACQUIRE_TIMEOUT_SECONDS", "10", int),
            "idle_timeout_seconds": _number(environment, "DB_POOL_IDLE_TIMEOUT_SECONDS", "60", int),
            "max_lifetime_seconds": _number(environment, "DB_POOL_MAX_LIFETIME_SECONDS", "1800", int),
        },
        "resource_cpu_quotas": CPU_QUOTAS,
        "metrics": {
            "collector_interval_seconds": _number(environment, "METRICS_SAMPLE_INTERVAL_SECONDS", "2"),
            "prometheus_scrape_interval_seconds": 5,
            "cadvisor_housekeeping_interval_seconds": 1,
        },
        "execution": {
            "official_rounds": _number(environment, "OFFICIAL_ROUNDS", "5", int),
            "language_order_base": ["python", "node", "java", "go", "dotnet"],
            "language_order_rotation": "round_minus_one_modulo_language_count",
            "stop_timeout_seconds": 5,
            "duration_tolerance_seconds": 0.25,
            "window_start_event": "spawning_complete_after_stats_reset",
            "window_end_event": "last_worker_stop_received_before_bounded_drain",
            "drained_request_rule": "started_before_worker_stop_boundary",
        },
        "compose_config_sha256": _compose_digest(),
        "calibration_sha256": _sha256(calibration_path),
    }
    canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    protocol_hash = hashlib.sha256(canonical).hexdigest()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "protocol": protocol,
        "protocol_sha256": protocol_hash,
        "commit_sha": commit,
        "campaign_fingerprint": f"m{methodology}_{commit[:12]}_{protocol_hash[:12]}",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--load-profile", default="environment")
    parser.add_argument("--scenario", default="mixed")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--assert-sha256")
    args = parser.parse_args()
    try:
        manifest = build_protocol(args.load_profile, args.scenario)
        if args.assert_sha256 and manifest["protocol_sha256"] != args.assert_sha256:
            raise RuntimeError(
                f"Protocol changed: expected {args.assert_sha256}, got {manifest['protocol_sha256']}"
            )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    serialized = json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8", newline="\n")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
