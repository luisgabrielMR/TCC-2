#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def prometheus_get(base_url: str, path: str, parameters: dict[str, str] | None = None) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    if parameters:
        url += "?" + urllib.parse.urlencode(parameters)
    last_error: Exception | None = None
    for _ in range(15):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                payload = json.load(response)
            if payload.get("status") != "success":
                raise RuntimeError(f"Prometheus returned {payload.get('status')}")
            return payload
        except Exception as exc:  # Prometheus and cAdvisor may still be starting.
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Prometheus query failed: {last_error}")


def grafana_get(base_url: str, path: str) -> Any:
    last_error: Exception | None = None
    for _ in range(15):
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=10) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Grafana request failed for {path}: {last_error}")


def container_id(container_name: str) -> str | None:
    completed = subprocess.run(
        ["docker", "inspect", container_name, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    return completed.stdout.strip() if completed.returncode == 0 and completed.stdout.strip() else None


def metric_matches(metric: dict[str, str], compose_service: str, name: str, identifier: str | None) -> bool:
    cgroup = metric.get("id", "")
    if cgroup in {"/", "/docker", "/restricted"}:
        return False
    if identifier:
        return identifier in cgroup or identifier[:12] in cgroup
    service_labels = {
        metric.get("container_label_com_docker_compose_service"),
        metric.get("container_label_com_docker_compose_service_legacy"),
        metric.get("container"),
    }
    if compose_service in service_labels:
        return True
    names = {metric.get("name"), metric.get("container_name")}
    if name in names or f"/{name}" in names:
        return True
    cgroup = metric.get("id", "")
    return bool(identifier and (identifier in cgroup or identifier[:12] in cgroup))


def query_series(base_url: str, metric_name: str) -> list[dict[str, Any]]:
    payload = prometheus_get(base_url, "/api/v1/query", {"query": metric_name})
    return payload.get("data", {}).get("result", [])


def cadvisor_collection_config() -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["docker", "inspect", "tcc_benchmark_cadvisor", "--format", "{{json .Config.Cmd}}"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        command = json.loads(completed.stdout)
        flags = dict(argument.lstrip("-").split("=", 1) for argument in command if "=" in argument)
        valid = flags.get("allow_dynamic_housekeeping") == "false" and flags.get("housekeeping_interval") == "1s"
        return {"command": command, "fixed_interval_valid": valid}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {"command": [], "fixed_interval_valid": False}


def build_report(base_url: str, grafana_url: str, api_service: str, mode: str) -> dict[str, Any]:
    targets_payload = prometheus_get(base_url, "/api/v1/targets")
    targets = targets_payload.get("data", {}).get("activeTargets", [])
    target_health = {
        target.get("labels", {}).get("job", "unknown"): target.get("health", "unknown") for target in targets
    }
    cpu_series = query_series(base_url, "container_cpu_usage_seconds_total")
    memory_series = query_series(base_url, "container_memory_working_set_bytes")

    components = {
        "api": (api_service, "tcc_benchmark_" + api_service.replace("-", "_")),
        "postgresql": ("postgres", "tcc_benchmark_postgres"),
        "locust": ("locust", "tcc_benchmark_locust"),
    }
    component_status: dict[str, Any] = {}
    cadvisor_blockers: list[str] = []
    collection_config = cadvisor_collection_config()
    if not collection_config["fixed_interval_valid"]:
        cadvisor_blockers.append("cAdvisor must use fixed one-second housekeeping (dynamic collection disabled)")
    operational_blockers: list[str] = []
    for component, (service, name) in components.items():
        identifier = container_id(name)
        cpu_matches = [row for row in cpu_series if metric_matches(row.get("metric", {}), service, name, identifier)]
        memory_matches = [row for row in memory_series if metric_matches(row.get("metric", {}), service, name, identifier)]
        available = bool(cpu_matches and memory_matches)
        component_status[component] = {
            "compose_service": service,
            "container_name": name,
            "container_id": identifier,
            "cpu_series": len(cpu_matches),
            "memory_series": len(memory_matches),
            "available": available,
        }
        if not available:
            cadvisor_blockers.append(f"cAdvisor lacks identifiable CPU and memory series for {component}")

    for job in ("benchmark-results", "postgres", "prometheus"):
        if target_health.get(job) != "up":
            operational_blockers.append(f"Prometheus target {job} is not up")
    if target_health.get("cadvisor") != "up":
        cadvisor_blockers.append("Prometheus target cadvisor is not up")
    postgres_series = query_series(base_url, "pg_up")
    if not postgres_series:
        operational_blockers.append("postgres-exporter does not expose pg_up")
    results_exporter_series = query_series(base_url, "benchmark_results_exporter_up")
    results_exporter_healthy = any(
        float(row.get("value", [0, 0])[1]) == 1 for row in results_exporter_series
    )
    if not results_exporter_healthy:
        operational_blockers.append("benchmark-results-exporter does not report benchmark_results_exporter_up=1")
    try:
        grafana = grafana_get(grafana_url, "/api/health")
        grafana_dashboards = grafana_get(grafana_url, "/api/search?type=dash-db")
    except RuntimeError as exc:
        grafana = {"database": "unavailable", "error": str(exc)}
        grafana_dashboards = []
    if grafana.get("database") != "ok":
        operational_blockers.append("Grafana health endpoint did not report database=ok")
    dashboard_titles = {
        item.get("title") for item in grafana_dashboards if isinstance(item, dict)
    }
    expected_dashboards = {
        "TCC Benchmark - Resultados Oficiais",
        "TCC Benchmark - Monitoramento e Diagnostico",
    }
    missing_dashboards = sorted(expected_dashboards - dashboard_titles)
    if missing_dashboards:
        operational_blockers.append("Grafana dashboards are not provisioned: " + ", ".join(missing_dashboards))
    cadvisor_usable = target_health.get("cadvisor") == "up" and all(
        details["available"] for details in component_status.values()
    )
    blockers = operational_blockers + cadvisor_blockers

    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requested_mode": mode,
        "classification": "official_compatible" if mode == "official" and not blockers else "non_official",
        "operational_eligible": not operational_blockers,
        "operational_blockers": operational_blockers,
        "official_eligible": not blockers,
        "official_blockers": blockers,
        "prometheus_url": base_url,
        "grafana_url": grafana_url,
        "grafana_health": grafana,
        "grafana_dashboards": sorted(title for title in dashboard_titles if title),
        "prometheus_targets": target_health,
        "cadvisor_target_up": target_health.get("cadvisor") == "up",
        "cadvisor_components": component_status,
        "cadvisor_collection_config": collection_config,
        "postgres_exporter_series": len(postgres_series),
        "results_exporter_series": len(results_exporter_series),
        "results_exporter_healthy": results_exporter_healthy,
        "metric_sources": {
            "container_cpu": "cAdvisor" if cadvisor_usable else "cAdvisor unavailable; docker stats is complementary only",
            "container_memory": "cAdvisor" if cadvisor_usable else "cAdvisor unavailable; docker stats is complementary only",
            "postgresql": "postgres-exporter via Prometheus",
        },
    }


def wait_for_official_evidence(
    report_builder: Callable[[], dict[str, Any]],
    wait_seconds: float,
    poll_seconds: float = 2.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = monotonic() + max(0.0, wait_seconds)
    while True:
        report = report_builder()
        if report["official_eligible"] or monotonic() >= deadline:
            return report
        sleeper(min(poll_seconds, max(0.0, deadline - monotonic())))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate official benchmark monitoring prerequisites.")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    parser.add_argument("--grafana-url", default="http://127.0.0.1:3000")
    parser.add_argument("--api-service", required=True)
    parser.add_argument("--mode", choices=("pilot", "official"), default="pilot")
    parser.add_argument(
        "--series-wait-seconds",
        type=float,
        default=30,
        help="Maximum time to wait for the first identifiable cAdvisor series after containers start.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = wait_for_official_evidence(
        lambda: build_report(args.prometheus_url, args.grafana_url, args.api_service, args.mode),
        args.series_wait_seconds,
    )
    serialized = json.dumps(report, indent=2, ensure_ascii=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    blockers = report["official_blockers"] if args.mode == "official" else report["operational_blockers"]
    if blockers:
        prefix = "Official run blocked" if args.mode == "official" else "Monitoring pilot blocked"
        print(prefix + ": " + "; ".join(blockers), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
