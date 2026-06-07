import os

os.environ.setdefault("SCENARIO", "smoke")

from locustfile import BenchmarkUser  # noqa: F401,E402
