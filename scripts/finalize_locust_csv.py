#!/usr/bin/env python3
"""Prepare and promote the final Locust CSV snapshot for one run."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


KINDS = ("stats", "failures", "exceptions")


def prepare(prefix: Path) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    for path in prefix.parent.glob(f"{prefix.name}_*.csv"):
        path.unlink()
    Path(f"{prefix}_measurement_bounds.json").unlink(missing_ok=True)


def promote(prefix: Path) -> None:
    for kind in KINDS:
        source = Path(f"{prefix}_final_{kind}.csv")
        destination = Path(f"{prefix}_{kind}.csv")
        if not source.exists():
            raise RuntimeError(f"Locust did not produce final snapshot: {source}")
        source.replace(destination)

    stats_path = Path(f"{prefix}_stats.csv")
    with stats_path.open("r", encoding="utf-8-sig", newline="") as handle:
        aggregate = next((row for row in csv.DictReader(handle) if row.get("Name") == "Aggregated"), None)
    if aggregate is None:
        raise RuntimeError(f"Locust final CSV has no Aggregated row: {stats_path}")
    print(
        "Locust final CSV promoted: "
        f"requests={aggregate['Request Count']} failures={aggregate['Failure Count']} path={stats_path}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prefix)
    else:
        promote(args.prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
