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

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose falhou: $($Arguments -join ' ')"
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
        [string]$CsvPrefix
    )

    Invoke-BenchmarkCompose @(
        "--profile", "load", "run", "--rm",
        "-e", "SCENARIO=$Scenario",
        "-e", "PAYLOAD_DIR=/mnt/payloads",
        "locust", "-f", "locustfile.py", "--headless",
        "-u", "$Users", "-r", "$SpawnRate", "-t", $Duration,
        "--host", $HostUrl, "--csv", $CsvPrefix, "--only-summary"
    )
}

function Get-LanguageMetadata {
    param([string]$Language)

    switch ($Language) {
        "python" { return @{ Version = "Python 3.12.14"; Driver = "psycopg 3.2.3"; Framework = "FastAPI 0.115.6 + Uvicorn 0.34.0"; Pool = "psycopg_pool 3.2.4" } }
        "node" { return @{ Version = "Node.js 22.23.2"; Driver = "pg 8.13.1"; Framework = "Express 4.22.2"; Pool = "pg.Pool: min nao preabre conexoes" } }
        "java" { return @{ Version = "Java Temurin 21.0.11+10 LTS"; Driver = "PostgreSQL JDBC 42.7.4"; Framework = "JDK HttpServer + Jackson 2.17.2"; Pool = "HikariCP 5.1.0" } }
        "go" { return @{ Version = "Go 1.23.12"; Driver = "lib/pq 1.10.9"; Framework = "net/http"; Pool = "database/sql nao oferece timeout por aquisicao; valor aplicado ao ping inicial" } }
        "dotnet" { return @{ Version = ".NET 8.0.30"; Driver = "Npgsql 8.0.5"; Framework = "ASP.NET Core Minimal API"; Pool = "Pooling nativo do Npgsql" } }
        default { throw "Linguagem invalida: $Language" }
    }
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
    param([string]$ResultDirectory, [double]$IntervalSeconds = 2)
    New-Item -ItemType Directory -Force $ResultDirectory | Out-Null
    $python = Get-BenchmarkPythonCommand
    $scriptPath = Join-Path $script:BenchmarkRoot "scripts/collect_docker_stats.py"
    $outputPath = Join-Path $ResultDirectory "docker_stats_raw.csv"
    $stopPath = Join-Path $ResultDirectory ".stop_docker_stats"
    $stdoutPath = Join-Path $ResultDirectory "docker_stats_collector.log"
    $stderrPath = Join-Path $ResultDirectory "docker_stats_collector.error.log"
    Remove-Item $stopPath, $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    $arguments = @($python.Prefix) + @($scriptPath, "--output", $outputPath, "--stop-file", $stopPath, "--interval", "$IntervalSeconds")
    $quotedArguments = $arguments | ForEach-Object { '"' + $_.Replace('"', '\"') + '"' }
    $process = Start-Process -FilePath $python.FilePath -ArgumentList $quotedArguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    return [pscustomobject]@{
        Process = $process
        StopPath = $stopPath
        SummaryPath = (Join-Path $ResultDirectory "docker_stats_summary.csv")
        ErrorPath = $stderrPath
        StartEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
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
    param([string]$ResultDirectory, [hashtable]$Environment, [long]$StartEpoch, [long]$EndEpoch)
    $prometheusPort = Get-BenchmarkValue $Environment "PROMETHEUS_PORT" "9090"
    $prometheusUrl = "http://127.0.0.1:$prometheusPort"
    Invoke-WebRequest -UseBasicParsing -Uri "$prometheusUrl/-/ready" -TimeoutSec 5 | Out-Null
    Invoke-BenchmarkPython @(
        (Join-Path $script:BenchmarkRoot "scripts/export_prometheus_data.py"),
        "--url", $prometheusUrl,
        "--output", (Join-Path $ResultDirectory "prometheus_series.json"),
        "--start", "$StartEpoch",
        "--end", "$EndEpoch",
        "--step", "5"
    )
}
