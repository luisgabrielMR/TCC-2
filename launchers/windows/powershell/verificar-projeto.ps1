$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "benchmark-common.ps1")
Set-Location $script:BenchmarkRoot

$environment = Get-BenchmarkEnvironment
$apiBaseUrl = Get-BenchmarkValue $environment "API_BASE_URL" "http://127.0.0.1:8000"
$locustHost = Get-BenchmarkValue $environment "LOCUST_HOST" "http://host.docker.internal:8000"
$languages = @("python", "node", "java", "go", "dotnet")
$services = $languages | ForEach-Object { "$_-api" }
$activeService = $null
$measurement = $null
$mainRunStarted = $false
$verificationDirectory = Join-Path $script:BenchmarkRoot "results/raw/verification"
$contractBaseline = "/mnt/results/raw/verification/contract-baseline.json"

try {
    Write-Host "[1/7] Validando Docker Compose..."
    Stop-BenchmarkServices -Services $services
    Invoke-BenchmarkCompose -Arguments @("config", "--quiet")

    Write-Host "[2/7] Construindo as cinco APIs..."
    $buildArguments = @()
    foreach ($language in $languages) { $buildArguments += @("--profile", $language) }
    $buildArguments += "build"
    $buildArguments += $services
    Invoke-BenchmarkCompose -Arguments $buildArguments

    Write-Host "[3/7] Resetando e validando o banco..."
    Reset-BenchmarkDatabase $environment
    $user = Get-BenchmarkValue $environment "POSTGRES_USER" "benchmark_user"
    $database = Get-BenchmarkValue $environment "POSTGRES_DB" "benchmark_db"
    Invoke-BenchmarkCompose -Arguments @(
        "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
        "-U", $user, "-d", $database, "-f", "/benchmark/database/scripts/validate_database.sql"
    )

    Write-Host "[4/7] Testando os oito endpoints em cada linguagem..."
    New-Item -ItemType Directory -Force $verificationDirectory | Out-Null
    Remove-Item (Join-Path $verificationDirectory "contract-baseline.json") -Force -ErrorAction SilentlyContinue
    foreach ($language in $languages) {
        $activeService = "$language-api"
        Reset-BenchmarkDatabase $environment
        Invoke-BenchmarkCompose -Arguments @("--profile", $language, "up", "-d", $activeService)
        Wait-BenchmarkApi $apiBaseUrl
        $contractArguments = @(
            "--profile", "load", "run", "--rm", "--no-deps", "--entrypoint", "python",
            "locust", "/mnt/scripts/contract_test_api.py", "--base-url", $locustHost
        )
        if ($language -eq "python") { $contractArguments += @("--snapshot", $contractBaseline) }
        else { $contractArguments += @("--compare", $contractBaseline) }
        Invoke-BenchmarkCompose -Arguments $contractArguments
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "testar-payloads.ps1") -BaseUrl $apiBaseUrl
        if ($LASTEXITCODE -ne 0) { throw "Endpoints da API $language falharam." }
        Invoke-BenchmarkCompose -Arguments @("stop", $activeService)
        $activeService = $null
    }

    Write-Host "[5/7] Validando monitoramento..."
    Invoke-BenchmarkCompose -Arguments @("--profile", "monitoring", "up", "-d", "--force-recreate", "postgres-exporter", "prometheus", "grafana", "cadvisor")
    $prometheusPort = Get-BenchmarkValue $environment "PROMETHEUS_PORT" "9090"
    $prometheusUrl = "http://127.0.0.1:$prometheusPort"
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$prometheusUrl/-/ready" -TimeoutSec 2 | Out-Null
            break
        }
        catch {
            if ($attempt -eq 30) { throw "Prometheus nao ficou pronto." }
            Start-Sleep -Seconds 2
        }
    }
    $targetsReady = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $targetsResponse = Invoke-RestMethod -Uri "$prometheusUrl/api/v1/targets" -TimeoutSec 10
            $targets = @($targetsResponse.data.activeTargets)
            $unhealthy = @($targets | Where-Object { $_.health -ne "up" })
            if ($targets.Count -eq 3 -and $unhealthy.Count -eq 0) {
                $targetsReady = $true
                break
            }
        }
        catch {
            # A pilha ainda pode estar inicializando.
        }
        Start-Sleep -Seconds 2
    }
    if (-not $targetsReady) {
        throw "Os tres targets Prometheus nao ficaram saudaveis dentro do tempo esperado."
    }
    $grafanaPort = Get-BenchmarkValue $environment "GRAFANA_PORT" "3000"
    $grafanaReady = $false
    for ($attempt = 1; $attempt -le 30; $attempt++) {
        try {
            $grafanaHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$grafanaPort/api/health" -TimeoutSec 5
            if ($grafanaHealth.database -eq "ok") {
                $grafanaReady = $true
                break
            }
        }
        catch {
            # Grafana pode levar alguns segundos para concluir o provisionamento.
        }
        Start-Sleep -Seconds 2
    }
    if (-not $grafanaReady) {
        throw "Grafana nao ficou saudavel dentro do tempo esperado."
    }

    Write-Host "[6/7] Executando warmup misto curto pelo Locust..."
    Reset-BenchmarkDatabase $environment
    $activeService = "python-api"
    Invoke-BenchmarkCompose -Arguments @("--profile", "python", "up", "-d", $activeService)
    Wait-BenchmarkApi $apiBaseUrl
    New-Item -ItemType Directory -Force $verificationDirectory | Out-Null
    Get-ChildItem $verificationDirectory -Filter "locust*.csv" -ErrorAction SilentlyContinue | Remove-Item -Force
    $uniquenessCheck = "from locustfile import customers_create; assert len(customers_create._values) >= 75000; rows=[customers_create.next() for _ in range(5000)]; assert len({r['email'] for r in rows}) == 5000; assert len({r['documentNumber'] for r in rows}) == 5000"
    Invoke-BenchmarkCompose -Arguments @(
        "--profile", "load", "run", "--rm", "--no-deps", "--entrypoint", "python",
        "-e", "PAYLOAD_DIR=/mnt/payloads", "locust", "-c", $uniquenessCheck
    )
    $measurement = Start-BenchmarkMeasurements $verificationDirectory 1
    $mainRunStarted = $true
    Invoke-BenchmarkLocust "warmup" 20 10 "15s" $locustHost "/mnt/results/raw/verification/locust"
    Stop-BenchmarkMeasurements $measurement
    $metricsEndEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    Export-BenchmarkPrometheus $verificationDirectory $environment $measurement.StartEpoch $metricsEndEpoch
    $stats = Import-Csv (Join-Path $verificationDirectory "locust_stats.csv")
    $aggregate = $stats | Where-Object { $_.Name -eq "Aggregated" }
    if (-not $aggregate -or [int]$aggregate."Failure Count" -ne 0) {
        throw "A carga curta do Locust registrou falhas."
    }
    foreach ($endpoint in @("POST /customers", "PUT /customers/{id}", "POST /orders")) {
        $endpointRow = $stats | Where-Object { $_.Name -eq $endpoint }
        if (-not $endpointRow -or [int]$endpointRow."Request Count" -lt 1) {
            throw "O warmup nao exercitou a rota de escrita $endpoint."
        }
    }
    $resource = Import-Csv (Join-Path $verificationDirectory "docker_stats_summary.csv") |
        Where-Object { $_.container_name -eq "tcc_benchmark_python_api" }
    if (-not $resource -or [int]$resource.samples -lt 2) {
        throw "A coleta continua nao registrou amostras suficientes da API Python."
    }
    $prometheus = Get-Content (Join-Path $verificationDirectory "prometheus_series.json") -Raw | ConvertFrom-Json
    if (@($prometheus.queries.postgres_up.response.data.result).Count -lt 1 -or
        @($prometheus.queries.postgres_connections.response.data.result).Count -lt 1) {
        throw "As series do PostgreSQL nao foram exportadas pelo Prometheus."
    }
    Reset-BenchmarkDatabase $environment
    $mainRunStarted = $false

    Write-Host "[7/7] Validando consolidadores e testes automatizados..."
    Invoke-BenchmarkPython @("-m", "unittest", "discover", "-s", "tests", "-v")
    Invoke-BenchmarkPython @("scripts/summarize_results.py")
    Invoke-BenchmarkPython @("scripts/generate_results_dashboard.py")

    Write-Host "Verificacao completa concluida: banco, 5 APIs, warmup misto, monitoramento, relatorios e testes aprovados."
}
finally {
    if ($measurement -and -not $measurement.Stopped) {
        try { Stop-BenchmarkMeasurements $measurement } catch { Write-Warning $_.Exception.Message }
    }
    if ($activeService) {
        Stop-BenchmarkServices -Services @($activeService)
    }
    Stop-BenchmarkServices -Profiles @("monitoring") -Services @("postgres-exporter", "prometheus", "grafana", "cadvisor")
    try {
        Reset-BenchmarkDatabase $environment
        $mainRunStarted = $false
    }
    catch {
        Write-Warning "Nao foi possivel restaurar o banco durante a limpeza: $($_.Exception.Message)"
    }
}
