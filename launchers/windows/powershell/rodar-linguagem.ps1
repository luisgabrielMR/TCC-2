param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("python", "node", "java", "go", "dotnet")]
    [string]$Language,
    [ValidateSet("smoke", "warmup", "read_heavy", "write_heavy", "mixed")]
    [string]$Scenario = "mixed",
    [int]$RunNumber = 0,
    [ValidateSet("environment", "controlled_50", "capacity_100", "capacity_200")]
    [string]$LoadProfile = "environment",
    [ValidateSet("pilot", "official")]
    [string]$RunMode = "pilot"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "benchmark-common.ps1")
Set-Location $script:BenchmarkRoot

$environment = Get-BenchmarkEnvironment
$apiBaseUrl = Get-BenchmarkValue $environment "API_BASE_URL" "http://127.0.0.1:8000"
$locustHost = Get-BenchmarkValue $environment "LOCUST_HOST" "http://host.docker.internal:8000"
$users = [int](Get-BenchmarkValue $environment "LOCUST_USERS" "50")
$spawnRate = [int](Get-BenchmarkValue $environment "LOCUST_SPAWN_RATE" "10")
$duration = Get-BenchmarkValue $environment "LOCUST_DURATION" "5m"
$warmupSeconds = [int](Get-BenchmarkValue $environment "WARMUP_DURATION_SECONDS" "300")
$warmupWindowSeconds = [int](Get-BenchmarkValue $environment "WARMUP_STABILITY_WINDOW_SECONDS" "45")
$warmupMaxDriftPercent = [double](Get-BenchmarkValue $environment "WARMUP_MAX_RPS_DRIFT_PERCENT" "10")
$waitSeconds = Get-BenchmarkValue $environment "LOCUST_WAIT_SECONDS" "0.1"
$metricsInterval = [double](Get-BenchmarkValue $environment "METRICS_SAMPLE_INTERVAL_SECONDS" "2")
switch ($LoadProfile) {
    "controlled_50" { $users = 50; $spawnRate = 10 }
    "capacity_100" { $users = 100; $spawnRate = 20 }
    "capacity_200" { $users = 200; $spawnRate = 40 }
}
if ($LoadProfile -like "capacity_*" -and $Scenario -ne "mixed") {
    throw "Os perfis de capacidade usam o workload mixed."
}

$resultScenario = switch ($LoadProfile) {
    "capacity_100" { "${Scenario}_capacity_100" }
    "capacity_200" { "${Scenario}_capacity_200" }
    default { $Scenario }
}
$benchmarkKind = if ($LoadProfile -like "capacity_*") { "capacity" } else { "controlled_load" }
$service = "$Language-api"
$scenarioDirectory = Join-Path $script:BenchmarkRoot "results/raw/$Language/$resultScenario"
if ($RunNumber -le 0) {
    $existingRuns = @(Get-ChildItem $scenarioDirectory -Directory -Filter "run_*" -ErrorAction SilentlyContinue |
        ForEach-Object { if ($_.Name -match '^run_(\d+)$') { [int]$matches[1] } })
    $RunNumber = if ($existingRuns.Count) { ($existingRuns | Measure-Object -Maximum).Maximum + 1 } else { 1 }
}
$resultRelative = "results/raw/$Language/$resultScenario/run_$RunNumber"
$resultDirectory = Join-Path $script:BenchmarkRoot $resultRelative
if (Test-Path (Join-Path $resultDirectory "locust_stats.csv")) {
    throw "A rodada ja existe: $resultRelative. Use RunNumber 0 para selecionar a proxima automaticamente."
}
$apiStarted = $false
$locustPreflightStarted = $false
$mainRunStarted = $false
$databaseNeedsReset = $false
$measurement = $null
$metricsEndEpoch = 0
$warmupResult = $null
$testStartedAt = $null
$testFinishedAt = $null
$testElapsedSeconds = 0
$runnerElapsedSeconds = 0
$metricsStartEpoch = 0
$preflightPath = Join-Path $resultDirectory "preflight.json"
$monitoringPreflightPath = Join-Path $resultDirectory "monitoring-preflight.json"

New-Item -ItemType Directory -Force $resultDirectory | Out-Null
$startedAt = (Get-Date).ToString("o")
$commit = (& git rev-parse --short HEAD 2>$null)
if (-not $commit) { $commit = "unknown" }

try {
    Invoke-BenchmarkCompose @("--profile", "monitoring", "up", "-d", "postgres-exporter", "benchmark-results-exporter", "prometheus", "grafana", "cadvisor")
    Reset-BenchmarkDatabase $environment
    $databaseNeedsReset = $false
    Invoke-BenchmarkCompose @("--profile", $Language, "up", "-d", "--build", $service)
    $apiStarted = $true
    Wait-BenchmarkApi $apiBaseUrl
    Invoke-BenchmarkCompose @("--profile", "load", "up", "-d", "locust")
    $locustPreflightStarted = $true
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/preflight.py"),
        "--mode", $RunMode, "--output", $preflightPath
    )
    $preflight = Get-Content $preflightPath -Raw | ConvertFrom-Json
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/validate_monitoring.py"),
        "--prometheus-url", "http://127.0.0.1:$(Get-BenchmarkValue $environment 'PROMETHEUS_PORT' '9090')",
        "--grafana-url", "http://127.0.0.1:$(Get-BenchmarkValue $environment 'GRAFANA_PORT' '3000')",
        "--api-service", $service, "--mode", $RunMode, "--output", $monitoringPreflightPath
    )
    $monitoringPreflight = Get-Content $monitoringPreflightPath -Raw | ConvertFrom-Json
    Invoke-BenchmarkCompose @("stop", "locust")
    $locustPreflightStarted = $false

    Invoke-BenchmarkCompose @(
        "--profile", "load", "run", "--rm", "--no-deps", "--entrypoint", "python",
        "locust", "/mnt/scripts/contract_test_api.py", "--base-url", $locustHost
    )
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "testar-payloads.ps1") -BaseUrl $apiBaseUrl
    if ($LASTEXITCODE -ne 0) { throw "A validacao dos endpoints falhou." }

    # Os testes de contrato escrevem no banco; o warmup deve partir do mesmo estado em todas as APIs.
    $databaseNeedsReset = $true
    Reset-BenchmarkDatabase $environment
    $databaseNeedsReset = $false
    $databaseNeedsReset = $true
    $warmupResult = Invoke-BenchmarkWarmup `
        -Environment $environment `
        -Scenario $Scenario `
        -Users $users `
        -SpawnRate $spawnRate `
        -InitialDurationSeconds $warmupSeconds `
        -StabilityWindowSeconds $warmupWindowSeconds `
        -MaxRpsDriftPercent $warmupMaxDriftPercent `
        -WaitSeconds $waitSeconds `
        -HostUrl $locustHost `
        -ResultRelative $resultRelative
    Reset-BenchmarkDatabase $environment
    $databaseNeedsReset = $false
    $boundsPath = Join-Path $resultDirectory "locust_measurement_bounds.json"
    $measurement = Start-BenchmarkMeasurements $resultDirectory $boundsPath $metricsInterval
    $mainRunStarted = $true
    $databaseNeedsReset = $true
    $testStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Invoke-BenchmarkLocust $Scenario $users $spawnRate $duration $locustHost "/mnt/$resultRelative/locust" $waitSeconds
    $testStopwatch.Stop()
    $runnerElapsedSeconds = [math]::Round($testStopwatch.Elapsed.TotalSeconds, 3)
    if (-not (Test-Path $boundsPath)) { throw "Locust nao produziu os limites exatos da medicao." }
    $loadBounds = Get-Content $boundsPath -Raw | ConvertFrom-Json
    if (-not $loadBounds.finished_epoch -or [double]$loadBounds.elapsed_seconds -le 0) { throw "Limites de medicao invalidos em $boundsPath" }
    $testStartedAt = [DateTimeOffset]::FromUnixTimeMilliseconds([long]([double]$loadBounds.started_epoch * 1000))
    $testFinishedAt = [DateTimeOffset]::FromUnixTimeMilliseconds([long]([double]$loadBounds.finished_epoch * 1000))
    $testElapsedSeconds = [math]::Round([double]$loadBounds.elapsed_seconds, 3)
    $metricsStartEpoch = [double]$loadBounds.started_epoch
    $metricsEndEpoch = [double]$loadBounds.finished_epoch
    Stop-BenchmarkMeasurements $measurement
    $measurementValidationPath = Join-Path $resultDirectory "measurement_stability.json"
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/validate_warmup_stability.py"),
        "--stats", (Join-Path $resultDirectory "locust_stats.csv"),
        "--history", (Join-Path $resultDirectory "locust_stats_history.csv"),
        "--scenario", $Scenario,
        "--expected-users", "$users",
        "--phase-label", "Measurement",
        "--window-seconds", "$warmupWindowSeconds",
        "--max-rps-drift-percent", "$warmupMaxDriftPercent",
        "--output", $measurementValidationPath
    ) | Out-Host
    $measurementValidation = Get-Content $measurementValidationPath -Raw | ConvertFrom-Json
    $measurementStable = [bool]$measurementValidation.stable
    Export-BenchmarkPrometheus $resultDirectory $environment $metricsStartEpoch $metricsEndEpoch $service $RunMode
    Reset-BenchmarkDatabase $environment
    $databaseNeedsReset = $false
    $mainRunStarted = $false

    $image = (& docker compose images -q $service 2>$null | Select-Object -First 1)
    $runtime = $preflight.runtimes.$Language
    $libraries = $preflight.libraries.$Language.libraries
    $driverVersion = switch ($Language) {
        "python" { "psycopg $($libraries.psycopg)" }
        "node" { "pg $($libraries.pg)" }
        "java" { "PostgreSQL JDBC $($libraries.postgresql)" }
        "go" { "lib/pq $($libraries.'github.com/lib/pq')" }
        "dotnet" { "Npgsql $($libraries.Npgsql)" }
    }
    $framework = switch ($Language) {
        "python" { "FastAPI $($libraries.fastapi) + Uvicorn $($libraries.uvicorn)" }
        "node" { "Express $($libraries.express)" }
        "java" { "JDK HttpServer + Jackson $($libraries.'jackson-databind')" }
        "go" { "net/http" }
        "dotnet" { "ASP.NET Core Minimal API ($($runtime.version_output))" }
    }
    $poolNotes = switch ($Language) {
        "python" { "psycopg_pool $($libraries.'psycopg-pool')" }
        "node" { "pg.Pool; min nao preabre conexoes" }
        "java" { "HikariCP $($libraries.HikariCP)" }
        "go" { "database/sql; minimo preaberto e timeout aplicado ao contexto" }
        "dotnet" { "Pooling nativo do Npgsql" }
    }
    $metadata = [ordered]@{
        result_classification = $(if ($RunMode -eq "official" -and $measurementStable) { "official" } else { "non_official" })
        requested_run_mode = $RunMode
        official_run = ($RunMode -eq "official")
        language = $Language
        scenario = $resultScenario
        workload_scenario = $Scenario
        load_profile = $LoadProfile
        methodology_version = 6
        benchmark_kind = $benchmarkKind
        run_number = $RunNumber
        execution_order = [ordered]@{
            sequence_id = $(if ($env:BENCHMARK_SEQUENCE_ID) { $env:BENCHMARK_SEQUENCE_ID } else { "manual" })
            position = $(if ($env:BENCHMARK_ORDER_POSITION) { [int]$env:BENCHMARK_ORDER_POSITION } else { 0 })
        }
        started_at = $startedAt
        finished_at = (Get-Date).ToString("o")
        git_commit = $preflight.git.commit_sha
        commit_sha = $preflight.git.commit_sha
        git_dirty = $preflight.git.git_dirty
        tracked_diff_sha256 = $preflight.git.tracked_diff_sha256
        untracked_files = $preflight.git.untracked_files
        untracked_files_sha256 = $preflight.git.untracked_files_sha256
        docker_image = $(if ($image) { $image } else { "unknown" })
        language_version = $runtime.version_output
        postgres_driver_version = $driverVersion
        http_library_or_framework = $framework
        environment = $preflight
        monitoring_preflight = $monitoringPreflight
        framework_justification = "Somente HTTP, JSON, SQL explicito e pool de conexoes; nenhum ORM e utilizado."
        database_initial_state = "Seed deterministico carregado por database/reset/reset_database.sql."
        warmup = [ordered]@{
            enabled = $true
            scenario = $Scenario
            users = $users
            spawn_rate = $spawnRate
            requested_duration_seconds = $warmupSeconds
            retry_duration_seconds = 0
            total_duration_seconds = $warmupResult.total_duration_seconds
            included_in_results = $false
            stability_window_seconds = $warmupWindowSeconds
            max_rps_drift_percent = $warmupMaxDriftPercent
            stable = $warmupResult.stable
            attempts = $warmupResult.attempts
        }
        database_pool = [ordered]@{
            min = [int](Get-BenchmarkValue $environment "DB_POOL_MIN" "1")
            max = [int](Get-BenchmarkValue $environment "DB_POOL_MAX" "20")
            acquire_timeout_seconds = [int](Get-BenchmarkValue $environment "DB_POOL_ACQUIRE_TIMEOUT_SECONDS" "10")
            idle_timeout_seconds = [int](Get-BenchmarkValue $environment "DB_POOL_IDLE_TIMEOUT_SECONDS" "60")
            max_lifetime_seconds = [int](Get-BenchmarkValue $environment "DB_POOL_MAX_LIFETIME_SECONDS" "1800")
            driver_specific_notes = $poolNotes
        }
        framework_policy = [ordered]@{
            minimum_framework_usage = $true
            http_library_or_framework = $framework
            justification = "Estrutura minima para expor o contrato HTTP comum mantendo SQL explicito."
            orm_used = $false
        }
        resource_policy = [ordered]@{
            api_containers = 1
            application_processes = 1
            replicas = 1
            cpu_limit = "Docker Desktop host allocation"
            interpretation = "single application instance; not an intrinsic language ranking"
        }
        easy_execution = [ordered]@{ launcher_used = "launchers/windows/powershell/rodar-linguagem.ps1"; manual_command_available = $true }
        locust = [ordered]@{
            users = $users
            spawn_rate = $spawnRate
            duration = $duration
            wait_seconds = [double]$waitSeconds
            theoretical_rps_ceiling = [math]::Round($users / [double]$waitSeconds, 3)
            host = $locustHost
        }
        test_phase = [ordered]@{
            started_at = $testStartedAt.ToString("o")
            finished_at = $testFinishedAt.ToString("o")
            elapsed_seconds = $testElapsedSeconds
            runner_elapsed_seconds = $runnerElapsedSeconds
            excludes_warmup = $true
        }
        measurement_stability = $measurementValidation
        metrics = [ordered]@{
            window_source = "locust_test_start_stop"
            response_time_source = "Locust locust_stats.csv"
            percentile_source = "Locust locust_stats.csv"
            throughput_source = "Locust locust_stats.csv"
            request_count_source = "Locust locust_stats.csv"
            failure_and_error_rate_source = "Locust locust_stats.csv"
            total_test_time_source = "Locust test_start/test_stop events"
            sample_interval_seconds = $metricsInterval
            container_primary_source = "cAdvisor via Prometheus"
            container_cpu_source = "cAdvisor via Prometheus"
            container_memory_source = "cAdvisor via Prometheus"
            cadvisor_summary_file = "cadvisor_summary.csv"
            docker_stats_source = "continuous docker stats (complementary or contingency)"
            docker_stats_summary_file = "docker_stats_summary.csv"
            postgresql_metrics_source = "postgres-exporter via Prometheus query_range"
            postgresql_summary_file = "postgres_summary.csv"
            prometheus_series_file = "prometheus_series.json"
            started_epoch = $metricsStartEpoch
            finished_epoch = $metricsEndEpoch
        }
        notes = $(if ($benchmarkKind -eq "controlled_load") {
            "Carga controlada; nao representa a capacidade maxima da API."
        } else {
            "Teste extra de escalabilidade; representa o limite pratico observado neste ambiente."
        })
    }
    $metadata | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 (Join-Path $resultDirectory "metadata.json")
    if ($RunMode -eq "official" -and -not $measurementStable) {
        throw "A medicao oficial ficou instavel e foi registrada como non_official: $($measurementValidation.reasons -join '; ')"
    }
    Write-Host "Rodada concluida: $resultRelative"
}
finally {
    if ($locustPreflightStarted) {
        Stop-BenchmarkServices -Services @("locust")
    }
    if ($measurement -and -not $measurement.Stopped) {
        try { Stop-BenchmarkMeasurements $measurement } catch { Write-Warning $_.Exception.Message }
    }
    if ($mainRunStarted -or $databaseNeedsReset) {
        try { Reset-BenchmarkDatabase $environment } catch { Write-Warning "Falha no reset final: $($_.Exception.Message)" }
    }
    if ($apiStarted) {
        Stop-BenchmarkServices -Services @($service)
    }
}
