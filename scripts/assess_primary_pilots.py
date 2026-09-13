#!/usr/bin/env python3
"""Read-only assessment of explicit pilot sequences; never promotes results."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.snapshot_integrity import verified_stats

LANGUAGES = ("python", "node", "java", "go", "dotnet")
PROFILES = ("fixed_50", "fixed_100")


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def first_csv(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return next(csv.DictReader(handle), {})


def prometheus_scrape_interval_seconds(metadata, manifest):
    for source in (metadata.get("metrics", {}), manifest.get("protocol", {}).get("metrics", {})):
        interval = numeric(source.get("prometheus_scrape_interval_seconds"))
        if interval is not None and interval > 0:
            return interval
    return 1.0


def recorded_minimum_delivery_rps(metadata, manifest):
    for source in (
        metadata.get("locust", {}),
        manifest.get("protocol", {}).get("load", {}),
    ):
        minimum = numeric(source.get("minimum_delivery_rps"))
        if minimum is not None and minimum > 0:
            return minimum
    return None


def assess(raw: Path, sequence: str) -> dict:
    rows = []
    sources = []
    commits = set()
    protocols = {profile: set() for profile in PROFILES}
    for path in sorted(raw.glob("*/*/run_*/metadata.json")):
        metadata = json.loads(path.read_text(encoding="utf-8-sig"))
        if metadata.get("execution_order", {}).get("sequence_id") != sequence:
            continue
        profile, language = metadata.get("load_profile"), metadata.get("language")
        if profile not in PROFILES or language not in LANGUAGES:
            raise ValueError(f"Unexpected profile/language in pilot sequence: {path}")
        directory = path.parent
        manifest = json.loads((directory / "protocol-manifest.json").read_text(encoding="utf-8-sig"))
        sources.append(manifest["protocol"].get("experimental_source_sha256"))
        commits.add(manifest.get("commit_sha"))
        protocols[profile].add(manifest.get("protocol_sha256"))
        maximum_cadvisor_gap = prometheus_scrape_interval_seconds(metadata, manifest) * 1.5
        reasons = []
        try:
            aggregate = next(row for row in verified_stats(directory / "locust") if row["Name"] == "Aggregated")
        except (OSError, ValueError, RuntimeError, StopIteration) as exc:
            aggregate = {}
            reasons.append(f"Invalid request snapshot: {exc}")
        postgres = first_csv(directory / "postgres_summary.csv")
        load = metadata.get("locust", {})
        database = metadata.get("shared_database", {})
        target = numeric(load.get("target_rps"))
        delivered = numeric(load.get("achieved_rps"))
        minimum_delivery = recorded_minimum_delivery_rps(metadata, manifest)
        failures = numeric(aggregate.get("Failure Count"))
        if (target is None or delivered is None or target <= 0 or minimum_delivery is None
                or delivered < minimum_delivery):
            reasons.append("Delivered rate is below the recorded fixed-load minimum")
        if failures != 0:
            reasons.append("HTTP failures or missing HTTP evidence")
        if (numeric(aggregate.get("Request Count")) or 0) <= 0:
            reasons.append("No completed HTTP requests")
        for phase in ("warmup", "measurement_stability"):
            if metadata.get(phase, {}).get("stable") is not True:
                reasons.append(f"{phase} stability not confirmed")
        if load.get("generator_headroom_met") is not True or database.get("database_headroom_met") is not True:
            reasons.append("Operational CPU margin was not confirmed")
        if postgres.get("activity_diagnostics_available") != "True":
            reasons.append("Complete activity/wait diagnostics unavailable")
        bounds_path = directory / "measurement-bounds-validation.json"
        bounds = json.loads(bounds_path.read_text(encoding="utf-8-sig")) if bounds_path.exists() else {}
        if bounds.get("valid") is not True:
            reasons.append("Measurement bounds unavailable or invalid")
        if metadata.get("result_classification") != "non_official":
            reasons.append("Expected non_official pilot classification")
        pg_cpu = numeric(database.get("postgres_cpu_quota_average_percent"))
        pg_peak = numeric(database.get("postgres_cpu_quota_max_percent"))
        if pg_cpu is None or pg_peak is None or numeric(load.get("locust_cpu_quota_average_percent")) is None:
            reasons.append("Missing normalized CPU measurements")
        cadvisor_path = directory / "cadvisor_summary.csv"
        resources = {}
        if cadvisor_path.exists():
            with cadvisor_path.open(encoding="utf-8-sig", newline="") as handle:
                resources = {row.get("component"): row for row in csv.DictReader(handle)}
        for component in ("api", "postgresql", "locust"):
            resource = resources.get(component, {})
            gap = numeric(resource.get("maximum_scrape_gap_seconds"))
            if ((numeric(resource.get("coverage_percent")) or 0) < 90
                    or numeric(resource.get("cpu_counter_resets")) != 0
                    or gap is None or gap > maximum_cadvisor_gap):
                reasons.append(f"Insufficient cAdvisor evidence for {component}")
        diagnostics = []
        # Advisory selection margin, distinct from the existing 90% operational gate.
        if pg_cpu is None or pg_cpu >= 70:
            diagnostics.append("Review database CPU margin (pilot advisory threshold: mean >=70% of quota)")
        if pg_peak is not None and pg_peak >= 90:
            diagnostics.append("Database CPU intervals reached >=90% of quota")
        for metric in ("waiting_lock_sessions_max", "waiting_io_sessions_max"):
            if (numeric(postgres.get(metric)) or 0) > 0:
                diagnostics.append(f"Observed {metric} > 0; inspect time series")
        rows.append({
            "language": language, "profile": profile, "path": str(directory),
            "classification": metadata.get("result_classification"),
            "campaign_fingerprint": manifest.get("campaign_fingerprint"),
            "nominal_rps": target, "minimum_delivery_rps": minimum_delivery, "delivered_rps": delivered,
            "requests": numeric(aggregate.get("Request Count")), "failures": failures,
            "average_ms": numeric(aggregate.get("Average Response Time")),
            "p95_ms": numeric(aggregate.get("95%")),
            "postgres_cpu_quota_average_percent": pg_cpu,
            "postgres_cpu_quota_max_percent": pg_peak,
            "locust_cpu_quota_average_percent": numeric(load.get("locust_cpu_quota_average_percent")),
            "active_sessions_average": numeric(postgres.get("active_sessions_average")),
            "waiting_lock_sessions_max": numeric(postgres.get("waiting_lock_sessions_max")),
            "waiting_io_sessions_max": numeric(postgres.get("waiting_io_sessions_max")),
            "evidence_issues": reasons, "diagnostics_to_review": diagnostics,
        })
    expected = {(profile, language) for profile in PROFILES for language in LANGUAGES}
    observed = [(row["profile"], row["language"]) for row in rows]
    complete = set(observed) == expected and len(observed) == len(expected)
    comparable_inputs = bool(sources) and all(source and source == sources[0] for source in sources)
    comparable_inputs = comparable_inputs and len(commits) == 1 and all(len(values) == 1 for values in protocols.values())
    return {
        "kind": "pilot_assessment_not_official_clearance", "sequence_id": sequence,
        "complete_two_levels_five_languages": complete,
        "same_executable_sources_and_protocol_per_level": comparable_inputs,
        "all_evidence_checks_passed": complete and comparable_inputs and not any(row["evidence_issues"] for row in rows),
        "interpretation": "Closed paced load. Sampled CPU/waits cannot prove absence of a bottleneck. No statistical language ranking; review pilot diagnostics before freezing the full campaign.",
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "results/raw")
    parser.add_argument("--sequence", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = assess(args.raw, args.sequence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["all_evidence_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
