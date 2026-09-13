import csv
import json
import sys
import tempfile
import unittest
import os
import subprocess
from unittest.mock import patch
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "load-tests" / "locust"))
from workload_schedule import DeterministicActionSchedule, initial_user_phase, load_scenario
from scripts.export_prometheus_data import QUERIES, write_postgres_summary
from scripts.benchmark_protocol import build_protocol
from scripts.summarize_results import generate_outputs
from scripts.assess_primary_pilots import assess, LANGUAGES, PROFILES


class ScheduleTests(unittest.TestCase):
    def schedule(self, scenario="mixed"):
        name, actions = load_scenario(ROOT / "load-tests/locust/config/scenarios.json", scenario)
        return DeterministicActionSchedule(name, actions)

    def test_exact_mix_and_repeatability_for_every_scenario(self):
        for name in ("mixed", "read_heavy", "write_heavy", "warmup"):
            first, second = self.schedule(name), self.schedule(name)
            length = first.manifest["cycle_length"]
            observed = [first.next_action() for _ in range(length)]
            self.assertEqual(observed, [second.next_action() for _ in range(length)])
            self.assertEqual(observed, [first.next_action() for _ in range(length)])
            counts = Counter(observed)
            total_weight = sum(item["weight"] for item in first.manifest["actions"])
            for item in first.manifest["actions"]:
                self.assertEqual(counts[item["action"]] / length, item["weight"] / total_weight)
            self.assertEqual(first.manifest, second.manifest)

    def test_weights_are_interleaved_not_grouped_bursts(self):
        schedule = self.schedule()
        actions = [schedule.next_action() for _ in range(20)]
        self.assertTrue(all(a != b for a, b in zip(actions, actions[1:])))

    def test_workers_have_reproducible_offsets_and_full_cycles(self):
        baseline = self.schedule()
        length = baseline.manifest["cycle_length"]
        expected = [baseline.next_action() for _ in range(length)]
        for worker in range(4):
            schedule = self.schedule()
            schedule.configure_worker_offset(worker, 4)
            offset = worker * length // 4
            self.assertEqual([schedule.next_action() for _ in range(length)], expected[offset:] + expected[:offset])

    def test_rejects_invalid_weights_and_empty_actions(self):
        with self.assertRaises(ValueError):
            DeterministicActionSchedule("empty", [])
        for weight in (0, -1, True, 1.5):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                DeterministicActionSchedule("bad", [{"action": "x", "endpoint": "GET /", "weight": weight}])
        duplicate = {"action": "x", "endpoint": "GET /", "weight": 1}
        with self.assertRaises(ValueError):
            DeterministicActionSchedule("bad", [duplicate, duplicate])

    def test_user_phases_cover_period_without_worker_collisions(self):
        phases = sorted(initial_user_phase(index, worker, 4, 100, 2)
                        for worker in range(4) for index in range(25))
        self.assertEqual(len(set(phases)), 100)
        self.assertAlmostEqual(phases[0], 0.01)
        self.assertAlmostEqual(phases[-1], 1.99)
        for a, b in zip(phases, phases[1:]):
            self.assertAlmostEqual(b - a, 0.02)
        with self.assertRaises(ValueError):
            initial_user_phase(25, 0, 4, 100, 2)
        # Locust can assign remainder users to any worker, not necessarily index 0.
        phases = [initial_user_phase(index, worker, 4, 50, 1, population)
                  for worker, population in enumerate((12, 12, 13, 13)) for index in range(population)]
        self.assertEqual(len(set(phases)), 50)
        self.assertTrue(all(0 < phase < 1 for phase in phases))


class ActivityDiagnosticsTests(unittest.TestCase):
    def capture(self, revision):
        keys = [key for key in QUERIES if key.startswith("postgres_")]
        if revision < 3:
            keys = [key for key in keys if not key.endswith("sessions")]
        return {"collector_revision": revision, "start_epoch": 100, "end_epoch": 110,
                "step_seconds": 5,
                "queries": {key: {"response": {"data": {"result": [{"values":
                    [[100, "1"], [105, "1"], [110, "1"]]}]}}} for key in keys}}

    def test_legacy_has_unavailable_diagnostics_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.csv"
            write_postgres_summary(path, self.capture(2), require=True)
            with path.open(newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["active_sessions_average"], "")
            self.assertEqual(row["activity_diagnostics_available"], "False")

    def test_current_capture_requires_diagnostics_and_preserves_real_zero(self):
        result = self.capture(3)
        key = "postgres_waiting_lock_sessions"
        result["queries"][key]["response"]["data"]["result"][0]["values"] = [[100, "0"], [105, "0"], [110, "0"]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.csv"
            write_postgres_summary(path, result, require=True)
            with path.open(newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["waiting_lock_sessions_average"], "0.000000")
            self.assertEqual(row["activity_diagnostics_available"], "True")
            del result["queries"][key]
            with self.assertRaisesRegex(RuntimeError, key):
                write_postgres_summary(path, result, require=True)


class CohortTests(unittest.TestCase):
    def test_optional_calibration_never_changes_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            calibration = Path(directory) / "calibration.json"
            with patch("scripts.benchmark_protocol._compose_digest", return_value="test-compose"):
                values = {"LOAD_GENERATOR_CALIBRATION_FILE": str(calibration)}
                first = build_protocol("fixed_50", "mixed", values)
                calibration.write_text('{"old_methodology": 1}')
                second = build_protocol("fixed_50", "mixed", values)
                high = build_protocol("fixed_100", "mixed", values)
            self.assertEqual(first["protocol_sha256"], second["protocol_sha256"])
            self.assertNotEqual(first["protocol_sha256"], high["protocol_sha256"])
            self.assertEqual(first["protocol"]["load"]["users"], high["protocol"]["load"]["users"])
            self.assertEqual(first["protocol"]["load"]["model"], "closed_paced_users_v1")
            self.assertEqual(first["protocol"]["load"]["nominal_pacing_rps"], 50)

    def test_explicit_campaign_excludes_other_results_and_endpoints(self):
        foreign = {"campaign_fingerprint": "other"}
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.summarize_results.collect_runs", return_value=([foreign], [foreign])
        ):
            root = Path(directory)
            paths = generate_outputs(root, root / "processed", root / "summaries", "all", "selected")
            for path in paths[:3]:
                with path.open(newline="") as handle:
                    self.assertEqual(list(csv.DictReader(handle)), [])


class LauncherTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows PowerShell launcher")
    def test_menu_rotates_both_profiles_and_all_five_languages(self):
        # Load only the planning function AST, never the interactive entrypoint.
        code = r'''
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path (Get-Location) 'launchers/windows/powershell/menu-testes.ps1'), [ref]$null, [ref]$null)
$definition = $ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-NextOfficialRoundPlan'}, $true)
Invoke-Expression $definition.Extent.Text
function Get-BenchmarkEnvironment { return @{} }
function Get-BenchmarkValue($Environment, $Name, $Default) {
    switch ($Name) {
        'OFFICIAL_PROFILES' { return 'fixed_50,fixed_100' }
        'OFFICIAL_ROUNDS' { return '5' }
        default { return $Default }
    }
}
function Get-OfficialCampaignIdentity($Environment, $Profile) {
    return [pscustomobject]@{ fingerprint=$Profile; methodology_version=15; commit_sha='test' }
}
$global:completed = @{}
function Get-OfficialLanguagesForSequence($SequenceId, $Profile, $MethodologyVersion, $CommitSha) {
    if ($global:completed.ContainsKey($SequenceId)) { return @('python','node','java','go','dotnet') }
    return @()
}
$plans = @()
for ($step = 0; $step -lt 10; $step++) {
    $plan = Get-NextOfficialRoundPlan
    if ($plan.all_complete) { throw 'Premature completion' }
    $plans += $plan
    $global:completed[$plan.sequence_id] = $true
}
if (-not (Get-NextOfficialRoundPlan).all_complete) { throw 'Campaign never completes' }
ConvertTo-Json -Depth 5 -InputObject $plans -Compress
'''
        result = subprocess.run(["powershell", "-NoProfile", "-Command", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        plans = json.loads(result.stdout)
        languages = ["python", "node", "java", "go", "dotnet"]
        for index, plan in enumerate(plans):
            round_index = index // 2
            expected_profile = ["fixed_50", "fixed_100"][(index % 2 + round_index) % 2]
            self.assertEqual(plan["load_profile"], expected_profile)
            self.assertEqual(plan["round"], round_index + 1)
            self.assertEqual(plan["ordered_languages"], languages[round_index:] + languages[:round_index])

    @unittest.skipUnless(Path(r"C:\Program Files\Git\bin\bash.exe").exists(), "Git Bash required")
    def test_bash_environment_lists_and_explicit_overrides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            (root / "scripts/_lib.sh").write_text((ROOT / "scripts/_lib.sh").read_text(), newline="\n")
            (root / ".env").write_text("BENCHMARK_PROFILES=saturation_25 saturation_50\nLOCUST_DURATION=5m\n")
            result = subprocess.run([r"C:\Program Files\Git\bin\bash.exe", "-c",
                'source scripts/_lib.sh; printf "%s|%s" "$BENCHMARK_PROFILES" "$LOCUST_DURATION"'],
                cwd=root, env={**os.environ, "LOCUST_DURATION": "90s"},
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "saturation_25 saturation_50|90s")


class PilotAssessmentTests(unittest.TestCase):
    def test_isolated_cli_reports_incomplete_cohort_without_import_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "assessment.json"
            result = subprocess.run(
                [sys.executable, "-I", str(ROOT / "scripts/assess_primary_pilots.py"),
                 "--raw", str(Path(directory) / "raw"), "--sequence", "missing",
                 "--output", str(report_path)],
                cwd=directory, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report["all_evidence_checks_passed"])
            self.assertEqual(report["rows"], [])

    def test_empty_sequence_is_not_complete_or_acceptable(self):
        with tempfile.TemporaryDirectory() as directory:
            report = assess(Path(directory), "missing")
            self.assertFalse(report["complete_two_levels_five_languages"])
            self.assertFalse(report["all_evidence_checks_passed"])

    def test_full_cohort_requires_consistent_sources_and_delivery(self):
        aggregate = {"Name": "Aggregated", "Failure Count": "0", "Request Count": "4500",
                     "Average Response Time": "5", "95%": "7"}
        with tempfile.TemporaryDirectory() as directory, patch(
            "scripts.assess_primary_pilots.verified_stats", return_value=[aggregate]
        ):
            root = Path(directory)
            for profile in PROFILES:
                for language in LANGUAGES:
                    path = root / language / f"mixed_{profile}" / "run_1"
                    path.mkdir(parents=True)
                    nominal = int(profile.split("_")[1])
                    metadata = {"execution_order": {"sequence_id": "selected"},
                        "load_profile": profile, "language": language, "result_classification": "non_official",
                        "warmup": {"stable": True}, "measurement_stability": {"stable": True},
                        "locust": {"target_rps": nominal, "achieved_rps": nominal, "generator_headroom_met": True, "locust_cpu_quota_average_percent": 5},
                        "shared_database": {"database_headroom_met": True, "postgres_cpu_quota_average_percent": 20, "postgres_cpu_quota_max_percent": 40}}
                    manifest = {"commit_sha": "same", "protocol_sha256": profile,
                                "protocol": {"experimental_source_sha256": {"code": "hash"}}}
                    (path / "metadata.json").write_text(json.dumps(metadata))
                    (path / "protocol-manifest.json").write_text(json.dumps(manifest))
                    (path / "measurement-bounds-validation.json").write_text('{"valid":true}')
                    (path / "postgres_summary.csv").write_text("activity_diagnostics_available\nTrue\n")
                    (path / "cadvisor_summary.csv").write_text(
                        "component,coverage_percent,cpu_counter_resets,maximum_scrape_gap_seconds\n"
                        "api,100,0,5\npostgresql,100,0,5\nlocust,100,0,5\n")
            self.assertTrue(assess(root, "selected")["all_evidence_checks_passed"])
            (path / "protocol-manifest.json").write_text(json.dumps({**manifest,
                "protocol": {"experimental_source_sha256": {"code": "changed"}}}))
            self.assertFalse(assess(root, "selected")["same_executable_sources_and_protocol_per_level"])
            (path / "protocol-manifest.json").write_text(json.dumps(manifest))
            metadata["locust"]["achieved_rps"] = 1
            (path / "metadata.json").write_text(json.dumps(metadata))
            self.assertFalse(assess(root, "selected")["all_evidence_checks_passed"])


if __name__ == "__main__":
    unittest.main()
