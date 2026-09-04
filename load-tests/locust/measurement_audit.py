"""Independent end-of-run counters; one file per worker, no per-request I/O."""
import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path


class CooperativeStopMixin:
    def stop(self, force=False):
        from locust.user.task import LOCUST_STATE_RUNNING, LOCUST_STATE_STOPPING, LOCUST_STATE_WAITING

        if not force and self._state in (LOCUST_STATE_RUNNING, LOCUST_STATE_WAITING, LOCUST_STATE_STOPPING):
            # killone() yields: a WAITING user can resume into its next request
            # before the kill arrives. TaskSet.wait() checks STOPPING after sleep.
            self._state = LOCUST_STATE_STOPPING
            return False
        return super().stop(force=force)


def validate_worker_reports(prefix: Path, stats_path: Path) -> dict:
    manifest = json.loads(Path(f"{prefix}_expected_workers.json").read_text())
    bounds = json.loads(Path(f"{prefix}_measurement_bounds.json").read_text())
    expected = manifest["workers"]
    def valid_time(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if not all(valid_time(value) for value in (
        bounds.get("started_epoch"), bounds["finished_epoch"],
        manifest["started_epoch"], manifest["stop_requested_epoch"],
    )):
        raise RuntimeError("Invalid measurement timestamps")
    if not (
        bounds["started_epoch"] <= manifest["started_epoch"] <= bounds["started_epoch"] + 0.05
        and manifest["started_epoch"] <= manifest["stop_requested_epoch"] <= bounds["finished_epoch"]
        and bounds["finished_epoch"] - manifest["stop_requested_epoch"] <= 0.25
    ):
        raise RuntimeError("Invalid measurement timestamp order")
    if (not expected or type(manifest["processes"]) is not int or len(expected) != manifest["processes"]
            or any(type(index) is not int or index < 0 for index in expected.values())
            or set(expected.values()) != set(range(manifest["processes"]))):
        raise RuntimeError("Invalid expected worker manifest")
    combined = {}
    for identity, index in expected.items():
        path = Path(f"{prefix}_worker_{index}_final.json")
        report = json.loads(path.read_text())
        if not all(valid_time(report.get(key)) for key in (
            "started_epoch", "started_monotonic_ns", "stop_requested_epoch",
            "stop_requested_monotonic_ns", "finished_epoch",
        )):
            raise RuntimeError(f"Invalid worker timestamps: {path}")
        if not (
            report["started_epoch"] <= report["stop_requested_epoch"] <= report["finished_epoch"]
            and report["stop_requested_epoch"] <= bounds["finished_epoch"] + 0.05
            and report["stop_requested_epoch"] >= manifest["stop_requested_epoch"] - 0.05
            and report["stop_requested_monotonic_ns"] >= report["started_monotonic_ns"]
        ):
            raise RuntimeError(f"Worker timestamps outside run lifecycle: {path}")
        if (
            report["worker_id"] != identity
            or report["started_epoch"] < manifest["started_epoch"] - 0.05
            or report["started_epoch"] > manifest["started_epoch"] + 0.25
        ):
            raise RuntimeError(f"Stale or unexpected worker report: {path}")
        if not math.isfinite(report["finished_epoch"]) or report["finished_epoch"] < report["started_epoch"]:
            raise RuntimeError(f"Invalid worker timestamps: {path}")
        if report["finished_epoch"] > bounds["finished_epoch"] + 5.0:
            raise RuntimeError(f"Worker {index} exceeded the bounded drain period")
        if report["in_flight"] != 0 or report["cancelled"] != 0:
            raise RuntimeError(f"Worker {index} has unfinished/cancelled requests")
        if report.get("started_at_stop") != report["started"]:
            raise RuntimeError(f"Worker {index} started a request after the stop boundary")
        completed = sum(row["requests"] for row in report["endpoints"])
        if completed != report["started"]:
            raise RuntimeError(f"Worker {index} request lifecycle does not reconcile")
        endpoint_keys = [(row["method"], row["name"]) for row in report["endpoints"]]
        if len(endpoint_keys) != len(set(endpoint_keys)):
            raise RuntimeError(f"Duplicate worker endpoint: {path}")
        for row in report["endpoints"]:
            if (type(row["requests"]) is not int or type(row["failures"]) is not int
                    or not 0 <= row["failures"] <= row["requests"]
                    or not valid_time(row["total_response_time"]) or row["total_response_time"] < 0):
                raise RuntimeError(f"Invalid worker endpoint counters: {path}")
            histogram = row.get("response_times")
            if not isinstance(histogram, dict) or any(
                not str(bucket).lstrip("-").isdigit() or int(bucket) < 0
                or type(count) is not int or count < 0
                for bucket, count in histogram.items()
            ) or sum(histogram.values()) != row["requests"]:
                raise RuntimeError(f"Invalid worker response-time histogram: {path}")
            key = (row["method"], row["name"])
            value = combined.setdefault(key, [0, 0, 0.0, {}])
            value[0] += row["requests"]
            value[1] += row["failures"]
            value[2] += row["total_response_time"]
            for bucket, count in histogram.items():
                value[3][int(bucket)] = value[3].get(int(bucket), 0) + count
    with stats_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    aggregate = [row for row in rows if row["Name"] == "Aggregated"]
    if len(aggregate) != 1:
        raise RuntimeError("Worker reconciliation requires one Aggregated row")
    total_count = sum(value[0] for value in combined.values())
    total_failures = sum(value[1] for value in combined.values())
    total_time = math.fsum(value[2] for value in combined.values())
    if (int(aggregate[0]["Request Count"]) != total_count
            or int(aggregate[0]["Failure Count"]) != total_failures
            or not math.isclose(float(aggregate[0]["Average Response Time"]) * total_count,
                                total_time, rel_tol=1e-8, abs_tol=0.001)):
        raise RuntimeError("Worker/Aggregated totals differ")
    master = {(row["Type"], row["Name"]): row for row in rows if row["Name"] != "Aggregated"}
    if len(master) != len(rows) - 1:
        raise RuntimeError("Duplicate master endpoint")
    if set(master) != set(combined):
        raise RuntimeError("Worker/master endpoint sets differ")
    def percentile(histogram, count, percent):
        target = int(count * percent)
        processed = 0
        for response_time in sorted(histogram, reverse=True):
            processed += histogram[response_time]
            if count - processed <= target:
                return response_time
        return 0

    aggregate_histogram = {}
    for key, (count, failures, total_time, histogram) in combined.items():
        row = master[key]
        if count != int(row["Request Count"]) or failures != int(row["Failure Count"]):
            raise RuntimeError(f"Worker/master counts differ: {key}")
        master_total = float(row["Average Response Time"]) * count
        if not math.isfinite(total_time) or not math.isclose(total_time, master_total, rel_tol=1e-8, abs_tol=0.001):
            raise RuntimeError(f"Worker/master response-time totals differ: {key}")
        for field, percent in (("50%", 0.50), ("95%", 0.95), ("99%", 0.99)):
            calculated = percentile(histogram, count, percent)
            if not math.isclose(float(row[field]), calculated, rel_tol=0, abs_tol=0.001):
                raise RuntimeError(f"Worker/master percentile differs: {key} {field}")
        for bucket, bucket_count in histogram.items():
            aggregate_histogram[bucket] = aggregate_histogram.get(bucket, 0) + bucket_count
    aggregate_count = sum(v[0] for v in combined.values())
    for field, percent in (("50%", 0.50), ("95%", 0.95), ("99%", 0.99)):
        calculated = percentile(aggregate_histogram, aggregate_count, percent)
        if not math.isclose(float(aggregate[0][field]), calculated, rel_tol=0, abs_tol=0.001):
            raise RuntimeError(f"Worker/Aggregated percentile differs: {field}")
    latest_worker_finish = max(
        json.loads(Path(f"{prefix}_worker_{index}_final.json").read_text())["finished_epoch"]
        for index in expected.values()
    )
    return {"valid": True, "workers": len(expected), "requests": aggregate_count,
            "cancelled": 0, "in_flight": 0,
            "stop_propagation_seconds": bounds["finished_epoch"] - manifest["stop_requested_epoch"],
            "drain_seconds": latest_worker_finish - bounds["finished_epoch"],
            "measurement_excludes_drain_and_coordination": True,
            "scope": "all expected workers, endpoint counts, response-time sums and rounded histograms",
            "percentiles_recalculated": [50, 95, 99]}


def install(events, processes):
    import gevent
    from gevent.event import Event
    from locust.runners import MasterRunner, WorkerRunner

    state = {}
    context = {}
    measurement_ready = Event()

    @events.init_command_line_parser.add_listener
    def arguments(parser, **kwargs):
        parser.add_argument("--benchmark-audit-prefix", default="")
        parser.add_argument("--benchmark-measurement-seconds", type=float, default=0)

    @events.init.add_listener
    def configure(environment, **kwargs):
        context["environment"] = environment
        if not isinstance(environment.runner, WorkerRunner):
            # Locust disables the standard CSV prefix in forked workers. Custom
            # parsed options are forwarded in the master's spawn message.
            environment.parsed_options.benchmark_audit_prefix = environment.parsed_options.csv_prefix
        if isinstance(environment.runner, MasterRunner):
            runner = environment.runner
            original_quit = runner.quit

            def quit_after_workers_stop():
                # Locust 2.32.6 quit() otherwise fires test_stop before sending
                # quit to workers. stop() waits for client_stopped acknowledgements.
                runner.stop(send_stop_to_client=True)
                original_quit()

            runner.quit = quit_after_workers_stop
        if not isinstance(environment.runner, WorkerRunner):
            # Let cAdvisor observe the new Locust container before the timed phase.
            gevent.sleep(10)

    def prefix(environment):
        value = (getattr(environment.parsed_options, "csv_prefix", None)
                 or getattr(environment.parsed_options, "benchmark_audit_prefix", None))
        return Path(value) if value else None

    @events.test_start.add_listener
    def start(environment, **kwargs):
        measurement_ready.clear()
        state.clear()
        state.update(started_epoch=None, started_monotonic_ns=None, accepting_requests=False,
                     started=0, in_flight=0, cancelled=0, endpoints={}, latency_buckets={})

    @events.spawning_complete.add_listener
    def begin_measurement(user_count, **kwargs):
        environment = context.get("environment")
        if environment is None:
            raise RuntimeError("Locust environment was not initialized before spawning completed")
        environment.stats.reset_all()
        state.clear()
        state.update(started_epoch=time.time(), started_monotonic_ns=time.monotonic_ns(),
                     accepting_requests=True, started=0, in_flight=0, cancelled=0,
                     endpoints={}, latency_buckets={})
        path = prefix(environment)
        if path is not None:
            runner = environment.runner
            if isinstance(runner, MasterRunner):
                workers = {client.id: runner.get_worker_index(client.id) for client in runner.clients.all}
            elif not isinstance(runner, WorkerRunner):
                workers = {"local": 0}
            else:
                workers = None
            if workers is not None:
                Path(f"{path}_expected_workers.json").write_text(json.dumps({
                    "started_epoch": state["started_epoch"], "processes": processes, "workers": workers,
                }), encoding="utf-8")
        measurement_ready.set()

    @events.request.add_listener
    def completed(request_type, name, response_time, exception, **kwargs):
        row = state["endpoints"].setdefault((request_type, name), {
            "method": request_type, "name": name, "requests": 0, "failures": 0,
            "total_response_time": 0.0, "response_times": {},
        })
        row["requests"] += 1
        row["failures"] += int(exception is not None)
        row["total_response_time"] += response_time
        if response_time < 100:
            rounded = round(response_time)
        elif response_time < 1000:
            rounded = round(response_time, -1)
        elif response_time < 10000:
            rounded = round(response_time, -2)
        else:
            rounded = round(response_time, -3)
        row["response_times"][str(int(rounded))] = row["response_times"].get(str(int(rounded)), 0) + 1
        second = int(time.time())
        bucket = state["latency_buckets"].setdefault((second, request_type, name), {
            "second": second, "method": request_type, "name": name,
            "requests": 0, "total_response_time": 0.0,
        })
        bucket["requests"] += 1
        bucket["total_response_time"] += response_time

    @events.test_stopping.add_listener
    def stopping(environment, **kwargs):
        state["accepting_requests"] = False
        state["stop_requested_epoch"] = time.time()
        state["stop_requested_monotonic_ns"] = time.monotonic_ns()
        state["in_flight_at_stop"] = state["in_flight"]
        state["started_at_stop"] = state["started"]
        path = prefix(environment)
        if path and not isinstance(environment.runner, WorkerRunner):
            manifest_path = Path(f"{path}_expected_workers.json")
            manifest = json.loads(manifest_path.read_text())
            manifest["stop_requested_epoch"] = state["stop_requested_epoch"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    @events.test_stop.add_listener
    def stopped(environment, **kwargs):
        runner = environment.runner
        path = prefix(environment)
        if path is None or isinstance(runner, MasterRunner):
            return
        index = runner.worker_index if isinstance(runner, WorkerRunner) else 0
        identity = runner.client_id if isinstance(runner, WorkerRunner) else "local"
        report = {**state, "worker_id": identity, "finished_epoch": time.time(),
                  "latency_buckets": list(state["latency_buckets"].values()),
                  "endpoints": list(state["endpoints"].values())}
        Path(f"{path}_worker_{index}_final.json").write_text(json.dumps(report), encoding="utf-8")
        if isinstance(runner, WorkerRunner):
            # WorkerRunner fires test_stop before acknowledging the stop to the
            # master. Send completed drain samples while this worker is known.
            runner._send_stats()

    def wrap_client(client):
        original = client.request

        def request(*args, **kwargs):
            if not state.get("accepting_requests", False):
                from locust.exception import StopUser
                raise StopUser()
            state["started"] += 1
            state["in_flight"] += 1
            returned = False
            try:
                response = original(*args, **kwargs)
                returned = True
                return response
            finally:
                state["in_flight"] -= 1
                if not returned:
                    state["cancelled"] += 1

        client.request = request

    wrap_client.wait_until_measurement = measurement_ready.wait
    return wrap_client


def align_bounds_to_worker_stop(prefix: Path) -> dict:
    """Close the aggregate window when the last worker receives the stop command."""
    manifest = json.loads(Path(f"{prefix}_expected_workers.json").read_text())
    bounds_path = Path(f"{prefix}_measurement_bounds.json")
    bounds = json.loads(bounds_path.read_text())
    reports = [
        json.loads(Path(f"{prefix}_worker_{index}_final.json").read_text())
        for index in manifest["workers"].values()
    ]
    if not reports:
        raise RuntimeError("Cannot align measurement bounds without worker reports")
    latest = max(reports, key=lambda report: report["stop_requested_monotonic_ns"])
    bounds["master_stop_requested_epoch"] = manifest["stop_requested_epoch"]
    bounds["master_timer_finished_epoch"] = bounds["finished_epoch"]
    bounds["master_timer_finished_monotonic_ns"] = bounds["finished_monotonic_ns"]
    bounds["finished_epoch"] = latest["stop_requested_epoch"]
    bounds["finished_monotonic_ns"] = latest["stop_requested_monotonic_ns"]
    bounds["finished_at_utc"] = datetime.fromtimestamp(
        bounds["finished_epoch"], timezone.utc
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    bounds["elapsed_seconds"] = (
        bounds["finished_monotonic_ns"] - bounds["started_monotonic_ns"]
    ) / 1_000_000_000
    bounds["wall_elapsed_seconds"] = bounds["finished_epoch"] - bounds["started_epoch"]
    bounds["clock_drift_seconds"] = bounds["wall_elapsed_seconds"] - bounds["elapsed_seconds"]
    bounds["stop_propagation_seconds"] = bounds["finished_epoch"] - manifest["stop_requested_epoch"]
    bounds["window_end_event"] = "last_worker_stop_received_before_bounded_drain"
    bounds["drained_request_rule"] = "started_before_worker_stop_boundary"
    bounds_path.write_text(json.dumps(bounds, separators=(",", ":")), encoding="utf-8")
    return bounds
