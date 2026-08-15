param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("python", "node", "java", "go", "dotnet")]
    [string]$Language,
    [ValidateSet("smoke", "warmup", "read_heavy", "write_heavy", "mixed")]
    [string]$Scenario = "mixed",
    [int]$RunNumber = 1
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
$warmupSeconds = [int](Get-BenchmarkValue $environment "WARMUP_DURATION_SECONDS" "180")
$warmupUsers = [int](Get-BenchmarkValue $environment "WARMUP_USERS" "20")
$warmupSpawnRate = [int](Get-BenchmarkValue $environment "WARMUP_SPAWN_RATE" "5")
$metricsInterval = [double](Get-BenchmarkValue $environment "METRICS_SAMPLE_INTERVAL_SECONDS" "2")
$service = "$Language-api"
$resultRelative = "results/raw/$Language/$Scenario/run_$RunNumber"
$resultDirectory = Join-Path $script:BenchmarkRoot $resultRelative
$metadataValues = Get-LanguageMetadata $Language
$apiStarted = $false
$mainRunStarted = $false
$measurement = $null
$metricsEndEpoch = 0

New-Item -ItemType Directory -Force $resultDirectory | Out-Null
$startedAt = (Get-Date).ToString("o")
$commit = (& git rev-parse --short HEAD 2>$null)
if (-not $commit) { $commit = "unknown" }

try {
    Invoke-BenchmarkCompose @("--profile", "monitoring", "up", "-d", "postgres-exporter", "prometheus", "grafana", "cadvisor")
    Reset-BenchmarkDatabase $environment
    Invoke-BenchmarkCompose @("--profile", $Language, "up", "-d", "--build", $service)
    $apiStarted = $true
    Wait-BenchmarkApi $apiBaseUrl

    Invoke-BenchmarkCompose @(
        "--profile", "load", "run", "--rm", "--no-deps", "--entrypoint", "python",
        "locust", "/mnt/scripts/contract_test_api.py", "--base-url", $locustHost
    )
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "testar-payloads.ps1") -BaseUrl $apiBaseUrl
    if ($LASTEXITCODE -ne 0) { throw "A validacao dos endpoints falhou." }

    Write-Host "Rodando warmup por $warmupSeconds segundos..."
    Invoke-BenchmarkLocust "warmup" $warmupUsers $warmupSpawnRate "${warmupSeconds}s" $locustHost "/mnt/results/raw/warmup/warmup"

    Reset-BenchmarkDatabase $environment
    $measurement = Start-BenchmarkMeasurements $resultDirectory $metricsInterval
    $mainRunStarted = $true
    Invoke-BenchmarkLocust $Scenario $users $spawnRate $duration $locustHost "/mnt/$resultRelative/locust"
    Stop-BenchmarkMeasurements $measurement
    $metricsEndEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    Export-BenchmarkPrometheus $resultDirectory $environment $measurement.StartEpoch $metricsEndEpoch
    Reset-BenchmarkDatabase $environment
    $mainRunStarted = $false

    $image = (& docker compose images -q $service 2>$null | Select-Object -First 1)
    $metadata = [ordered]@{
        language = $Language
        scenario = $Scenario
        run_number = $RunNumber
        started_at = $startedAt
        finished_at = (Get-Date).ToString("o")
        git_commit = $commit
        docker_image = $(if ($image) { $image } else { "unknown" })
        language_version = $metadataValues.Version
        postgres_driver_version = $metadataValues.Driver
        http_library_or_framework = $metadataValues.Framework
        framework_justification = "Somente HTTP, JSON, SQL explicito e pool de conexoes; nenhum ORM e utilizado."
        database_initial_state = "Seed deterministico carregado por database/reset/reset_database.sql."
        warmup = [ordered]@{ enabled = $true; duration_seconds = $warmupSeconds; users = $warmupUsers; spawn_rate = $warmupSpawnRate; included_in_results = $false }
        database_pool = [ordered]@{
            min = [int](Get-BenchmarkValue $environment "DB_POOL_MIN" "1")
            max = [int](Get-BenchmarkValue $environment "DB_POOL_MAX" "20")
            acquire_timeout_seconds = [int](Get-BenchmarkValue $environment "DB_POOL_ACQUIRE_TIMEOUT_SECONDS" "10")
            idle_timeout_seconds = [int](Get-BenchmarkValue $environment "DB_POOL_IDLE_TIMEOUT_SECONDS" "60")
            max_lifetime_seconds = [int](Get-BenchmarkValue $environment "DB_POOL_MAX_LIFETIME_SECONDS" "300")
            driver_specific_notes = $metadataValues.Pool
        }
        framework_policy = [ordered]@{
            minimum_framework_usage = $true
            http_library_or_framework = $metadataValues.Framework
            justification = "Estrutura minima para expor o contrato HTTP comum mantendo SQL explicito."
            orm_used = $false
        }
        easy_execution = [ordered]@{ launcher_used = "launchers/windows/powershell/rodar-linguagem.ps1"; manual_command_available = $true }
        locust = [ordered]@{ users = $users; spawn_rate = $spawnRate; duration = $duration; host = $locustHost }
        metrics = [ordered]@{
            sample_interval_seconds = $metricsInterval
            docker_stats_source = "continuous docker stats"
            prometheus_source = "PostgreSQL exporter query_range"
            started_epoch = $measurement.StartEpoch
            finished_epoch = $metricsEndEpoch
        }
        notes = ""
    }
    $metadata | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $resultDirectory "metadata.json")
    Write-Host "Rodada concluida: $resultRelative"
}
finally {
    if ($measurement -and -not $measurement.Stopped) {
        try { Stop-BenchmarkMeasurements $measurement } catch { Write-Warning $_.Exception.Message }
    }
    if ($mainRunStarted) {
        try { Reset-BenchmarkDatabase $environment } catch { Write-Warning "Falha no reset final: $($_.Exception.Message)" }
    }
    if ($apiStarted) {
        Stop-BenchmarkServices -Services @($service)
    }
}
