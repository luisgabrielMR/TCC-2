from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitoring.results_exporter import read_resources, render_metrics


class ResultsExporterTests(unittest.TestCase):
    def write_csv(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def write_run(self, root: Path, run: int, rps: int) -> None:
        directory = root / "raw" / "python" / "mixed" / f"run_{run}"
        directory.mkdir(parents=True)
        metadata = {
            "methodology_version": 6,
            "result_classification": "official",
            "load_profile": "controlled_50",
            "execution_order": {"position": run, "sequence_id": f"round_{run}"},
            "locust": {"users": 50},
            "test_phase": {"elapsed_seconds": 300},
            "warmup": {"total_duration_seconds": 300},
            "measurement_stability": {"stable": True, "first_last_rps_change_percent": 2},
            "metrics": {"window_source": "locust_test_start_stop"},
            "monitoring_preflight": {"official_eligible": True},
        }
        (directory / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        self.write_csv(directory / "locust_stats.csv", [
            {
                "Type": "GET", "Name": "GET /customers", "Request Count": "1000",
                "Failure Count": "0", "Average Response Time": "15", "Requests/s": str(rps / 2),
                "50%": "12", "95%": "30", "99%": "40",
            },
            {
                "Type": "", "Name": "Aggregated", "Request Count": "2000",
                "Failure Count": "0", "Average Response Time": "20", "Requests/s": str(rps),
                "50%": "15", "95%": "35", "99%": "50",
            },
        ])
        resources = [
            {
                "container_name": "tcc_benchmark_python_api", "cpu_average_percent": "50",
                "cpu_max_percent": "70", "memory_average_bytes": "100000000", "memory_max_bytes": "120000000",
                "network_rx_delta_bytes": "1000", "network_tx_delta_bytes": "2000",
            },
            {
                "container_name": "tcc_benchmark_locust", "cpu_average_percent": "40",
                "cpu_max_percent": "60", "memory_average_bytes": "80000000", "memory_max_bytes": "90000000",
                "network_rx_delta_bytes": "0", "network_tx_delta_bytes": "0",
            },
            {
                "container_name": "tcc_benchmark_postgres", "cpu_average_percent": "30",
                "cpu_max_percent": "55", "memory_average_bytes": "200000000", "memory_max_bytes": "250000000",
                "network_rx_delta_bytes": "0", "network_tx_delta_bytes": "0",
            },
        ]
        self.write_csv(directory / "docker_stats_summary.csv", resources)
        self.write_csv(directory / "cadvisor_summary.csv", resources)
        self.write_csv(directory / "postgres_summary.csv", [{
            "samples": "60", "connections_average": "12", "connections_max": "20",
            "commits_total": "2000", "rollbacks_total": "0", "commits_per_second": "6.67",
            "rollbacks_per_second": "0", "blocks_read_total": "10", "blocks_hit_total": "9990",
            "cache_hit_ratio": "0.999", "database_size_average_bytes": "50000000",
            "database_size_max_bytes": "51000000", "metric_source": "postgres_exporter_via_prometheus",
        }])

    def test_exports_consolidated_and_live_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            results = Path(temp)
            for run, rps in enumerate((100, 102, 104), start=1):
                self.write_run(results, run, rps)
            latest = results / "raw" / "python" / "mixed" / "run_3"
            self.write_csv(latest / "locust_stats_history.csv", [{
                "Timestamp": "1", "User Count": "50", "Type": "", "Name": "Aggregated",
                "Requests/s": "103", "Failures/s": "0", "50%": "15", "95%": "35", "99%": "50",
                "Total Request Count": "2100", "Total Failure Count": "0", "Total Average Response Time": "20",
            }])
            self.write_csv(latest / "docker_stats_raw.csv", [{
                "timestamp_utc": "2026-01-01T00:00:00Z", "container_name": "tcc_benchmark_python_api",
                "container_id": "abc", "cpu_percent": "52", "memory_usage_bytes": "101000000",
                "memory_limit_bytes": "1000000000", "network_rx_bytes": "100", "network_tx_bytes": "200",
                "block_read_bytes": "0", "block_write_bytes": "0", "pids": "12",
            }])

            output = render_metrics(results)

        self.assertIn("benchmark_results_completed_runs 3", output)
        self.assertIn('benchmark_result_confidence{campaign="legacy",classification="official",language="python",load_profile="controlled_50",methodology="6",scenario="mixed",status="adequate",users="50"} 1', output)
        self.assertIn('benchmark_result_throughput_rps{campaign="legacy",classification="official",language="python",load_profile="controlled_50",methodology="6",scenario="mixed",stat="median",users="50"} 102', output)
        self.assertIn('benchmark_run_throughput_rps{campaign="legacy",classification="official",language="python",load_profile="controlled_50",methodology="6",run="1",scenario="mixed",users="50"} 100', output)
        self.assertIn('benchmark_endpoint_latency_ms{campaign="legacy",classification="official",endpoint="GET /customers"', output)
        self.assertIn('metric_source="cadvisor_via_prometheus"', output)
        self.assertIn('benchmark_result_postgres_connections{campaign="legacy",classification="official",language="python"', output)
        self.assertNotIn("benchmark_result_network_bytes", output)
        self.assertIn("benchmark_live_locust_rps", output)
        self.assertIn("benchmark_live_container_cpu_percent", output)

    def test_official_methodology_six_never_falls_back_to_docker_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write_csv(root / "docker_stats_summary.csv", [{
                "container_name": "tcc_benchmark_python_api",
                "cpu_average_percent": "99",
            }])
            rows, source = read_resources(root, {
                "methodology_version": 6,
                "result_classification": "official",
            })
        self.assertEqual(rows, [])
        self.assertEqual(source, "cadvisor_via_prometheus")

    def test_missing_official_cadvisor_is_not_exported_as_zero_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            results = Path(temp)
            self.write_run(results, 1, 100)
            (results / "raw" / "python" / "mixed" / "run_1" / "cadvisor_summary.csv").unlink()
            output = render_metrics(results)

        self.assertNotIn("benchmark_result_cpu_percent", output)
        self.assertNotIn("benchmark_result_memory_bytes", output)
        self.assertIn("benchmark_result_postgres_connections", output)
        self.assertIn('status="invalid_missing_resources"', output)


if __name__ == "__main__":
    unittest.main()
