#!/usr/bin/env python3
"""Prepare and promote the final Locust CSV snapshot for one run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
audit_directory = root / "load-tests" / "locust"
if not audit_directory.exists():
    audit_directory = root / "locust"  # Container mount layout.
sys.path.insert(0, str(audit_directory))
from measurement_audit import validate_worker_reports


KINDS = ("stats", "failures", "exceptions")


def publish(source: Path, destination: Path) -> None:
    # Docker bind-mounted source files need not support a Windows rename.
    # Keep the evidence and atomically publish a host-owned copy instead.
    data = source.read_bytes()
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", dir=destination.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                temporary.replace(destination)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def prepare(prefix: Path) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{prefix}_snapshot_validation.json").unlink(missing_ok=True)
    for path in prefix.parent.glob(f"{prefix.name}_*.csv"):
        path.unlink()
    Path(f"{prefix}_measurement_bounds.json").unlink(missing_ok=True)
    Path(f"{prefix}_expected_workers.json").unlink(missing_ok=True)
    for path in prefix.parent.glob(f"{prefix.name}_worker_*_final.json"):
        path.unlink()


def validate_stats(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    totals = [row for row in rows if row.get("Name") == "Aggregated"]
    if len(totals) != 1:
        raise RuntimeError("Final CSV must contain exactly one Aggregated row")
    endpoints = [row for row in rows if row.get("Name") != "Aggregated"]
    keys = [(row.get("Type"), row.get("Name")) for row in endpoints]
    if len(set(keys)) != len(keys):
        raise RuntimeError("Final CSV has duplicate endpoint rows")
    for row in rows:
        try:
            count, failures = int(row["Request Count"]), int(row["Failure Count"])
            if count < 0 or not 0 <= failures <= count:
                raise ValueError("invalid counts")
            values = [float(row[key]) for key in ("Average Response Time", "50%", "95%", "99%")]
            if not all(math.isfinite(value) and value >= 0 for value in values):
                raise ValueError("nonfinite or negative latency")
            if not values[1] <= values[2] <= values[3]:
                raise ValueError("unordered percentiles")
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f"Invalid final CSV row {row.get('Name')}: {exc}") from exc
    for field in ("Request Count", "Failure Count"):
        if sum(int(row[field]) for row in endpoints) != int(totals[0][field]):
            raise RuntimeError(f"Final CSV endpoint sum differs from Aggregated: {field}")
    if int(totals[0]["Request Count"]) <= 0:
        raise RuntimeError("Final CSV contains no completed requests")
    endpoint_time = math.fsum(int(row["Request Count"]) * float(row["Average Response Time"]) for row in endpoints)
    aggregate_time = int(totals[0]["Request Count"]) * float(totals[0]["Average Response Time"])
    if not math.isclose(endpoint_time, aggregate_time, rel_tol=1e-8, abs_tol=0.001):
        raise RuntimeError("Final CSV weighted mean differs from Aggregated")
    return {"valid": True, "requests": int(totals[0]["Request Count"]),
            "failures": int(totals[0]["Failure Count"]), "endpoint_count": len(endpoints),
            "scope": "CSV internal consistency; does not prove delivery of every worker report",
            "percentile_method": "Locust rounded response-time histogram"}


def promote(prefix: Path) -> None:
    Path(f"{prefix}_snapshot_validation.json").unlink(missing_ok=True)
    # Validate all files before replacing any previous snapshot.
    for kind in KINDS:
        source = Path(f"{prefix}_final_{kind}.csv")
        if not source.exists():
            raise RuntimeError(f"Locust did not produce final snapshot: {source}")
    report = validate_stats(Path(f"{prefix}_final_stats.csv"))
    report["worker_reconciliation"] = validate_worker_reports(prefix, Path(f"{prefix}_final_stats.csv"))
    report["scope"] = "CSV consistency and independent final reports from every expected worker"
    report["sha256"] = {}
    for kind in KINDS:
        source = Path(f"{prefix}_final_{kind}.csv")
        destination = Path(f"{prefix}_{kind}.csv")
        if not source.exists():
            raise RuntimeError(f"Locust did not produce final snapshot: {source}")
        report["sha256"][kind] = hashlib.sha256(source.read_bytes()).hexdigest()
        publish(source, destination)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != report["sha256"][kind]:
            raise RuntimeError(f"Published snapshot differs from final source: {kind}")
    Path(f"{prefix}_snapshot_validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")

    stats_path = Path(f"{prefix}_stats.csv")
    with stats_path.open("r", encoding="utf-8-sig", newline="") as handle:
        aggregate = next((row for row in csv.DictReader(handle) if row.get("Name") == "Aggregated"), None)
    if aggregate is None:
        raise RuntimeError(f"Locust final CSV has no Aggregated row: {stats_path}")
    print(
        "Locust final CSV promoted: "
        f"requests={aggregate['Request Count']} failures={aggregate['Failure Count']} path={stats_path}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prefix)
    else:
        promote(args.prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
