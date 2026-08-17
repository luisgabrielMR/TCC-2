from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.summarize_results import duration_from_metadata, measurement_status, scalability_rows
from scripts.validate_warmup_stability import DEFAULT_SCENARIOS, validate


class WarmupValidationTests(unittest.TestCase):
    def write_fixture(self, root: Path, include_writes: bool = True) -> tuple[Path, Path]:
        config = json.loads(DEFAULT_SCENARIOS.read_text(encoding="utf-8"))
        endpoints = [entry["endpoint"] for entry in config["scenarios"]["mixed"]]
        if not include_writes:
            endpoints = [endpoint for endpoint in endpoints if not endpoint.startswith(("POST", "PUT"))]

        stats = root / "locust_stats.csv"
        with stats.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["Name", "Request Count", "Failure Count"])
            writer.writeheader()
            for endpoint in endpoints:
                writer.writerow({"Name": endpoint, "Request Count": 100, "Failure Count": 0})
            writer.writerow({"Name": "Aggregated", "Request Count": 800, "Failure Count": 0})

        history = root / "locust_stats_history.csv"
        with history.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["Timestamp", "User Count", "Name", "Total Request Count"],
            )
            writer.writeheader()
            for timestamp, requests in ((1, 0), (46, 4500), (91, 9000), (136, 13500)):
                writer.writerow({
                    "Timestamp": timestamp,
                    "User Count": 50,
                    "Name": "Aggregated",
                    "Total Request Count": requests,
                })

        (root / "locust_exceptions.csv").write_text("Count,Message,Traceback,Nodes\n", encoding="utf-8")
        return stats, history

    def test_mixed_warmup_is_stable_when_all_routes_are_covered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stats, history = self.write_fixture(Path(temp))
            result = validate(stats, history, "mixed", DEFAULT_SCENARIOS, 45, 10)
        self.assertTrue(result["stable"])
        self.assertEqual(result["missing_endpoints"], [])
        self.assertEqual(result["rps_drift_percent"], 0)

    def test_mixed_warmup_rejects_read_only_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stats, history = self.write_fixture(Path(temp), include_writes=False)
            result = validate(stats, history, "mixed", DEFAULT_SCENARIOS, 45, 10)
        self.assertFalse(result["stable"])
        self.assertEqual(result["missing_endpoints"], [
            "POST /customers", "PUT /customers/{id}", "POST /orders",
        ])

    def test_warmup_allows_initial_change_when_three_final_windows_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stats, history = self.write_fixture(root)
            with history.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["Timestamp", "User Count", "Name", "Total Request Count"],
                )
                writer.writeheader()
                for timestamp, requests in ((1, 0), (46, 4500), (91, 11250), (136, 18000), (181, 24750)):
                    writer.writerow({
                        "Timestamp": timestamp,
                        "User Count": 50,
                        "Name": "Aggregated",
                        "Total Request Count": requests,
                    })
            result = validate(stats, history, "mixed", DEFAULT_SCENARIOS, 45, 10)
        self.assertTrue(result["stable"])
        self.assertEqual(result["rps_drift_percent"], 0)
        self.assertEqual(result["first_last_rps_drift_percent"], 50)
        self.assertEqual(result["first_last_rps_change_percent"], 50)

    def test_warmup_rejects_transition_inside_three_final_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stats, history = self.write_fixture(root)
            with history.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["Timestamp", "User Count", "Name", "Total Request Count"],
                )
                writer.writeheader()
                for timestamp, requests in ((1, 0), (46, 4500), (91, 9000), (136, 15750)):
                    writer.writerow({
                        "Timestamp": timestamp,
                        "User Count": 50,
                        "Name": "Aggregated",
                        "Total Request Count": requests,
                    })
            result = validate(stats, history, "mixed", DEFAULT_SCENARIOS, 45, 10)
        self.assertFalse(result["stable"])
        self.assertEqual(result["rps_drift_percent"], 50)

    def test_warmup_rejects_when_expected_user_count_is_not_reached(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stats, history = self.write_fixture(Path(temp))
            result = validate(stats, history, "mixed", DEFAULT_SCENARIOS, 45, 10, expected_users=100)
        self.assertFalse(result["stable"])
        self.assertEqual(result["expected_users"], 100)
        self.assertEqual(result["observed_peak_users"], 50)
        self.assertIn("peak user count 50 does not match expected 100", result["reasons"])


class SummaryTests(unittest.TestCase):
    def test_duration_prefers_exact_test_phase(self) -> None:
        elapsed, source = duration_from_metadata({
            "test_phase": {"elapsed_seconds": 301.25},
            "metrics": {"started_epoch": 100, "finished_epoch": 500},
        })
        self.assertEqual((elapsed, source), (301.25, "test_phase"))

    def test_duration_supports_legacy_metrics(self) -> None:
        elapsed, source = duration_from_metadata({"metrics": {"started_epoch": 100, "finished_epoch": 407}})
        self.assertEqual((elapsed, source), (307, "metrics_window_legacy"))

    def test_measurement_trend_statuses(self) -> None:
        self.assertEqual(measurement_status(12, True), "possible_late_warmup")
        self.assertEqual(measurement_status(12, False), "fluctuating")
        self.assertEqual(measurement_status(-12, True), "decreasing_throughput")
        self.assertEqual(measurement_status(2, False), "fluctuating")
        self.assertEqual(measurement_status(2, True), "stable")

    def test_scalability_marks_flat_throughput_as_probable_saturation(self) -> None:
        common = {
            "language": "node", "run": "1", "failures": 0, "requests": 1000,
            "p95_ms": 100, "test_elapsed_seconds": 300, "cpu_average_percent": 50,
            "locust_cpu_average_percent": 60, "postgres_cpu_average_percent": 40,
        }
        rows = [
            {**common, "scenario": "mixed", "users": 50, "throughput_rps": 500},
            {**common, "scenario": "mixed_capacity_100", "users": 100, "throughput_rps": 530},
        ]
        result = scalability_rows(rows)
        self.assertEqual(result[1]["capacity_status"], "probable_saturation")

    def test_scalability_excludes_legacy_baseline_when_current_run_exists(self) -> None:
        common = {
            "language": "node", "run": "1", "failures": 0, "requests": 1000,
            "p95_ms": 100, "test_elapsed_seconds": 300, "cpu_average_percent": 50,
            "locust_cpu_average_percent": 60, "postgres_cpu_average_percent": 40,
        }
        rows = [
            {
                **common, "scenario": "mixed", "users": 50, "throughput_rps": 900,
                "load_profile": "legacy",
            },
            {
                **common, "scenario": "mixed", "users": 50, "throughput_rps": 500,
                "load_profile": "controlled_50", "methodology_version": 1, "run": "2",
            },
            {
                **common, "scenario": "mixed", "users": 50, "throughput_rps": 510,
                "load_profile": "controlled_50", "methodology_version": 2, "run": "3",
            },
            {
                **common, "scenario": "mixed_capacity_100", "users": 100,
                "throughput_rps": 561, "load_profile": "capacity_100", "methodology_version": 2,
            },
        ]
        result = scalability_rows(rows)
        self.assertEqual(result[0]["runs"], 1)
        self.assertEqual(result[0]["throughput_rps"], "510.000")
        self.assertEqual(result[1]["rps_gain_vs_50_percent"], "10.000")


if __name__ == "__main__":
    unittest.main()
