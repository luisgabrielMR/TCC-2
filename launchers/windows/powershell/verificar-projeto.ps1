$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "benchmark-common.ps1")
Set-Location $script:BenchmarkRoot

$environment = Get-BenchmarkEnvironment
$methodologyVersion = [int](Get-BenchmarkValue $environment "METHODOLOGY_VERSION" "9")
$apiBaseUrl = Get-BenchmarkValue $environment "API_BASE_URL" "http://127.0.0.1:8000"
$languages = @("python", "node", "java", "go", "dotnet")
$services = $languages | ForEach-Object { "$_-api" }
$activeService = $null
$measurement = $null
$mainRunStarted = $false
$locustPreflightStarted = $false
$verificationId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
$verificationRoot = Join-Path $script:BenchmarkRoot "results/raw/verification"
$verificationDirectory = Join-Path $verificationRoot $verificationId
$contractBaseline = "/mnt/results/raw/verification/$verificationId/contract-baseline.json"
$databaseStateBaseline = Join-Path $verificationDirectory "database-state-python.json"

try {
    $resolvedVerificationRoot = [IO.Path]::GetFullPath($verificationRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $resolvedVerificationDirectory = [IO.Path]::GetFullPath($verificationDirectory)
    if (-not $resolvedVerificationDirectory.StartsWith(
        $resolvedVerificationRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Diretorio de verificacao inesperado: $verificationDirectory"
    }
    New-Item -ItemType Directory -Force $verificationDirectory | Out-Null

    Write-Host "[1/8] Validando Docker Compose..."
    Stop-BenchmarkServices -Services $services
    Invoke-BenchmarkCompose -Arguments @("config", "--quiet")

    Write-Host "[2/8] Construindo as cinco APIs..."
    $buildArguments = @()
    foreach ($language in $languages) { $buildArguments += @("--profile", $language) }
    $buildArguments += "build"
    $buildArguments += $services
    Invoke-BenchmarkCompose -Arguments $buildArguments
    Invoke-BenchmarkCompose -Arguments @(
        "--profile", "python", "run", "--rm", "--no-deps", "--entrypoint", "python",
        "-v", "./scripts:/mnt/scripts:ro", "-v", "./common:/mnt/common:ro",
        "python-api", "/mnt/scripts/validate_openapi.py", "/mnt/common/openapi/openapi.yaml"
    )

    Write-Host "[3/8] Resetando e validando o banco..."
    Reset-BenchmarkDatabase $environment
    $user = Get-BenchmarkValue $environment "POSTGRES_USER" "benchmark_user"
    $database = Get-BenchmarkValue $environment "POSTGRES_DB" "benchmark_db"
    Invoke-BenchmarkCompose -Arguments @(
        "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
        "-U", $user, "-d", $database, "-f", "/benchmark/database/scripts/validate_database.sql"
    )
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/preflight.py"),
        "--mode", "pilot", "--output", (Join-Path $verificationDirectory "preflight.json")
    )

    Write-Host "[4/8] Testando os oito endpoints em cada linguagem..."
    foreach ($language in $languages) {
        $activeService = "$language-api"
        $activeLocustHost = "http://${activeService}:8000"
        Reset-BenchmarkDatabase $environment
        Invoke-BenchmarkCompose -Arguments @(
            "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-q",
            "-U", $user, "-d", $database,
            "-c", "UPDATE payments SET paid_at = NULL WHERE order_id = 1;"
        )
        Invoke-BenchmarkCompose -Arguments @("--profile", $language, "up", "-d", $activeService)
        Wait-BenchmarkApi $apiBaseUrl
        $contractArguments = @(
            "--profile", "load", "run", "--rm", "--no-deps", "--entrypoint", "python",
            "locust", "/mnt/scripts/contract_test_api.py", "--base-url", $activeLocustHost, "--label", $language
        )
        if ($language -eq "python") { $contractArguments += @("--snapshot", $contractBaseline) }
        else { $contractArguments += @("--compare", $contractBaseline) }
        Invoke-BenchmarkCompose -Arguments $contractArguments
        $waitPolicyOutput = Invoke-BenchmarkCompose -Arguments @(
            "--profile", "python", "run", "--rm", "--no-deps", "--entrypoint", "python",
            "-v", "./scripts:/mnt/scripts:ro", "python-api", "/mnt/scripts/verify_api_wait_policy.py",
            "--base-url", $activeLocustHost
        )
        $waitPolicyJson = $waitPolicyOutput | Where-Object { $_.Trim().StartsWith("{") } | Select-Object -Last 1
        if (-not $waitPolicyJson) { throw "Diagnostico de timeout ausente para $language." }
        $waitPolicyJson | ConvertFrom-Json | Out-Null
        $waitPolicyJson | Set-Content -Encoding utf8 (Join-Path $verificationDirectory "wait-policy-$language.json")
        Write-Host $waitPolicyJson

        $databaseStatePath = Join-Path $verificationDirectory "database-state-$language.json"
        $stateOutput = Invoke-BenchmarkCompose -Arguments @(
            "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-Atq",
            "-U", $user, "-d", $database,
            "-f", "/benchmark/database/scripts/capture_contract_state.sql"
        )
        $stateJson = ($stateOutput | Where-Object { $_.Trim().StartsWith("{") } | Select-Object -Last 1)
        if (-not $stateJson) { throw "Snapshot do banco nao foi produzido para $language." }
        $stateJson | Set-Content -LiteralPath $databaseStatePath -Encoding utf8
        if ($language -ne "python") {
            Invoke-BenchmarkPython @(
                (Join-Path $script:BenchmarkRoot "scripts/compare_json.py"),
                $databaseStateBaseline,
                $databaseStatePath,
                "--label", "database state for $language"
            )
        }

        Invoke-BenchmarkCompose -Arguments @("stop", "postgres")
        Start-Sleep -Seconds 2
        Invoke-BenchmarkCompose -Arguments @(
            "--profile", "load", "run", "--rm", "--no-deps", "--entrypoint", "python",
            "locust", "/mnt/scripts/contract_test_api.py", "--base-url", $activeLocustHost,
            "--label", $language, "--database-error-only"
        )
        Reset-BenchmarkDatabase $environment
        Wait-BenchmarkApi $apiBaseUrl
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "testar-payloads.ps1") -BaseUrl $apiBaseUrl
        if ($LASTEXITCODE -ne 0) { throw "Endpoints da API $language falharam." }
        Invoke-BenchmarkCompose -Arguments @("stop", $activeService)
        $activeService = $null
    }

    Write-Host "[5/8] Validando estabilidade do pool da API Go..."
    Reset-BenchmarkDatabase $environment
    $activeService = "go-api"
    Invoke-BenchmarkCompose -Arguments @("--profile", "go", "up", "-d", $activeService)
    Wait-BenchmarkApi $apiBaseUrl
    Invoke-BenchmarkCompose -Arguments @(
        "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-q",
        "-U", $user, "-d", $database, "-c", "SELECT pg_stat_reset();"
    )
    $goPoolDirectory = Join-Path $verificationDirectory "go-pool"
    New-Item -ItemType Directory -Force $goPoolDirectory | Out-Null
    Invoke-BenchmarkLocust "smoke" 20 10 "15s" "http://go-api:8000" "/mnt/results/raw/verification/$verificationId/go-pool/locust" -Processes 1
    $goPoolStats = Import-Csv (Join-Path $goPoolDirectory "locust_stats.csv")
    $goPoolAggregate = $goPoolStats | Where-Object { $_.Name -eq "Aggregated" }
    if (-not $goPoolAggregate -or [int]$goPoolAggregate."Failure Count" -ne 0) {
        throw "O diagnostico do pool Go registrou falhas HTTP."
    }
    $sessionCount = [int]((Invoke-BenchmarkCompose -Arguments @(
        "exec", "-T", "postgres", "psql", "-Atq",
        "-U", $user, "-d", $database,
        "-c", "SELECT sessions FROM pg_stat_database WHERE datname = current_database();"
    ) | Select-Object -Last 1).Trim())
    $backendCount = [int]((Invoke-BenchmarkCompose -Arguments @(
        "exec", "-T", "postgres", "psql", "-Atq",
        "-U", $user, "-d", $database,
        "-c", "SELECT numbackends FROM pg_stat_database WHERE datname = current_database();"
    ) | Select-Object -Last 1).Trim())
    $poolMax = [int](Get-BenchmarkValue $environment "DB_POOL_MAX" "20")
    [pscustomobject]@{
        sessions_created_after_reset = $sessionCount
        active_backends = $backendCount
        configured_pool_max = $poolMax
        session_limit = 100
        backend_limit = $poolMax + 2
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $goPoolDirectory "diagnostic.json") -Encoding utf8
    if ($sessionCount -gt 100) {
        throw "O pool Go recriou $sessionCount conexoes em 15 segundos; limite de regressao: 100."
    }
    if ($backendCount -gt ($poolMax + 2)) {
        throw "A API Go manteve $backendCount backends para um pool maximo de $poolMax."
    }
    Invoke-BenchmarkCompose -Arguments @("stop", $activeService)
    $activeService = $null

    Write-Host "[6/8] Validando monitoramento..."
    Invoke-BenchmarkCompose -Arguments @("--profile", "monitoring", "up", "-d", "--force-recreate", "postgres-exporter", "benchmark-results-exporter", "prometheus", "grafana", "cadvisor")
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
            $requiredJobs = @("benchmark-results", "postgres", "prometheus")
            $unhealthyRequired = @($requiredJobs | Where-Object {
                $job = $_
                -not ($targets | Where-Object { $_.labels.job -eq $job -and $_.health -eq "up" })
            })
            if ($targets.Count -ge 4 -and $unhealthyRequired.Count -eq 0) {
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
        throw "Os targets operacionais do Prometheus nao ficaram saudaveis dentro do tempo esperado."
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

    Write-Host "[7/8] Executando warmup misto curto pelo Locust..."
    Reset-BenchmarkDatabase $environment
    $activeService = "python-api"
    Invoke-BenchmarkCompose -Arguments @("--profile", "python", "up", "-d", $activeService)
    Wait-BenchmarkApi $apiBaseUrl
    Invoke-BenchmarkCompose -Arguments @("--profile", "load", "up", "-d", "locust")
    $locustPreflightStarted = $true
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/validate_monitoring.py"),
        "--prometheus-url", $prometheusUrl,
        "--grafana-url", "http://127.0.0.1:$grafanaPort",
        "--api-service", $activeService,
        "--mode", "pilot",
        "--output", (Join-Path $verificationDirectory "monitoring-preflight.json")
    )
    Invoke-BenchmarkCompose -Arguments @("stop", "locust")
    $locustPreflightStarted = $false
    New-Item -ItemType Directory -Force $verificationDirectory | Out-Null
    $uniquenessCheck = "from pathlib import Path; from payload_sequences import PayloadSequence; streams=[PayloadSequence(Path('/mnt/payloads/customers_create.jsonl')) for _ in range(4)]; [stream.configure_shard(index,4) for index,stream in enumerate(streams)]; rows=[stream.next() for stream in streams for _ in range(5000)]; assert len({r['email'] for r in rows}) == 20000; assert len({r['documentNumber'] for r in rows}) == 20000"
    Invoke-BenchmarkCompose -Arguments @(
        "--profile", "load", "run", "--rm", "--no-deps", "--entrypoint", "python",
        "-e", "PAYLOAD_DIR=/mnt/payloads", "locust", "-c", $uniquenessCheck
    )
    $verificationBounds = Join-Path $verificationDirectory "locust_measurement_bounds.json"
    $measurement = Start-BenchmarkMeasurements $verificationDirectory $verificationBounds 1
    $mainRunStarted = $true
    Invoke-BenchmarkLocust "warmup" 20 10 "15s" "http://python-api:8000" "/mnt/results/raw/verification/$verificationId/locust" -Processes 1
    $loadBounds = Get-Content $verificationBounds -Raw | ConvertFrom-Json
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/validate_measurement_bounds.py"),
        "--bounds", $verificationBounds,
        "--expected-duration-seconds", "15",
        "--duration-tolerance-seconds", "0.25",
        "--output", (Join-Path $verificationDirectory "measurement-bounds-validation.json")
    )
    Stop-BenchmarkMeasurements $measurement
    $metricsStartEpoch = [double]$loadBounds.started_epoch
    $metricsEndEpoch = [double]$loadBounds.finished_epoch
    Export-BenchmarkPrometheus $verificationDirectory $environment $metricsStartEpoch $metricsEndEpoch $activeService "pilot"
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

    Write-Host "[8/8] Validando consolidadores e testes automatizados..."
    Get-ChildItem (Join-Path $script:BenchmarkRoot "monitoring/grafana/dashboards") -Filter "*.json" |
        ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
    Invoke-BenchmarkPython @("-m", "unittest", "discover", "-s", "tests", "-v")

    $finalPreflightPath = Join-Path $verificationDirectory "preflight-final.json"
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/preflight.py"),
        "--mode", "pilot", "--output", $finalPreflightPath
    )
    $finalPreflight = Get-Content $finalPreflightPath -Raw | ConvertFrom-Json
    $monitoringEvidence = Get-Content (Join-Path $verificationDirectory "monitoring-preflight.json") -Raw | ConvertFrom-Json
    $measurementBoundsEvidence = Get-Content (Join-Path $verificationDirectory "measurement-bounds-validation.json") -Raw | ConvertFrom-Json
    $snapshotEvidence = Get-Content (Join-Path $verificationDirectory "locust_snapshot_validation.json") -Raw | ConvertFrom-Json
    $verificationReport = [ordered]@{
        available = $true
        completed = $true
        checked_at = (Get-Date).ToUniversalTime().ToString("o")
        methodology_version = $methodologyVersion
        commit_sha = $finalPreflight.git.commit_sha
        git_dirty = [bool]$finalPreflight.git.git_dirty
        tracked_diff_sha256 = $finalPreflight.git.tracked_diff_sha256
        untracked_files_sha256 = $finalPreflight.git.untracked_files_sha256
        monitoring_official_eligible = [bool]$monitoringEvidence.official_eligible
        contract_languages = $languages
        sql_wait_policy_languages = $languages
        openapi_valid = $true
        database_state_equivalent = $true
        all_executable_tests_passed = $true
        measurement_bounds_valid = [bool]$measurementBoundsEvidence.valid
        measurement_window_excludes_ramp_up = ($loadBounds.window_start_event -eq "spawning_complete_after_stats_reset")
        worker_histograms_reconciled = [bool]$snapshotEvidence.worker_reconciliation.valid
        worker_percentiles_recalculated = @($snapshotEvidence.worker_reconciliation.percentiles_recalculated)
        artifact_directory = "results/raw/verification/$verificationId"
    }
    $verificationReport | ConvertTo-Json -Depth 6 |
        Set-Content -Encoding utf8 (Join-Path $script:BenchmarkRoot "results/summaries/project-verification.json")

    Write-Host "Verificacao piloto concluida: banco, 5 APIs, contrato, pool Go, warmup misto, monitoramento e testes com fixtures aprovados. Evidencias: results/raw/verification/$verificationId."
}
finally {
    if ($locustPreflightStarted) {
        Stop-BenchmarkServices -Services @("locust")
    }
    if ($measurement -and -not $measurement.Stopped) {
        try { Stop-BenchmarkMeasurements $measurement } catch { Write-Warning $_.Exception.Message }
    }
    if ($activeService) {
        Stop-BenchmarkServices -Services @($activeService)
    }
    Stop-BenchmarkServices -Profiles @("monitoring") -Services @("postgres-exporter", "benchmark-results-exporter", "prometheus", "grafana", "cadvisor")
    try {
        Reset-BenchmarkDatabase $environment
        $mainRunStarted = $false
    }
    catch {
        Write-Warning "Nao foi possivel restaurar o banco durante a limpeza: $($_.Exception.Message)"
    }
}
