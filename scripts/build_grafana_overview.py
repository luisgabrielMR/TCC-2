"""Build consolidated and complementary Grafana result dashboards."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "monitoring/grafana/dashboards/benchmark-overview.json"
ANALYSIS_DESTINATION = DESTINATION.with_name("benchmark-analysis.json")
SOURCE = {"type": "prometheus", "uid": "Prometheus"}
LANGUAGES = {"python": ("Python", "#E0B400"), "node": ("Node.js", "#73BF69"), "java": ("Java", "#FF9830"), "go": ("Go", "#56D9EB"), "dotnet": (".NET", "#B877D9")}
FILTER = 'classification="official",methodology="$methodology",campaign="$campaign",scenario="$scenario",load_profile="$load_profile",language=~"$language"'
LANGUAGES = dict(sorted(LANGUAGES.items()))
CENTER = "Consolidado"  # central series; the Consolidação filter renames it to Mediana or Média
CENTER_NAME = "${consolidacao:text}"
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
    key_label = {"run": "Execução", "language": "Linguagem", "endpoint": "Operação", "quantile": "Percentil"}[key]
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
    if key == "quantile":
        key_properties.append({"id": "mappings", "value": [{"type": "value", "options": {
            value: {"text": value.upper(), "index": i} for i, value in enumerate(("p50", "p95", "p99"))}}]})
    panel.update(targets=targets, transformations=[
        {"id": "filterFieldsByName", "options": {"include": {"pattern": f"^({key}|Value.*)$"}}},
        *([{"id": "joinByField", "options": {"byField": key, "mode": "outer"}}] if len(expressions) > 1 else []),
        {"id": "organize", "options": {"renameByName": renamed, "indexByName": {}, "excludeByName": {}}},
        {"id": "sortBy", "options": {"sort": [{"field": key_label, "desc": False}], "fields": {}}},
    ], fieldConfig={"defaults": {"unit": unit, "decimals": 2 if key == "language" else 0, "min": 0,
                                 "color": {"mode": "palette-classic"}, "custom": custom},
                    "overrides": colors() + [{"matcher": {"id": "byName", "options": label}, "properties": [
                        {"id": "color", "value": {"mode": "fixed", "fixedColor": color}},
                        *([{"id": "displayName", "value": CENTER_NAME}] if label == CENTER else [])]} for label, color in
                        [("Mínimo", "#8F9CAB"), (CENTER, "#56D9EB"), ("Máximo", "#FF9830")]] + [{"matcher": {"id": "byName", "options": key_label}, "properties": key_properties}]},
                 options={"xField": key_label, "orientation": "vertical", "stacking": "none", "groupWidth": .65,
                          "barWidth": .85, "barRadius": .03, "showValue": "always" if key == "language" and len(expressions) == 1 else "never",
                          "legend": {"showLegend": key != "language" or len(expressions) > 1, "placement": "bottom", "displayMode": "list"},
                          "tooltip": {"mode": "multi", "sort": "none"}, "xTickLabelRotation": 0,
                          "xTickLabelSpacing": 0, "fullHighlight": False})
    if key == "language" and len(expressions) == 1:
        panel["options"]["colorByField"] = key_label
    PANELS.append(panel)
    return panel


def by_language(name, extra=""):
    return [(label, metric(name, extra).replace('language=~"$language"', f'language="{code}"')
             + f' and on(language) {metric("benchmark_result_runs")}') for code, (label, _) in LANGUAGES.items()]


def consolidate(median, mean):
    """Keep only the series selected by the Consolidação filter (median or mean)."""
    return (f'(label_replace({median}, "consolidacao", "median", "", "") or '
            f'label_replace({mean}, "consolidacao", "mean", "", "")) '
            'and on(consolidacao) label_replace(vector(1), "consolidacao", "$consolidacao", "", "")')


def consolidated_metric(result_name, run_name, extra="", divisor=""):
    """Median from the published results or mean of the per-run series, by language."""
    suffix = f" / {divisor}" if divisor else ""
    return consolidate(metric(result_name, extra) + suffix, f"avg by(language)({metric(run_name, extra)})" + suffix)


def consolidated_by_language(result_name, run_name, extra, by):
    """One expression per language: median of the published results or mean of the per-run series, by `by`."""
    expressions = []
    for code, (label, _) in LANGUAGES.items():
        scope = lambda name: metric(name, extra).replace('language=~"$language"', f'language="{code}"')
        runs = metric("benchmark_result_runs")
        expressions.append((label, consolidate(f"{scope(result_name)} and on(language) {runs}",
                                               f"avg by({by})({scope(run_name)} and on(language) {runs})")))
    return expressions


def range_expressions(expression):
    return [("Mínimo", f"min by(language)({expression})"),
            (CENTER, consolidate(f"quantile by(language)(0.5, {expression})", f"avg by(language)({expression})")),
            ("Máximo", f"max by(language)({expression})")]


def delivery_table(y, *, show_ranges=False):
    expressions = []
    for prefix, expression in [("Vazão", metric("benchmark_run_throughput_rps")),
                               ("Erro", "100 * " + metric("benchmark_run_failures") + " / " + metric("benchmark_run_requests"))]:
        if show_ranges:
            expressions.extend((f"{prefix} · {label}", query) for label, query in range_expressions(expression))
        else:
            expressions.append((prefix, range_expressions(expression)[1][1]))
    panel = chart(61, "Vazão e taxa de erro" if show_ranges else "Vazão e taxa de erro · ${consolidacao:text} das execuções",
                  expressions, "language", 0, y, 24, 9,
                  ("Mínimo, valor consolidado (mediana ou média, conforme o filtro Consolidação) e máximo entre execuções. " if show_ranges
                   else "Valores consolidados entre execuções: mediana ou média, conforme o filtro Consolidação. ")
                  + "Vazão em req/s e erro em %. A vazão próxima de 100 req/s decorre da carga configurada e não mede capacidade máxima.")
    panel["type"] = "table"
    panel["options"] = {"showHeader": True, "cellHeight": "md", "enablePagination": False, "footer": {"show": False}}
    panel["fieldConfig"]["defaults"] = {"unit": "reqps", "decimals": 3,
        "custom": {"align": "right", "cellOptions": {"type": "auto"}, "minWidth": 80}}
    panel["fieldConfig"]["overrides"] += [
        *[{"matcher": {"id": "byName", "options": name}, "properties": [
            {"id": "unit", "value": "percent"}, {"id": "decimals", "value": 2}]} for name in ("Erro", "Erro · Mínimo", f"Erro · {CENTER}", "Erro · Máximo")],
        *([{"matcher": {"id": "byName", "options": f"{prefix} · {CENTER}"}, "properties": [
            {"id": "displayName", "value": f"{prefix} · {CENTER_NAME}"}]} for prefix in ("Vazão", "Erro")] if show_ranges else []),
        {"matcher": {"id": "byName", "options": "Linguagem"}, "properties": [{"id": "custom.align", "value": "left"}]},
    ]


def variable(name, label, query, current, multi=False, sort=1):
    return {"name": name, "label": label, "type": "query", "datasource": SOURCE,
            "query": {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
            "definition": query, "refresh": 1, "sort": sort, "hide": 0, "includeAll": multi,
            "multi": multi, "allValue": ".*", "options": [], "regex": "", "skipUrlSync": False,
            "current": {"text": "Todas" if multi else current, "value": "$__all" if multi else current, "selected": True}}


def build(*, secondary=False):
    PANELS.clear()
    if secondary:
        row(20, "Variabilidade da latência", 0)
        chart(51, "$quantile por execução", by_language("benchmark_run_latency_ms", 'quantile="$quantile"'),
              "run", 0, 1, 12, 11, "Cada grupo compara a métrica de latência selecionada na execução indicada. O filtro Latência alterna média, P50, P95 e P99. Unidade: milissegundos.")
        chart(23, "$quantile · ${consolidacao:text}, mínimo e máximo", range_expressions(metric("benchmark_run_latency_ms", 'quantile="$quantile"')),
              "language", 12, 1, 12, 11, "Mínimo, valor consolidado (mediana ou média, conforme o filtro Consolidação) e máximo da métrica selecionada entre execuções, conforme o TCC, p. 14. Não são extremos de requisições individuais nem intervalos de confiança.")
        row(30, "Variabilidade dos recursos", 12)
        chart(31, "CPU · ${consolidacao:text}, mínimo e máximo", range_expressions(metric("benchmark_run_cpu_percent", 'component="api",stat="average"')),
              "language", 0, 13, 12, 10, "Extremos e valor consolidado (mediana ou média, conforme o filtro Consolidação) das médias de CPU de cada execução. Não são picos instantâneos. 100% corresponde a um núcleo lógico; cota: dois núcleos.", "percent", 30)
        chart(32, "Memória · ${consolidacao:text}, mínimo e máximo", range_expressions(metric("benchmark_run_memory_bytes", 'stat="average"') + " / 1048576"),
              "language", 12, 13, 12, 10, "Extremos e valor consolidado (mediana ou média, conforme o filtro Consolidação) das médias do working set de cada execução, em MiB. Não são picos instantâneos. Fonte: cAdvisor / Prometheus.", "suffix:MiB", 250)
        row(60, "Variabilidade da vazão e dos erros", 23)
        delivery_table(24, show_ranges=True)
    else:
        row(20, "Latência das APIs", 0)
        chart(21, "Tempo médio de resposta · ${consolidacao:text} das execuções",
              [("Latência", consolidated_metric("benchmark_result_latency_ms", "benchmark_run_latency_ms", 'quantile="avg"'))],
              "language", 0, 1, 12, 10, "Valor consolidado entre as execuções das médias de latência: mediana ou média, conforme o filtro Consolidação. Menor = resposta mais rápida. A variabilidade está no painel Análise complementar.", soft_max=40)
        chart(22, "Percentis de resposta · P50, P95 e P99 · ${consolidacao:text} das execuções",
              consolidated_by_language("benchmark_result_latency_ms", "benchmark_run_latency_ms", 'quantile=~"p50|p95|p99"', "quantile"),
              "quantile", 12, 1, 12, 10, "P50, P95 e P99 são os tempos abaixo dos quais ficam aproximadamente 50%, 95% e 99% das requisições. As barras consolidam os percentis de cada execução (mediana ou média, conforme o filtro Consolidação); não são percentis globais.")
        row(30, "Recursos das APIs", 11)
        chart(31, "Uso médio de CPU · ${consolidacao:text} das execuções",
              [("CPU", consolidated_metric("benchmark_result_cpu_percent", "benchmark_run_cpu_percent", 'component="api",stat="average"'))],
              "language", 0, 12, 12, 10, "Valor consolidado entre as execuções das médias de CPU: mediana ou média, conforme o filtro Consolidação. 100% corresponde a um núcleo lógico; cota: dois núcleos. A escala acompanha o consumo observado.", "percent", 30)
        chart(32, "Uso médio de memória · ${consolidacao:text} das execuções",
              [("Memória", consolidated_metric("benchmark_result_memory_bytes", "benchmark_run_memory_bytes", 'stat="average"', "1048576"))],
              "language", 12, 12, 12, 10, "Valor consolidado entre as execuções das médias do working set do container, em MiB: mediana ou média, conforme o filtro Consolidação. Fonte: cAdvisor / Prometheus.", "suffix:MiB", 250)
        row(40, "Tempo de resposta por operação", 22)
        for identifier, title, pattern, y in [(41, "Leituras · $quantile · ${consolidacao:text}", "GET .*", 23), (42, "Escritas · $quantile · ${consolidacao:text}", "(POST|PUT) .*", 35)]:
            chart(identifier, title, consolidated_by_language("benchmark_endpoint_latency_ms", "benchmark_endpoint_run_latency_ms", f'quantile="$quantile",endpoint=~"{pattern}"', "endpoint"),
                  "endpoint", 0, y, 24, 12, "Mediana ou média entre execuções, conforme o filtro Consolidação, da métrica selecionada por operação. Cada grupo compara as APIs na mesma operação. Leituras e escritas usam escalas próprias, iniciadas em zero. GET /health não integra a carga.")
        row(60, "Vazão e erros", 47)
        delivery_table(48)
    variables = [
        variable("methodology", "Metodologia", 'label_values(benchmark_result_runs{classification="official"}, methodology)', "17", sort=4),
        variable("campaign", "Campanha", 'label_values(benchmark_result_runs{classification="official",methodology="$methodology"}, campaign)', "m17_d2716c1f9187_92483cd5afca"),
        variable("scenario", "Cenário", 'label_values(benchmark_result_runs{classification="official",campaign="$campaign"}, scenario)', "mixed_fixed_100"),
        variable("load_profile", "Perfil", 'label_values(benchmark_result_runs{classification="official",campaign="$campaign",scenario="$scenario"}, load_profile)', "fixed_100"),
        variable("language", "Linguagem", 'label_values(benchmark_result_runs{classification="official",campaign="$campaign"}, language)', "", multi=True),
        {"name": "consolidacao", "label": "Consolidação", "type": "custom", "query": "Mediana : median,Média : mean",
         "description": "Como os valores das cinco execuções são combinados: mediana (padrão do TCC) ou média.",
         "current": {"text": "Mediana", "value": "median"}, "options": [{"text": text, "value": value, "selected": value == "median"} for text, value in [("Mediana", "median"), ("Média", "mean")]],
         "multi": False, "includeAll": False, "hide": 0, "skipUrlSync": False},
        {"name": "quantile", "label": "Latência" if secondary else "Latência por operação", "type": "custom", "query": "Média : avg,P50 : p50,P95 : p95,P99 : p99", "current": {"text": "P95", "value": "p95"}, "options": [{"text": text, "value": value, "selected": value == "p95"} for text, value in [("Média", "avg"), ("P50", "p50"), ("P95", "p95"), ("P99", "p99")]], "multi": False, "includeAll": False, "hide": 0, "skipUrlSync": False},
    ]
    for item in variables:
        if item["name"] in {"methodology", "campaign", "scenario", "load_profile"}:
            item["hide"] = 2
    return {"annotations": {"list": []}, "id": None, "uid": "tcc-benchmark-analysis" if secondary else "tcc-benchmark-overview", "title": "TCC Benchmark - Análise Complementar" if secondary else "TCC Benchmark - Resultados Oficiais", "description": "Variação entre execuções e extremos das métricas oficiais; consolidação por mediana ou média." if secondary else "Comparação consolidada das APIs, por mediana ou média entre execuções: latência média, P50/P95/P99, CPU, memória, operações, vazão e erros.", "editable": True, "schemaVersion": 40, "version": 2 if secondary else 15, "timezone": "browser", "refresh": "30s", "time": {"from": "now-15m", "to": "now"}, "tags": ["tcc", "benchmark", "resultados-oficiais"], "templating": {"list": variables}, "panels": list(PANELS), "links": [
        {"title": "Resultados consolidados" if secondary else "Análise complementar", "type": "link",
         "url": "/d/tcc-benchmark-overview" if secondary else "/d/tcc-benchmark-analysis",
         "icon": "dashboard", "includeVars": True, "keepTime": False},
        {"title": "Monitoramento ao vivo", "type": "link", "url": "/d/tcc-benchmark-extras/tcc-benchmark-monitoramento-e-diagnostico", "icon": "dashboard", "includeVars": False, "keepTime": False},
        {"title": "Resultados e evidências no GitHub", "type": "link", "url": "https://github.com/luisgabrielMR/TCC-2/tree/main/results/official/2026-10-12_fixed_100_m17", "icon": "external link", "targetBlank": True},
    ]}


if __name__ == "__main__":
    for destination, secondary in [(DESTINATION, False), (ANALYSIS_DESTINATION, True)]:
        destination.write_text(json.dumps(build(secondary=secondary), indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(destination)
