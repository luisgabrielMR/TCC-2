$script:BenchmarkRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")

function Get-BenchmarkEnvironment {
    $values = @{}
    $envPath = Join-Path $script:BenchmarkRoot ".env"
    if (-not (Test-Path $envPath)) {
        $envPath = Join-Path $script:BenchmarkRoot ".env.example"
    }

    if (Test-Path $envPath) {
        Get-Content $envPath | ForEach-Object {
            if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
                $values[$matches[1].Trim()] = $matches[2].Trim()
            }
        }
    }
    return $values
}

function Get-BenchmarkValue {
    param(
        [hashtable]$Environment,
        [string]$Name,
        [string]$Default
    )

    $processValue = [Environment]::GetEnvironmentVariable($Name)
    if ($null -ne $processValue -and $processValue -ne "") {
        return $processValue
    }
    if ($Environment.ContainsKey($Name)) {
        return $Environment[$Name]
    }
    return $Default
}

function Invoke-BenchmarkCompose {
    param([string[]]$Arguments)

    if ($Arguments -contains "build") {
        Invoke-BenchmarkComposeBuild -Arguments $Arguments
        return
    }

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose falhou: $($Arguments -join ' ')"
    }
}

function Invoke-BenchmarkComposeBuild {
    param([string[]]$Arguments)

    $logDirectory = Join-Path $script:BenchmarkRoot "results\summaries\build-logs"
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    $buildId = [Guid]::NewGuid().ToString("N")
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $logPath = Join-Path $logDirectory "$buildId-attempt-$attempt.log"
        $previousPreference = $ErrorActionPreference
        try {
            # Windows PowerShell treats redirected native stderr as ErrorRecord.
            $ErrorActionPreference = "Continue"
            $PSNativeCommandUseErrorActionPreference = $false
            & docker compose --progress plain @Arguments 2>&1 |
                ForEach-Object { $_.ToString() } |
                Tee-Object -FilePath $logPath | Out-Host
            $buildExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($buildExitCode -eq 0) { return }

        $log = Get-Content -LiteralPath $logPath -Raw
        $registryNetworkFailure = $log -match '(?im)(failed to do request|failed to resolve source metadata|failed to fetch oauth token)[^\r\n]*(no such host|i/o timeout|TLS handshake timeout|connection reset by peer|temporary failure in name resolution)'
        if ($registryNetworkFailure -and $attempt -lt 3) {
            Write-Warning "Falha de rede ao acessar o registro de imagens. Nova tentativa em 5 segundos ($attempt/3). Log: $logPath"
            Start-Sleep -Seconds 5
            continue
        }
        $cause = ($log -split '\r?\n' | Where-Object { $_ -match '(?i)error|failed|no such host' } | Select-Object -Last 5) -join "`n"
        throw "docker compose build falhou (codigo $buildExitCode). Log: $logPath`n$cause"
    }
}

function Stop-BenchmarkServices {
    param(
        [string[]]$Profiles = @(),
        [string[]]$Services
    )

    $arguments = @()
    foreach ($profile in $Profiles) { $arguments += @("--profile", $profile) }
    $arguments += "stop"
    $arguments += $Services
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & docker compose @arguments 2>&1 | Out-Null
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Wait-BenchmarkPostgres {
    param([hashtable]$Environment)

    $user = Get-BenchmarkValue $Environment "POSTGRES_USER" "benchmark_user"
    $database = Get-BenchmarkValue $Environment "POSTGRES_DB" "benchmark_db"
    Write-Host "Aguardando PostgreSQL..."
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        & docker compose exec -T postgres pg_isready -U $user -d $database *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "PostgreSQL pronto."
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "PostgreSQL nao ficou pronto dentro do tempo esperado."
}

function Reset-BenchmarkDatabase {
    param([hashtable]$Environment)

    $user = Get-BenchmarkValue $Environment "POSTGRES_USER" "benchmark_user"
    $database = Get-BenchmarkValue $Environment "POSTGRES_DB" "benchmark_db"
    Invoke-BenchmarkCompose @("up", "-d", "postgres")
    Wait-BenchmarkPostgres $Environment
    Invoke-BenchmarkCompose @(
        "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1",
        "-U", $user, "-d", $database, "-f", "/benchmark/database/reset/reset_database.sql"
    )
    Write-Host "Banco restaurado para o estado inicial conhecido."
}

function Wait-BenchmarkApi {
    param([string]$BaseUrl)

    Write-Host "Aguardando API em $BaseUrl ..."
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/health" -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                Write-Host "API pronta."
                return
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "API nao respondeu em $BaseUrl dentro do tempo esperado."
}

function Invoke-BenchmarkLocust {
    param(
        [string]$Scenario,
        [int]$Users,
        [int]$SpawnRate,
        [string]$Duration,
        [string]$HostUrl,
        [string]$CsvPrefix,
        [string]$WaitSeconds = "0.1",
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 64)]
        [int]$Processes
    )

    $containerRoot = "/mnt/results/"
    if (-not $CsvPrefix.StartsWith($containerRoot)) {
        throw "O prefixo CSV do Locust deve estar dentro de /mnt/results: $CsvPrefix"
    }
    $relativePrefix = $CsvPrefix.Substring($containerRoot.Length).Replace("/", [IO.Path]::DirectorySeparatorChar)
    $hostPrefix = Join-Path (Join-Path $script:BenchmarkRoot "results") $relativePrefix
    $finalizer = Join-Path $script:BenchmarkRoot "scripts/finalize_locust_csv.py"
    Invoke-BenchmarkPython @($finalizer, "--prefix", $hostPrefix, "--prepare")

    Invoke-BenchmarkCompose @(
        "--profile", "load", "run", "--rm",
        "-e", "SCENARIO=$Scenario",
        "-e", "PAYLOAD_DIR=/mnt/payloads",
        "-e", "LOCUST_WAIT_SECONDS=$WaitSeconds",
        "-e", "LOCUST_PROCESSES=$Processes",
        "locust", "-f", "locustfile.py", "--headless", "--stop-timeout", "5", "--processes", "$Processes",
        "-u", "$Users", "-r", "$SpawnRate", "-t", $Duration,
        "--host", $HostUrl, "--csv", $CsvPrefix, "--only-summary"
    )
    Invoke-BenchmarkPython @($finalizer, "--prefix", $hostPrefix)
}

function Invoke-BenchmarkWarmup {
    param(
        [hashtable]$Environment,
        [string]$Scenario,
        [int]$Users,
        [int]$SpawnRate,
        [int]$InitialDurationSeconds,
        [int]$StabilityWindowSeconds,
        [double]$MaxRpsDriftPercent,
        [string]$WaitSeconds,
        [ValidateRange(1, 64)]
        [int]$Processes,
        [string]$HostUrl,
        [string]$ResultRelative
    )

    $attempts = @()
    $durationSeconds = $InitialDurationSeconds
    $attemptNumber = 1
    $attemptRelative = "$ResultRelative/warmup/attempt_$attemptNumber"
    $attemptDirectory = Join-Path $script:BenchmarkRoot $attemptRelative
    New-Item -ItemType Directory -Force $attemptDirectory | Out-Null
    Write-Host "Warmup ${attemptNumber}: $Scenario, $Users usuarios, ${durationSeconds}s..."
    Invoke-BenchmarkLocust $Scenario $Users $SpawnRate "${durationSeconds}s" $HostUrl "/mnt/$attemptRelative/locust" $WaitSeconds -Processes $Processes | Out-Host

    $validationPath = Join-Path $attemptDirectory "validation.json"
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/validate_warmup_stability.py"),
        "--stats", (Join-Path $attemptDirectory "locust_stats.csv"),
        "--history", (Join-Path $attemptDirectory "locust_stats_history.csv"),
        "--scenario", $Scenario,
        "--expected-users", "$Users",
        "--window-seconds", "$StabilityWindowSeconds",
        "--max-rps-drift-percent", "$MaxRpsDriftPercent",
        "--output", $validationPath
    ) | Out-Host
    $validation = Get-Content $validationPath -Raw | ConvertFrom-Json
    $attempts += [pscustomobject]@{
        attempt = $attemptNumber
        duration_seconds = $durationSeconds
        validation = $validation
    }
    if ($validation.stable) {
        return [pscustomobject]@{
            stable = $true
            total_duration_seconds = $InitialDurationSeconds
            attempts = $attempts
        }
    }

    $lastReasons = $attempts[-1].validation.reasons -join "; "
    throw "Warmup nao estabilizou na duracao padronizada: $lastReasons"
}

function Get-BenchmarkPythonCommand {
    $bundled = "C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe"
    if (Test-Path $bundled) {
        return [pscustomobject]@{ FilePath = $bundled; Prefix = @() }
    }
    foreach ($candidate in @(@{ Name = "py"; Prefix = @("-3") }, @{ Name = "python"; Prefix = @() })) {
        $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $testArguments = @($candidate.Prefix) + "--version"
        & $command.Source @testArguments *> $null
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{ FilePath = $command.Source; Prefix = @($candidate.Prefix) }
        }
    }
    throw "Python 3 nao foi encontrado para executar os coletores de metricas."
}

function Invoke-BenchmarkPython {
    param([string[]]$Arguments)
    $python = Get-BenchmarkPythonCommand
    $allArguments = @($python.Prefix) + $Arguments
    & $python.FilePath @allArguments
    if ($LASTEXITCODE -ne 0) { throw "Python falhou: $($Arguments -join ' ')" }
}

function Start-BenchmarkMeasurements {
    param([string]$ResultDirectory, [string]$BoundsPath, [double]$IntervalSeconds = 2)
    New-Item -ItemType Directory -Force $ResultDirectory | Out-Null
    $python = Get-BenchmarkPythonCommand
    $scriptPath = Join-Path $script:BenchmarkRoot "scripts/collect_docker_stats.py"
    $outputPath = Join-Path $ResultDirectory "docker_stats_raw.csv"
    $stopPath = Join-Path $ResultDirectory ".stop_docker_stats"
    $stdoutPath = Join-Path $ResultDirectory "docker_stats_collector.log"
    $stderrPath = Join-Path $ResultDirectory "docker_stats_collector.error.log"
    Remove-Item $stopPath, $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    $arguments = @($python.Prefix) + @($scriptPath, "--output", $outputPath, "--stop-file", $stopPath, "--interval", "$IntervalSeconds", "--bounds", $BoundsPath)
    $quotedArguments = $arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }
    $process = Start-Process -FilePath $python.FilePath -ArgumentList $quotedArguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    return [pscustomobject]@{
        Process = $process
        StopPath = $stopPath
        SummaryPath = (Join-Path $ResultDirectory "docker_stats_summary.csv")
        ErrorPath = $stderrPath
        Stopped = $false
    }
}

function Stop-BenchmarkMeasurements {
    param($Measurement)
    if ($null -eq $Measurement -or $Measurement.Stopped) { return }
    "stop" | Set-Content -Encoding ascii $Measurement.StopPath
    if (-not $Measurement.Process.WaitForExit(30000)) {
        Stop-Process -Id $Measurement.Process.Id -Force
        throw "O coletor docker stats nao encerrou no tempo esperado."
    }
    $Measurement.Stopped = $true
    if (-not (Test-Path $Measurement.SummaryPath)) {
        $detail = if (Test-Path $Measurement.ErrorPath) { Get-Content $Measurement.ErrorPath -Raw } else { "sem log" }
        throw "O coletor docker stats falhou: $detail"
    }
    Remove-Item $Measurement.StopPath -Force -ErrorAction SilentlyContinue
}

function Export-BenchmarkPrometheus {
    param(
        [string]$ResultDirectory,
        [hashtable]$Environment,
        [double]$StartEpoch,
        [double]$EndEpoch,
        [string]$ApiService,
        [ValidateSet("pilot", "official")]
        [string]$RunMode = "pilot",
        [double]$MinimumCadvisorCoveragePercent = 90
    )
    $prometheusPort = Get-BenchmarkValue $Environment "PROMETHEUS_PORT" "9090"
    $prometheusUrl = "http://127.0.0.1:$prometheusPort"
    $startArgument = $StartEpoch.ToString("R", [Globalization.CultureInfo]::InvariantCulture)
    $endArgument = $EndEpoch.ToString("R", [Globalization.CultureInfo]::InvariantCulture)
    Invoke-WebRequest -UseBasicParsing -Uri "$prometheusUrl/-/ready" -TimeoutSec 5 | Out-Null
    $arguments = @(
        (Join-Path $script:BenchmarkRoot "scripts/export_prometheus_data.py"),
        "--url", $prometheusUrl,
        "--output", (Join-Path $ResultDirectory "prometheus_series.json"),
        "--start", $startArgument,
        "--end", $endArgument,
        "--step", "5",
        "--require-postgres",
        "--minimum-cadvisor-coverage-percent", $MinimumCadvisorCoveragePercent.ToString("R", [Globalization.CultureInfo]::InvariantCulture),
        "--component", "api=$ApiService,tcc_benchmark_$($ApiService.Replace('-', '_'))",
        "--component", "postgresql=postgres,tcc_benchmark_postgres",
        "--component", "locust=locust,tcc_benchmark_locust"
    )
    if ($RunMode -eq "official") { $arguments += "--require-cadvisor" }
    Invoke-BenchmarkPython $arguments
}
