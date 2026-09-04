#!/usr/bin/env python3
"""Read-only HTTP probe of database-wide transaction overhead, never an official run."""
import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("python", "node", "java", "go", "dotnet")
READS = (("/customers/1", 1), ("/customers?page=1&pageSize=50", 2),
         ("/products?categoryId=1", 2), ("/orders/1", 1))


def compose(*args):
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def snapshot():
    # Observe benchmark_db from postgres so the observer's own transaction is excluded.
    sql = "SELECT xact_commit, xact_rollback FROM pg_stat_database WHERE datname='benchmark_db'"
    text = compose("exec", "-T", "postgres", "sh", "-c",
                   'psql -U "$POSTGRES_USER" -d postgres -At -c "$1"', "probe", sql)
    return tuple(map(int, text.strip().split("|")))


def request(path):
    with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP {response.status}: {path}")
        json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.requests < 1:
        parser.error("--requests must be positive")
    active = set(compose("ps", "--services", "--status", "running").split())
    if "locust" in active or any(name.endswith("-api") for name in active):
        raise RuntimeError("Stop active APIs/Locust before this diagnostic; no running workload is interrupted")
    report = {"classification": "diagnostic_only", "scope": "database-wide; includes monitoring",
              "sampling": "pg_stat_database; asynchronous reporting; ratios are approximate", "rows": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for language in LANGUAGES:
        service = language + "-api"
        try:
            compose("--profile", language, "up", "-d", "--no-build", service)
            for attempt in range(60):
                try:
                    request("/health")
                    break
                except OSError:
                    time.sleep(1)
            else:
                raise RuntimeError(f"{language}: health timeout")
            for endpoint, expected in READS:
                for _ in range(10):
                    request(endpoint)
                time.sleep(1.2)
                request(endpoint)
                before = snapshot()
                started = time.monotonic()
                for _ in range(args.requests):
                    request(endpoint)
                time.sleep(1.2)
                request(endpoint)  # Give this backend another opportunity to flush pending statistics.
                after = snapshot()
                count = args.requests + 1
                row = {"language": language, "endpoint": endpoint, "requests": count,
                       "logical_read_transactions_per_request": expected,
                       "database_commits_delta": after[0] - before[0],
                       "database_rollbacks_delta": after[1] - before[1],
                       "database_commits_per_request": (after[0] - before[0]) / count,
                       "probe_elapsed_seconds": time.monotonic() - started}
                report["rows"].append(row)
                print(json.dumps(row), flush=True)
                args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        finally:
            compose("--profile", language, "stop", service)


if __name__ == "__main__":
    main()
