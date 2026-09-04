"""Diagnostic only: hold a table lock, verify HTTP deadlines, always roll back."""
import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request

import psycopg


def verify(base_url):
    database = os.environ["POSTGRES_DB"]
    if database != "benchmark_db":
        raise RuntimeError("Lock diagnostics are restricted to benchmark_db")
    results = []
    with psycopg.connect(host=os.environ["POSTGRES_HOST"], dbname=database,
                        user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
                        autocommit=True) as connection:
        if connection.execute("SHOW statement_timeout").fetchone()[0] != "30s":
            raise RuntimeError("Expected PostgreSQL statement_timeout=30s")
        for hold_seconds, expected_status in ((12, 200), (33, 500)):
            outcome = []
            started_request = threading.Event()
            def request():
                started = time.perf_counter()
                started_request.set()
                try:
                    with urllib.request.urlopen(base_url + "/customers/1", timeout=40) as response:
                        outcome.append((response.status, json.load(response), time.perf_counter() - started))
                except urllib.error.HTTPError as response:
                    outcome.append((response.code, json.load(response), time.perf_counter() - started))
                except Exception as error:
                    outcome.append(error)
            connection.execute("BEGIN")
            thread = threading.Thread(target=request)
            try:
                connection.execute("LOCK TABLE customers IN ACCESS EXCLUSIVE MODE")
                thread.start()
                if not started_request.wait(5):
                    raise RuntimeError("Request thread did not start")
                time.sleep(hold_seconds)
            finally:
                connection.execute("ROLLBACK")
                if thread.ident is not None:
                    thread.join(45)
            if thread.is_alive() or len(outcome) != 1 or isinstance(outcome[0], Exception):
                raise RuntimeError(f"Request did not complete correctly: {outcome}")
            status, body, elapsed = outcome[0]
            if status != expected_status:
                raise RuntimeError(f"{base_url}: held {hold_seconds}s, expected {expected_status}, got {status}: {body}")
            if expected_status == 200 and not 11 <= elapsed <= 15:
                raise RuntimeError(f"Read did not observe the intended lock wait: {elapsed}")
            if expected_status == 500 and (body != {"error": {"code": "DATABASE_ERROR", "message": "Database error", "details": []}}):
                raise RuntimeError(f"Unexpected database error contract: {body}")
            if expected_status == 500 and not 29 <= elapsed <= 33:
                raise RuntimeError(f"SQL deadline outside tolerance: {elapsed}")
            results.append({"lock_seconds": hold_seconds, "status": status, "elapsed_seconds": elapsed})
    return {"diagnostic_only": True, "base_url": base_url, "checks": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.base_url)))
