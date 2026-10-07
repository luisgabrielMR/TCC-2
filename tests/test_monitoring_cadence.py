import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.validate_monitoring import build_report


class MonitoringCadenceTests(unittest.TestCase):
    def test_direct_cli_imports_work_with_isolated_python_outside_repository(self):
        # --help exits before any Docker, Prometheus or Grafana interaction.
        # A subprocess cannot inherit the sys.path fixup used by this test module.
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-B", str(ROOT / "scripts/validate_monitoring.py"), "--help"],
                cwd=directory, capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--minimum-cadvisor-coverage-percent", result.stdout)

    def report(self, timestamps):
        identifiers = {
            "tcc_benchmark_python_api": "api-id",
            "tcc_benchmark_postgres": "postgres-id",
            "tcc_benchmark_locust": "locust-id",
        }
        series = [{
            "metric": {"id": f"/docker/{identifier}"}, "value": [33, "1"],
            "values": [[t, str(t + 10)] for t in timestamps],
        } for identifier in identifiers.values()]
        targets = [{"labels": {"job": job}, "health": "up", "scrapeInterval": "1s"}
                   for job in ("cadvisor", "postgres", "prometheus", "benchmark-results")]

        def instant_query(_, metric):
            return series if metric.startswith("container_") else [{"value": [33, "1"]}]

        def grafana(_, path):
            if path == "/api/health":
                return {"database": "ok"}
            return [{"title": "TCC Benchmark - Resultados Oficiais"},
                    {"title": "TCC Benchmark - Monitoramento e Diagnostico"}]

        with (
            patch("scripts.validate_monitoring.prometheus_get", return_value={
                "data": {"activeTargets": targets},
            }),
            patch("scripts.validate_monitoring.query_series", side_effect=instant_query),
            patch("scripts.validate_monitoring.query_sample_window", return_value=series),
            patch("scripts.validate_monitoring.container_id", side_effect=identifiers.get),
            patch("scripts.validate_monitoring.cadvisor_collection_config", return_value={
                "fixed_interval_valid": True,
            }),
            patch("scripts.validate_monitoring.grafana_get", side_effect=grafana),
            patch("scripts.validate_monitoring.time.time", return_value=33),
        ):
            return build_report("http://unused", "http://unused", "python-api", "official")

    def test_up_targets_do_not_make_jittered_samples_official(self):
        # A one-second nominal collector can still produce 1.8s source gaps.
        timestamps = sorted([i * 3 for i in range(12)] + [i * 3 + 1.2 for i in range(12)])
        report = self.report(timestamps)
        self.assertTrue(report["operational_eligible"])
        self.assertFalse(report["official_eligible"])
        self.assertTrue(all(item["available"] for item in report["cadvisor_components"].values()))
        self.assertTrue(any("scrape_gap_1.800000s" in reason for reason in report["official_blockers"]))

    def test_continuous_source_samples_allow_official_preflight(self):
        report = self.report(range(34))
        self.assertTrue(report["official_eligible"], report["official_blockers"])
        for details in report["cadvisor_components"].values():
            self.assertEqual(details["sample_quality"]["metrics"]["cpu"]["coverage_percent"], 100)

    def test_new_series_must_fill_the_preflight_window(self):
        report = self.report(range(25, 34))
        self.assertFalse(report["official_eligible"])
        self.assertTrue(any("coverage_20.0_percent" in reason for reason in report["official_blockers"]))


if __name__ == "__main__":
    unittest.main()
