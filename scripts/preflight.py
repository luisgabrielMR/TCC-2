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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from load_generator_calibration import validate_calibration


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DOCKER = "29.5.2"
EXPECTED_COMPOSE = "5.1.4"
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
EXPECTED_CUSTOMER_CREATE_PAYLOADS = 200_000
EXPECTED_LOCUST_PROCESSES = 4
EXPECTED_DOCKER_LOGICAL_PROCESSORS = 8
EXPECTED_CPU_LIMITS = {
    "postgres": 1.0,
    "locust": 4.0,
    "python-api": 2.0,
    "node-api": 2.0,
    "java-api": 2.0,
    "go-api": 2.0,
    "dotnet-api": 2.0,
}


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


def methodology_version(environment: dict[str, str] | None = None) -> int:
    values = environment or load_env()
    try:
        return int(values.get("METHODOLOGY_VERSION", "7"))
    except ValueError:
        return 7


def configured_locust_processes(environment: dict[str, str] | None = None) -> int | None:
    values = environment or load_env()
    try:
        processes = int(values.get("LOCUST_PROCESSES", "4"))
    except ValueError:
        return None
    return processes if processes > 0 else None


def configured_resource_policy(api_service: str | None = None) -> dict[str, Any]:
    code, output, error = run(compose_command("config", "--format", "json"), timeout=45)
    if code != 0:
        return {"available": False, "error": error or output or "compose config failed"}
    try:
        configuration = json.loads(output)
    except json.JSONDecodeError as exc:
        return {"available": False, "error": f"invalid compose JSON: {exc}"}

    selected = ["postgres", "locust", api_service] if api_service else list(EXPECTED_CPU_LIMITS)
    services = configuration.get("services", {})
    limits: dict[str, Any] = {}
    for service in selected:
        configured = services.get(service, {}).get("cpus")
        try:
            configured = float(configured)
        except (TypeError, ValueError):
            configured = None
        limits[service] = {
            "configured_cpus": configured,
            "expected_cpus": EXPECTED_CPU_LIMITS.get(service),
            "matches_expected": configured == EXPECTED_CPU_LIMITS.get(service),
        }
    return {
        "available": True,
        "compose_config_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "limits": limits,
    }


def runtime_resource_policy(api_service: str | None = None) -> dict[str, Any]:
    if api_service is None:
        return {"available": False, "required": False, "limits": {}}
    selected = ["postgres", "locust"]
    if api_service:
        selected.append(api_service)
    limits: dict[str, Any] = {}
    for service in selected:
        ps_code, container_output, ps_error = run(["docker", "compose", "ps", "-q", service])
        container = container_output.splitlines()[0] if ps_code == 0 and container_output else ""
        if not container:
            limits[service] = {"available": False, "error": ps_error or "container is not running"}
            continue
        inspect_code, inspect_output, inspect_error = run(
            ["docker", "inspect", container, "--format", "{{.HostConfig.NanoCpus}}"]
        )
        try:
            nano_cpus = int(inspect_output) if inspect_code == 0 else 0
        except ValueError:
            nano_cpus = 0
        effective_cpus = nano_cpus / 1_000_000_000 if nano_cpus > 0 else None
        limits[service] = {
            "available": inspect_code == 0 and effective_cpus is not None,
            "container_id": container,
            "nano_cpus": nano_cpus or None,
            "effective_cpu_quota": effective_cpus,
            "expected_cpus": EXPECTED_CPU_LIMITS.get(service),
            "matches_expected": effective_cpus == EXPECTED_CPU_LIMITS.get(service),
            "error": inspect_error if inspect_code != 0 else None,
        }
    return {"limits": limits, "available": all(item.get("available") for item in limits.values()), "required": True}


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
    config_code, config_output, config_error = run(
        compose_command("config", "--format", "json"), timeout=45
    )
    try:
        compose_config = json.loads(config_output) if config_code == 0 else {}
        compose_services = compose_config.get("services", {})
        compose_project = str(compose_config.get("name") or "")
    except json.JSONDecodeError:
        compose_services = {}
        compose_project = ""
        config_error = "docker compose config returned invalid JSON"

    result: dict[str, Any] = {}
    for name, (service_parts, runtime_command) in commands.items():
        service = service_parts[0]
        service_config = compose_services.get(service, {})
        image_reference = str(service_config.get("image") or "")
        if not image_reference and service_config.get("build") and compose_project:
            image_reference = f"{compose_project}-{service}"
        if not image_reference:
            result[name] = {
                "available": False,
                "error": config_error or f"Compose did not resolve an image for {service}",
            }
            continue
        inspect_code, image_id, inspect_error = run(
            ["docker", "image", "inspect", image_reference, "--format", "{{.Id}}"], timeout=45
        )
        if inspect_code != 0:
            result[name] = {
                "available": False,
                "image_reference": image_reference,
                "error": inspect_error or "image not built",
            }
            continue
        code, output, error = run(
            ["docker", "run", "--rm", "--entrypoint", runtime_command[0], image_reference, *runtime_command[1:]],
            timeout=60,
        )
        result[name] = {
            "available": code == 0,
            "version_output": (output or error).splitlines()[0] if (output or error) else None,
            "image_id": image_id,
            "image_reference": image_reference,
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


def payload_inventory() -> dict[str, Any]:
    path = ROOT / "common" / "payloads" / "customers_create.jsonl"
    try:
        count = 0
        last_byte = b""
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                count += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if last_byte and last_byte != b"\n":
            count += 1
        return {
            "available": True,
            "customers_create": count,
            "minimum_customers_create": EXPECTED_CUSTOMER_CREATE_PAYLOADS,
            "path": str(path),
        }
    except OSError as exc:
        return {
            "available": False,
            "customers_create": 0,
            "minimum_customers_create": EXPECTED_CUSTOMER_CREATE_PAYLOADS,
            "path": str(path),
            "error": str(exc),
        }


def project_verification() -> dict[str, Any]:
    try:
        value = json.loads(VERIFICATION_EVIDENCE.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {"available": False, "error": "invalid root"}
    except FileNotFoundError:
        return {"available": False, "error": "project verification evidence is missing"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc)}


def verification_matches_current_project(
    verification: dict[str, Any], git: dict[str, Any], expected_methodology: int | None = None
) -> bool:
    expected_methodology = expected_methodology or methodology_version()
    return (
        verification.get("available") is True
        and verification.get("completed") is True
        and verification.get("methodology_version") == expected_methodology
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


def build_report(mode: str, api_service: str | None = None, load_profile: str = "environment") -> dict[str, Any]:
    environment = load_env()
    expected_methodology = methodology_version(environment)
    expected_locust_processes = configured_locust_processes(environment)
    git = git_provenance()
    docker = docker_environment()
    images = configured_images()
    bases = dockerfile_bases()
    host = host_environment()
    postgres = postgres_version()
    runtimes = runtime_versions()
    libraries = manifest_versions()
    verification = project_verification()
    payloads = payload_inventory()
    configured_resources = configured_resource_policy(api_service)
    runtime_resources = runtime_resource_policy(api_service)
    calibration_required = load_profile.startswith(("fixed_", "saturation_"))
    calibration_path = ROOT / environment.get(
        "LOAD_GENERATOR_CALIBRATION_FILE", "results/summaries/load-generator-calibration.json"
    )
    calibration = (
        validate_calibration(
            calibration_path,
            expected_methodology,
            git,
            docker,
            images,
            EXPECTED_LOCUST_PROCESSES,
            EXPECTED_CPU_LIMITS["locust"],
        )
        if calibration_required
        else {"available": False, "valid": True, "required": False, "reasons": []}
    )
    calibration["required"] = calibration_required
    violations: list[str] = []
    if not docker.get("available"):
        violations.append("Docker Engine, Compose and allocation information must all be available")
    if expected_locust_processes is None:
        violations.append("LOCUST_PROCESSES must be a positive integer")
    elif expected_locust_processes != EXPECTED_LOCUST_PROCESSES:
        violations.append(
            f"LOCUST_PROCESSES must be {EXPECTED_LOCUST_PROCESSES}; configured {expected_locust_processes}"
        )
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
    if not payloads.get("available") or payloads.get("customers_create", 0) < EXPECTED_CUSTOMER_CREATE_PAYLOADS:
        violations.append(
            f"customers_create.jsonl must contain at least {EXPECTED_CUSTOMER_CREATE_PAYLOADS} unique payloads"
        )
    allocation = docker.get("allocation", {})
    if not allocation.get("logical_processors") or not allocation.get("memory_bytes"):
        violations.append("Effective Docker CPU or memory allocation is unavailable")
    elif allocation["logical_processors"] < EXPECTED_DOCKER_LOGICAL_PROCESSORS:
        violations.append(
            "Docker must expose at least "
            f"{EXPECTED_DOCKER_LOGICAL_PROCESSORS} logical processors to provide aggregate headroom for "
            f"the API (2), PostgreSQL (1), Locust (4) and monitoring services; detected "
            f"{allocation['logical_processors']}"
        )
    if not configured_resources.get("available"):
        violations.append("Configured per-container CPU quotas could not be read from Docker Compose")
    else:
        for service, details in configured_resources.get("limits", {}).items():
            if not details.get("matches_expected"):
                violations.append(
                    f"{service} CPU quota must be {details.get('expected_cpus')}; "
                    f"configured {details.get('configured_cpus') or 'unavailable'}"
                )
    for service, details in runtime_resources.get("limits", {}).items():
        if not details.get("matches_expected"):
            violations.append(
                f"{service} effective CPU quota must be {details.get('expected_cpus')}; "
                f"detected {details.get('effective_cpu_quota') or 'unavailable'}"
            )
    if mode == "official":
        if calibration_required and not calibration.get("valid"):
            violations.append(
                "A current health-only Locust calibration is required: "
                + "; ".join(calibration.get("reasons", []))
            )
        if not verification_matches_current_project(verification, git, expected_methodology):
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
            "methodology_version": expected_methodology,
            "locust_processes": EXPECTED_LOCUST_PROCESSES,
            "images": EXPECTED_IMAGES,
            "cpu_limits": EXPECTED_CPU_LIMITS,
            "docker_logical_processors": EXPECTED_DOCKER_LOGICAL_PROCESSORS,
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
        "payload_inventory": payloads,
        "resource_policy": {
            "semantics": "CPU quotas are maximum shares, not exclusive reservations",
            "configured": configured_resources,
            "effective": runtime_resources,
        },
        "load_profile": load_profile,
        "load_generator_calibration": calibration,
        "project_verification": verification,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect benchmark provenance and enforce official-run prerequisites.")
    parser.add_argument("--mode", choices=("pilot", "official"), default="pilot")
    parser.add_argument("--api-service", choices=tuple(EXPECTED_CPU_LIMITS)[2:])
    parser.add_argument("--load-profile", default="environment")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.mode, args.api_service, args.load_profile)
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
