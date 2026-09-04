#!/usr/bin/env python3
"""Validate Locust measurement boundaries and monotonic duration."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path


def validate_bounds(
    bounds: dict,
    expected_duration_seconds: float | None = None,
    duration_tolerance_seconds: float = 0.25,
) -> dict:
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
    if expected_duration_seconds is not None:
        if bounds.get("window_start_event") != "spawning_complete_after_stats_reset":
            reasons.append("measurement window must start after spawning and statistics reset")
        if bounds.get("window_end_event") != "last_worker_stop_received_before_bounded_drain":
            reasons.append("measurement window must end before bounded drain and coordination")
        if bounds.get("drained_request_rule") != "started_before_worker_stop_boundary":
            reasons.append("drained requests must have started before the measurement boundary")
        if not math.isfinite(expected_duration_seconds) or expected_duration_seconds <= 0:
            reasons.append("expected_duration_seconds must be finite and positive")
        elif abs(elapsed - expected_duration_seconds) > duration_tolerance_seconds:
            reasons.append(
                f"observed duration {elapsed:.6f}s differs from configured duration "
                f"{expected_duration_seconds:.6f}s by more than {duration_tolerance_seconds:.6f}s"
            )
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
    # A long run must not silently permit seconds of wall-clock displacement.
    tolerance = 0.05
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
        "configured_duration_seconds": expected_duration_seconds,
        "duration_tolerance_seconds": duration_tolerance_seconds if expected_duration_seconds is not None else None,
        "duration_difference_seconds": (
            elapsed - expected_duration_seconds if expected_duration_seconds is not None else None
        ),
        "duration_source": "time.monotonic_ns",
        "prometheus_boundary_source": "time.time_ns",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounds", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-duration-seconds", type=float)
    parser.add_argument("--duration-tolerance-seconds", type=float, default=0.25)
    args = parser.parse_args()
    try:
        bounds = json.loads(args.bounds.read_text(encoding="utf-8-sig"))
        report = validate_bounds(
            bounds,
            expected_duration_seconds=args.expected_duration_seconds,
            duration_tolerance_seconds=args.duration_tolerance_seconds,
        )
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
