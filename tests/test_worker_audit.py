import csv
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "load-tests" / "locust"))
from measurement_audit import CooperativeStopMixin, install, validate_worker_reports

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.validate_monitoring import cadvisor_collection_config


class WorkerAuditTests(unittest.TestCase):
    def test_graceful_stop_never_schedules_a_kill_for_waiting_users(self):
        calls = []

        class Parent:
            def stop(self, force=False):
                calls.append(force)
                return True

        class User(CooperativeStopMixin, Parent):
            pass

        states = SimpleNamespace(LOCUST_STATE_RUNNING="running", LOCUST_STATE_WAITING="waiting",
                                 LOCUST_STATE_STOPPING="stopping")
        with patch.dict(sys.modules, {"locust.user.task": states}):
            user = User()
            for state in ("running", "waiting", "stopping"):
                user._state = state
                self.assertFalse(user.stop())
                self.assertEqual(user._state, "stopping")
                self.assertEqual(calls, [])
            self.assertTrue(user.stop(force=True))
            self.assertEqual(calls, [True])
            user._state = None
            self.assertTrue(user.stop())
            self.assertEqual(calls, [True, False])

    def test_cadvisor_requires_fixed_runtime_sampling(self):
        with patch("scripts.validate_monitoring.subprocess.run") as run:
            run.return_value.stdout = json.dumps(["--allow_dynamic_housekeeping=false", "--housekeeping_interval=1s"])
            self.assertTrue(cadvisor_collection_config()["fixed_interval_valid"])
            run.return_value.stdout = json.dumps(["--housekeeping_interval=1s"])
            self.assertFalse(cadvisor_collection_config()["fixed_interval_valid"])
            run.return_value.stdout = json.dumps(["--allow_dynamic_housekeeping=false", "--housekeeping_interval=1s", "--allow_dynamic_housekeeping=true"])
            self.assertFalse(cadvisor_collection_config()["fixed_interval_valid"])

    def test_master_quit_stops_workers_before_original_quit(self):
        class Event:
            def __init__(self):
                self.listeners = []

            def add_listener(self, listener):
                self.listeners.append(listener)
                return listener

        calls = []

        class Master:
            def stop(self, send_stop_to_client):
                calls.append(("stop", send_stop_to_client))

            def quit(self):
                calls.append(("quit",))

        events = SimpleNamespace(**{key: Event() for key in
            ("init_command_line_parser", "init", "test_start", "request", "test_stopping", "test_stop")})
        runners = SimpleNamespace(MasterRunner=Master, WorkerRunner=type("Worker", (), {}))
        fake_gevent = SimpleNamespace(sleep=lambda seconds: None)
        with patch.dict(sys.modules, {"locust.runners": runners, "gevent": fake_gevent}):
            install(events, 4)
        environment = SimpleNamespace(runner=Master(), parsed_options=SimpleNamespace(csv_prefix="/tmp/locust"))
        events.init.listeners[0](environment)
        self.assertEqual(environment.parsed_options.benchmark_audit_prefix, "/tmp/locust")
        environment.runner.quit()
        self.assertEqual(calls, [("stop", True), ("quit",)])

    def test_reconciliation_and_failure_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "locust"
            manifest = {"workers": {"worker-a": 0, "worker-b": 1}, "processes": 2,
                        "started_epoch": 100, "stop_requested_epoch": 129}
            Path(f"{prefix}_expected_workers.json").write_text(json.dumps(manifest))
            Path(f"{prefix}_measurement_bounds.json").write_text(json.dumps({"finished_epoch": 131}))
            row = {"method": "GET", "name": "GET /health", "requests": 5,
                   "failures": 0, "total_response_time": 10.0}
            report = {"started_epoch": 100.01, "finished_epoch": 130, "in_flight": 0,
                      "cancelled": 0, "started": 5, "endpoints": [row]}
            first = Path(f"{prefix}_worker_0_final.json")
            second = Path(f"{prefix}_worker_1_final.json")
            first.write_text(json.dumps({**report, "worker_id": "worker-a"}))
            second.write_text(json.dumps({**report, "worker_id": "worker-b"}))
            stats = Path(f"{prefix}_final_stats.csv")
            with stats.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Type", "Name", "Request Count", "Failure Count", "Average Response Time"])
                writer.writeheader()
                writer.writerow({"Type": "GET", "Name": "GET /health", "Request Count": 10,
                                 "Failure Count": 0, "Average Response Time": 2})
                writer.writerow({"Type": "", "Name": "Aggregated", "Request Count": 10,
                                 "Failure Count": 0, "Average Response Time": 2})
            result = validate_worker_reports(prefix, stats)
            self.assertEqual(result["requests"], 10)
            self.assertEqual(result["workers"], 2)
            self.assertEqual(result["drain_and_coordination_seconds"], 2)
            for change in ({"cancelled": 1}, {"in_flight": 1}, {"started": 6},
                           {"worker_id": "wrong"}, {"started_epoch": 90}, {"finished_epoch": 132},
                           {"started_epoch": float("nan")}, {"started_epoch": float("inf")},
                           {"started_epoch": True}, {"finished_epoch": float("nan")},
                           {"endpoints": [{**row, "total_response_time": 99}]},
                           {"endpoints": [{**row, "failures": 1}]}):
                with self.subTest(change=change):
                    first.write_text(json.dumps({**report, "worker_id": "worker-a", **change}))
                    with self.assertRaises(RuntimeError):
                        validate_worker_reports(prefix, stats)
            first.write_text(json.dumps({**report, "worker_id": "worker-a"}))
            second.unlink()
            with self.assertRaises(FileNotFoundError):
                validate_worker_reports(prefix, stats)


if __name__ == "__main__":
    unittest.main()
