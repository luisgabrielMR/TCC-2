"""Build the provisioned official-results dashboard (Grafana 11 core panels)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "monitoring/grafana/dashboards/benchmark-overview.json"
SOURCE = {"type": "prometheus", "uid": "Prometheus"}
LANGUAGES = {"python": ("Python", "#E0B400"), "node": ("Node.js", "#73BF69"), "java": ("Java", "#FF9830"), "go": ("Go", "#56D9EB"), "dotnet": (".NET", "#B877D9")}
FILTER = 'classification="official",methodology="$methodology",campaign="$campaign",scenario="$scenario",load_profile="$load_profile",language=~"$language"'
LANGUAGES = dict(sorted(LANGUAGES.items()))
PANELS: list[dict] = []


def metric(name: str, extra: str = "") -> str:
    return name + "{" + FILTER + ("," + extra if extra else "") + "}"


def base(identifier, title, kind, x, y, width, height, description=""):
    return {"id": identifier, "title": title, "type": kind, "description": description,
            "gridPos": {"x": x, "y": y, "w": width, "h": height}, "datasource": SOURCE}


def target(expression, ref="A", table=False, legend="{{language}}"):
    return {"refId": ref, "expr": expression, "instant": True, "range": False,
            "editorMode": "code", "format": "table" if table else "time_series", "legendFormat": legend}


def colors():
    return [{"matcher": {"id": "byRegexp", "options": f"^({code}|{name.replace('.', '[.]')})$"},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": color}}]}
            for code, (name, color) in LANGUAGES.items()]


def row(identifier, title, y):
    panel = base(identifier, title, "row", 0, y, 24, 1)
    panel.update(collapsed=False, panels=[])
    PANELS.append(panel)


def chart(identifier, title, expressions, key, x, y, width, height, description, unit="ms", soft_max=None):
    """Use real shared-axis bars, never per-field progress gauges."""
    panel = base(identifier, title, "barchart", x, y, width, height, description)
    key_label = {"run": "Execução", "language": "Linguagem", "endpoint": "Operação"}[key]
    renamed = {key: key_label}
    targets = []
    for index, (label, expression) in enumerate(expressions):
        ref = chr(65 + index)
        targets.append(target(expression, ref, table=True))
        renamed.update({f"Value #{ref}": label, f"Value {ref}": label})
    if len(expressions) == 1:
        renamed["Value"] = expressions[0][0]
    custom = {"axisPlacement": "left", "axisLabel": {"ms": "Latência (ms)", "percent": "CPU (%)", "suffix:MiB": "Memória (MiB)"}[unit],
              "fillOpacity": 90, "lineWidth": 0, "hideFrom": {"legend": False, "tooltip": False, "viz": False}}
    if soft_max is not None:
        custom["axisSoftMax"] = soft_max
    key_properties = [{"id": "unit", "value": "none"}, {"id": "decimals", "value": 0}]
    if key == "language":
        key_properties.append({"id": "mappings", "value": [{"type": "value", "options": {
            code: {"text": name, "color": color, "index": i} for i, (code, (name, color)) in enumerate(LANGUAGES.items())}}]})
    panel.update(targets=targets, transformations=[
        {"id": "filterFieldsByName", "options": {"include": {"pattern": f"^({key}|Value.*)$"}}},
        *([{"id": "joinByField", "options": {"byField": key, "mode": "outer"}}] if len(expressions) > 1 else []),
        {"id": "organize", "options": {"renameByName": renamed, "indexByName": {}, "excludeByName": {}}},
        {"id": "sortBy", "options": {"sort": [{"field": key_label, "desc": False}], "fields": {}}},
    ], fieldConfig={"defaults": {"unit": unit, "decimals": 2 if key == "language" else 0, "min": 0,
                                 "color": {"mode": "palette-classic"}, "custom": custom},
                    "overrides": colors() + [{"matcher": {"id": "byName", "options": key_label}, "properties": key_properties}]},
                 options={"xField": key_label, "orientation": "vertical", "stacking": "none", "groupWidth": .65,
                          "barWidth": .85, "barRadius": .03, "showValue": "always" if key == "language" else "never",
                          "legend": {"showLegend": key != "language", "placement": "bottom", "displayMode": "list"},
                          "tooltip": {"mode": "multi", "sort": "none"}, "xTickLabelRotation": 0,
                          "xTickLabelSpacing": 0, "fullHighlight": False})
    if key == "language":
        panel["options"]["colorByField"] = key_label
    PANELS.append(panel)
    return panel


def by_language(name, extra=""):
    return [(label, metric(name, extra).replace('language=~"$language"', f'language="{code}"')
             + f' and on(language) {metric("benchmark_result_runs")}') for code, (label, _) in LANGUAGES.items()]


def variable(name, label, query, current, multi=False, sort=1):
    return {"name": name, "label": label, "type": "query", "datasource": SOURCE,
            "query": {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
            "definition": query, "refresh": 1, "sort": sort, "hide": 0, "includeAll": multi,
            "multi": multi, "allValue": ".*", "options": [], "regex": "", "skipUrlSync": False,
            "current": {"text": "Todas" if multi else current, "value": "$__all" if multi else current, "selected": True}}


def build():
    PANELS.clear()
    row(20, "Latência das APIs", 0)
    chart(21, "Tempo médio de resposta", [("Latência", metric("benchmark_result_latency_ms", 'quantile="avg"'))],
          "language", 0, 1, 12, 11, "Mediana das médias de latência. Eixo comum para todas as APIs, iniciado em zero. Menor = resposta mais rápida.", soft_max=40)
    chart(51, "P95 por execução", by_language("benchmark_run_latency_ms", 'quantile="p95"'),
          "run", 12, 1, 12, 11, "Cada grupo compara o P95 das APIs na execução indicada. Unidade: milissegundos. Não são percentagens nem percentis globais.")
    row(30, "Recursos das APIs", 12)
    chart(31, "Uso médio de CPU", [("CPU", metric("benchmark_result_cpu_percent", 'component="api",stat="average"'))],
          "language", 0, 13, 12, 10, "Mediana das médias de CPU do container. 100% corresponde a um núcleo lógico; cota: dois núcleos. O eixo começa em zero e acompanha os valores observados.", "percent", 30)
    chart(32, "Uso médio de memória", [("Memória", metric("benchmark_result_memory_bytes", 'stat="average"') + " / 1048576")],
          "language", 12, 13, 12, 10, "Mediana das médias do working set do container, em MiB. Fonte: cAdvisor / Prometheus.", "suffix:MiB", 250)
    row(40, "Tempo de resposta por operação", 23)
    for identifier, title, pattern, y in [(41, "Leituras · $quantile", "GET .*", 24), (42, "Escritas · $quantile", "(POST|PUT) .*", 36)]:
        chart(identifier, title, by_language("benchmark_endpoint_latency_ms", f'quantile="$quantile",endpoint=~"{pattern}"'),
              "endpoint", 0, y, 24, 12, "Mediana da métrica selecionada por operação. Cada grupo compara as APIs na mesma operação. Leituras e escritas usam escalas próprias, iniciadas em zero. GET /health não integra a carga.")
    variables = [
        variable("methodology", "Metodologia", 'label_values(benchmark_result_runs{classification="official"}, methodology)', "17", sort=4),
        variable("campaign", "Campanha", 'label_values(benchmark_result_runs{classification="official",methodology="$methodology"}, campaign)', "m17_d2716c1f9187_92483cd5afca"),
        variable("scenario", "Cenário", 'label_values(benchmark_result_runs{classification="official",campaign="$campaign"}, scenario)', "mixed_fixed_100"),
        variable("load_profile", "Perfil", 'label_values(benchmark_result_runs{classification="official",campaign="$campaign",scenario="$scenario"}, load_profile)', "fixed_100"),
        variable("language", "Linguagem", 'label_values(benchmark_result_runs{classification="official",campaign="$campaign"}, language)', "", multi=True),
        {"name": "quantile", "label": "Latência da operação", "type": "custom", "query": "Média : avg,P50 : p50,P95 : p95,P99 : p99", "current": {"text": "P95", "value": "p95"}, "options": [{"text": text, "value": value, "selected": value == "p95"} for text, value in [("Média", "avg"), ("P50", "p50"), ("P95", "p95"), ("P99", "p99")]], "multi": False, "includeAll": False, "hide": 0, "skipUrlSync": False},
    ]
    for item in variables:
        if item["name"] in {"methodology", "campaign", "scenario", "load_profile"}:
            item["hide"] = 2
    return {"annotations": {"list": []}, "id": None, "uid": "tcc-benchmark-overview", "title": "TCC Benchmark - Resultados Oficiais", "description": "Resultados oficiais: latência, CPU, memória e operações. Uma campanha por vez; diagnósticos ao vivo em outro dashboard.", "editable": True, "schemaVersion": 40, "version": 12, "timezone": "browser", "refresh": "30s", "time": {"from": "now-15m", "to": "now"}, "tags": ["tcc", "benchmark", "resultados-oficiais"], "templating": {"list": variables}, "panels": PANELS, "links": [
        {"title": "Monitoramento ao vivo", "type": "link", "url": "/d/tcc-benchmark-extras/tcc-benchmark-monitoramento-e-diagnostico", "icon": "dashboard", "includeVars": False, "keepTime": False},
        {"title": "Resultados e evidências no GitHub", "type": "link", "url": "https://github.com/luisgabrielMR/TCC-2/tree/main/results/official/2026-10-12_fixed_100_m17", "icon": "external link", "targetBlank": True},
    ]}


if __name__ == "__main__":
    DESTINATION.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(DESTINATION)
