param([switch]$NoOpen)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $Root
. (Join-Path $PSScriptRoot "benchmark-common.ps1")

Invoke-BenchmarkPython @("scripts/summarize_results.py")
Invoke-BenchmarkPython @("scripts/generate_results_dashboard.py")

$Dashboard = Resolve-Path "results/summaries/benchmark_dashboard.html"
if (-not $NoOpen) {
    Start-Process -FilePath $Dashboard
    Write-Host "Painel aberto no navegador: $Dashboard"
} else {
    Write-Host "Painel gerado: $Dashboard"
}
