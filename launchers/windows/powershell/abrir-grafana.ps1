$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "benchmark-common.ps1")
Set-Location $script:BenchmarkRoot

& docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop nao esta pronto. Abra o Docker Desktop e tente novamente."
}

$environment = Get-BenchmarkEnvironment
$grafanaPort = Get-BenchmarkValue $environment "GRAFANA_PORT" "3000"
$grafanaBaseUrl = "http://127.0.0.1:$grafanaPort"
$dashboardUrl = "$grafanaBaseUrl/d/tcc-benchmark-overview/tcc-benchmark-resultados-oficiais?orgId=1&refresh=5s"

Invoke-BenchmarkCompose -Arguments @(
    "--profile", "monitoring", "up", "-d",
    "postgres", "postgres-exporter", "benchmark-results-exporter", "prometheus", "grafana", "cadvisor"
)

$ready = $false
for ($attempt = 1; $attempt -le 60; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "$grafanaBaseUrl/api/health" -TimeoutSec 3
        if ($health.database -eq "ok") {
            $ready = $true
            break
        }
    }
    catch {
        # O Grafana ainda pode estar inicializando.
    }
    Start-Sleep -Seconds 1
}
if (-not $ready) {
    throw "Grafana nao ficou pronto em $grafanaBaseUrl."
}

Write-Host "Grafana pronto: $dashboardUrl"
Write-Host "O painel oficial possui um link no topo para o monitoramento e diagnostico."
Write-Host "A visualizacao abre sem login. Para editar, use admin / admin."
Start-Process $dashboardUrl
