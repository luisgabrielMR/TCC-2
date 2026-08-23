#!/usr/bin/env python3
"""Generate a self-contained HTML dashboard from benchmark result CSV files."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
OUTPUT = ROOT / "results" / "summaries" / "benchmark_dashboard.html"
LANGUAGE_ORDER = {name: index for index, name in enumerate(("python", "node", "java", "go", "dotnet"))}


def number(value: str | None) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def median(rows: list[dict], key: str) -> float:
    values = [number(row.get(key)) for row in rows if row.get(key) not in (None, "")]
    return statistics.median(values) if values else 0.0


def comparable_rows(rows: list[dict]) -> list[dict]:
    """Prefer runs produced by the current methodology over legacy results."""
    current = [row for row in rows if row.get("loadProfile", "legacy") != "legacy"]
    candidates = current or rows
    latest_version = max(int(number(row.get("methodologyVersion")) or 1) for row in candidates)
    return [row for row in candidates if int(number(row.get("methodologyVersion")) or 1) == latest_version]


def measurement_status(change_percent: float, final_windows_stable: bool, available: bool = True) -> str:
    if not available:
        return "unavailable"
    if not final_windows_stable:
        return "fluctuating"
    if change_percent > 10:
        return "possible_late_warmup"
    if change_percent < -10:
        return "decreasing_throughput"
    return "stable"


def result_confidence(rows: list[dict]) -> str:
    if any(row.get("resultClassification") in {"non_official", "legacy"} for row in rows):
        return "non_official"
    if any(row["failures"] > 0 for row in rows):
        return "invalid_failures"
    if any(not row["resourceMetricsAvailable"] for row in rows):
        return "invalid_missing_resources"
    if any(not row["exactMeasurementWindow"] for row in rows):
        return "invalid_measurement_window"
    if any(row["locustCpuMax"] >= 90 for row in rows):
        return "invalid_load_generator"
    if any(not row["measurementAvailable"] or not row["measurementFinalStable"] or abs(row["measurementRpsChange"]) > 10 for row in rows):
        return "invalid_instability"
    if len(rows) < 3:
        return "preliminary_fewer_than_3_runs"
    order_positions = {row["executionOrderPosition"] for row in rows}
    if 0 in order_positions or len(order_positions) < 3:
        return "invalid_order_bias"
    rps_values = [row["rps"] for row in rows]
    rps_median = statistics.median(rps_values) if rps_values else 0
    if rps_median <= 0 or (max(rps_values) - min(rps_values)) / rps_median * 100 > 10:
        return "invalid_run_variability"
    return "adequate"


def read_metadata(run_directory: Path) -> dict:
    path = run_directory / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def use_cadvisor_resources(metadata: dict) -> bool:
    methodology = int(number(metadata.get("methodology_version")) or 1)
    return methodology >= 6 and metadata.get("result_classification") == "official"


def read_resources(run_directory: Path, metadata: dict) -> tuple[list[dict[str, str]], str]:
    if use_cadvisor_resources(metadata):
        return read_csv_rows(run_directory / "cadvisor_summary.csv"), "cadvisor_via_prometheus"
    return read_csv_rows(run_directory / "docker_stats_summary.csv"), "docker_stats_complementary"


def find_resource(rows: list[dict[str, str]], predicate) -> dict[str, str]:
    return next((row for row in rows if predicate(row.get("container_name", ""))), {})


def elapsed_seconds(metadata: dict) -> float:
    elapsed = number(metadata.get("test_phase", {}).get("elapsed_seconds"))
    if elapsed > 0:
        return elapsed
    metrics = metadata.get("metrics", {})
    started = number(metrics.get("started_epoch"))
    finished = number(metrics.get("finished_epoch"))
    return finished - started if finished > started > 0 else 0.0


def collect() -> dict:
    runs: list[dict] = []
    endpoint_runs: list[dict] = []

    for stats_path in sorted(RAW.glob("*/*/run_*/locust_stats.csv")):
        language, scenario, run_dir = stats_path.relative_to(RAW).parts[:3]
        run_number = int(run_dir.removeprefix("run_"))
        with stats_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        aggregate = next((row for row in rows if row.get("Name") == "Aggregated"), None)
        if aggregate is None:
            continue

        metadata = read_metadata(stats_path.parent)
        resources, resource_source = read_resources(stats_path.parent, metadata)
        cadvisor_rows = read_csv_rows(stats_path.parent / "cadvisor_summary.csv")
        api = find_resource(resources, lambda name: name == f"tcc_benchmark_{language}_api")
        locust = find_resource(resources, lambda name: "locust-run-" in name or name == "tcc_benchmark_locust")
        postgres = find_resource(resources, lambda name: name == "tcc_benchmark_postgres")
        cadvisor_api = find_resource(cadvisor_rows, lambda name: name == f"tcc_benchmark_{language}_api")
        cadvisor_locust = find_resource(cadvisor_rows, lambda name: name == "tcc_benchmark_locust")
        cadvisor_postgres = find_resource(cadvisor_rows, lambda name: name == "tcc_benchmark_postgres")
        locust_metadata = metadata.get("locust", {})
        measurement = metadata.get("measurement_stability", {})
        methodology_version = int(number(metadata.get("methodology_version")) or 1)
        classification = metadata.get("result_classification", "legacy")
        cadvisor_available = bool(cadvisor_api and cadvisor_locust and cadvisor_postgres)
        runs.append({
            "language": language,
            "scenario": scenario,
            "run": run_number,
            "loadProfile": metadata.get("load_profile", "legacy"),
            "methodologyVersion": methodology_version,
            "resultClassification": classification,
            "executionOrderPosition": int(number(metadata.get("execution_order", {}).get("position"))),
            "users": number(locust_metadata.get("users")),
            "testElapsedSeconds": elapsed_seconds(metadata),
            "benchmarkKind": metadata.get("benchmark_kind", "controlled_load"),
            "requests": number(aggregate.get("Request Count")),
            "failures": number(aggregate.get("Failure Count")),
            "rps": number(aggregate.get("Requests/s")),
            "avgMs": number(aggregate.get("Average Response Time")),
            "p50Ms": number(aggregate.get("50%")),
            "p95Ms": number(aggregate.get("95%")),
            "p99Ms": number(aggregate.get("99%")),
            "cpuAvg": number(api.get("cpu_average_percent")),
            "cpuMax": number(api.get("cpu_max_percent")),
            "memoryAvgMiB": number(api.get("memory_average_bytes")) / 1024 / 1024,
            "memoryMaxMiB": number(api.get("memory_max_bytes")) / 1024 / 1024,
            "locustCpuAvg": number(locust.get("cpu_average_percent")),
            "locustCpuMax": number(locust.get("cpu_max_percent")),
            "postgresCpuAvg": number(postgres.get("cpu_average_percent")),
            "resourceMetricSource": resource_source,
            "resourceMetricsAvailable": bool(api and locust and postgres) and (
                not use_cadvisor_resources(metadata)
                or bool(metadata.get("monitoring_preflight", {}).get("official_eligible"))
            ),
            "exactMeasurementWindow": (
                methodology_version >= 5
                and metadata.get("metrics", {}).get("window_source") == "locust_test_start_stop"
            ),
            "measurementAvailable": bool(measurement),
            "measurementFinalStable": bool(measurement.get("stable")),
            "measurementRpsChange": number(measurement.get("first_last_rps_change_percent")),
        })

        for row in rows:
            if row.get("Name") == "Aggregated":
                continue
            endpoint_runs.append({
                "language": language,
                "scenario": scenario,
                "run": run_number,
                "loadProfile": metadata.get("load_profile", "legacy"),
                "methodologyVersion": methodology_version,
                "resultClassification": classification,
                "users": number(locust_metadata.get("users")),
                "endpoint": row.get("Name", ""),
                "method": row.get("Type", ""),
                "requests": number(row.get("Request Count")),
                "failures": number(row.get("Failure Count")),
                "rps": number(row.get("Requests/s")),
                "avgMs": number(row.get("Average Response Time")),
                "p50Ms": number(row.get("50%")),
                "p95Ms": number(row.get("95%")),
                "p99Ms": number(row.get("99%")),
            })

    if not runs:
        return {
            "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "scenarios": {},
            "scalability": {},
        }

    scenarios: dict[str, dict] = {}
    scenario_names = sorted({row["scenario"] for row in runs})
    for scenario in scenario_names:
        summary_groups: dict[tuple[str, str, int, str], list[dict]] = defaultdict(list)
        endpoint_groups: dict[tuple[str, str, str, str, int, str], list[dict]] = defaultdict(list)
        for row in runs:
            if row["scenario"] == scenario:
                summary_groups[(
                    row["language"], row["loadProfile"], row["methodologyVersion"], row["resultClassification"]
                )].append(row)

        selected_run_keys = {
            (row["language"], row["loadProfile"], row["methodologyVersion"], row["resultClassification"], row["run"])
            for rows in summary_groups.values()
            for row in rows
        }
        for row in endpoint_runs:
            if row["scenario"] == scenario and (
                row["language"], row["loadProfile"], row["methodologyVersion"], row["resultClassification"], row["run"]
            ) in selected_run_keys:
                endpoint_groups[(
                    row["endpoint"], row["method"], row["language"], row["loadProfile"],
                    row["methodologyVersion"], row["resultClassification"],
                )].append(row)

        summary = []
        for (language, load_profile, methodology, classification), rows in summary_groups.items():
            total_requests = sum(row["requests"] for row in rows)
            total_failures = sum(row["failures"] for row in rows)
            trend_rows = [row for row in rows if row["measurementAvailable"]]
            measurement_change = median(trend_rows, "measurementRpsChange")
            summary.append({
                "language": language,
                "loadProfile": load_profile,
                "methodologyVersion": methodology,
                "resultClassification": classification,
                "runs": len(rows),
                "users": median(rows, "users"),
                "testElapsedSeconds": median(rows, "testElapsedSeconds"),
                "benchmarkKind": rows[0]["benchmarkKind"],
                "requests": median(rows, "requests"),
                "failures": total_failures,
                "errorRate": total_failures / total_requests if total_requests else 0,
                "rps": median(rows, "rps"),
                "avgMs": median(rows, "avgMs"),
                "p50Ms": median(rows, "p50Ms"),
                "p95Ms": median(rows, "p95Ms"),
                "p99Ms": median(rows, "p99Ms"),
                "cpuAvg": median(rows, "cpuAvg"),
                "cpuMax": median(rows, "cpuMax"),
                "memoryAvgMiB": median(rows, "memoryAvgMiB"),
                "memoryMaxMiB": median(rows, "memoryMaxMiB"),
                "locustCpuAvg": median(rows, "locustCpuAvg"),
                "postgresCpuAvg": median(rows, "postgresCpuAvg"),
                "measurementRpsChange": measurement_change,
                "measurementStatus": measurement_status(
                    measurement_change,
                    all(row["measurementFinalStable"] for row in trend_rows),
                    bool(trend_rows),
                ),
                "confidence": result_confidence(rows),
            })
        summary.sort(key=lambda row: LANGUAGE_ORDER.get(row["language"], 99))

        endpoints: dict[str, list[dict]] = defaultdict(list)
        for (endpoint, method, language, load_profile, methodology, classification), rows in endpoint_groups.items():
            label = endpoint if endpoint.upper().startswith(f"{method.upper()} ") else f"{method} {endpoint}"
            endpoints[label].append({
                "language": language,
                "loadProfile": load_profile,
                "methodologyVersion": methodology,
                "resultClassification": classification,
                "runs": len(rows),
                "requests": median(rows, "requests"),
                "failures": sum(row["failures"] for row in rows),
                "rps": median(rows, "rps"),
                "avgMs": median(rows, "avgMs"),
                "p50Ms": median(rows, "p50Ms"),
                "p95Ms": median(rows, "p95Ms"),
                "p99Ms": median(rows, "p99Ms"),
            })
        for rows in endpoints.values():
            rows.sort(key=lambda row: LANGUAGE_ORDER.get(row["language"], 99))

        scenarios[scenario] = {
            "summary": summary,
            "endpoints": dict(sorted(endpoints.items())),
        }

    baseline = {
        (row["language"], row["methodologyVersion"], row["resultClassification"]): row
        for row in scenarios.get("mixed", {}).get("summary", [])
        if row["loadProfile"] == "controlled_50"
    }
    scalability: dict[str, list[dict]] = defaultdict(list)
    for scenario, scenario_data in scenarios.items():
        if scenario != "mixed" and not scenario.startswith("mixed_capacity_"):
            continue
        for row in scenario_data["summary"]:
            cohort = (row["language"], row["methodologyVersion"], row["resultClassification"])
            base = baseline.get(cohort, row)
            base_rps = base["rps"]
            expected_rps = base_rps * row["users"] / base["users"] if base["users"] else 0
            efficiency = row["rps"] / expected_rps * 100 if expected_rps else 0
            cohort_key = "|".join(map(str, cohort))
            scalability[cohort_key].append({
                "language": row["language"],
                "methodologyVersion": row["methodologyVersion"],
                "resultClassification": row["resultClassification"],
                "scenario": scenario,
                "users": row["users"],
                "rps": row["rps"],
                "p95Ms": row["p95Ms"],
                "failures": row["failures"],
                "testElapsedSeconds": row["testElapsedSeconds"],
                "scaleEfficiency": efficiency,
                "locustCpuAvg": row["locustCpuAvg"],
                "measurementRpsChange": row["measurementRpsChange"],
                "measurementStatus": row["measurementStatus"],
            })
    for rows in scalability.values():
        rows.sort(key=lambda row: row["users"])
        previous = None
        for row in rows:
            row["rpsGainPrevious"] = (row["rps"] / previous["rps"] - 1) * 100 if previous and previous["rps"] else 0
            if row["users"] == 50:
                row["status"] = "baseline"
            elif row["failures"]:
                row["status"] = "failures_detected"
            elif row["locustCpuAvg"] >= 90:
                row["status"] = "load_generator_limit"
            elif row["rpsGainPrevious"] < 10:
                row["status"] = "probable_saturation"
            else:
                row["status"] = "scaling"
            previous = row

    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scenarios": scenarios,
        "scalability": dict(sorted(
            scalability.items(),
            key=lambda item: (
                LANGUAGE_ORDER.get(item[1][0]["language"], 99),
                item[1][0]["methodologyVersion"], item[1][0]["resultClassification"],
            ),
        )),
    }


def render(data: dict) -> str:
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Resultados do benchmark</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, "Segoe UI", Arial, sans-serif; background: #f4f6f8; color: #17212b; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #f4f6f8; }}
    header {{ background: #ffffff; border-bottom: 1px solid #dce2e8; }}
    .header-inner, main {{ width: min(1440px, calc(100% - 32px)); margin: 0 auto; }}
    .header-inner {{ min-height: 76px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }}
    h1 {{ margin: 0; font-size: 24px; line-height: 1.2; letter-spacing: 0; }}
    .subtitle {{ margin: 5px 0 0; color: #637180; font-size: 13px; }}
    .controls {{ display: flex; align-items: center; gap: 10px; }}
    label {{ color: #52606d; font-size: 13px; font-weight: 600; }}
    select {{ min-width: 150px; height: 36px; border: 1px solid #bac5cf; border-radius: 6px; background: #fff; padding: 0 34px 0 10px; color: #17212b; }}
    main {{ padding: 24px 0 40px; }}
    .summary-strip {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border: 1px solid #dce2e8; background: #fff; border-radius: 8px; overflow: hidden; }}
    .summary-item {{ min-height: 92px; padding: 18px; border-right: 1px solid #e4e9ee; }}
    .summary-item:last-child {{ border-right: 0; }}
    .summary-label {{ color: #6b7785; font-size: 12px; font-weight: 700; text-transform: uppercase; }}
    .summary-value {{ margin-top: 8px; font-size: 24px; font-weight: 750; font-variant-numeric: tabular-nums; }}
    .status-ok {{ color: #087a4b; }}
    .method-note {{ margin: 14px 0 0; padding: 11px 14px; border-left: 3px solid #2b6f89; background: #eef5f7; color: #344b57; font-size: 13px; }}
    .section-title {{ margin: 28px 0 12px; font-size: 17px; letter-spacing: 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
    .panel {{ background: #fff; border: 1px solid #dce2e8; border-radius: 8px; padding: 18px; min-width: 0; }}
    .panel-head {{ display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 18px; }}
    .panel h3 {{ margin: 0; font-size: 15px; letter-spacing: 0; }}
    .hint {{ color: #778493; font-size: 12px; }}
    .bar-chart {{ display: grid; gap: 13px; }}
    .bar-row {{ display: grid; grid-template-columns: 72px minmax(80px, 1fr) 86px; align-items: center; gap: 10px; min-height: 26px; }}
    .bar-label {{ font-size: 13px; font-weight: 650; text-transform: capitalize; }}
    .bar-track {{ height: 12px; background: #edf1f4; border-radius: 3px; overflow: hidden; }}
    .bar-fill {{ height: 100%; width: var(--width); background: var(--bar); border-radius: 3px; transition: width 220ms ease; }}
    .bar-value {{ text-align: right; color: #344250; font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid #dce2e8; border-radius: 8px; background: #fff; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid #e7ebef; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
    th {{ position: sticky; top: 0; background: #f7f9fa; color: #52606d; font-size: 11px; text-transform: uppercase; }}
    th:first-child, td:first-child {{ text-align: left; }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    tbody tr:hover {{ background: #f8fafb; }}
    .language {{ display: inline-flex; align-items: center; gap: 8px; font-weight: 700; text-transform: capitalize; }}
    .swatch {{ width: 10px; height: 10px; border-radius: 2px; background: var(--bar); flex: none; }}
    .endpoint-toolbar {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }}
    .endpoint-toolbar select {{ min-width: min(460px, 70vw); }}
    footer {{ margin-top: 22px; color: #71808e; font-size: 12px; }}
    @media (max-width: 860px) {{
      .header-inner {{ align-items: flex-start; flex-direction: column; padding: 16px 0; gap: 14px; }}
      .controls {{ width: 100%; justify-content: space-between; }}
      .summary-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .summary-item {{ border-bottom: 1px solid #e4e9ee; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 520px) {{
      .header-inner, main {{ width: min(100% - 20px, 1440px); }}
      .summary-strip {{ grid-template-columns: 1fr; }}
      .summary-item {{ border-right: 0; border-bottom: 1px solid #e4e9ee; }}
      .summary-item:last-child {{ border-bottom: 0; }}
      .bar-row {{ grid-template-columns: 62px minmax(70px, 1fr) 72px; gap: 7px; }}
      .endpoint-toolbar {{ align-items: stretch; flex-direction: column; }}
      .endpoint-toolbar select {{ min-width: 0; width: 100%; }}
    }}
    @media print {{
      body {{ background: #fff; }}
      .controls, .endpoint-toolbar label {{ display: none; }}
      .header-inner, main {{ width: 100%; }}
      .panel, .summary-strip, .table-wrap {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <div>
        <h1>Resultados do benchmark</h1>
        <p class="subtitle" id="generatedAt"></p>
      </div>
      <div class="controls">
        <label for="scenario">Cenário</label>
        <select id="scenario"></select>
      </div>
    </div>
  </header>
  <main>
    <section class="summary-strip" aria-label="Resumo">
      <div class="summary-item"><div class="summary-label">Linguagens</div><div class="summary-value" id="languageCount">0</div></div>
      <div class="summary-item"><div class="summary-label">Rodadas</div><div class="summary-value" id="runCount">0</div></div>
      <div class="summary-item"><div class="summary-label">Usuários</div><div class="summary-value" id="userCount">0</div></div>
      <div class="summary-item"><div class="summary-label">Falhas</div><div class="summary-value" id="failureCount">0</div></div>
      <div class="summary-item"><div class="summary-label">Maior vazão</div><div class="summary-value" id="bestRps">0 RPS</div></div>
    </section>
    <p class="method-note" id="methodNote"></p>

    <h2 class="section-title">Comparação geral</h2>
    <section class="grid">
      <article class="panel"><div class="panel-head"><h3>Vazão</h3><span class="hint">maior é melhor</span></div><div class="bar-chart" id="rpsChart"></div></article>
      <article class="panel"><div class="panel-head"><h3>Latência P95</h3><span class="hint">menor é melhor</span></div><div class="bar-chart" id="p95Chart"></div></article>
      <article class="panel"><div class="panel-head"><h3>CPU média</h3><span class="hint">100% equivale a 1 núcleo lógico</span></div><div class="bar-chart" id="cpuChart"></div></article>
      <article class="panel"><div class="panel-head"><h3>Memória média</h3><span class="hint">MiB por container</span></div><div class="bar-chart" id="memoryChart"></div></article>
      <article class="panel"><div class="panel-head"><h3>Tempo total medido</h3><span class="hint">sem aquecimento</span></div><div class="bar-chart" id="durationChart"></div></article>
      <article class="panel"><div class="panel-head"><h3>CPU média do Locust</h3><span class="hint">limite do gerador</span></div><div class="bar-chart" id="locustCpuChart"></div></article>
    </section>

    <h2 class="section-title">Valores consolidados</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>Linguagem</th><th>Usuários</th><th>Rodadas</th><th>Confiança</th><th>Tempo</th><th>Tendência RPS</th><th>Req./rodada</th><th>Falhas</th><th>RPS</th><th>Média</th><th>P50</th><th>P95</th><th>P99</th><th>CPU API</th><th>CPU Locust</th><th>CPU PostgreSQL</th><th>Memória média</th></tr></thead>
      <tbody id="summaryRows"></tbody>
    </table></div>

    <h2 class="section-title">Comparação por endpoint</h2>
    <div class="endpoint-toolbar"><label for="endpoint">Endpoint</label><select id="endpoint"></select></div>
    <section class="grid">
      <article class="panel"><div class="panel-head"><h3>Latência P95</h3><span class="hint">menor é melhor</span></div><div class="bar-chart" id="endpointP95"></div></article>
      <article class="panel"><div class="panel-head"><h3>Vazão do endpoint</h3><span class="hint">maior é melhor</span></div><div class="bar-chart" id="endpointRps"></div></article>
    </section>

    <h2 class="section-title">Escalabilidade</h2>
    <div class="endpoint-toolbar"><label for="scalingLanguage">Linguagem</label><select id="scalingLanguage"></select></div>
    <section class="grid">
      <article class="panel"><div class="panel-head"><h3>RPS por quantidade de usuários</h3><span class="hint">50, 100 e 200</span></div><div class="bar-chart" id="capacityRps"></div></article>
      <article class="panel"><div class="panel-head"><h3>Eficiência de escala</h3><span class="hint">100% equivale a crescimento linear</span></div><div class="bar-chart" id="capacityEfficiency"></div></article>
    </section>
    <div class="table-wrap" style="margin-top:16px"><table>
      <thead><tr><th>Usuários</th><th>RPS</th><th>Ganho anterior</th><th>P95</th><th>Eficiência</th><th>CPU Locust</th><th>Tempo</th><th>Tendência RPS</th><th>Estado</th></tr></thead>
      <tbody id="capacityRows"></tbody>
    </table></div>
    <footer>Valores consolidados pela mediana das rodadas disponíveis. Em CPU, 100% equivale aproximadamente a um núcleo lógico. O limite indicado é prático e vale somente para este ambiente.</footer>
  </main>
  <script>
    const DATA = {serialized};
    const COLORS = {{python: "#3776ab", node: "#3c873a", java: "#d1493f", go: "#168ca5", dotnet: "#6f4aa8"}};
    const names = {{python: "Python", node: "Node.js", java: "Java", go: "Go", dotnet: ".NET"}};
    const scenarioSelect = document.querySelector("#scenario");
    const endpointSelect = document.querySelector("#endpoint");
    const scalingLanguageSelect = document.querySelector("#scalingLanguage");
    const fmt = new Intl.NumberFormat("pt-BR", {{maximumFractionDigits: 2}});
    const statuses = {{baseline: "base controlada", scaling: "escalando", probable_saturation: "saturação provável", failures_detected: "falhas detectadas", load_generator_limit: "limite do Locust"}};
    const trendStatuses = {{stable: "estável", possible_late_warmup: "possível aquecimento", decreasing_throughput: "queda ao longo do teste", fluctuating: "oscilando", unavailable: "indisponível"}};
    const confidenceStatuses = {{adequate: "adequada", non_official: "não oficial", preliminary_fewer_than_3_runs: "preliminar (<3)", invalid_failures: "inválida: falhas", invalid_missing_resources: "inválida: métricas ausentes", invalid_measurement_window: "inválida: janela", invalid_load_generator: "inválida: Locust", invalid_instability: "inválida: instável", invalid_order_bias: "inválida: ordem fixa", invalid_run_variability: "inválida: variação"}};

    function color(language) {{ return COLORS[language] || "#52606d"; }}
    function displayName(language) {{ return names[language] || language; }}
    function value(value, suffix = "") {{ return `${{fmt.format(value)}}${{suffix}}`; }}

    function bars(targetId, rows, key, suffix = "") {{
      const target = document.querySelector(`#${{targetId}}`);
      const max = Math.max(...rows.map(row => row[key]), 1);
      target.innerHTML = rows.map(row => `
        <div class="bar-row">
          <div class="bar-label">${{displayName(row.language)}}</div>
          <div class="bar-track"><div class="bar-fill" style="--bar:${{color(row.language)}};--width:${{Math.max((row[key] / max) * 100, row[key] > 0 ? 1 : 0)}}%"></div></div>
          <div class="bar-value">${{value(row[key], suffix)}}</div>
        </div>`).join("");
    }}

    function levelBars(targetId, rows, key, suffix = "") {{
      const target = document.querySelector(`#${{targetId}}`);
      const max = Math.max(...rows.map(row => row[key]), 1);
      const language = rows[0]?.language || "";
      target.innerHTML = rows.map(row => `
        <div class="bar-row">
          <div class="bar-label">${{fmt.format(row.users)}} usr.</div>
          <div class="bar-track"><div class="bar-fill" style="--bar:${{color(language)}};--width:${{Math.max((row[key] / max) * 100, row[key] > 0 ? 1 : 0)}}%"></div></div>
          <div class="bar-value">${{value(row[key], suffix)}}</div>
        </div>`).join("");
    }}

    function renderScaling() {{
      const rows = DATA.scalability[scalingLanguageSelect.value] || [];
      levelBars("capacityRps", rows, "rps", " RPS");
      levelBars("capacityEfficiency", rows, "scaleEfficiency", "%");
      document.querySelector("#capacityRows").innerHTML = rows.map(row => `
        <tr><td>${{fmt.format(row.users)}}</td><td>${{value(row.rps)}}</td><td>${{value(row.rpsGainPrevious, "%")}}</td>
        <td>${{value(row.p95Ms, " ms")}}</td><td>${{value(row.scaleEfficiency, "%")}}</td>
        <td>${{value(row.locustCpuAvg, "%")}}</td><td>${{value(row.testElapsedSeconds, " s")}}</td>
        <td>${{value(row.measurementRpsChange, "%")}} (${{trendStatuses[row.measurementStatus] || row.measurementStatus}})</td>
        <td>${{statuses[row.status] || row.status}}</td></tr>`).join("");
    }}

    function renderEndpoint() {{
      const scenario = DATA.scenarios[scenarioSelect.value];
      const rows = scenario.endpoints[endpointSelect.value] || [];
      bars("endpointP95", rows, "p95Ms", " ms");
      bars("endpointRps", rows, "rps", " RPS");
    }}

    function renderScenario() {{
      const scenario = DATA.scenarios[scenarioSelect.value];
      const rows = scenario.summary;
      const failures = rows.reduce((sum, row) => sum + row.failures, 0);
      const best = [...rows].sort((a, b) => b.rps - a.rps)[0];
      document.querySelector("#languageCount").textContent = rows.length;
      document.querySelector("#runCount").textContent = rows.reduce((sum, row) => sum + row.runs, 0);
      document.querySelector("#userCount").textContent = rows.length ? fmt.format(rows[0].users) : "0";
      document.querySelector("#methodNote").textContent = rows.some(row => row.benchmarkKind === "capacity")
        ? "Teste extra de escalabilidade. O resultado representa o limite prático observado neste computador."
        : "Carga controlada com 50 usuários. Este cenário não representa a capacidade máxima da API.";
      const failureNode = document.querySelector("#failureCount");
      failureNode.textContent = fmt.format(failures);
      failureNode.classList.toggle("status-ok", failures === 0);
      document.querySelector("#bestRps").textContent = best ? value(best.rps, " RPS") : "0 RPS";

      bars("rpsChart", rows, "rps", " RPS");
      bars("p95Chart", rows, "p95Ms", " ms");
      bars("cpuChart", rows, "cpuAvg", "%");
      bars("memoryChart", rows, "memoryAvgMiB", " MiB");
      bars("durationChart", rows, "testElapsedSeconds", " s");
      bars("locustCpuChart", rows, "locustCpuAvg", "%");

      document.querySelector("#summaryRows").innerHTML = rows.map(row => `
        <tr>
          <td><span class="language"><span class="swatch" style="--bar:${{color(row.language)}}"></span>${{displayName(row.language)}}</span></td>
          <td>${{fmt.format(row.users)}}</td><td>${{row.runs}}</td><td>${{confidenceStatuses[row.confidence] || row.confidence}}</td><td>${{value(row.testElapsedSeconds)}} s</td>
          <td>${{value(row.measurementRpsChange, "%")}} (${{trendStatuses[row.measurementStatus] || row.measurementStatus}})</td>
          <td>${{fmt.format(Math.round(row.requests))}}</td><td>${{fmt.format(row.failures)}}</td>
          <td>${{value(row.rps)}}</td><td>${{value(row.avgMs)}} ms</td><td>${{value(row.p50Ms)}} ms</td>
          <td>${{value(row.p95Ms)}} ms</td><td>${{value(row.p99Ms)}} ms</td><td>${{value(row.cpuAvg)}}%</td>
          <td>${{value(row.locustCpuAvg)}}%</td><td>${{value(row.postgresCpuAvg)}}%</td>
          <td>${{value(row.memoryAvgMiB)}} MiB</td>
        </tr>`).join("");

      const previousEndpoint = endpointSelect.value;
      endpointSelect.innerHTML = Object.keys(scenario.endpoints).map(endpoint => `<option value="${{endpoint}}">${{endpoint}}</option>`).join("");
      if (Object.hasOwn(scenario.endpoints, previousEndpoint)) endpointSelect.value = previousEndpoint;
      renderEndpoint();
    }}

    document.querySelector("#generatedAt").textContent = `Gerado em ${{new Date(DATA.generatedAt).toLocaleString("pt-BR")}}`;
    const availableScenarios = Object.entries(DATA.scenarios);
    scenarioSelect.innerHTML = availableScenarios.map(([name, scenario]) => `<option value="${{name}}">${{name}} (${{fmt.format(scenario.summary[0]?.users || 0)}} usuários)</option>`).join("");
    scalingLanguageSelect.innerHTML = Object.entries(DATA.scalability).map(([key, rows]) => {{
      const row = rows[0];
      return `<option value="${{key}}">${{displayName(row.language)}} · metodologia ${{row.methodologyVersion}} · ${{row.resultClassification}}</option>`;
    }}).join("");
    scenarioSelect.addEventListener("change", renderScenario);
    endpointSelect.addEventListener("change", renderEndpoint);
    scalingLanguageSelect.addEventListener("change", renderScaling);
    if (availableScenarios.length) {{
      renderScenario();
      renderScaling();
    }} else {{
      scenarioSelect.disabled = true;
      endpointSelect.disabled = true;
      scalingLanguageSelect.disabled = true;
      document.querySelector("#methodNote").textContent = "Nenhuma rodada oficial disponível. Execute a bateria de testes para gerar os resultados.";
    }}
  </script>
</body>
</html>
"""


def main() -> None:
    data = collect()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render(data), encoding="utf-8", newline="\n")
    print(f"Generated {OUTPUT}")


if __name__ == "__main__":
    main()
