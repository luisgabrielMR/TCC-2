from __future__ import annotations

import json
import threading
from pathlib import Path


class PayloadCycle:
    def __init__(self, path: Path, parse_json: bool = True) -> None:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"Payload file is empty: {path}")
        self._values = [json.loads(line) if parse_json else line for line in lines]
        self._index = 0
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._values)

    def configure_worker_offset(self, worker_index: int) -> None:
        if worker_index < 0:
            raise ValueError("worker_index must be non-negative")
        with self._lock:
            self._index = worker_index % len(self._values)

    def next(self):
        with self._lock:
            value = self._values[self._index % len(self._values)]
            self._index += 1
            return value


class PayloadSequence:
    def __init__(self, path: Path) -> None:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"Payload file is empty: {path}")
        self._values = [json.loads(line) for line in lines]
        self._stride = 1
        self._index = 0
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._values)

    def configure_shard(self, offset: int, stride: int) -> None:
        if stride < 1:
            raise ValueError("stride must be positive")
        if offset < 0 or offset >= stride:
            raise ValueError("offset must identify a worker inside the configured stride")
        with self._lock:
            self._stride = stride
            self._index = offset

    def next(self):
        with self._lock:
            if self._index >= len(self._values):
                raise RuntimeError("customers_create.jsonl exhausted; generate more payloads before the benchmark")
            value = self._values[self._index]
            self._index += self._stride
            return value
