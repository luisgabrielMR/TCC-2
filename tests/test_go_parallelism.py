import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import preflight


class GoParallelismTests(unittest.TestCase):
    def test_configuration_is_required_even_before_go_starts(self):
        for value in (None, "", "8", "0", "2.0"):
            self.assertTrue(preflight.go_parallelism_violations({"go_parallelism": value}, {}, None))
        self.assertEqual(preflight.go_parallelism_violations({"go_parallelism": "2"}, {}, None), [])

    def test_probe_must_match_configuration_and_quota(self):
        for probe in ({}, {"gomaxprocs": 8, "configured_gomaxprocs": "2"},
                      {"gomaxprocs": 2, "configured_gomaxprocs": ""},
                      {"gomaxprocs": "2", "configured_gomaxprocs": "2"}):
            effective = {"limits": {"go-api": {"runtime_parallelism": probe}}}
            self.assertTrue(preflight.go_parallelism_violations({"go_parallelism": "2"}, effective, "go-api"))
        effective = {"limits": {"go-api": {"runtime_parallelism": {"gomaxprocs": 2, "configured_gomaxprocs": "2"}}}}
        self.assertEqual(preflight.go_parallelism_violations({"go_parallelism": "2"}, effective, "go-api"), [])

    def test_runtime_probe_errors_fail_closed(self):
        for code, output in ((1, ""), (0, "not json"), (0, "[]"), (0, "null")):
            def run(command, **kwargs):
                if command[:3] == ["docker", "compose", "ps"]:
                    return 0, "container-id", ""
                if command[1] == "inspect":
                    return 0, "2000000000", ""
                return code, output, ""
            with patch.object(preflight, "run", side_effect=run):
                effective = preflight.runtime_resource_policy("go-api")
            self.assertTrue(preflight.go_parallelism_violations({"go_parallelism": "2"}, effective, "go-api"))

    def test_compose_environment_is_collected_for_every_profile(self):
        config = {"services": {"go-api": {"environment": {"GOMAXPROCS": "2"}}}}
        with patch.object(preflight, "run", return_value=(0, json.dumps(config), "")):
            result = preflight.configured_resource_policy("python-api")
        self.assertEqual(result["go_parallelism"], "2")


if __name__ == "__main__":
    unittest.main()
