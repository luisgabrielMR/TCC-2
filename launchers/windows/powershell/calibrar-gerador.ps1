param(
    [ValidateSet("python", "node", "java", "go", "dotnet")]
    [string]$Language = "go"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "benchmark-common.ps1")
Set-Location $script:BenchmarkRoot

$environment = Get-BenchmarkEnvironment
$methodologyVersion = [int](Get-BenchmarkValue $environment "METHODOLOGY_VERSION" "8")
$calibrationRelative = Get-BenchmarkValue $environment "LOAD_GENERATOR_CALIBRATION_FILE" "results/summaries/load-generator-calibration.json"
$calibrationPath = Join-Path $script:BenchmarkRoot $calibrationRelative
$service = "$Language-api"
$hostUrl = "http://${service}:8000"
$apiBaseUrl = Get-BenchmarkValue $environment "API_BASE_URL" "http://127.0.0.1:8000"
$metricsInterval = [double](Get-BenchmarkValue $environment "METRICS_SAMPLE_INTERVAL_SECONDS" "2")
$locustProcesses = [int](Get-BenchmarkValue $environment "LOCUST_PROCESSES" "4")
if ($locustProcesses -lt 1) { throw "LOCUST_PROCESSES deve ser um inteiro positivo." }
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
$calibrationRootRelative = "results/calibration/$stamp"
$calibrationRoot = Join-Path $script:BenchmarkRoot $calibrationRootRelative
$preflightPath = Join-Path $calibrationRoot "preflight.json"
$samples = @()
$apiStarted = $false
$locustStarted = $false

New-Item -ItemType Directory -Force $calibrationRoot | Out-Null

try {
    Invoke-BenchmarkCompose @("--profile", "monitoring", "up", "-d", "postgres-exporter", "benchmark-results-exporter", "prometheus", "grafana", "cadvisor")
    Reset-BenchmarkDatabase $environment
    Invoke-BenchmarkCompose @("--profile", $Language, "up", "-d", "--build", $service)
    $apiStarted = $true
    Wait-BenchmarkApi $apiBaseUrl
    Invoke-BenchmarkCompose @("--profile", "load", "up", "-d", "locust")
    $locustStarted = $true
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/preflight.py"),
        "--mode", "pilot", "--api-service", $service,
        "--load-profile", "environment", "--output", $preflightPath
    )
    $preflight = Get-Content $preflightPath -Raw | ConvertFrom-Json
    $locustCpuQuota = [double]$preflight.resource_policy.effective.limits.locust.effective_cpu_quota
    if ($locustCpuQuota -le 0) { throw "O preflight nao confirmou a cota efetiva de CPU do Locust." }
    if ($preflight.git.git_dirty) {
        throw "A calibracao que libera rodadas oficiais exige uma arvore Git limpa. Versione as correcoes primeiro."
    }
    if ($preflight.docker.engine_server_version -ne $preflight.expected.docker_engine -or
        ([string]$preflight.docker.compose_version).TrimStart("v") -ne $preflight.expected.docker_compose) {
        throw "A calibracao exige Docker $($preflight.expected.docker_engine) e Compose $($preflight.expected.docker_compose)."
    }
    $invalidCpuLimits = @($preflight.resource_policy.configured.limits.PSObject.Properties.Value |
        Where-Object { -not $_.matches_expected }) + @($preflight.resource_policy.effective.limits.PSObject.Properties.Value |
        Where-Object { -not $_.matches_expected })
    if ($invalidCpuLimits.Count) { throw "As cotas de CPU configuradas ou efetivas nao correspondem a metodologia." }
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/validate_monitoring.py"),
        "--prometheus-url", "http://127.0.0.1:$(Get-BenchmarkValue $environment 'PROMETHEUS_PORT' '9090')",
        "--grafana-url", "http://127.0.0.1:$(Get-BenchmarkValue $environment 'GRAFANA_PORT' '3000')",
        "--api-service", $service, "--mode", "official",
        "--output", (Join-Path $calibrationRoot "monitoring-preflight.json")
    )
    Invoke-BenchmarkCompose @("stop", "locust")
    $locustStarted = $false

    foreach ($users in @(25, 50, 100, 200, 400)) {
        $stepRelative = "$calibrationRootRelative/users_$users"
        $stepDirectory = Join-Path $script:BenchmarkRoot $stepRelative
        New-Item -ItemType Directory -Force $stepDirectory | Out-Null
        $boundsPath = Join-Path $stepDirectory "locust_measurement_bounds.json"
        $measurement = Start-BenchmarkMeasurements $stepDirectory $boundsPath $metricsInterval
        try {
            Write-Host "Calibrando Locust: /health, $users usuarios, pacing 0, 60 s..." -ForegroundColor Cyan
            Invoke-BenchmarkLocust "health_only" $users $users "60s" $hostUrl "/mnt/$stepRelative/locust" "0" -Processes $locustProcesses
        }
        finally {
            Stop-BenchmarkMeasurements $measurement
        }

        $boundsValidationPath = Join-Path $stepDirectory "measurement-bounds-validation.json"
        Invoke-BenchmarkPython @(
            (Join-Path $script:BenchmarkRoot "scripts/validate_measurement_bounds.py"),
            "--bounds", $boundsPath, "--output", $boundsValidationPath
        )
        $bounds = Get-Content $boundsPath -Raw | ConvertFrom-Json
        $boundsValidation = Get-Content $boundsValidationPath -Raw | ConvertFrom-Json
        Export-BenchmarkPrometheus $stepDirectory $environment ([double]$bounds.started_epoch) ([double]$bounds.finished_epoch) $service "official" 80

        $aggregate = Import-Csv (Join-Path $stepDirectory "locust_stats.csv") |
            Where-Object { $_.Name -eq "Aggregated" } | Select-Object -First 1
        $locustResource = Import-Csv (Join-Path $stepDirectory "cadvisor_summary.csv") |
            Where-Object { $_.component -eq "locust" } | Select-Object -First 1
        if (-not $aggregate -or -not $locustResource) {
            throw "A calibracao de $users usuarios nao produziu estatisticas completas."
        }
        $elapsed = [double]$bounds.elapsed_seconds
        $requestCount = [int64]$aggregate."Request Count"
        $samples += [ordered]@{
            users = $users
            spawn_rate = $users
            elapsed_seconds = [math]::Round($elapsed, 9)
            requests = $requestCount
            failures = [int64]$aggregate."Failure Count"
            throughput_rps_exact = [math]::Round($requestCount / $elapsed, 9)
            locust_reported_rps = [double]$aggregate."Requests/s"
            locust_cpu_raw_average_percent = [double]$locustResource.cpu_average_percent
            locust_cpu_raw_max_percent = [double]$locustResource.cpu_max_percent
            locust_cpu_quota_average_percent = [math]::Round([double]$locustResource.cpu_average_percent / $locustCpuQuota, 6)
            locust_cpu_quota_max_percent = [math]::Round([double]$locustResource.cpu_max_percent / $locustCpuQuota, 6)
            cadvisor_coverage_percent = [double]$locustResource.coverage_percent
            cpu_metric_source = "cadvisor_via_prometheus"
            bounds_valid = [bool]$boundsValidation.valid
            result_directory = $stepRelative
        }
    }

    $validRps = @($samples |
        Where-Object { [int64]$_["failures"] -eq 0 } |
        ForEach-Object { [double]$_["throughput_rps_exact"] })
    $validatedCapacity = if ($validRps.Count) {
        ($validRps | Measure-Object -Maximum).Maximum
    } else { 0 }
    $locustImage = $preflight.configured_images.images |
        Where-Object { $_.configured_reference -like "locustio/locust:2.32.6@sha256:*" } |
        Select-Object -ExpandProperty configured_reference -First 1
    $artifact = [ordered]@{
        schema_version = 3
        classification = "non_official_calibration"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        methodology_version = $methodologyVersion
        scenario = "health_only"
        wait_seconds = 0
        step_duration_seconds = 60
        processes = $locustProcesses
        api_service = $service
        git = [ordered]@{
            commit_sha = $preflight.git.commit_sha
            git_dirty = [bool]$preflight.git.git_dirty
            tracked_diff_sha256 = $preflight.git.tracked_diff_sha256
            untracked_files_sha256 = $preflight.git.untracked_files_sha256
        }
        environment = [ordered]@{
            docker_engine = $preflight.docker.engine_server_version
            docker_compose = $preflight.docker.compose_version
            docker_logical_processors = $preflight.docker.allocation.logical_processors
            docker_memory_bytes = $preflight.docker.allocation.memory_bytes
            locust_image = $locustImage
            locust_processes = $locustProcesses
            locust_cpu_quota = $locustCpuQuota
        }
        samples = $samples
        validated_capacity_rps = [math]::Round([double]$validatedCapacity, 9)
    }
    New-Item -ItemType Directory -Force (Split-Path $calibrationPath -Parent) | Out-Null
    $artifact | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $calibrationPath
    $validationPath = Join-Path $calibrationRoot "calibration-validation.json"
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/preflight.py"),
        "--mode", "pilot", "--api-service", $service,
        "--load-profile", "fixed_200", "--output", $validationPath
    )
    $calibrationValidation = (Get-Content $validationPath -Raw | ConvertFrom-Json).load_generator_calibration
    if (-not $calibrationValidation.valid) {
        throw "A calibracao foi gravada, mas nao passou no validador: $($calibrationValidation.reasons -join '; ')"
    }
    Write-Host "Calibracao gravada em $calibrationRelative" -ForegroundColor Green
    Write-Host "Capacidade de pico validada: $validatedCapacity req/s"
    Write-Host "Limite operacional das rodadas (80%): $([math]::Round([double]$validatedCapacity * 0.8, 3)) req/s"
}
finally {
    if ($locustStarted) { Stop-BenchmarkServices -Services @("locust") }
    if ($apiStarted) { Stop-BenchmarkServices -Services @($service) }
}
