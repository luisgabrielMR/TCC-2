import os

os.environ.setdefault("SCENARIO", "write_heavy")

from locustfile import BenchmarkUser  # noqa: F401,E402
