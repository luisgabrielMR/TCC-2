from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.collect_docker_stats import measured_rows
from scripts.compare_json import first_difference
from scripts.export_prometheus_data import (
    counter_window_delta,
    matching_series,
    metric_matches,
    sampled_container_ids,
    series_cpu_rates,
    write_postgres_summary,
)
import scripts.generate_results_dashboard as dashboard
from scripts.preflight import verification_matches_current_project
import scripts.summarize_results as summary
from scripts.summarize_results import duration_from_metadata, measurement_status, result_confidence, scalability_rows
from scripts.validate_monitoring import (
    metric_matches as monitoring_metric_matches,
    wait_for_official_evidence,
)
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
            "resource_metrics_available": True,
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
            "resource_metrics_available": True,
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

    def test_confidence_requires_three_clean_stable_runs(self) -> None:
        clean = {
            "failures": 0,
            "resource_metrics_available": True,
            "exact_measurement_window": True,
            "locust_cpu_max_percent": 70,
            "measurement_stability_status": "stable",
            "throughput_rps": 1000,
        }
        self.assertEqual(result_confidence([clean, clean]), "preliminary_fewer_than_3_runs")
        ordered = [{**clean, "execution_order_position": position} for position in (1, 2, 3)]
        self.assertEqual(result_confidence(ordered), "adequate")
        self.assertEqual(result_confidence([{**ordered[0], "locust_cpu_max_percent": 90}, *ordered[1:]]), "invalid_load_generator")
        variable = [{**row, "throughput_rps": rps} for row, rps in zip(ordered, (800, 1000, 1200))]
        self.assertEqual(result_confidence(variable), "invalid_run_variability")

    def test_dashboard_accepts_an_empty_results_directory(self) -> None:
        original_raw = dashboard.RAW
        try:
            with tempfile.TemporaryDirectory() as temp:
                dashboard.RAW = Path(temp)
                data = dashboard.collect()
        finally:
            dashboard.RAW = original_raw
        self.assertEqual(data["scenarios"], {})
        self.assertEqual(data["scalability"], {})


class ResourceWindowTests(unittest.TestCase):
    def test_docker_summary_uses_only_exact_load_window(self) -> None:
        rows = [
            {"timestamp_utc": "2026-01-01T00:00:00.000Z"},
            {"timestamp_utc": "2026-01-01T00:00:02.000Z"},
            {"timestamp_utc": "2026-01-01T00:00:04.000Z"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            bounds = Path(temp) / "bounds.json"
            bounds.write_text(json.dumps({
                "started_epoch": 1767225601,
                "finished_epoch": 1767225603,
            }), encoding="utf-8")
            selected = measured_rows(rows, bounds)
        self.assertEqual(selected, [rows[1]])

    def test_official_methodology_six_never_falls_back_to_docker_stats(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docker_stats_summary.csv").write_text(
                "container_name,cpu_average_percent\ntcc_benchmark_python_api,99\n",
                encoding="utf-8",
            )
            rows, source = summary.read_resource_rows(root, {
                "methodology_version": 6,
                "result_classification": "official",
            })
        self.assertEqual(rows, [])
        self.assertEqual(source, "cadvisor_via_prometheus")

    def test_cadvisor_series_can_be_matched_by_full_or_short_container_id(self) -> None:
        identifier = "abcdef1234567890"
        self.assertTrue(metric_matches({"id": "/docker/abcdef1234567890"}, "python-api", "missing", identifier))
        self.assertTrue(metric_matches({"id": "/docker/abcdef123456"}, "python-api", "missing", identifier))
        self.assertFalse(metric_matches({"id": "/docker/different"}, "python-api", "missing", identifier))

    def test_transient_locust_id_is_recovered_from_resource_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            summary_path = Path(temp) / "cadvisor_summary.csv"
            (summary_path.parent / "docker_stats_raw.csv").write_text(
                "container_name,container_id\ntcc-benchmark-locust-run-123,locust-id\n",
                encoding="utf-8",
            )
            identifiers = sampled_container_ids(summary_path, "locust", "tcc_benchmark_locust")
        self.assertEqual(identifiers, ["locust-id"])

    def test_cadvisor_cpu_uses_only_deltas_inside_the_exported_window(self) -> None:
        series = [{
            "metric": {"container_label_com_docker_compose_service": "python-api"},
            "values": [[100, "10"], [105, "11"], [110, "11.5"]],
        }]
        self.assertEqual(series_cpu_rates(series, "python-api", "unused"), [20.0, 10.0])

    def test_measured_container_id_excludes_stale_series_with_the_same_service_label(self) -> None:
        series = [
            {"metric": {"id": "/docker/old", "container_label_com_docker_compose_service": "locust"}},
            {"metric": {"id": "/docker/measured", "container_label_com_docker_compose_service": "locust"}},
        ]
        selected = matching_series(series, "locust", "tcc_benchmark_locust", ["measured"])
        self.assertEqual(selected, [series[1]])

    def test_postgres_counter_uses_only_deltas_inside_the_window(self) -> None:
        self.assertEqual(counter_window_delta([2, 5, 9]), 7)
        self.assertEqual(counter_window_delta([900, 950, 3, 8, 10]), 60)
        self.assertEqual(counter_window_delta([9]), 0)

    def test_postgres_summary_requires_and_reduces_a_complete_window(self) -> None:
        def response(values: list[float]) -> dict:
            return {"data": {"result": [{
                "values": [[100 + index * 5, str(value)] for index, value in enumerate(values)]
            }]}}

        series = {
            "postgres_up": [1, 1, 1],
            "postgres_connections": [4, 8, 6],
            "postgres_commits_total": [100, 105, 107],
            "postgres_rollbacks_total": [2, 2, 3],
            "postgres_blocks_read": [10, 12, 13],
            "postgres_blocks_hit": [1000, 1040, 1097],
            "postgres_database_size_bytes": [50_000_000, 50_100_000, 50_200_000],
        }
        result = {
            "start_epoch": 100,
            "end_epoch": 110,
            "queries": {key: {"response": response(values)} for key, values in series.items()},
        }
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "postgres_summary.csv"
            write_postgres_summary(output, result, require=True)
            with output.open("r", encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["commits_total"], "7.000000")
            self.assertEqual(row["commits_per_second"], "0.700000")
            self.assertEqual(row["blocks_read_total"], "3.000000")
            self.assertEqual(row["blocks_hit_total"], "97.000000")

            incomplete = {
                **result,
                "queries": {
                    key: {"response": response(values[:1])}
                    for key, values in series.items()
                },
            }
            with self.assertRaisesRegex(RuntimeError, "insufficient_samples"):
                write_postgres_summary(output, incomplete, require=True)


class JsonComparisonTests(unittest.TestCase):
    def test_reports_nested_database_state_field(self) -> None:
        expected = {"auditLogs": [{"payload": {"payment": {"method": "pix"}}}]}
        actual = {"auditLogs": [{"payload": {"payment": {"method": "boleto"}}}]}
        difference = first_difference(expected, actual)
        self.assertEqual(
            difference,
            "$.auditLogs[0].payload.payment.method: expected 'pix', got 'boleto'",
        )


class OfficialVerificationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.git = {
            "commit_sha": "abc123",
            "tracked_diff_sha256": "tracked",
            "untracked_files_sha256": "untracked",
        }
        self.evidence = {
            "available": True,
            "completed": True,
            "methodology_version": 6,
            "commit_sha": "abc123",
            "tracked_diff_sha256": "tracked",
            "untracked_files_sha256": "untracked",
            "git_dirty": False,
            "monitoring_official_eligible": True,
            "contract_languages": ["python", "node", "java", "go", "dotnet"],
            "openapi_valid": True,
            "database_state_equivalent": True,
            "all_executable_tests_passed": True,
        }

    def test_accepts_complete_evidence_for_the_same_clean_commit(self) -> None:
        self.assertTrue(verification_matches_current_project(self.evidence, self.git))

    def test_rejects_each_incomplete_or_stale_evidence_field(self) -> None:
        invalid_values = {
            "available": False,
            "completed": False,
            "methodology_version": 5,
            "commit_sha": "different",
            "tracked_diff_sha256": "different",
            "untracked_files_sha256": "different",
            "git_dirty": True,
            "monitoring_official_eligible": False,
            "contract_languages": ["python"],
            "openapi_valid": False,
            "database_state_equivalent": False,
            "all_executable_tests_passed": False,
        }
        for field, value in invalid_values.items():
            with self.subTest(field=field):
                evidence = {**self.evidence, field: value}
                self.assertFalse(verification_matches_current_project(evidence, self.git))


class SummaryFixtureTests(unittest.TestCase):
    @staticmethod
    def write_summary_run(root: Path, run_number: int, classification: str) -> None:
        run = root / "python" / "mixed" / f"run_{run_number}"
        run.mkdir(parents=True)
        (run / "metadata.json").write_text(json.dumps({
            "methodology_version": 6,
            "result_classification": classification,
            "load_profile": "controlled_50",
            "benchmark_kind": "controlled_load",
            "execution_order": {"position": run_number},
            "locust": {"users": 50, "spawn_rate": 10},
            "test_phase": {"elapsed_seconds": 300},
            "metrics": {"window_source": "locust_test_start_stop"},
            "monitoring_preflight": {"official_eligible": classification == "official"},
        }), encoding="utf-8")
        with (run / "locust_stats.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "Type", "Name", "Request Count", "Failure Count", "Average Response Time",
                "50%", "95%", "99%", "Requests/s",
            ])
            writer.writeheader()
            row = {
                "Type": "GET", "Name": "GET /customers", "Request Count": 100,
                "Failure Count": 0, "Average Response Time": 10, "50%": 8,
                "95%": 20, "99%": 30, "Requests/s": 40,
            }
            writer.writerow(row)
            writer.writerow({**row, "Type": "", "Name": "Aggregated"})

    def test_endpoint_rows_preserve_all_methodological_dimensions(self) -> None:
        original_raw = summary.RAW
        try:
            with tempfile.TemporaryDirectory() as temp:
                raw = Path(temp)
                run = raw / "python" / "mixed" / "run_1"
                run.mkdir(parents=True)
                (run / "metadata.json").write_text(json.dumps({
                    "methodology_version": 6,
                    "result_classification": "non_official",
                    "load_profile": "controlled_50",
                    "locust": {"users": 50, "spawn_rate": 10},
                    "test_phase": {"elapsed_seconds": 300},
                    "metrics": {"window_source": "locust_test_start_stop"},
                    "monitoring_preflight": {"official_eligible": False},
                }), encoding="utf-8")
                with (run / "locust_stats.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=[
                        "Type", "Name", "Request Count", "Failure Count", "Average Response Time",
                        "50%", "95%", "99%", "Requests/s",
                    ])
                    writer.writeheader()
                    writer.writerow({
                        "Type": "GET", "Name": "GET /customers", "Request Count": 100,
                        "Failure Count": 1, "Average Response Time": 10, "50%": 8,
                        "95%": 20, "99%": 30, "Requests/s": 40,
                    })
                    writer.writerow({
                        "Type": "", "Name": "Aggregated", "Request Count": 100,
                        "Failure Count": 1, "Average Response Time": 10, "50%": 8,
                        "95%": 20, "99%": 30, "Requests/s": 40,
                    })
                (run / "postgres_summary.csv").write_text(
                    "connections_average,connections_max,commits_total,rollbacks_total,commits_per_second,"
                    "rollbacks_per_second,blocks_read_total,blocks_hit_total,cache_hit_ratio,"
                    "database_size_average_bytes,database_size_max_bytes,metric_source\n"
                    "12,20,1000,2,3.33,0.01,10,9990,0.999,50000000,51000000,"
                    "postgres_exporter_via_prometheus\n",
                    encoding="utf-8",
                )
                summary.RAW = raw
                runs, endpoints = summary.collect_runs()
        finally:
            summary.RAW = original_raw
        self.assertEqual(len(runs), 1)
        self.assertEqual(endpoints[0]["load_profile"], "controlled_50")
        self.assertEqual(endpoints[0]["methodology_version"], 6)
        self.assertEqual(endpoints[0]["result_classification"], "non_official")
        self.assertEqual(endpoints[0]["error_rate"], "0.010000")
        self.assertEqual(runs[0]["postgres_connections_average"], 12)
        self.assertEqual(runs[0]["postgres_metric_source"], "postgres_exporter_via_prometheus")

    def test_scalability_never_mixes_result_classifications(self) -> None:
        rows = []
        for classification, base_rps, capacity_rps in (
            ("official", 100, 180),
            ("non_official", 400, 440),
        ):
            common = {
                "language": "python", "methodology_version": 6,
                "result_classification": classification, "failures": 0,
                "requests": 1000, "p95_ms": 20, "locust_cpu_average_percent": 30,
                "measurement_stability_status": "stable",
                "measurement_final_windows_stable": True,
                "measurement_rps_change_percent": 1,
                "resource_metrics_available": True, "exact_measurement_window": True,
                "execution_order_position": 1,
            }
            rows.extend((
                {**common, "scenario": "mixed", "load_profile": "controlled_50", "users": 50, "throughput_rps": base_rps},
                {**common, "scenario": "mixed_capacity_100", "load_profile": "capacity_100", "users": 100, "throughput_rps": capacity_rps},
            ))
        output = scalability_rows(rows)
        official_100 = next(row for row in output if row["result_classification"] == "official" and row["users"] == 100)
        preliminary_100 = next(row for row in output if row["result_classification"] == "non_official" and row["users"] == 100)
        self.assertEqual(official_100["rps_gain_vs_50_percent"], "80.000")
        self.assertEqual(preliminary_100["rps_gain_vs_50_percent"], "10.000")

    def test_final_outputs_default_to_official_and_keep_current_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, processed, summaries = root / "raw", root / "processed", root / "summaries"
            self.write_summary_run(raw, 1, "official")
            self.write_summary_run(raw, 2, "non_official")

            summary.generate_outputs(raw, processed, summaries)

            with (processed / "summary_by_language.csv").open(encoding="utf-8", newline="") as handle:
                language_rows = list(csv.DictReader(handle))
            with (processed / "summary_by_endpoint.csv").open(encoding="utf-8", newline="") as handle:
                endpoint_reader = csv.DictReader(handle)
                endpoint_fields = endpoint_reader.fieldnames
                endpoint_rows = list(endpoint_reader)
            with (processed / "summary_scalability.csv").open(encoding="utf-8", newline="") as handle:
                scalability_reader = csv.DictReader(handle)
                scalability_fields = scalability_reader.fieldnames
                scalability_rows_output = list(scalability_reader)

        self.assertEqual({row["result_classification"] for row in language_rows}, {"official"})
        self.assertEqual({row["result_classification"] for row in endpoint_rows}, {"official"})
        self.assertEqual({row["result_classification"] for row in scalability_rows_output}, {"official"})
        self.assertEqual(endpoint_fields, summary.ENDPOINT_FIELDS)
        self.assertEqual(scalability_fields, summary.SCALABILITY_FIELDS)
        for field in (
            "language", "method", "endpoint", "scenario", "load_profile", "run",
            "methodology_version", "result_classification", "requests", "failures",
            "error_rate", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "throughput_rps",
            "cpu_average_percent", "memory_average_bytes",
        ):
            self.assertIn(field, endpoint_fields)

    def test_empty_official_results_write_only_headers_and_explain_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw, processed, summaries = root / "raw", root / "processed", root / "summaries"
            self.write_summary_run(raw, 1, "non_official")

            paths = summary.generate_outputs(raw, processed, summaries)

            for path, fields in zip(paths[:3], (
                summary.LANGUAGE_FIELDS, summary.ENDPOINT_FIELDS, summary.SCALABILITY_FIELDS,
            )):
                with path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, fields)
                    self.assertEqual(list(reader), [])
            final_summary = (summaries / "final_summary.md").read_text(encoding="utf-8")

        self.assertIn("classificacao `official`", final_summary)
        self.assertIn("somente o cabecalho metodologico atual", final_summary)
        self.assertIn("nao foram promovidos para resultados oficiais", final_summary)


class MonitoringValidationTests(unittest.TestCase):
    def test_real_container_id_matches_but_generic_cgroups_do_not(self) -> None:
        identifier = "47d788b3861af3662a9752f3090c3d5aac548deedbdd2cb900ad51a45b60042d"
        self.assertTrue(monitoring_metric_matches(
            {"id": f"/docker/{identifier}", "name": identifier},
            "python-api", "tcc_benchmark_python_api", identifier,
        ))
        for generic in ("/", "/docker", "/restricted"):
            with self.subTest(generic=generic):
                self.assertFalse(monitoring_metric_matches(
                    {"id": generic}, "python-api", "tcc_benchmark_python_api", identifier,
                ))

    def test_waits_for_the_first_complete_cadvisor_scrape(self) -> None:
        reports = iter((
            {"official_eligible": False},
            {"official_eligible": True},
        ))
        now = [0.0]

        report = wait_for_official_evidence(
            lambda: next(reports),
            wait_seconds=30,
            poll_seconds=2,
            monotonic=lambda: now[0],
            sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
        )

        self.assertTrue(report["official_eligible"])
        self.assertEqual(now[0], 2)


if __name__ == "__main__":
    unittest.main()
