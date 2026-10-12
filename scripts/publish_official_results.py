"""Freeze an official cohort with reproducible figures and byte-preserved evidence.

Generation requires matplotlib 3.10.8; --verify uses only the standard library.
This script neither runs a benchmark nor changes raw artifacts or classification.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import statistics
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LANGUAGES = ("dotnet", "go", "java", "node", "python")
NAMES = {"python": "Python", "node": "Node.js", "java": "Java", "go": "Go", "dotnet": ".NET"}
COLORS = {"python": "#ad8500", "node": "#38844a", "java": "#c45b14", "go": "#078b9c", "dotnet": "#8655ba"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def validate_cohort(metadata):
    """Prevent missing/duplicate rounds, pilot promotion and cross-protocol merging."""
    if len(metadata) != 25:
        raise ValueError("Expected exactly 25 official executions")
    if any(row["methodology_version"] != 17 or row["load_profile"] != "fixed_100" or row["scenario"] != "mixed_fixed_100" for row in metadata):
        raise ValueError("This publication layout requires methodology 17, mixed_fixed_100")
    for key in ("protocol_sha256", "commit_sha", "load_profile", "methodology_version", "scenario"):
        if len({row[key] for row in metadata}) != 1:
            raise ValueError(f"Cohort mixes {key}")
    if len({row["execution_order"]["campaign_fingerprint"] for row in metadata}) != 1:
        raise ValueError("Cohort mixes campaigns")
    if any(row["result_classification"] != "official" for row in metadata):
        raise ValueError("Non-official result in publication")
    if Counter(row["language"] for row in metadata) != Counter({language: 5 for language in LANGUAGES}):
        raise ValueError("Expected five executions per language")
    for language in LANGUAGES:
        if sorted(row["run_number"] for row in metadata if row["language"] == language) != [1, 2, 3, 4, 5]:
            raise ValueError(f"Missing or duplicated round for {language}")


def archive_evidence(output, files, root):
    records = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            name = path.relative_to(root).as_posix()
            data = path.read_bytes()
            # Fixed ZIP metadata makes the package reproducible; file bytes are original.
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            records.append({"path": name, "bytes": len(data), "sha256": sha256(data)})
    return records


def verify(output):
    manifest = read_json(output / "manifest.json")
    for line in (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        path = output / name
        if not path.resolve().is_relative_to(output.resolve()) or sha256(path.read_bytes()) != digest:
            raise ValueError(f"Published file differs: {name}")
    archive_path = output / "evidence.zip"
    if sha256(archive_path.read_bytes()) != manifest["archive_sha256"]:
        raise ValueError("Evidence archive hash differs")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != {item["path"] for item in manifest["files"]}:
            raise ValueError("Evidence file inventory differs")
        for item in manifest["files"]:
            data = archive.read(item["path"])
            if len(data) != item["bytes"] or sha256(data) != item["sha256"]:
                raise ValueError(f"Evidence hash differs: {item['path']}")
    return {"valid": True, "files": len(manifest["files"]), "archive_bytes": archive_path.stat().st_size}


def figures(output, runs, endpoints):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.spines.left": False, "axes.spines.bottom": False,
                         "axes.titleweight": "bold", "axes.titlecolor": "#19344b", "text.color": "#19344b",
                         "axes.labelcolor": "#475569", "xtick.color": "#475569", "ytick.color": "#475569",
                         "svg.hashsalt": "tcc-official-m17"})
    directory = output / "figures"
    directory.mkdir(exist_ok=True)
    labels = [NAMES[language] for language in LANGUAGES]
    palette = [COLORS[language] for language in LANGUAGES]
    formatter = FuncFormatter(lambda value, _: f"{value:g}".replace(".", ","))

    def save(fig, name):
        fig.savefig(directory / f"{name}.png", dpi=180, bbox_inches="tight", facecolor="white")
        fig.savefig(directory / f"{name}.svg", bbox_inches="tight", facecolor="white", metadata={"Date": None})
        plt.close(fig)

    def style(ax, title, unit):
        ax.set_title(title, loc="left", pad=20, fontsize=14)
        ax.set_ylabel(unit, labelpad=12)
        ax.grid(axis="y", color="#e2e8f0", linewidth=.8)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", length=0, pad=9)
        ax.yaxis.set_major_formatter(formatter)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.set_ylim(bottom=0)

    def bars(ax, field, title, unit, factor=1):
        values = [statistics.median(row[field] / factor for row in runs if row["language"] == language) for language in LANGUAGES]
        artists = ax.bar(labels, values, color=palette, width=.58, zorder=3)
        ax.bar_label(artists, labels=[f"{value:.2f}".replace(".", ",") for value in values], padding=8, fontsize=11, fontweight="bold")
        ax.set_ylim(0, max(values) * 1.22)
        style(ax, title, unit)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), layout="constrained")
    bars(axes[0], "avg_ms", "Tempo médio de resposta", "Latência (ms)")
    bars(axes[1], "p99_ms", "Latência P99", "Latência (ms)")
    fig.supxlabel("Medianas por API · P99: mediana dos percentis de cada execução · menor valor = resposta mais rápida", fontsize=10, color="#64748b")
    save(fig, "latency")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), layout="constrained")
    bars(axes[0], "api_cpu_avg", "Uso médio de CPU", "CPU (% de um núcleo)")
    bars(axes[1], "api_memory_avg", "Uso médio de memória", "Working set (MiB)", 1024 ** 2)
    fig.supxlabel("Medianas das médias do container · CPU: 100% por núcleo lógico · fonte: cAdvisor / Prometheus", fontsize=10, color="#64748b")
    save(fig, "resources")

    operations = ["GET /customers/{id}", "GET /customers", "GET /products", "GET /orders/{id}", "POST /customers", "PUT /customers/{id}", "POST /orders"]
    fig, axes = plt.subplots(2, 1, figsize=(13, 9), layout="constrained")
    for ax, selected, title in [(axes[0], operations[:4], "Operações de leitura"), (axes[1], operations[4:], "Operações de escrita")]:
        maximum = 0
        for li, language in enumerate(LANGUAGES):
            values = [statistics.median(row["avg_ms"] for row in endpoints if row["language"] == language and row["endpoint"] == endpoint) for endpoint in selected]
            artists = ax.bar([i + (li - 2) * .14 for i in range(len(selected))], values, width=.12, color=COLORS[language], label=NAMES[language], zorder=3)
            ax.bar_label(artists, labels=[f"{value:.1f}".replace(".", ",") for value in values], padding=5, fontsize=9)
            maximum = max(maximum, max(values))
        ax.set_xticks(range(len(selected)), selected)
        ax.set_ylim(0, maximum * 1.22)
        style(ax, title, "Latência média (ms)")
    fig.legend(handles=[Line2D([0], [0], color=COLORS[l], lw=7, label=NAMES[l]) for l in LANGUAGES], loc="outside lower center", ncol=5, frameon=False)
    save(fig, "endpoints")

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), layout="constrained")
    markers = ["o", "s", "^", "D", "X"]
    styles = ["-", "--", "-.", ":", "-"]
    handles = []
    for i, language in enumerate(LANGUAGES):
        rows = sorted((row for row in runs if row["language"] == language), key=lambda row: row["run"])
        for ax, field in [(axes[0], "avg_ms"), (axes[1], "p95_ms")]:
            line, = ax.plot([row["run"] for row in rows], [row[field] for row in rows], marker=markers[i], markersize=7,
                           linestyle=styles[i], linewidth=1.8, color=COLORS[language], label=NAMES[language], alpha=.9)
            if field == "avg_ms":
                handles.append(line)
    for ax, title in zip(axes, ["Tempo médio por execução", "P95 por execução"]):
        style(ax, title, "Latência (ms)")
        ax.set_xticks(range(1, 6))
        ax.set_xlabel("Execução", labelpad=10)
        ax.set_xlim(.8, 5.2)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.08)
    fig.legend(handles=handles, loc="outside lower center", ncol=5, frameon=False)
    save(fig, "rounds")


def generate(raw, output, campaign):
    from monitoring.results_exporter import collect_completed_runs
    from scripts.finalize_locust_csv import validate_stats, validate_worker_reports
    from scripts.snapshot_integrity import verified_stats
    from scripts.validate_measurement_bounds import validate_bounds
    from scripts.summarize_results import generate_outputs

    selected = [(path, read_json(path)) for path in sorted(raw.glob("*/*/run_*/metadata.json"))]
    selected = [(path, metadata) for path, metadata in selected if metadata.get("execution_order", {}).get("campaign_fingerprint") == campaign]
    metadata = [item for _, item in selected]
    validate_cohort(metadata)
    first = metadata[0]
    files, validations = [], []
    coverage, gaps = [], []
    for path, item in selected:
        directory = path.parent
        prefix = directory / "locust"
        verified_stats(prefix)
        stats = validate_stats(directory / "locust_stats.csv")
        worker = validate_worker_reports(prefix, directory / "locust_stats.csv")
        bounds = validate_bounds(read_json(directory / "locust_measurement_bounds.json"), item["protocol"]["load"]["measurement_duration_seconds"])
        canonical = json.dumps(item["protocol"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        checks = {
            "protocol_hash": sha256(canonical) == item["protocol_sha256"], "bounds": bounds["valid"],
            "preflight": read_json(directory / "preflight.json")["environment_eligible_for_official_run"],
            "monitoring_preflight": read_json(directory / "monitoring-preflight.json")["official_eligible"],
            "cadvisor": read_json(directory / "cadvisor-validation.json")["valid"],
            "prometheus": read_json(directory / "prometheus-validation.json")["valid"],
            "load_delivery": item["locust"]["rate_target_met"], "generator": item["locust"]["generator_headroom_met"],
            "database": item["shared_database"]["database_headroom_met"], "workers": worker["valid"],
        }
        if not all(checks.values()):
            raise ValueError(f"Invalid evidence: {directory}: {checks}")
        for component in read_json(directory / "cadvisor-validation.json")["components"].values():
            for sample in component["metrics"].values():
                coverage.append(sample["coverage_percent"])
                gaps.append(sample["maximum_gap_seconds"])
        validations.append({"language": item["language"], "run": item["run_number"], "checks": checks,
                            "requests": stats["requests"], "failures": stats["failures"], "workers": worker["workers"]})
        files.extend(p for p in directory.rglob("*") if p.is_file())
    output.mkdir(parents=True, exist_ok=True)
    generate_outputs(raw, output / "tables", output / "tables", campaign=campaign)
    # Replace the generated local-path summary with portable package documentation.
    (output / "tables/final_summary.md").write_text("# Tabelas oficiais\n\n25 execuções, sete operações e uma campanha. `summary_by_language.csv` tem uma linha por execução; `summary_by_endpoint.csv`, uma por operação e execução. O arquivo de escalabilidade não sustenta comparação entre cargas: só existe fixed_100.\n", encoding="utf-8")
    runs, endpoints = collect_completed_runs(raw.parent)
    runs = [row for row in runs if row["campaign"] == campaign]
    endpoints = [row for row in endpoints if row["campaign"] == campaign]
    if len(runs) != 25 or len(endpoints) != 175:
        raise ValueError("Incomplete validated publication")
    figures(output, runs, endpoints)
    # Include the complete saved verification summary without claiming a new integration run.
    verification = raw.parent / "summaries/project-verification.json"
    if verification.exists():
        files.append(verification)
    records = archive_evidence(output / "evidence.zip", files, raw.parent)
    manifest = {"schema_version": 1, "campaign": campaign, "classification": "official",
                "methodology_version": first["methodology_version"], "load_profile": first["load_profile"],
                "measured_commit": first["commit_sha"], "protocol_sha256": first["protocol_sha256"],
                "collection_started_at": min(item["started_at"] for item in metadata),
                "collection_finished_at": max(item["finished_at"] for item in metadata),
                "executions": 25, "requests": sum(row["requests"] for row in runs), "failures": sum(row["failures"] for row in runs),
                "minimum_cadvisor_coverage_percent": min(coverage), "maximum_cadvisor_gap_seconds": max(gaps),
                "archive_sha256": sha256((output / "evidence.zip").read_bytes()), "files": records,
                "validation": validations, "interpretation": "Official according to recorded protocol gates; no statistical significance or universal ranking is asserted."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "protocol.json").write_text(json.dumps(first["protocol"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = []
    for language in LANGUAGES:
        rows = [row for row in runs if row["language"] == language]
        entry = {"language": NAMES[language], "runs": len(rows), "requests": sum(row["requests"] for row in rows), "failures": sum(row["failures"] for row in rows)}
        entry.update({field: statistics.median(row[field] for row in rows) for field in ("rps", "avg_ms", "p95_ms", "p99_ms", "api_cpu_avg", "api_memory_avg")})
        summary.append(entry)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    header = ["Linguagem", "req/s", "Média (ms)", "P95 (ms)", "P99 (ms)", "CPU (%)", "Memória (MiB)"]
    cells = [[row["language"], f"{row['rps']:.3f}", f"{row['avg_ms']:.2f}", f"{row['p95_ms']:.0f}", f"{row['p99_ms']:.0f}", f"{row['api_cpu_avg']:.2f}", f"{row['api_memory_avg']/1024**2:.2f}"] for row in summary]
    table = "| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n" + "\n".join("| " + " | ".join(row) + " |" for row in cells)
    requests_label = f"{manifest['requests']:,}".replace(",", ".")
    readme = f"""# Resultados da campanha oficial · fixed_100 · metodologia 17

Coleta de **10 a 12 de outubro de 2026**: cinco rodadas de cinco implementações, **25 execuções**, **{requests_label} requisições** e **zero falhas registradas pelo Locust**. Os arquivos foram publicados após a conclusão e preservam a classificação original `official`.

## Leitura dos resultados

{table}

As métricas acima são **medianas entre as cinco rodadas**: mediana das médias de latência, dos P95/P99, da vazão e das médias de CPU/memória. Mediana de P95 não é o P95 global. CPU usa 100% por núcleo lógico; cada API tinha cota de dois núcleos. Memória é o working set do container.

![Latência e dispersão das cinco rodadas](figures/latency.png)

![CPU e memória das APIs](figures/resources.png)

![Comparação das sete operações](figures/endpoints.png)

![Variação entre as rodadas](figures/rounds.png)

As barras mostram medianas e as linhas mostram os valores de cada execução. Os eixos começam em zero; não há intervalos de confiança. Os gráficos descrevem esta campanha; não demonstram significância estatística ou superioridade geral de uma linguagem. As figuras por operação usam escalas separadas para leituras e escritas, ambas iniciadas em zero.

## Condições e validade

- 100 usuários, subida de 20 usuários/s, pacing de 1 s e quatro processos Locust.
- Carga fechada; 100 req/s é teto nominal. Todas as execuções superaram o piso de 95 req/s.
- Cinco minutos úteis por execução, excluindo warmup e subida de usuários; ordem das linguagens alternada entre rodadas.
- Sete operações no cenário `mixed`; `GET /health` não integra a medição.
- Fonte primária de CPU/memória: cAdvisor via Prometheus. Os critérios registrados exigem cobertura ≥95% e lacunas ≤1,5 s para API, PostgreSQL e Locust.
- Os snapshots foram novamente verificados por hash e reconciliados com os quatro workers, incluindo contagens, médias e histogramas P50/P95/P99. Limites temporais e gates registrados passaram em 25/25 execuções.
- Cobertura observada de CPU/memória: mínimo de {min(coverage):.1f}%; maior lacuna de {max(gaps):.3f} s nas séries preservadas.
- Um único nível de carga: estes dados não medem capacidade máxima nem escalabilidade entre níveis.
- CPU e memória são do container inteiro, sem atribuição por endpoint. PostgreSQL é compartilhado; CPU baixa não elimina sua influência na latência.
- Percentis seguem o arredondamento dos histogramas Locust. Warmup, verificações e dados de `docker stats` estão preservados como evidência e não foram somados aos resultados oficiais.

## Proveniência e arquivos

- **Commit medido:** [`{first['commit_sha']}`](https://github.com/luisgabrielMR/TCC-2/commit/{first['commit_sha']}). A atualização posterior dos dashboards e esta publicação não alteram o protocolo da coleta.
- **Campanha:** `{campaign}`.
- **SHA-256 do protocolo:** `{first['protocol_sha256']}`. O hash é calculado sobre JSON canônico (chaves ordenadas, sem espaços), não sobre a formatação de `protocol.json`.
- [Protocolo](protocol.json), [manifesto e inventário de hashes](manifest.json), [resumo numérico](summary.json).
- [CSV por execução](tables/summary_by_language.csv) e [CSV por operação e execução](tables/summary_by_endpoint.csv).
- [Pacote completo de evidências originais](evidence.zip): {len(records)} arquivos, preservados byte a byte, incluindo warmup e o resumo da verificação de projeto anterior à coleta. Não contém `.env`.
- [Relatório HTML para baixar e abrir localmente](index.html): independente de Grafana/Docker. As figuras em SVG também estão na pasta `figures`.
- [SHA256SUMS](SHA256SUMS): integridade de todos os arquivos publicados, exceto o próprio arquivo de hashes.

## Conferência após baixar o repositório

Na raiz do projeto, execute (não exige Matplotlib):

```bash
python scripts/publish_official_results.py --verify results/official/{output.name}
```

Para conferir os CSVs novamente sem executar carga nem alterar o banco:

```bash
python -m zipfile -e results/official/{output.name}/evidence.zip results/summaries/official-review
python scripts/summarize_results.py --raw results/summaries/official-review/raw --processed results/summaries/official-review/processed --summaries results/summaries/official-review/report --campaign {campaign}
```

O material publicado é um retrato da campanha medida no commit indicado. O diretório `results/raw` local continua sendo área de trabalho; novas campanhas devem receber outra pasta de publicação e outro fingerprint.

Para gerar novamente as figuras e o pacote a partir dos resultados locais, use Python com `matplotlib==3.10.8` e execute `python scripts/publish_official_results.py --campaign {campaign} --output results/official/{output.name}`. A geração não executa benchmark nem promove resultados não oficiais.
"""
    (output / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    html_table = "<table><thead><tr>" + "".join(f"<th>{html.escape(value)}</th>" for value in header) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>" for row in cells) + "</tbody></table>"
    images = "".join(f'<section id="{name}"><h2>{label}</h2><svg' + (output / f"figures/{name}.svg").read_text(encoding="utf-8").split("<svg", 1)[1] + "</section>" for name, label in [("latency", "01 · Latência"), ("resources", "02 · Recursos"), ("endpoints", "03 · Operações"), ("rounds", "04 · Latência por execução")])
    page = f'''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Campanha oficial — fixed_100 / metodologia 17</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#f5f7fa;color:#172b40;line-height:1.55}}main{{max-width:1240px;margin:auto;padding:42px 24px}}h1{{font-size:38px;line-height:1.15;margin:12px 0}}h2{{font-size:23px}}.eyebrow{{letter-spacing:.12em;font-size:12px;font-weight:700;color:#34627b}}.lead{{font-size:18px;max-width:850px}}nav{{display:flex;gap:18px;flex-wrap:wrap;margin:24px 0}}a{{color:#125678}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:28px 0}}.stats div,section{{background:white;border:1px solid #dce3eb;border-radius:12px;padding:22px}}.stats b{{display:block;font-size:32px}}section{{margin:24px 0}}svg{{width:100%;height:auto}}table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}td,th{{padding:12px;text-align:right;border-bottom:1px solid #e1e7ee}}th:first-child,td:first-child{{text-align:left}}.table{{overflow:auto}}small,footer{{color:#486073}}@media(max-width:700px){{.stats{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:30px}}main{{padding:24px 12px}}section{{padding:12px}}}}@media print{{nav{{display:none}}section{{break-inside:avoid}}}}</style>
<main><div class="eyebrow">TCC · POSTGRESQL BACKEND BENCHMARK · RESULTADOS OFICIAIS</div><h1>Comparação das APIs</h1><p class="lead">Campanha fixed_100, metodologia 17. Coleta de 10 a 12 de outubro de 2026. Latência e consumo de recursos sob a mesma carga.</p><nav><a href="#summary">Resumo</a><a href="#latency">Latência</a><a href="#resources">Recursos</a><a href="#endpoints">Operações</a><a href="#rounds">Por execução</a><a href="#evidence">Evidências</a></nav><section id="summary"><h2>Resumo comparativo</h2><p>Medianas entre as cinco rodadas de cada linguagem. P95/P99 são medianas dos percentis de cada execução; não percentis globais.</p><div class="table">{html_table}</div></section>{images}<section id="evidence"><h2>Como interpretar e conferir</h2><p>Barras: medianas por API. Linhas: valores de cada execução. Todos os eixos começam em zero. CPU: 100% por núcleo lógico; cota de dois núcleos por API. Memória: working set. As escalas de leituras e escritas são separadas e começam em zero.</p><p>Esta campanha mede uma carga fechada com pacing de 1 s e 100 usuários. Não mede capacidade máxima, não demonstra escalabilidade e não permite afirmar superioridade universal ou significância estatística. CPU e memória abrangem o container inteiro.</p><p>Campanha: <code>{campaign}</code><br>Commit medido: <code>{first['commit_sha']}</code></p><p>Os CSVs, manifesto SHA-256 e pacote original de evidências estão no <a href="https://github.com/luisgabrielMR/TCC-2/tree/main/results/official/{output.name}">GitHub</a>. O arquivo README da publicação descreve os critérios e comandos de verificação.</p></section><footer>Relatório derivado de artefatos oficiais preservados. Nenhuma nova carga foi executada para gerar esta publicação.</footer></main></html>'''
    (output / "index.html").write_text(page, encoding="utf-8", newline="\n")
    # Derived text uses LF on every platform; original evidence bytes stay inside the ZIP.
    for path in output.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".json", ".csv", ".svg", ".html"}:
            data = path.read_bytes().replace(b"\r\n", b"\n")
            if path.suffix in {".svg", ".html"}:
                data = b"\n".join(line.rstrip(b" \t") for line in data.split(b"\n"))
            path.write_bytes(data)
    checksums = [f"{sha256(path.read_bytes())}  {path.relative_to(output).as_posix()}" for path in sorted(output.rglob("*")) if path.is_file() and path.name != "SHA256SUMS"]
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8", newline="\n")
    return verify(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--raw", type=Path, default=ROOT / "results/raw")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--campaign")
    args = parser.parse_args()
    if args.verify:
        result = verify(args.verify)
    else:
        if not args.output or not args.campaign:
            parser.error("generation requires --output and --campaign")
        result = generate(args.raw, args.output, args.campaign)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
