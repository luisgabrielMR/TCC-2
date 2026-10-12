import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.publish_official_results import archive_evidence, validate_cohort, verify


class OfficialPublicationTests(unittest.TestCase):
    def cohort(self):
        return [{"language": language, "run_number": run, "result_classification": "official",
                 "methodology_version": 17, "load_profile": "fixed_100", "scenario": "mixed_fixed_100",
                 "protocol_sha256": "same-protocol", "commit_sha": "measured-commit",
                 "execution_order": {"campaign_fingerprint": "same-campaign"}}
                for language in ("python", "node", "java", "go", "dotnet") for run in range(1, 6)]

    def test_rejects_pilot_mixed_protocol_and_duplicate_round(self):
        validate_cohort(self.cohort())
        for field, value in [("result_classification", "non_official"), ("protocol_sha256", "different"),
                             ("commit_sha", "different"), ("run_number", 2), ("load_profile", "fixed_50")]:
            with self.subTest(field=field):
                rows = self.cohort()
                rows[0][field] = value
                with self.assertRaises(ValueError):
                    validate_cohort(rows)
        with self.assertRaises(ValueError):
            validate_cohort(self.cohort()[:-1])

    def test_rejects_cross_campaign_even_when_other_identity_matches(self):
        rows = self.cohort()
        rows[0]["execution_order"]["campaign_fingerprint"] = "other-campaign"
        with self.assertRaisesRegex(ValueError, "campaign"):
            validate_cohort(rows)

    def test_archive_preserves_original_bytes_and_verify_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw/python/run_1/stats.csv"
            source.parent.mkdir(parents=True)
            original = b"header,value\r\nmeasured,42\r\n"
            source.write_bytes(original)
            output = root / "publication"
            output.mkdir()
            records = archive_evidence(output / "evidence.zip", [source], root)
            with zipfile.ZipFile(output / "evidence.zip") as archive:
                self.assertEqual(archive.read("raw/python/run_1/stats.csv"), original)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(records[0]["sha256"], hashlib.sha256(original).hexdigest())
            manifest = {"files": records, "archive_sha256": hashlib.sha256((output / "evidence.zip").read_bytes()).hexdigest()}
            (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            (output / "summary.csv").write_bytes(original)
            (output / "SHA256SUMS").write_text(hashlib.sha256(original).hexdigest() + "  summary.csv\n", encoding="utf-8")
            self.assertTrue(verify(output)["valid"])
            (output / "summary.csv").write_bytes(original.replace(b"42", b"43"))
            with self.assertRaisesRegex(ValueError, "summary.csv"):
                verify(output)


if __name__ == "__main__":
    unittest.main()
