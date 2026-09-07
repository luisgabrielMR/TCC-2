import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from preflight import EXPECTED_POSTGRES_SETTINGS, normalized_postgres_setting

RUNNER = (ROOT / "scripts" / "run_one_language.sh").read_text(encoding="utf-8")
POWERSHELL = (ROOT / "launchers" / "windows" / "powershell" / "rodar-linguagem.ps1").read_text(
    encoding="utf-8"
)
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


class PostgresSettingsTests(unittest.TestCase):
    def test_compose_declares_every_expected_setting(self):
        for name, value in EXPECTED_POSTGRES_SETTINGS.items():
            self.assertIn(f'"{name}={value}"', COMPOSE)

    def test_internal_units_are_normalized_before_comparison(self):
        self.assertEqual(normalized_postgres_setting("shared_buffers", "16384|8kB"), "128MB")
        self.assertEqual(normalized_postgres_setting("effective_cache_size", "524288|8kB"), "4GB")
        self.assertEqual(normalized_postgres_setting("work_mem", "4096|kB"), "4MB")
        self.assertEqual(normalized_postgres_setting("max_connections", "100|"), "100")

    def test_missing_setting_never_reports_a_match(self):
        self.assertIsNone(normalized_postgres_setting("shared_buffers", None))
        for name, expected in EXPECTED_POSTGRES_SETTINGS.items():
            self.assertNotEqual(normalized_postgres_setting(name, None), expected)

    def test_a_different_cache_size_is_not_accepted_as_the_declared_one(self):
        self.assertNotEqual(normalized_postgres_setting("shared_buffers", "65536|8kB"), "128MB")


class DatabaseHeadroomGateTests(unittest.TestCase):
    def test_both_runners_read_the_postgresql_row_from_cadvisor(self):
        self.assertIn('row.get("component") == "postgresql"', RUNNER)
        self.assertIn('$_.component -eq "postgresql"', POWERSHELL)

    def test_both_runners_normalize_by_the_postgres_quota(self):
        self.assertIn('["limits"]["postgres"]["effective_cpu_quota"]', RUNNER)
        self.assertIn("resource_policy.effective.limits.postgres.effective_cpu_quota", POWERSHELL)

    def test_the_gate_uses_the_same_threshold_as_the_generator_gate(self):
        self.assertIn(
            'raise SystemExit(0 if float(sys.argv[1]) < 90 else 1)\' "$POSTGRES_CPU_QUOTA_AVERAGE_PERCENT"',
            RUNNER,
        )
        self.assertIn("$postgresCpuQuotaAveragePercent -lt 90", POWERSHELL)

    def test_a_missing_series_blocks_only_official_runs(self):
        self.assertIn(
            'if [ "$POSTGRES_CPU_QUOTA_AVERAGE_PERCENT" = null ]; then\n'
            '  if [ "$RUN_MODE" = official ]; then DATABASE_HEADROOM_MET=false; fi',
            RUNNER,
        )
        self.assertIn(
            '$databaseHeadroomMet = if ($null -eq $postgresCpuQuotaAveragePercent) '
            '{ $RunMode -ne "official" }',
            POWERSHELL,
        )

    def test_the_gate_participates_in_the_official_classification(self):
        self.assertIn(
            '[ "$GENERATOR_HEADROOM_MET" = true ] && [ "$DATABASE_HEADROOM_MET" = true ]', RUNNER
        )
        self.assertEqual(
            POWERSHELL.count("$generatorHeadroomMet -and $databaseHeadroomMet"), 2
        )

    def test_both_runners_record_the_same_shared_database_fields(self):
        fields = (
            "postgres_cpu_quota",
            "postgres_cpu_average_percent",
            "postgres_cpu_max_percent",
            "postgres_cpu_quota_average_percent",
            "postgres_cpu_quota_max_percent",
            "database_headroom_cpu_metric",
            "database_headroom_threshold_percent",
            "database_headroom_met",
        )
        for field in fields:
            self.assertIn(f'"{field}":', RUNNER)
            self.assertRegex(POWERSHELL, re.compile(rf"^\s*{field} = ", re.MULTILINE))


if __name__ == "__main__":
    unittest.main()
