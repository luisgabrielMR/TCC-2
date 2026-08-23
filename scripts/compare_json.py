#!/usr/bin/env python3
"""Compare JSON artifacts and report the first structural divergence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def first_difference(expected: Any, actual: Any, path: str = "$") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}: expected type {type(expected).__name__}, got {type(actual).__name__}"
    if isinstance(expected, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            return f"{path}: missing keys {missing}, extra keys {extra}"
        for key in sorted(expected):
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: expected {len(expected)} items, got {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = first_difference(expected_item, actual_item, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, got {actual!r}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("expected", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--label", default="JSON")
    args = parser.parse_args()

    expected = json.loads(args.expected.read_text(encoding="utf-8-sig"))
    actual = json.loads(args.actual.read_text(encoding="utf-8-sig"))
    difference = first_difference(expected, actual)
    if difference:
        raise SystemExit(f"{args.label} differs at {difference}")
    print(f"{args.label} comparison ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
