import os

os.environ.setdefault("SCENARIO", "read_heavy")

from locustfile import BenchmarkUser  # noqa: F401,E402
