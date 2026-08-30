#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/_lib.sh"

LANGUAGE="${1:-go}"
API_SERVICE="$(api_service_for_language "$LANGUAGE")"
LOCUST_HOST="http://$API_SERVICE:8000"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CALIBRATION_ROOT="results/calibration/$STAMP"
PREFLIGHT_PATH="$CALIBRATION_ROOT/preflight.json"
PYTHON_BIN="$(python_bin)"
if ! [[ "$LOCUST_PROCESSES" =~ ^[1-9][0-9]*$ ]]; then
  echo "LOCUST_PROCESSES deve ser um inteiro positivo." >&2
  exit 2
fi
API_STARTED=false
LOCUST_STARTED=false
METRICS_PID=""
METRICS_STOP_FILE=""

cleanup() {
  if [ -n "$METRICS_PID" ]; then
    touch "$METRICS_STOP_FILE"
    wait "$METRICS_PID" >/dev/null 2>&1 || true
  fi
  if [ "$LOCUST_STARTED" = true ]; then docker compose stop locust >/dev/null 2>&1 || true; fi
  if [ "$API_STARTED" = true ]; then docker compose stop "$API_SERVICE" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

mkdir -p "$CALIBRATION_ROOT"
docker compose --profile monitoring up -d postgres-exporter benchmark-results-exporter prometheus grafana cadvisor
"$SCRIPT_DIR/reset_db.sh"
docker compose --profile "$LANGUAGE" up -d --build "$API_SERVICE"
API_STARTED=true
wait_for_api "$API_BASE_URL"
docker compose --profile load up -d locust
LOCUST_STARTED=true
"$PYTHON_BIN" "$SCRIPT_DIR/preflight.py" --mode pilot --api-service "$API_SERVICE" \
  --load-profile environment --output "$PREFLIGHT_PATH"
if "$PYTHON_BIN" -c 'import json,sys; raise SystemExit(0 if json.load(open(sys.argv[1], encoding="utf-8"))["git"]["git_dirty"] else 1)' "$PREFLIGHT_PATH"; then
  echo "A calibracao que libera rodadas oficiais exige uma arvore Git limpa." >&2
  exit 2
fi
"$PYTHON_BIN" - "$PREFLIGHT_PATH" <<'PY'
import json, sys
p=json.load(open(sys.argv[1], encoding="utf-8"))
versions_ok=(p["docker"].get("engine_server_version") == p["expected"]["docker_engine"] and str(p["docker"].get("compose_version") or "").lstrip("v") == p["expected"]["docker_compose"])
limits=[*p["resource_policy"]["configured"].get("limits", {}).values(), *p["resource_policy"]["effective"].get("limits", {}).values()]
if not versions_ok or any(not item.get("matches_expected") for item in limits):
    raise SystemExit("Calibration requires the exact Docker/Compose versions and effective CPU quotas")
PY
"$PYTHON_BIN" "$SCRIPT_DIR/validate_monitoring.py" \
  --prometheus-url "http://127.0.0.1:${PROMETHEUS_PORT:-9090}" \
  --grafana-url "http://127.0.0.1:${GRAFANA_PORT:-3000}" \
  --api-service "$API_SERVICE" --mode official \
  --output "$CALIBRATION_ROOT/monitoring-preflight.json"
docker compose stop locust
LOCUST_STARTED=false

for users in 25 50 100 200 400; do
  STEP_DIR="$CALIBRATION_ROOT/users_$users"
  mkdir -p "$STEP_DIR"
  BOUNDS_FILE="$STEP_DIR/locust_measurement_bounds.json"
  METRICS_STOP_FILE="$STEP_DIR/.stop_docker_stats"
  rm -f "$METRICS_STOP_FILE"
  "$SCRIPT_DIR/collect_docker_stats.sh" "$STEP_DIR" "$METRICS_STOP_FILE" \
    "$METRICS_SAMPLE_INTERVAL_SECONDS" "$BOUNDS_FILE" >"$STEP_DIR/docker_stats_collector.log" 2>&1 &
  METRICS_PID=$!
  echo "Calibrando Locust: /health, $users usuarios, pacing 0, 60 s..."
  "$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix "$STEP_DIR/locust" --prepare
  SCENARIO=health_only docker compose --profile load run --rm \
    -e SCENARIO=health_only -e PAYLOAD_DIR=/mnt/payloads -e LOCUST_WAIT_SECONDS=0 \
    -e LOCUST_PROCESSES="$LOCUST_PROCESSES" \
    locust -f locustfile.py --headless --processes "$LOCUST_PROCESSES" -u "$users" -r "$users" -t 60s \
    --host "$LOCUST_HOST" --csv "/mnt/$STEP_DIR/locust" --only-summary
  "$PYTHON_BIN" "$SCRIPT_DIR/finalize_locust_csv.py" --prefix "$STEP_DIR/locust"
  touch "$METRICS_STOP_FILE"
  wait "$METRICS_PID"
  METRICS_PID=""
  rm -f "$METRICS_STOP_FILE"
  "$PYTHON_BIN" "$SCRIPT_DIR/validate_measurement_bounds.py" --bounds "$BOUNDS_FILE" \
    --output "$STEP_DIR/measurement-bounds-validation.json"
  IFS='|' read -r start_epoch end_epoch <<EOF
$($PYTHON_BIN -c 'import json,sys; b=json.load(open(sys.argv[1], encoding="utf-8")); print("{}|{}".format(b["started_epoch"], b["finished_epoch"]))' "$BOUNDS_FILE")
EOF
  "$SCRIPT_DIR/export_prometheus_data.sh" "$STEP_DIR" "$start_epoch" "$end_epoch" "$API_SERVICE" official 80
done

"$PYTHON_BIN" - "$CALIBRATION_ROOT" "$PREFLIGHT_PATH" "$LOAD_GENERATOR_CALIBRATION_FILE" "$METHODOLOGY_VERSION" "$API_SERVICE" "$LOCUST_PROCESSES" <<'PY'
import csv, json, sys
from datetime import datetime, timezone
from pathlib import Path

root, preflight_path, output_path = map(Path, sys.argv[1:4])
methodology, api_service, processes = int(sys.argv[4]), sys.argv[5], int(sys.argv[6])
preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
locust_cpu_quota = float(preflight["resource_policy"]["effective"]["limits"]["locust"]["effective_cpu_quota"])
if locust_cpu_quota <= 0:
    raise SystemExit("Locust effective CPU quota is unavailable")
samples = []
for users in (25, 50, 100, 200, 400):
    directory = root / f"users_{users}"
    bounds = json.loads((directory / "locust_measurement_bounds.json").read_text(encoding="utf-8"))
    validation = json.loads((directory / "measurement-bounds-validation.json").read_text(encoding="utf-8"))
    aggregate = next(row for row in csv.DictReader((directory / "locust_stats.csv").open(encoding="utf-8-sig")) if row["Name"] == "Aggregated")
    locust = next(row for row in csv.DictReader((directory / "cadvisor_summary.csv").open(encoding="utf-8-sig")) if row["component"] == "locust")
    requests, elapsed = int(aggregate["Request Count"]), float(bounds["elapsed_seconds"])
    samples.append({
        "users": users, "spawn_rate": users, "elapsed_seconds": round(elapsed, 9), "requests": requests,
        "failures": int(aggregate["Failure Count"]),
        "throughput_rps_exact": round(requests / elapsed, 9),
        "locust_reported_rps": float(aggregate["Requests/s"]),
        "locust_cpu_raw_average_percent": float(locust["cpu_average_percent"]),
        "locust_cpu_raw_max_percent": float(locust["cpu_max_percent"]),
        "locust_cpu_quota_average_percent": round(float(locust["cpu_average_percent"]) / locust_cpu_quota, 6),
        "locust_cpu_quota_max_percent": round(float(locust["cpu_max_percent"]) / locust_cpu_quota, 6),
        "cadvisor_coverage_percent": float(locust["coverage_percent"]),
        "cpu_metric_source": "cadvisor_via_prometheus", "bounds_valid": bool(validation["valid"]),
        "result_directory": str(directory).replace("\\", "/"),
    })
valid = [row["throughput_rps_exact"] for row in samples if row["failures"] == 0]
locust_image = next((item["configured_reference"] for item in preflight["configured_images"]["images"] if item["configured_reference"].startswith("locustio/locust:2.32.6@sha256:")), None)
artifact = {
    "schema_version": 3, "classification": "non_official_calibration",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "methodology_version": methodology, "scenario": "health_only", "wait_seconds": 0,
    "step_duration_seconds": 60, "processes": processes, "api_service": api_service,
    "git": {key: preflight["git"][key] for key in ("commit_sha", "git_dirty", "tracked_diff_sha256", "untracked_files_sha256")},
    "environment": {
        "docker_engine": preflight["docker"]["engine_server_version"],
        "docker_compose": preflight["docker"]["compose_version"],
        "docker_logical_processors": preflight["docker"]["allocation"]["logical_processors"],
        "docker_memory_bytes": preflight["docker"]["allocation"]["memory_bytes"],
        "locust_image": locust_image,
        "locust_processes": processes,
        "locust_cpu_quota": locust_cpu_quota,
    },
    "samples": samples, "validated_capacity_rps": round(max(valid, default=0), 9),
}
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
PY

"$PYTHON_BIN" "$SCRIPT_DIR/preflight.py" --mode pilot --api-service "$API_SERVICE" \
  --load-profile fixed_200 --output "$CALIBRATION_ROOT/calibration-validation.json"
"$PYTHON_BIN" -c 'import json,sys; report=json.load(open(sys.argv[1], encoding="utf-8"))["load_generator_calibration"]; print("Calibration capacity: {:.3f} req/s".format(report["validated_capacity_rps"])); raise SystemExit(0 if report["valid"] else 2)' \
  "$CALIBRATION_ROOT/calibration-validation.json"
echo "Calibracao gravada em $LOAD_GENERATOR_CALIBRATION_FILE"
