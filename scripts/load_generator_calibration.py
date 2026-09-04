"""Validation rules for the non-official Locust generator calibration artifact."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


REQUIRED_USER_STEPS = [25, 50, 100, 200, 400]
MINIMUM_PEAK_RPS = 250.0
LOCUST_SATURATION_CPU_QUOTA_PERCENT = 90.0
SAFE_OPERATING_FACTOR = 0.8
MINIMUM_CADVISOR_COVERAGE_PERCENT = 80.0


def quota_normalized_cpu_percent(raw_cpu_percent: float, cpu_quota: float) -> float:
    if not math.isfinite(cpu_quota) or cpu_quota <= 0:
        raise ValueError("cpu_quota must be positive")
    if not math.isfinite(raw_cpu_percent) or raw_cpu_percent < 0:
        raise ValueError("raw_cpu_percent must be finite and nonnegative")
    return raw_cpu_percent / cpu_quota


def _locust_image_reference(configured_images: dict[str, Any]) -> str | None:
    for item in configured_images.get("images", []):
        reference = str(item.get("configured_reference", ""))
        if reference.startswith("locustio/locust:2.32.6@sha256:"):
            return reference
    return None


def validate_calibration(
    path: Path,
    methodology_version: int,
    git: dict[str, Any],
    docker: dict[str, Any],
    configured_images: dict[str, Any],
    expected_processes: int,
    expected_locust_cpu_quota: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    try:
        artifact = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"available": False, "valid": False, "path": str(path), "reasons": ["calibration artifact is missing"]}
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "valid": False, "path": str(path), "reasons": [str(exc)]}

    expected = {
        "schema_version": 3,
        "classification": "non_official_calibration",
        "scenario": "health_only",
        "wait_seconds": 0,
        "step_duration_seconds": 60,
        "processes": expected_processes,
        "methodology_version": methodology_version,
    }
    for key, value in expected.items():
        if artifact.get(key) != value:
            reasons.append(f"{key} must be {value!r}; found {artifact.get(key)!r}")

    provenance = artifact.get("git", {})
    for key in ("commit_sha", "tracked_diff_sha256", "untracked_files_sha256"):
        if provenance.get(key) != git.get(key):
            reasons.append(f"calibration git {key} does not match the current project")
    if provenance.get("git_dirty") is not False or git.get("git_dirty") is not False:
        reasons.append("calibration and current project must both use a clean Git tree")

    environment = artifact.get("environment", {})
    if environment.get("docker_engine") != docker.get("engine_server_version"):
        reasons.append("calibration Docker Engine differs from the current environment")
    current_compose = str(docker.get("compose_version") or "").lstrip("v")
    if str(environment.get("docker_compose") or "").lstrip("v") != current_compose:
        reasons.append("calibration Docker Compose differs from the current environment")
    allocation = docker.get("allocation", {})
    if environment.get("docker_logical_processors") != allocation.get("logical_processors"):
        reasons.append("calibration Docker CPU allocation differs from the current environment")
    if environment.get("docker_memory_bytes") != allocation.get("memory_bytes"):
        reasons.append("calibration Docker memory allocation differs from the current environment")
    if environment.get("locust_image") != _locust_image_reference(configured_images):
        reasons.append("calibration Locust image differs from the configured image")
    if environment.get("locust_processes") != expected_processes:
        reasons.append("calibration Locust process count differs from the configured environment")
    try:
        artifact_cpu_quota = float(environment.get("locust_cpu_quota"))
    except (TypeError, ValueError):
        artifact_cpu_quota = 0.0
        reasons.append("calibration Locust CPU quota is missing or invalid")
    if artifact_cpu_quota != expected_locust_cpu_quota:
        reasons.append("calibration Locust CPU quota differs from the official resource policy")

    samples = artifact.get("samples", [])
    if artifact.get("api_service") not in {"python-api", "node-api", "java-api", "go-api", "dotnet-api"}:
        reasons.append("api_service must identify one of the five benchmark APIs")
    observed_steps = [sample.get("users") for sample in samples if isinstance(sample, dict)]
    if observed_steps != REQUIRED_USER_STEPS:
        reasons.append(f"users steps must be exactly {REQUIRED_USER_STEPS}; found {observed_steps}")
    peak_rps_values: list[float] = []
    saturation_observed = False
    for sample in samples:
        users = sample.get("users")
        if sample.get("spawn_rate") != users:
            reasons.append(f"calibration sample for {users} users must use spawn_rate={users}")
        try:
            elapsed = float(sample.get("elapsed_seconds"))
            failures = int(sample.get("failures"))
            exact_rps = float(sample.get("throughput_rps_exact"))
            locust_cpu_raw_average = float(sample.get("locust_cpu_raw_average_percent"))
            locust_cpu_raw_max = float(sample.get("locust_cpu_raw_max_percent"))
            locust_cpu_quota_average = float(sample.get("locust_cpu_quota_average_percent"))
            locust_cpu_quota_max = float(sample.get("locust_cpu_quota_max_percent"))
            cadvisor_coverage = float(sample.get("cadvisor_coverage_percent"))
        except (TypeError, ValueError):
            reasons.append(f"calibration sample for {users} users has invalid numeric fields")
            continue
        values = (elapsed, exact_rps, locust_cpu_raw_average, locust_cpu_raw_max,
                  locust_cpu_quota_average, locust_cpu_quota_max, cadvisor_coverage)
        if not all(math.isfinite(value) and value >= 0 for value in values):
            reasons.append(f"calibration sample for {users} users has nonfinite or negative numeric fields")
            continue
        if cadvisor_coverage > 100:
            reasons.append(f"calibration sample for {users} users has coverage above 100%")
        if not 55 <= elapsed <= 75:
            reasons.append(f"calibration sample for {users} users has unexpected duration {elapsed:.3f}s")
        if failures != 0:
            reasons.append(f"calibration sample for {users} users has {failures} failures")
        if sample.get("bounds_valid") is not True:
            reasons.append(f"calibration sample for {users} users has invalid measurement bounds")
        if sample.get("cpu_metric_source") != "cadvisor_via_prometheus":
            reasons.append(f"calibration sample for {users} users does not use cAdvisor CPU")
        if cadvisor_coverage < MINIMUM_CADVISOR_COVERAGE_PERCENT:
            reasons.append(
                f"calibration sample for {users} users has less than "
                f"{MINIMUM_CADVISOR_COVERAGE_PERCENT:.0f}% cAdvisor coverage"
            )
        if exact_rps <= 0:
            reasons.append(f"calibration sample for {users} users has no throughput")
        try:
            expected_quota_average = quota_normalized_cpu_percent(
                locust_cpu_raw_average, expected_locust_cpu_quota
            )
            expected_quota_max = quota_normalized_cpu_percent(
                locust_cpu_raw_max, expected_locust_cpu_quota
            )
        except ValueError as exc:
            reasons.append(str(exc))
            expected_quota_average = float("inf")
            expected_quota_max = float("inf")
        if abs(locust_cpu_quota_average - expected_quota_average) > 0.001:
            reasons.append(
                f"calibration sample for {users} users has inconsistent average Locust CPU normalization"
            )
        if abs(locust_cpu_quota_max - expected_quota_max) > 0.001:
            reasons.append(
                f"calibration sample for {users} users has inconsistent maximum Locust CPU normalization"
            )
        if locust_cpu_quota_average >= LOCUST_SATURATION_CPU_QUOTA_PERCENT:
            saturation_observed = True
        if failures == 0 and exact_rps > 0:
            peak_rps_values.append(exact_rps)

    validated_capacity = max(peak_rps_values, default=0.0)
    if not saturation_observed:
        reasons.append(
            "calibration did not drive Locust to 90% of its CPU quota; "
            "the generator ceiling was not demonstrated"
        )
    if validated_capacity < MINIMUM_PEAK_RPS:
        reasons.append(
            f"validated generator peak {validated_capacity:.3f} req/s is below the required {MINIMUM_PEAK_RPS:.3f} req/s"
        )
    declared_capacity = artifact.get("validated_capacity_rps")
    try:
        if not math.isfinite(float(declared_capacity)) or abs(float(declared_capacity) - validated_capacity) > 0.001:
            reasons.append("declared validated_capacity_rps does not match the samples")
    except (TypeError, ValueError):
        reasons.append("validated_capacity_rps is missing or invalid")

    return {
        "available": True,
        "valid": not reasons,
        "path": str(path),
        "reasons": reasons,
        "validated_capacity_rps": validated_capacity,
        "safe_operating_rps": validated_capacity * SAFE_OPERATING_FACTOR,
        "minimum_peak_rps": MINIMUM_PEAK_RPS,
        "saturation_cpu_quota_percent": LOCUST_SATURATION_CPU_QUOTA_PERCENT,
        "safe_operating_factor": SAFE_OPERATING_FACTOR,
        "minimum_cadvisor_coverage_percent": MINIMUM_CADVISOR_COVERAGE_PERCENT,
        "artifact": artifact,
    }
