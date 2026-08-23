#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DOCKER = "29.7.2"
EXPECTED_COMPOSE = "5.3.1"
EXPECTED_IMAGES = {
    "postgres": "postgres:17",
    "locust": "locustio/locust:2.32.6",
    "prometheus": "prom/prometheus:v2.55.1",
    "grafana": "grafana/grafana:11.3.0",
    "postgres_exporter": "prometheuscommunity/postgres-exporter:v0.15.0",
    "cadvisor": "gcr.io/cadvisor/cadvisor:v0.49.1",
    "results_exporter": "python:3.12-slim",
}
EXPECTED_API_BASES = {
    "python-api": ("python:3.12-slim",),
    "node-api": ("node:22-slim",),
    "java-api": ("maven:3.9-eclipse-temurin-21", "eclipse-temurin:21-jre"),
    "go-api": ("golang:1.23-bookworm", "debian:bookworm-slim"),
    "dotnet-api": ("mcr.microsoft.com/dotnet/sdk:8.0", "mcr.microsoft.com/dotnet/aspnet:8.0"),
}
COMPOSE_PROFILES = ("python", "node", "java", "go", "dotnet", "load", "monitoring")
VERIFICATION_EVIDENCE = ROOT / "results" / "summaries" / "project-verification.json"
REQUIRED_CONTRACT_LANGUAGES = ["python", "node", "java", "go", "dotnet"]


def run(command: list[str], *, binary: bool = False, timeout: int = 30) -> tuple[int, Any, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=not binary,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, b"" if binary else "", str(exc)
    stdout = completed.stdout if binary else completed.stdout.strip()
    stderr = completed.stderr.decode(errors="replace") if binary else completed.stderr.strip()
    return completed.returncode, stdout, stderr


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in (ROOT / ".env.example", ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip()
    for key, value in os.environ.items():
        if value:
            values[key] = value
    return values


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_provenance() -> dict[str, Any]:
    _, commit, _ = run(["git", "rev-parse", "HEAD"])
    _, branch, _ = run(["git", "branch", "--show-current"])
    status_code, status_raw, status_error = run(["git", "status", "--porcelain=v1", "-z"], binary=True)
    diff_code, tracked_diff, diff_error = run(["git", "diff", "--binary", "HEAD", "--"], binary=True)
    untracked_code, untracked_raw, untracked_error = run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], binary=True
    )
    if any(code != 0 for code in (status_code, diff_code, untracked_code)):
        return {
            "available": False,
            "commit_sha": commit or "unknown",
            "branch": branch or "unknown",
            "error": "; ".join(filter(None, (status_error, diff_error, untracked_error))),
        }

    untracked_files = [item.decode("utf-8", errors="surrogateescape") for item in untracked_raw.split(b"\0") if item]
    untracked_entries: list[dict[str, Any]] = []
    aggregate = hashlib.sha256()
    for relative in sorted(untracked_files):
        path = ROOT / relative
        if path.is_file():
            digest = sha256_file(path)
            size = path.stat().st_size
        else:
            digest = "not_a_regular_file"
            size = 0
        aggregate.update(relative.encode("utf-8", errors="surrogateescape"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\0")
        untracked_entries.append({"path": relative.replace("\\", "/"), "sha256": digest, "size_bytes": size})

    status_entries = [item.decode("utf-8", errors="replace") for item in status_raw.split(b"\0") if item]
    return {
        "available": True,
        "commit_sha": commit,
        "branch": branch,
        "git_dirty": bool(status_entries),
        "status_porcelain": status_entries,
        "tracked_diff_sha256": sha256_bytes(tracked_diff),
        "tracked_diff_size_bytes": len(tracked_diff),
        "untracked_files": untracked_entries,
        "untracked_files_sha256": aggregate.hexdigest(),
    }


def powershell_json(script: str) -> Any:
    executable = shutil.which("powershell") or shutil.which("powershell.exe")
    if not executable:
        return None
    code, output, _ = run([executable, "-NoProfile", "-Command", script], timeout=45)
    if code != 0 or not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def host_environment() -> dict[str, Any]:
    root = Path(ROOT.anchor or "/")
    disk = shutil.disk_usage(root)
    result: dict[str, Any] = {
        "operating_system": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "platform": platform.platform(),
        },
        "cpu": {
            "architecture": platform.machine(),
            "logical_processors": os.cpu_count(),
            "model": platform.processor() or "unknown",
        },
        "physical_memory_bytes": None,
        "storage": {
            "path": str(root),
            "total_bytes": disk.total,
            "free_bytes": disk.free,
            "device_models": [],
        },
    }
    computer = powershell_json(
        "Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory | ConvertTo-Json -Compress"
    )
    processors = powershell_json(
        "Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress"
    )
    disks = powershell_json(
        "Get-CimInstance Win32_DiskDrive | Select-Object Model,Size,MediaType | ConvertTo-Json -Compress"
    )
    if isinstance(computer, dict):
        result["physical_memory_bytes"] = computer.get("TotalPhysicalMemory")
    if processors:
        values = processors if isinstance(processors, list) else [processors]
        result["cpu"]["processors"] = values
        result["cpu"]["physical_cores"] = sum(int(item.get("NumberOfCores") or 0) for item in values)
        result["cpu"]["logical_processors"] = sum(int(item.get("NumberOfLogicalProcessors") or 0) for item in values)
        result["cpu"]["model"] = "; ".join(str(item.get("Name") or "unknown").strip() for item in values)
    if disks:
        result["storage"]["device_models"] = disks if isinstance(disks, list) else [disks]
    if result["physical_memory_bytes"] is None and hasattr(os, "sysconf"):
        try:
            result["physical_memory_bytes"] = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError):
            pass
    if result["physical_memory_bytes"] is None and platform.system() == "Windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong), ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                result["physical_memory_bytes"] = status.total_physical
        except (AttributeError, OSError):
            pass
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        entries = cpuinfo.read_text(encoding="utf-8", errors="replace").split("\n\n")
        models = {
            line.split(":", 1)[1].strip()
            for entry in entries
            for line in entry.splitlines()
            if line.lower().startswith("model name") and ":" in line
        }
        core_pairs = set()
        for entry in entries:
            values = dict(
                line.split(":", 1) for line in entry.splitlines() if ":" in line
            )
            if "physical id" in values and "core id" in values:
                core_pairs.add((values["physical id"].strip(), values["core id"].strip()))
        if models:
            result["cpu"]["model"] = "; ".join(sorted(models))
        if core_pairs:
            result["cpu"]["physical_cores"] = len(core_pairs)
    return result


def docker_environment() -> dict[str, Any]:
    version_code, version_output, version_error = run(["docker", "version", "--format", "{{json .}}"])
    compose_code, compose_output, compose_error = run(["docker", "compose", "version", "--format", "json"])
    info_code, info_output, info_error = run(["docker", "info", "--format", "{{json .}}"])

    def parsed(output: str) -> Any:
        try:
            return json.loads(output)
        except (TypeError, json.JSONDecodeError):
            return None

    version = parsed(version_output) if version_code == 0 else None
    compose = parsed(compose_output) if compose_code == 0 else None
    info = parsed(info_output) if info_code == 0 else None
    compose_version = compose.get("version") if isinstance(compose, dict) else None
    if not compose_version and compose_output:
        match = re.search(r"v?(\d+\.\d+\.\d+)", compose_output)
        compose_version = match.group(1) if match else compose_output
    server = version.get("Server", {}) if isinstance(version, dict) else {}
    client = version.get("Client", {}) if isinstance(version, dict) else {}
    allocation = {
        "logical_processors": info.get("NCPU") if isinstance(info, dict) else None,
        "memory_bytes": info.get("MemTotal") if isinstance(info, dict) else None,
        "operating_system": info.get("OperatingSystem") if isinstance(info, dict) else None,
        "kernel_version": info.get("KernelVersion") if isinstance(info, dict) else None,
        "architecture": info.get("Architecture") if isinstance(info, dict) else None,
        "docker_root_dir": info.get("DockerRootDir") if isinstance(info, dict) else None,
        "storage_driver": info.get("Driver") if isinstance(info, dict) else None,
    }
    return {
        "available": version_code == compose_code == info_code == 0,
        "engine_server_version": server.get("Version"),
        "engine_client_version": client.get("Version"),
        "compose_version": compose_version,
        "allocation": allocation,
        "errors": [error for error in (version_error, compose_error, info_error) if error],
    }


def compose_command(*arguments: str) -> list[str]:
    command = ["docker", "compose"]
    for profile in COMPOSE_PROFILES:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return command


def configured_images() -> dict[str, Any]:
    code, output, error = run(compose_command("config", "--images"), timeout=45)
    references = sorted(set(output.splitlines())) if code == 0 else []
    images: list[dict[str, Any]] = []
    for reference in references:
        inspect_code, inspect_output, inspect_error = run(
            ["docker", "image", "inspect", reference, "--format", "{{json .}}"], timeout=45
        )
        details: dict[str, Any] = {"configured_reference": reference, "available_locally": inspect_code == 0}
        if inspect_code == 0:
            try:
                inspected = json.loads(inspect_output)
                details.update({
                    "image_id": inspected.get("Id"),
                    "repo_digests": inspected.get("RepoDigests") or [],
                    "created": inspected.get("Created"),
                    "os": inspected.get("Os"),
                    "architecture": inspected.get("Architecture"),
                })
            except json.JSONDecodeError:
                details["inspection_error"] = "invalid docker image inspect JSON"
        elif inspect_error:
            details["inspection_error"] = inspect_error
        images.append(details)
    return {"config_ok": code == 0, "config_error": error or None, "images": images}


def dockerfile_bases() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for service in EXPECTED_API_BASES:
        content = (ROOT / "apps" / service / "Dockerfile").read_text(encoding="utf-8")
        result[service] = re.findall(r"^FROM\s+([^\s]+)", content, flags=re.MULTILINE | re.IGNORECASE)
    return result


def manifest_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {}
    requirements = {}
    for line in (ROOT / "apps/python-api/requirements.lock").read_text(encoding="utf-8").splitlines():
        if "==" in line:
            name, value = line.split("==", 1)
            requirements[name.lower()] = value
    versions["python"] = {"source": "requirements.lock", "libraries": requirements}

    package_lock = json.loads((ROOT / "apps/node-api/package-lock.json").read_text(encoding="utf-8"))
    node_packages = package_lock.get("packages", {})
    versions["node"] = {
        "source": "package-lock.json",
        "libraries": {
            name: node_packages.get(f"node_modules/{name}", {}).get("version") for name in ("express", "pg")
        },
    }

    pom_root = ET.parse(ROOT / "apps/java-api/pom.xml").getroot()
    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}
    java_libraries: dict[str, str | None] = {}
    for dependency in pom_root.findall(".//m:dependency", namespace):
        artifact = dependency.findtext("m:artifactId", namespaces=namespace)
        value = dependency.findtext("m:version", namespaces=namespace)
        if artifact:
            java_libraries[artifact] = value
    versions["java"] = {"source": "pom.xml", "libraries": java_libraries}

    go_libraries: dict[str, str] = {}
    for line in (ROOT / "apps/go-api/go.mod").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(?:require\s+)?([^\s]+)\s+(v[^\s]+)\s*$", line)
        if match:
            go_libraries[match.group(1)] = match.group(2)
    versions["go"] = {"source": "go.mod", "libraries": go_libraries}

    dotnet_lock = json.loads((ROOT / "apps/dotnet-api/packages.lock.json").read_text(encoding="utf-8"))
    target = next(iter(dotnet_lock.get("dependencies", {}).values()), {})
    versions["dotnet"] = {
        "source": "packages.lock.json",
        "libraries": {name: data.get("resolved") for name, data in target.items()},
    }
    return versions


def runtime_versions() -> dict[str, Any]:
    commands = {
        "python": (["python-api"], ["python", "--version"]),
        "node": (["node-api"], ["node", "--version"]),
        "java": (["java-api"], ["java", "-version"]),
        "dotnet": (["dotnet-api"], ["dotnet", "--list-runtimes"]),
        "go": (["go-api"], ["/app/go-api", "--runtime-version"]),
        "locust": (["locust"], ["locust", "--version"]),
    }
    result: dict[str, Any] = {}
    for name, (service_parts, runtime_command) in commands.items():
        service = service_parts[0]
        image_code, image_id, image_error = run(compose_command("images", "-q", service), timeout=45)
        image_id = image_id.splitlines()[0] if image_id else ""
        if name == "locust" and not image_id:
            image_id = EXPECTED_IMAGES["locust"] + "@sha256:99278f4b23e2353e7a93b84f9c270700c8193b90c1611f5c2a1817a111c22ee3"
        if image_code != 0 or not image_id:
            result[name] = {"available": False, "error": image_error or "image not built"}
            continue
        code, output, error = run(
            ["docker", "run", "--rm", "--entrypoint", runtime_command[0], image_id, *runtime_command[1:]], timeout=60
        )
        result[name] = {
            "available": code == 0,
            "version_output": (output or error).splitlines()[0] if (output or error) else None,
            "image_id": image_id,
            "error": error if code != 0 else None,
        }

    return result


def postgres_version() -> dict[str, Any]:
    environment = load_env()
    code, output, error = run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-Atq", "-U", environment.get("POSTGRES_USER", "benchmark_user"), "-d", environment.get("POSTGRES_DB", "benchmark_db"), "-c", "SELECT version();"],
        timeout=30,
    )
    return {"available": code == 0, "version_output": output or None, "error": error if code != 0 else None}


def configured_pool(environment: dict[str, str]) -> dict[str, Any]:
    defaults = {
        "DB_POOL_MIN": "1",
        "DB_POOL_MAX": "20",
        "DB_POOL_ACQUIRE_TIMEOUT_SECONDS": "10",
        "DB_POOL_IDLE_TIMEOUT_SECONDS": "60",
        "DB_POOL_MAX_LIFETIME_SECONDS": "1800",
    }
    return {key.lower(): environment.get(key, value) for key, value in defaults.items()}


def project_verification() -> dict[str, Any]:
    try:
        value = json.loads(VERIFICATION_EVIDENCE.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"available": False, "error": "invalid root"}
    except FileNotFoundError:
        return {"available": False, "error": "project verification evidence is missing"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc)}


def verification_matches_current_project(verification: dict[str, Any], git: dict[str, Any]) -> bool:
    return (
        verification.get("available") is True
        and verification.get("completed") is True
        and verification.get("methodology_version") == 6
        and verification.get("commit_sha") == git.get("commit_sha")
        and verification.get("tracked_diff_sha256") == git.get("tracked_diff_sha256")
        and verification.get("untracked_files_sha256") == git.get("untracked_files_sha256")
        and verification.get("git_dirty") is False
        and verification.get("monitoring_official_eligible") is True
        and verification.get("contract_languages") == REQUIRED_CONTRACT_LANGUAGES
        and verification.get("openapi_valid") is True
        and verification.get("database_state_equivalent") is True
        and verification.get("all_executable_tests_passed") is True
    )


def image_policy_violations(images: dict[str, Any]) -> list[str]:
    configured = images.get("images", [])
    violations: list[str] = []
    for name, expected in EXPECTED_IMAGES.items():
        matches = [item for item in configured if item["configured_reference"].startswith(expected + "@")]
        if not matches:
            violations.append(f"{name} image must be {expected} and pinned by digest")
        elif not any(item.get("available_locally") for item in matches):
            violations.append(f"{name} pinned image is not available locally for inspection")
    return violations


def api_base_violations(bases: dict[str, list[str]]) -> list[str]:
    violations: list[str] = []
    for service, expected_prefixes in EXPECTED_API_BASES.items():
        actual = bases.get(service, [])
        for expected in expected_prefixes:
            matches = [reference for reference in actual if reference.startswith(expected + "@sha256:")]
            if not matches:
                violations.append(f"{service} base must be {expected} and pinned by digest")
    return violations


def build_report(mode: str) -> dict[str, Any]:
    environment = load_env()
    git = git_provenance()
    docker = docker_environment()
    images = configured_images()
    bases = dockerfile_bases()
    host = host_environment()
    postgres = postgres_version()
    runtimes = runtime_versions()
    libraries = manifest_versions()
    verification = project_verification()
    violations: list[str] = []
    if not docker.get("available"):
        violations.append("Docker Engine, Compose and allocation information must all be available")
    if docker.get("engine_server_version") != EXPECTED_DOCKER:
        violations.append(
            f"Docker Engine must be {EXPECTED_DOCKER}; detected {docker.get('engine_server_version') or 'unavailable'}"
        )
    detected_compose = str(docker.get("compose_version") or "").lstrip("v")
    if detected_compose != EXPECTED_COMPOSE:
        violations.append(f"Docker Compose must be {EXPECTED_COMPOSE}; detected {detected_compose or 'unavailable'}")
    if not git.get("available"):
        violations.append("Git provenance is unavailable")
    elif git.get("git_dirty"):
        violations.append("Git worktree must be clean for an official run")
    violations.extend(image_policy_violations(images))
    violations.extend(api_base_violations(bases))
    expected_runtime_patterns = {
        "python": r"Python 3\.12\.",
        "node": r"v22\.",
        "java": r"\b21(?:\.|\b)",
        "go": r"go1\.23\.",
        "dotnet": r"\b8\.0\.",
        "locust": r"\b2\.32\.6\b",
    }
    for runtime, pattern in expected_runtime_patterns.items():
        details = runtimes.get(runtime, {})
        version_output = str(details.get("version_output") or "")
        if not details.get("available") or not re.search(pattern, version_output):
            violations.append(f"{runtime} runtime is unavailable or differs from the required major/minor version")
    if not postgres.get("available") or "PostgreSQL 17" not in str(postgres.get("version_output") or ""):
        violations.append("PostgreSQL 17 runtime version could not be confirmed")
    for name, details in libraries.items():
        if not details.get("libraries") or any(value in (None, "") for value in details["libraries"].values()):
            violations.append(f"{name} library versions are incomplete")
    if not host.get("physical_memory_bytes") or not host.get("cpu", {}).get("logical_processors"):
        violations.append("Host CPU or physical memory inventory is incomplete")
    allocation = docker.get("allocation", {})
    if not allocation.get("logical_processors") or not allocation.get("memory_bytes"):
        violations.append("Effective Docker CPU or memory allocation is unavailable")
    if mode == "official":
        if not verification_matches_current_project(verification, git):
            violations.append("A complete project verification for this clean commit and cAdvisor state is required")

    return {
        "schema_version": 1,
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requested_mode": mode,
        "classification": "official_candidate" if mode == "official" and not violations else "non_official",
        "environment_eligible_for_official_run": not violations,
        "official_blockers": violations,
        "expected": {
            "docker_engine": EXPECTED_DOCKER,
            "docker_compose": EXPECTED_COMPOSE,
            "images": EXPECTED_IMAGES,
        },
        "git": git,
        "host": host,
        "docker": docker,
        "configured_images": images,
        "api_dockerfile_bases": bases,
        "postgresql": postgres,
        "runtimes": runtimes,
        "libraries": libraries,
        "database_pool": configured_pool(environment),
        "project_verification": verification,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect benchmark provenance and enforce official-run prerequisites.")
    parser.add_argument("--mode", choices=("pilot", "official"), default="pilot")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.mode)
    serialized = json.dumps(report, indent=2, ensure_ascii=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    if args.mode == "official" and report["official_blockers"]:
        print("Official run blocked: " + "; ".join(report["official_blockers"]), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
