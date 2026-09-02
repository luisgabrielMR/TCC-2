#!/usr/bin/env python3
"""Collect numeric Docker resource samples throughout one benchmark run."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


UNIT_FACTORS = {
    "B": 1, "kB": 1_000, "KB": 1_000, "MB": 1_000_000,
    "GB": 1_000_000_000, "TB": 1_000_000_000_000,
    "KiB": 1_024, "MiB": 1_024**2, "GiB": 1_024**3, "TiB": 1_024**4,
}
SIZE = re.compile(r"^\s*([0-9.]+)\s*([A-Za-z]+)\s*$")
FIELDS = [
    "timestamp_utc", "container_name", "container_id", "cpu_percent",
    "memory_usage_bytes", "memory_limit_bytes", "network_rx_bytes",
    "network_tx_bytes", "block_read_bytes", "block_write_bytes", "pids",
]


def bytes_value(value: str) -> int:
    match = SIZE.match(value)
    if not match:
        return 0
    return round(float(match.group(1)) * UNIT_FACTORS.get(match.group(2), 1))


def pair(value: str) -> tuple[int, int]:
    parts = value.split("/", 1)
    return bytes_value(parts[0]), bytes_value(parts[1]) if len(parts) == 2 else 0


def percent_value(value: object) -> float | None:
    text = str(value or "").strip().rstrip("%")
    if not text or text == "--":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def sample() -> list[dict[str, object]]:
    completed = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    rows = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        cpu_percent = percent_value(value.get("CPUPerc"))
        if cpu_percent is None:
            continue
        memory, memory_limit = pair(value.get("MemUsage", ""))
        network_rx, network_tx = pair(value.get("NetIO", ""))
        block_read, block_write = pair(value.get("BlockIO", ""))
        rows.append({
            "timestamp_utc": timestamp,
            "container_name": value.get("Name", ""),
            "container_id": value.get("ID", value.get("Container", "")),
            "cpu_percent": cpu_percent,
            "memory_usage_bytes": memory,
            "memory_limit_bytes": memory_limit,
            "network_rx_bytes": network_rx,
            "network_tx_bytes": network_tx,
            "block_read_bytes": block_read,
            "block_write_bytes": block_write,
            "pids": int(value.get("PIDs", "0") or 0),
        })
    return rows


def timestamp_epoch(value: object) -> float:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def measured_rows(rows: list[dict[str, object]], bounds_path: Path | None) -> list[dict[str, object]]:
    if bounds_path is None:
        return rows
    if not bounds_path.exists():
        raise RuntimeError(f"Measurement bounds were not produced: {bounds_path}")
    bounds = json.loads(bounds_path.read_text(encoding="utf-8"))
    start = float(bounds["started_epoch"])
    end = float(bounds["finished_epoch"])
    selected = [row for row in rows if start <= timestamp_epoch(row["timestamp_utc"]) <= end]
    if not selected:
        raise RuntimeError(f"No Docker statistics inside measurement bounds: {start}..{end}")
    return selected


def write_summary(path: Path, rows: list[dict[str, object]]) -> None:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["container_name"])].append(row)
    fields = [
        "container_name", "samples", "cpu_average_percent", "cpu_max_percent",
        "memory_average_bytes", "memory_max_bytes", "network_rx_delta_bytes",
        "network_tx_delta_bytes", "block_read_delta_bytes", "block_write_delta_bytes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for name in sorted(grouped):
            values = grouped[name]
            cpu = [float(row["cpu_percent"]) for row in values]
            memory = [int(row["memory_usage_bytes"]) for row in values]
            writer.writerow({
                "container_name": name,
                "samples": len(values),
                "cpu_average_percent": f"{sum(cpu) / len(cpu):.6f}",
                "cpu_max_percent": f"{max(cpu):.6f}",
                "memory_average_bytes": round(sum(memory) / len(memory)),
                "memory_max_bytes": max(memory),
                "network_rx_delta_bytes": max(0, int(values[-1]["network_rx_bytes"]) - int(values[0]["network_rx_bytes"])),
                "network_tx_delta_bytes": max(0, int(values[-1]["network_tx_bytes"]) - int(values[0]["network_tx_bytes"])),
                "block_read_delta_bytes": max(0, int(values[-1]["block_read_bytes"]) - int(values[0]["block_read_bytes"])),
                "block_write_delta_bytes": max(0, int(values[-1]["block_write_bytes"]) - int(values[0]["block_write_bytes"])),
            })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--stop-file", required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--bounds")
    args = parser.parse_args()
    output = Path(args.output)
    stop_file = Path(args.stop_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    stop_file.unlink(missing_ok=True)
    rows: list[dict[str, object]] = []

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        while not stop_file.exists():
            current = sample()
            rows.extend(current)
            writer.writerows(current)
            handle.flush()
            deadline = time.monotonic() + args.interval
            while not stop_file.exists() and time.monotonic() < deadline:
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    if not rows:
        raise RuntimeError("No Docker statistics were collected")
    selected = measured_rows(rows, Path(args.bounds) if args.bounds else None)
    write_summary(output.with_name("docker_stats_summary.csv"), selected)
    print(f"docker stats samples={len(rows)} measured_samples={len(selected)} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
