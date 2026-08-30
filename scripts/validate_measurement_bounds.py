#!/usr/bin/env python3
"""Validate Locust measurement boundaries and monotonic duration."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path


def validate_bounds(bounds: dict) -> dict:
    reasons: list[str] = []

    def finite_number(name: str) -> float:
        try:
            value = float(bounds.get(name))
        except (TypeError, ValueError):
            reasons.append(f"{name} is missing or not numeric")
            return 0.0
        if not math.isfinite(value):
            reasons.append(f"{name} is not finite")
            return 0.0
        return value

    started = finite_number("started_epoch")
    finished = finite_number("finished_epoch")
    elapsed = finite_number("elapsed_seconds")
    wall_elapsed = finite_number("wall_elapsed_seconds")
    if finished <= started:
        reasons.append("finished_epoch must be greater than started_epoch")
    if elapsed <= 0:
        reasons.append("elapsed_seconds must be positive")
    if bounds.get("duration_clock") != "time.monotonic_ns":
        reasons.append("duration_clock must be time.monotonic_ns")
    if bounds.get("boundary_clock") != "time.time_ns":
        reasons.append("boundary_clock must be time.time_ns")
    for timestamp_name, epoch in (("started_at_utc", started), ("finished_at_utc", finished)):
        raw_timestamp = bounds.get(timestamp_name)
        try:
            parsed = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone is missing")
            parsed_epoch = parsed.astimezone(timezone.utc).timestamp()
            if abs(parsed_epoch - epoch) > 0.000002:
                reasons.append(f"{timestamp_name} does not match its epoch boundary")
        except (TypeError, ValueError):
            reasons.append(f"{timestamp_name} is missing or invalid")

    observed_wall_elapsed = finished - started if finished > started else 0.0
    tolerance = max(0.5, elapsed * 0.005)
    drift = wall_elapsed - elapsed
    if abs(observed_wall_elapsed - wall_elapsed) > 0.001:
        reasons.append("wall_elapsed_seconds does not match epoch boundaries")
    if abs(drift) > tolerance:
        reasons.append(
            f"wall/monotonic clock drift {drift:.6f}s exceeds tolerance {tolerance:.6f}s"
        )

    return {
        "schema_version": 1,
        "valid": not reasons,
        "reasons": reasons,
        "elapsed_seconds": elapsed,
        "wall_elapsed_seconds": wall_elapsed,
        "clock_drift_seconds": drift,
        "clock_drift_tolerance_seconds": tolerance,
        "duration_source": "time.monotonic_ns",
        "prometheus_boundary_source": "time.time_ns",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounds", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        bounds = json.loads(args.bounds.read_text(encoding="utf-8-sig"))
        report = validate_bounds(bounds)
    except (OSError, json.JSONDecodeError) as exc:
        report = {"schema_version": 1, "valid": False, "reasons": [str(exc)]}
    serialized = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8", newline="\n")
    else:
        print(serialized, end="")
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
