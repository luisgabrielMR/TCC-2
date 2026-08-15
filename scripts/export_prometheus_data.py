#!/usr/bin/env python3
"""Export PostgreSQL and target time series from Prometheus."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path


QUERIES = {
    "targets_up": "up",
    "postgres_up": "pg_up",
    "postgres_connections": 'pg_stat_database_numbackends{datname="benchmark_db"}',
    "postgres_commits_per_second": 'rate(pg_stat_database_xact_commit{datname="benchmark_db"}[30s])',
    "postgres_rollbacks_per_second": 'rate(pg_stat_database_xact_rollback{datname="benchmark_db"}[30s])',
    "postgres_blocks_read": 'pg_stat_database_blks_read{datname="benchmark_db"}',
    "postgres_blocks_hit": 'pg_stat_database_blks_hit{datname="benchmark_db"}',
    "postgres_database_size_bytes": 'pg_database_size_bytes{datname="benchmark_db"}',
}


def query_range(base_url: str, query: str, start: float, end: float, step: int) -> dict:
    params = urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/v1/query_range?{params}", timeout=15) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9090")
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", required=True, type=float)
    parser.add_argument("--end", required=True, type=float)
    parser.add_argument("--step", type=int, default=5)
    args = parser.parse_args()
    result = {"start_epoch": args.start, "end_epoch": args.end, "step_seconds": args.step, "queries": {}}
    for name, query in QUERIES.items():
        result["queries"][name] = {"query": query, "response": query_range(args.url, query, args.start, args.end, args.step)}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
    print(f"Prometheus series exported to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
