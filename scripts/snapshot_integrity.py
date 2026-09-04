"""Read only fully published, hash-verified Locust snapshots."""
import csv
import hashlib
import io
import json
from pathlib import Path


def verified_stats(prefix: Path) -> list[dict]:
    report = json.loads(Path(f"{prefix}_snapshot_validation.json").read_text(encoding="utf-8"))
    if report.get("valid") is not True or report.get("worker_reconciliation", {}).get("valid") is not True:
        raise RuntimeError("Snapshot validation is incomplete")
    stats = None
    for kind in ("stats", "failures", "exceptions"):
        data = Path(f"{prefix}_{kind}.csv").read_bytes()
        if hashlib.sha256(data).hexdigest() != report.get("sha256", {}).get(kind):
            raise RuntimeError(f"Snapshot hash differs: {kind}")
        if kind == "stats":
            stats = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    return stats
