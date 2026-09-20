import csv
import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.finalize_locust_csv import publish, validate_stats
from scripts.snapshot_integrity import verified_stats


class TimingRegressionTests(unittest.TestCase):
    def test_every_completed_result_consumer_rejects_unpublished_revision_eight(self):
        from scripts import summarize_results, generate_results_dashboard
        from monitoring.results_exporter import collect_completed_runs
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "raw/python/mixed_fixed_200/run_1"
            run.mkdir(parents=True)
            (run / "metadata.json").write_text(json.dumps({"methodology_version": 8, "result_classification": "official"}))
            (run / "locust_stats.csv").write_text("Name,Request Count\nAggregated,10\n")
            with self.assertRaises(FileNotFoundError):
                summarize_results.collect_runs(root / "raw")
            with patch.object(generate_results_dashboard, "RAW", root / "raw"):
                with self.assertRaises(FileNotFoundError):
                    generate_results_dashboard.collect()
            self.assertEqual(collect_completed_runs(root), ([], []))

    def test_snapshot_requires_all_hashes_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "locust"
            report = {"valid": True, "worker_reconciliation": {"valid": True}, "sha256": {}}
            for kind in ("stats", "failures", "exceptions"):
                data = b"Name,Request Count\nAggregated,10\n"
                Path(f"{prefix}_{kind}.csv").write_bytes(data)
                report["sha256"][kind] = hashlib.sha256(data).hexdigest()
            marker = Path(f"{prefix}_snapshot_validation.json")
            marker.write_text(json.dumps(report))
            self.assertEqual(verified_stats(prefix)[0]["Request Count"], "10")
            Path(f"{prefix}_failures.csv").write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "hash differs"):
                verified_stats(prefix)
            marker.unlink()
            with self.assertRaises(FileNotFoundError):
                verified_stats(prefix)

    def test_bash_cpu_reader_executes_real_embedded_python(self):
        bash = Path("C:/Program Files/Git/bin/bash.exe")
        executable = str(bash) if bash.exists() else shutil.which("bash")
        if not executable:
            self.skipTest("Bash unavailable")
        source = (Path(__file__).resolve().parents[1] / "scripts/run_one_language.sh").read_text()
        start = source.index("read -r LOCUST_CPU_AVERAGE_PERCENT LOCUST_CPU_MAX_PERCENT <<EOF")
        finish = source.index("LOCUST_CPU_QUOTA_AVERAGE_PERCENT=null", start)
        python = Path(sys.executable).as_posix()
        if len(python) > 1 and python[1] == ":":
            python = "/" + python[0].lower() + python[2:]
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "cadvisor_summary.csv").write_text("component,cpu_average_percent,cpu_max_percent\nlocust,120,240\n")
            script = f'py() {{ "{python}" "$@"; }}\nPYTHON_BIN=py\nRESULT_DIR="{Path(directory).as_posix()}"\n'
            script += source[start:finish] + '\nprintf "%s %s" "$LOCUST_CPU_AVERAGE_PERCENT" "$LOCUST_CPU_MAX_PERCENT"\n'
            result = subprocess.run([executable, "-c", script], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "120 240", result.stderr)

    def test_publication_preserves_source_and_retries_transient_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "final.csv", Path(directory) / "stats.csv"
            source.write_bytes(b"new evidence")
            destination.write_bytes(b"previous")
            original = Path.replace
            calls = []
            def replace(path, target):
                calls.append(path)
                if len(calls) == 1:
                    raise PermissionError("sharing violation")
                return original(path, target)
            with patch.object(Path, "replace", replace), patch("scripts.finalize_locust_csv.time.sleep"):
                publish(source, destination)
            self.assertEqual(source.read_bytes(), b"new evidence")
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertEqual(len(calls), 2)

    def test_persistent_publication_failure_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / "final.csv", Path(directory) / "stats.csv"
            source.write_bytes(b"new")
            destination.write_bytes(b"previous")
            with patch.object(Path, "replace", side_effect=PermissionError("locked")), patch("scripts.finalize_locust_csv.time.sleep"):
                with self.assertRaises(PermissionError):
                    publish(source, destination)
            self.assertEqual(destination.read_bytes(), b"previous")
            self.assertEqual(source.read_bytes(), b"new")
            self.assertEqual(len(list(Path(directory).iterdir())), 2)

    def test_weighted_aggregate_latency_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.csv"
            row = {"Type": "GET", "Name": "GET /health", "Request Count": 10, "Failure Count": 0,
                   "Average Response Time": 2, "50%": 2, "95%": 2, "99%": 2}
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerows([row, {**row, "Name": "Aggregated", "Average Response Time": 999}])
            with self.assertRaisesRegex(RuntimeError, "weighted mean"):
                validate_stats(path)

if __name__ == "__main__":
    unittest.main()
