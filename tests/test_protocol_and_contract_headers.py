import json
import subprocess
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_protocol import build_protocol, duration_seconds
from scripts.contract_test_api import validate_content_type
from scripts.preflight import official_protocol_violations
from scripts.validate_measurement_bounds import validate_bounds


class ProtocolTests(unittest.TestCase):
    def test_official_mode_rejects_host_network_override(self):
        self.assertEqual(official_protocol_violations({}), [])
        self.assertIn(
            "LOCUST_HOST_OVERRIDE",
            official_protocol_violations({"LOCUST_HOST_OVERRIDE": "http://host.docker.internal:8000"})[0],
        )

    def test_duration_parser_is_explicit(self):
        self.assertEqual(duration_seconds("5m"), 300)
        self.assertEqual(duration_seconds("250ms"), 0.25)
        for value in ("", "nan", "0s", "5minutes"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                duration_seconds(value)

    def test_protocol_hash_changes_with_ignored_environment_values(self):
        base = {
            "METHODOLOGY_VERSION": "9", "LOCUST_DURATION": "5m", "LOCUST_PROCESSES": "4",
            "WARMUP_DURATION_SECONDS": "300", "WARMUP_STABILITY_WINDOW_SECONDS": "45",
            "WARMUP_MAX_RPS_DRIFT_PERCENT": "10", "DB_POOL_MIN": "1", "DB_POOL_MAX": "20",
            "DB_POOL_ACQUIRE_TIMEOUT_SECONDS": "10", "DB_POOL_IDLE_TIMEOUT_SECONDS": "60",
            "DB_POOL_MAX_LIFETIME_SECONDS": "1800", "METRICS_SAMPLE_INTERVAL_SECONDS": "2",
            "OFFICIAL_ROUNDS": "5", "LOAD_GENERATOR_CALIBRATION_FILE": "missing.json",
        }
        completed = subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n", stderr="")
        with patch("scripts.benchmark_protocol._compose_digest", return_value="compose"), \
             patch("scripts.benchmark_protocol.subprocess.run", return_value=completed):
            first = build_protocol("fixed_200", "mixed", base)
            second = build_protocol("fixed_200", "mixed", {**base, "LOCUST_DURATION": "6m"})
            proxied = build_protocol("fixed_200", "mixed", {
                **base, "LOCUST_HOST_OVERRIDE": "http://host.docker.internal:8000",
            })
        self.assertNotEqual(first["protocol_sha256"], second["protocol_sha256"])
        self.assertNotEqual(first["campaign_fingerprint"], second["campaign_fingerprint"])
        self.assertNotEqual(first["protocol_sha256"], proxied["protocol_sha256"])
        self.assertEqual(
            first["protocol"]["load"]["target"]["network_mode"],
            "docker_internal_compose_service",
        )
        self.assertEqual(proxied["protocol"]["load"]["target"]["network_mode"], "host_override")

    def test_official_bounds_require_post_spawn_event_and_configured_duration(self):
        bounds = {
            "window_start_event": "spawning_complete_after_stats_reset",
            "window_end_event": "last_worker_stop_received_before_bounded_drain",
            "drained_request_rule": "started_before_worker_stop_boundary",
            "started_epoch": 100, "finished_epoch": 400.1,
            "started_at_utc": "1970-01-01T00:01:40Z",
            "finished_at_utc": "1970-01-01T00:06:40.100000Z",
            "elapsed_seconds": 300.1, "wall_elapsed_seconds": 300.1,
            "duration_clock": "time.monotonic_ns", "boundary_clock": "time.time_ns",
        }
        self.assertTrue(validate_bounds(bounds, 300, 0.25)["valid"])
        self.assertFalse(validate_bounds({**bounds, "elapsed_seconds": 300.3}, 300, 0.25)["valid"])
        self.assertFalse(validate_bounds({**bounds, "window_start_event": "test_start"}, 300, 0.25)["valid"])


class ContractHeaderTests(unittest.TestCase):
    def header(self, value):
        headers = Message()
        headers["Content-Type"] = value
        return headers

    def test_accepts_only_json_with_optional_utf8_charset(self):
        validate_content_type(self.header("application/json"), "GET", "/health")
        validate_content_type(self.header("application/json; charset=utf-8"), "GET", "/health")
        for value in ("text/plain", "application/json; charset=latin-1"):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                validate_content_type(self.header(value), "GET", "/health")


if __name__ == "__main__":
    unittest.main()
