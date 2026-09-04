"""Independent end-of-run counters; one file per worker, no per-request I/O."""
import csv
import json
import math
import time
from pathlib import Path


def validate_worker_reports(prefix: Path, stats_path: Path) -> dict:
    manifest = json.loads(Path(f"{prefix}_expected_workers.json").read_text())
    bounds = json.loads(Path(f"{prefix}_measurement_bounds.json").read_text())
    expected = manifest["workers"]
    if not expected or len(set(expected.values())) != len(expected) or len(expected) != manifest["processes"]:
        raise RuntimeError("Invalid expected worker manifest")
    combined = {}
    for identity, index in expected.items():
        path = Path(f"{prefix}_worker_{index}_final.json")
        report = json.loads(path.read_text())
        if report["worker_id"] != identity or report["started_epoch"] < manifest["started_epoch"] - 0.05:
            raise RuntimeError(f"Stale or unexpected worker report: {path}")
        if not math.isfinite(report["finished_epoch"]) or report["finished_epoch"] < report["started_epoch"]:
            raise RuntimeError(f"Invalid worker timestamps: {path}")
        if report["finished_epoch"] > bounds["finished_epoch"] + 0.05:
            raise RuntimeError(f"Worker {index} finished outside the measurement window")
        if report["in_flight"] != 0 or report["cancelled"] != 0:
            raise RuntimeError(f"Worker {index} has unfinished/cancelled requests")
        completed = sum(row["requests"] for row in report["endpoints"])
        if completed != report["started"]:
            raise RuntimeError(f"Worker {index} request lifecycle does not reconcile")
        for row in report["endpoints"]:
            key = (row["method"], row["name"])
            value = combined.setdefault(key, [0, 0, 0.0])
            value[0] += row["requests"]
            value[1] += row["failures"]
            value[2] += row["total_response_time"]
    with stats_path.open(encoding="utf-8-sig", newline="") as handle:
        master = {(row["Type"], row["Name"]): row for row in csv.DictReader(handle) if row["Name"] != "Aggregated"}
    if set(master) != set(combined):
        raise RuntimeError("Worker/master endpoint sets differ")
    for key, (count, failures, total_time) in combined.items():
        row = master[key]
        if count != int(row["Request Count"]) or failures != int(row["Failure Count"]):
            raise RuntimeError(f"Worker/master counts differ: {key}")
        master_total = float(row["Average Response Time"]) * count
        if not math.isfinite(total_time) or not math.isclose(total_time, master_total, rel_tol=1e-8, abs_tol=0.001):
            raise RuntimeError(f"Worker/master response-time totals differ: {key}")
    return {"valid": True, "workers": len(expected), "requests": sum(v[0] for v in combined.values()),
            "cancelled": 0, "in_flight": 0,
            "drain_and_coordination_seconds": bounds["finished_epoch"] - manifest["stop_requested_epoch"],
            "scope": "all expected workers, endpoint counts and response-time sums"}


def install(events, processes):
    import gevent
    from locust.runners import MasterRunner, WorkerRunner

    state = {}

    @events.init_command_line_parser.add_listener
    def arguments(parser, **kwargs):
        parser.add_argument("--benchmark-audit-prefix", default="")

    @events.init.add_listener
    def configure(environment, **kwargs):
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
        state.clear()
        state.update(started_epoch=time.time(), started=0, in_flight=0, cancelled=0, endpoints={})
        path = prefix(environment)
        if path is None:
            return
        runner = environment.runner
        if isinstance(runner, MasterRunner):
            workers = {client.id: runner.get_worker_index(client.id) for client in runner.clients.all}
        elif not isinstance(runner, WorkerRunner):
            workers = {"local": 0}
        else:
            return
        Path(f"{path}_expected_workers.json").write_text(json.dumps({
            "started_epoch": state["started_epoch"], "processes": processes, "workers": workers,
        }), encoding="utf-8")

    @events.request.add_listener
    def completed(request_type, name, response_time, exception, **kwargs):
        row = state["endpoints"].setdefault((request_type, name), {
            "method": request_type, "name": name, "requests": 0, "failures": 0, "total_response_time": 0.0,
        })
        row["requests"] += 1
        row["failures"] += int(exception is not None)
        row["total_response_time"] += response_time

    @events.test_stopping.add_listener
    def stopping(environment, **kwargs):
        state["stop_requested_epoch"] = time.time()
        state["in_flight_at_stop"] = state["in_flight"]
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
                  "endpoints": list(state["endpoints"].values())}
        Path(f"{path}_worker_{index}_final.json").write_text(json.dumps(report), encoding="utf-8")
        if isinstance(runner, WorkerRunner):
            # Same ordered RPC channel as client_stopped. The master receives
            # final deltas before acknowledging this worker as stopped.
            runner._send_stats()

    def wrap_client(client):
        original = client.request

        def request(*args, **kwargs):
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

    return wrap_client
