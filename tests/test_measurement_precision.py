import json
import csv
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.export_prometheus_data import (
    clean_samples, matching_series, metric_matches, query_range, query_samples,
    sample_quality, write_postgres_summary,
)
from scripts.finalize_locust_csv import validate_stats, promote
from scripts.validate_measurement_bounds import validate_bounds


class MeasurementPrecisionTests(unittest.TestCase):
    def test_long_run_does_not_relax_clock_alignment(self):
        report = validate_bounds({
            "started_epoch": 0, "finished_epoch": 300.2,
            "started_at_utc": "1970-01-01T00:00:00Z",
            "finished_at_utc": "1970-01-01T00:05:00.200000Z",
            "elapsed_seconds": 300, "wall_elapsed_seconds": 300.2,
            "duration_clock": "time.monotonic_ns", "boundary_clock": "time.time_ns",
        })
        self.assertFalse(report["valid"])
        self.assertEqual(report["clock_drift_tolerance_seconds"], 0.05)

    def test_final_csv_checks_counts_and_percentiles_before_promotion(self):
        valid = {"Type": "GET", "Name": "GET /health", "Request Count": "10", "Failure Count": "0",
                 "Average Response Time": "1.5", "50%": "1", "95%": "2", "99%": "3"}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "locust_final_stats.csv"

            def write(row, aggregate_count="10"):
                with path.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(valid))
                    writer.writeheader()
                    writer.writerows([row, {**valid, "Type": "", "Name": "Aggregated", "Request Count": aggregate_count}])

            write(valid)
            self.assertTrue(validate_stats(path)["valid"])
            write(valid, "11")
            with self.assertRaisesRegex(RuntimeError, "endpoint sum"):
                validate_stats(path)
            for overrides in ({"95%": "0"}, {"99%": "nan"}, {"Failure Count": "11"}):
                write({**valid, **overrides})
                with self.assertRaisesRegex(RuntimeError, "Invalid final CSV row"):
                    validate_stats(path)
            destination = Path(temp) / "locust_stats.csv"
            destination.write_text("previous snapshot")
            with self.assertRaisesRegex(RuntimeError, "did not produce final snapshot"):
                promote(Path(temp) / "locust")
            self.assertEqual(destination.read_text(), "previous snapshot")

    def test_fetch_preserves_scrape_timestamps_instead_of_resampling(self):
        response = {"status": "success", "data": {"resultType": "matrix", "result": []}}
        with patch("scripts.export_prometheus_data.urllib.request.urlopen") as fetch:
            fetch.return_value.__enter__.return_value.read.return_value = json.dumps(response)
            self.assertEqual(query_range("http://localhost:9090", 'up{job="postgres"}', 100, 110, 5), response)
        url = urlparse(fetch.call_args.args[0])
        self.assertEqual(url.path, "/api/v1/query")
        self.assertEqual(parse_qs(url.query)["query"], ['up{job="postgres"}[10001ms]'])
        self.assertEqual(parse_qs(url.query)["time"], ["110"])

    def test_rejects_failed_prometheus_response(self):
        with patch("scripts.export_prometheus_data.urllib.request.urlopen") as fetch:
            fetch.return_value.__enter__.return_value.read.return_value = '{"status":"error"}'
            with self.assertRaises(RuntimeError):
                query_range("http://localhost", "up", 100, 110, 5)

    def test_internal_gap_does_not_count_as_full_coverage(self):
        quality = sample_quality([(0, 1), (5, 2), (95, 3), (100, 4)], 0, 100, 7.5)
        self.assertEqual(quality["covered_seconds"], 10)
        self.assertEqual(quality["maximum_gap_seconds"], 90)

    def test_counter_reset_is_not_treated_as_exact_delta(self):
        quality = sample_quality([(0, 20), (5, 2), (10, 5)], 0, 10, 7.5, True)
        self.assertEqual(quality["counter_resets"], 1)
        self.assertEqual(quality["covered_seconds"], 5)

    def test_known_id_never_falls_back_to_another_container(self):
        series = [{"metric": {"id": "/docker/old", "container_label_com_docker_compose_service": "locust"}}]
        self.assertEqual(matching_series(series, "locust", "locust", ["measured"]), [])
        self.assertFalse(metric_matches({"id": "/", "container_label_com_docker_compose_service": "locust"}, "locust", ""))

    def test_multiple_database_targets_are_ambiguous(self):
        result = {"queries": {"commits": {"response": {"data": {"result": [{}, {}]}}}}}
        with self.assertRaisesRegex(RuntimeError, "Ambiguous"):
            query_samples(result, "commits")

    def test_nonfinite_samples_are_excluded(self):
        self.assertEqual(clean_samples({"values": [[0, "nan"], [1, "inf"], [2, "3"]]}), [(2, 3)])

    def test_official_postgres_rejects_gaps_and_resets(self):
        keys = ("postgres_up", "postgres_connections", "postgres_commits_total", "postgres_rollbacks_total",
                "postgres_blocks_read", "postgres_blocks_hit", "postgres_database_size_bytes")
        for values, end in (([[0, "1"], [100, "2"]], 100), ([[0, "20"], [5, "2"]], 5)):
            with self.subTest(values=values), tempfile.TemporaryDirectory() as temp:
                result = {"start_epoch": 0, "end_epoch": end, "step_seconds": 5, "queries": {
                    key: {"response": {"data": {"result": [{"values": values}]}}} for key in keys}}
                with self.assertRaisesRegex(RuntimeError, "reset or scrape gap"):
                    write_postgres_summary(Path(temp) / "out.csv", result, require=True)


if __name__ == "__main__":
    unittest.main()
