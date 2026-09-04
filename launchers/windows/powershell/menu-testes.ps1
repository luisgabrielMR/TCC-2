param(
    [string]$Action = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $Root
. (Join-Path $PSScriptRoot "benchmark-common.ps1")

function Read-EnvFile {
    $map = @{}
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path $envPath)) {
        $envPath = Join-Path $Root ".env.example"
    }
    if (Test-Path $envPath) {
        Get-Content $envPath | ForEach-Object {
            if ($_ -match '^\s*#') { return }
            if ($_ -match '^\s*$') { return }
            if ($_ -match '^\s*([^=]+)=(.*)$') {
                $map[$matches[1].Trim()] = $matches[2].Trim()
            }
        }
    }
    return $map
}

$EnvMap = Read-EnvFile

function Get-EnvValue([string]$Name, [string]$Default) {
    if ($EnvMap.ContainsKey($Name)) { return $EnvMap[$Name] }
    return $Default
}

function Invoke-PythonScript([string]$Script) {
    Invoke-BenchmarkPython @($Script)
}

function Wait-Postgres {
    $user = Get-EnvValue "POSTGRES_USER" "benchmark_user"
    $db = Get-EnvValue "POSTGRES_DB" "benchmark_db"
    Write-Host "Aguardando PostgreSQL..."
    for ($i = 0; $i -lt 60; $i++) {
        docker compose exec -T postgres pg_isready -U $user -d $db *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "PostgreSQL pronto."
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "PostgreSQL nao ficou pronto dentro do tempo esperado."
}

function Invoke-Postgres {
    docker compose up -d postgres
}

function Invoke-PrepareDatabase {
    $user = Get-EnvValue "POSTGRES_USER" "benchmark_user"
    $db = Get-EnvValue "POSTGRES_DB" "benchmark_db"
    Invoke-Postgres
    Wait-Postgres
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/init/001_schema.sql
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/init/002_seed_base_data.sql
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/init/003_indexes.sql
}

function Invoke-ValidateDatabase {
    $user = Get-EnvValue "POSTGRES_USER" "benchmark_user"
    $db = Get-EnvValue "POSTGRES_DB" "benchmark_db"
    Invoke-Postgres
    Wait-Postgres
    docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U $user -d $db -f /benchmark/database/scripts/validate_database.sql
}

function Invoke-Warmup {
    $environment = Get-BenchmarkEnvironment
    $hostUrl = Get-BenchmarkValue $environment "LOCUST_HOST" "http://host.docker.internal:8000"
    $seconds = [int](Get-BenchmarkValue $environment "WARMUP_DURATION_SECONDS" "300")
    $windowSeconds = [int](Get-BenchmarkValue $environment "WARMUP_STABILITY_WINDOW_SECONDS" "45")
    $maxDrift = [double](Get-BenchmarkValue $environment "WARMUP_MAX_RPS_DRIFT_PERCENT" "10")
    $users = [int](Get-BenchmarkValue $environment "LOCUST_USERS" "50")
    $spawnRate = [int](Get-BenchmarkValue $environment "LOCUST_SPAWN_RATE" "10")
    $waitSeconds = Get-BenchmarkValue $environment "LOCUST_WAIT_SECONDS" "0.1"
    $locustProcesses = [int](Get-BenchmarkValue $environment "LOCUST_PROCESSES" "4")
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Invoke-BenchmarkWarmup `
        -Environment $environment -Scenario "mixed" -Users $users -SpawnRate $spawnRate `
        -InitialDurationSeconds $seconds `
        -StabilityWindowSeconds $windowSeconds -MaxRpsDriftPercent $maxDrift `
        -WaitSeconds $waitSeconds -Processes $locustProcesses `
        -HostUrl $hostUrl -ResultRelative "results/raw/warmup/manual_$stamp" | Out-Host
}

function Invoke-RunAllProfile(
    [string]$Profile,
    [int]$OrderOffset = 0,
    [string]$SequenceId = "manual",
    [ValidateSet("pilot", "official")][string]$RunMode = "pilot"
) {
    $languages = @("python", "node", "java", "go", "dotnet")
    for ($index = 0; $index -lt $languages.Count; $index++) {
        $language = $languages[($index + $OrderOffset) % $languages.Count]
        $env:BENCHMARK_SEQUENCE_ID = $SequenceId
        $env:BENCHMARK_ORDER_POSITION = "$($index + 1)"
        & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" `
            -Language $language -Scenario mixed -RunNumber 0 -LoadProfile $Profile -RunMode $RunMode
        if ($LASTEXITCODE -ne 0) { throw "A rodada $language falhou." }
    }
}

function Invoke-RunAll {
    Invoke-RunAllProfile "fixed_200"
}

function Get-ResultScenarioName([string]$Profile) {
    # run_one_language.sh grava perfis de capacidade, saturacao e taxa fixa em
    # "mixed_<perfil>"; so controlled_50 e environment usam "mixed" puro.
    if ($Profile -like "capacity_*" -or $Profile -like "saturation_*" -or $Profile -like "fixed_*") {
        return "mixed_$Profile"
    }
    return "mixed"
}

function Get-OfficialCampaignIdentity($Environment) {
    $methodologyVersion = [int](Get-BenchmarkValue $Environment "METHODOLOGY_VERSION" "8")
    $commitSha = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $commitSha) { throw "Nao foi possivel identificar o commit atual." }
    $calibrationRelative = Get-BenchmarkValue $Environment "LOAD_GENERATOR_CALIBRATION_FILE" "results/summaries/load-generator-calibration.json"
    $calibrationPath = Join-Path $Root $calibrationRelative
    $calibrationHash = if (Test-Path $calibrationPath) {
        (Get-FileHash -Algorithm SHA256 $calibrationPath).Hash.ToLowerInvariant()
    } else { "no_calibration" }
    $commitToken = $commitSha.Substring(0, [Math]::Min(12, $commitSha.Length))
    $calibrationToken = $calibrationHash.Substring(0, [Math]::Min(12, $calibrationHash.Length))
    return [pscustomobject]@{
        methodology_version = $methodologyVersion
        commit_sha = $commitSha
        fingerprint = "m${methodologyVersion}_${commitToken}_${calibrationToken}"
    }
}

function Get-OfficialLanguagesForSequence(
    [string]$SequenceId,
    [string]$Profile,
    [int]$MethodologyVersion,
    [string]$CommitSha
) {
    $completed = @()
    $resultScenario = Get-ResultScenarioName $Profile
    foreach ($language in @("python", "node", "java", "go", "dotnet")) {
        $scenarioDirectory = Join-Path $Root "results/raw/$language/$resultScenario"
        $metadataFiles = @(Get-ChildItem $scenarioDirectory -Directory -Filter "run_*" -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "metadata.json" } |
            Where-Object { Test-Path $_ })
        foreach ($metadataPath in $metadataFiles) {
            try {
                $metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
                if ($metadata.result_classification -eq "official" -and
                    $metadata.execution_order.sequence_id -eq $SequenceId -and
                    $metadata.load_profile -eq $Profile -and
                    [int]$metadata.methodology_version -eq $MethodologyVersion -and
                    $metadata.commit_sha -eq $CommitSha) {
                    $completed += $language
                    break
                }
            }
            catch {
                Write-Warning "Metadata ignorado por estar invalido: $metadataPath"
            }
        }
    }
    return @($completed)
}

function Get-NextOfficialRoundPlan {
    $environment = Get-BenchmarkEnvironment
    $officialProfile = Get-BenchmarkValue $environment "OFFICIAL_PROFILE" "fixed_200"
    $totalRounds = [int](Get-BenchmarkValue $environment "OFFICIAL_ROUNDS" "5")
    if ($totalRounds -lt 1) { throw "OFFICIAL_ROUNDS deve ser maior que zero." }
    $campaign = Get-OfficialCampaignIdentity $environment

    $languages = @("python", "node", "java", "go", "dotnet")
    for ($round = 1; $round -le $totalRounds; $round++) {
        $sequenceId = "${officialProfile}_$($campaign.fingerprint)_official_round_${round}_of_${totalRounds}"
        $completed = @(Get-OfficialLanguagesForSequence `
            $sequenceId $officialProfile $campaign.methodology_version $campaign.commit_sha)
        if ($completed.Count -lt $languages.Count) {
            $offset = ($round - 1) % $languages.Count
            $ordered = for ($index = 0; $index -lt $languages.Count; $index++) {
                $languages[($index + $offset) % $languages.Count]
            }
            return [pscustomobject]@{
                all_complete = $false
                load_profile = $officialProfile
                round = $round
                total_rounds = $totalRounds
                sequence_id = $sequenceId
                campaign_fingerprint = $campaign.fingerprint
                ordered_languages = @($ordered)
                completed_languages = @($completed)
            }
        }
    }

    return [pscustomobject]@{
        all_complete = $true
        load_profile = $officialProfile
        round = $totalRounds
        total_rounds = $totalRounds
        sequence_id = ""
        campaign_fingerprint = $campaign.fingerprint
        ordered_languages = @()
        completed_languages = @($languages)
    }
}

function Show-OfficialStatus {
    $plan = Get-NextOfficialRoundPlan
    if ($plan.all_complete) {
        Write-Host "Rodadas oficiais: $($plan.total_rounds)/$($plan.total_rounds) completas." -ForegroundColor Green
        return
    }
    Write-Host "Proxima rodada oficial: $($plan.round)/$($plan.total_rounds)" -ForegroundColor Cyan
    Write-Host "Perfil: $($plan.load_profile)"
    Write-Host "Campanha: $($plan.campaign_fingerprint)"
    Write-Host "Concluidas nesta rodada: $($plan.completed_languages.Count)/5"
    Write-Host "Ordem: $($plan.ordered_languages -join ' -> ')"
}

function Invoke-NextOfficialRound {
    $plan = Get-NextOfficialRoundPlan
    if ($plan.all_complete) {
        Write-Host "As $($plan.total_rounds) rodadas oficiais ja estao completas." -ForegroundColor Green
        return
    }

    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop nao esta ativo. Abra-o manualmente e aguarde Docker Engine running."
    }

    $preflightPath = Join-Path $Root "results/summaries/preflight-official-next.json"
    Invoke-BenchmarkPython @(
        (Join-Path $Root "scripts/preflight.py"),
        "--mode", "official", "--load-profile", $plan.load_profile, "--output", $preflightPath
    )

    Write-Host ""
    Show-OfficialStatus
    Write-Host "Cada rodada executa as cinco APIs, com warmup e medicao separados."
    Write-Host "Tempo estimado: aproximadamente 55 a 75 minutos."
    $confirmation = Read-Host "Digite SIM para iniciar esta rodada oficial"
    if ($confirmation.Trim().ToUpperInvariant() -ne "SIM") {
        Write-Host "Execucao cancelada."
        return
    }

    try {
        for ($index = 0; $index -lt $plan.ordered_languages.Count; $index++) {
            $language = $plan.ordered_languages[$index]
            if ($plan.completed_languages -contains $language) {
                Write-Host "Ignorando ${language}: ja concluida nesta rodada oficial."
                continue
            }
            $env:BENCHMARK_SEQUENCE_ID = $plan.sequence_id
            $env:BENCHMARK_CAMPAIGN_FINGERPRINT = $plan.campaign_fingerprint
            $env:BENCHMARK_ORDER_POSITION = "$($index + 1)"
            Write-Host "Iniciando $language, posicao $($index + 1)/5, rodada oficial $($plan.round)/$($plan.total_rounds)."
            & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" `
                -Language $language -Scenario mixed -RunNumber 0 -LoadProfile $plan.load_profile -RunMode official
            if ($LASTEXITCODE -ne 0) { throw "A execucao oficial de $language falhou." }
        }
    }
    finally {
        Remove-Item Env:BENCHMARK_SEQUENCE_ID, Env:BENCHMARK_CAMPAIGN_FINGERPRINT, Env:BENCHMARK_ORDER_POSITION -ErrorAction SilentlyContinue
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/gerar-graficos.ps1" -NoOpen
    if ($LASTEXITCODE -ne 0) { throw "A atualizacao dos resultados falhou." }
    Write-Host "Rodada oficial $($plan.round)/$($plan.total_rounds) concluida." -ForegroundColor Green
}

function Invoke-Summarize {
    Invoke-PythonScript "scripts/summarize_results.py"
}

function Invoke-Charts {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/gerar-graficos.ps1"
    if ($LASTEXITCODE -ne 0) { throw "A geracao dos graficos falhou." }
}

function Invoke-Grafana {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/abrir-grafana.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Nao foi possivel abrir o Grafana." }
}

function Invoke-Action([string]$SelectedAction) {
    switch ($SelectedAction) {
        "postgres" { Invoke-Postgres }
        "prepare-db" { Invoke-PrepareDatabase }
        "payloads" { Invoke-PythonScript "database/scripts/generate_test_payloads.py" }
        "validate-db" { Invoke-ValidateDatabase }
        "test-payloads" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/testar-payloads.ps1" -BaseUrl "http://127.0.0.1:8000" }
        "warmup" { Invoke-Warmup }
        "python" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language python -Scenario mixed -RunNumber 0 -LoadProfile fixed_200 -RunMode pilot }
        "node" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language node -Scenario mixed -RunNumber 0 -LoadProfile fixed_200 -RunMode pilot }
        "java" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language java -Scenario mixed -RunNumber 0 -LoadProfile fixed_200 -RunMode pilot }
        "go" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language go -Scenario mixed -RunNumber 0 -LoadProfile fixed_200 -RunMode pilot }
        "dotnet" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/rodar-linguagem.ps1" -Language dotnet -Scenario mixed -RunNumber 0 -LoadProfile fixed_200 -RunMode pilot }
        "all" { Invoke-RunAll }
        "capacity-100" { Invoke-RunAllProfile "capacity_100" }
        "capacity-200" { Invoke-RunAllProfile "capacity_200" }
        "official-status" { Show-OfficialStatus }
        "calibrate" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/calibrar-gerador.ps1" }
        "official-next" { Invoke-NextOfficialRound }
        "summarize" { Invoke-Summarize }
        "verify" { & powershell -NoProfile -ExecutionPolicy Bypass -File "launchers/windows/powershell/verificar-projeto.ps1" }
        "charts" { Invoke-Charts }
        "grafana" { Invoke-Grafana }
        "advanced" { Show-AdvancedMenu }
        default { throw "Acao desconhecida: $SelectedAction" }
    }
}

function Show-AdvancedMenu {
    while ($true) {
        Clear-Host
        Write-Host "Menu avancado - TCC PostgreSQL Backend Benchmark"
        Write-Host ""
        Write-Host "1  Subir PostgreSQL"
        Write-Host "2  Preparar banco"
        Write-Host "3  Gerar payloads"
        Write-Host "4  Validar banco"
        Write-Host "5  Testar payloads da API ativa"
        Write-Host "6  Rodar warmup da API ativa"
        Write-Host "7  Piloto Python mixed"
        Write-Host "8  Piloto Node.js mixed"
        Write-Host "9  Piloto Java mixed"
        Write-Host "10 Piloto Go mixed"
        Write-Host "11 Piloto .NET mixed"
        Write-Host "12 Piloto de todas sequencialmente"
        Write-Host "13 Resumir resultados oficiais"
        Write-Host "14 Verificar projeto completo"
        Write-Host "15 Gerar graficos e abrir painel"
        Write-Host "16 Piloto de capacidade: 100 usuarios"
        Write-Host "17 Piloto de capacidade: 200 usuarios"
        Write-Host "18 Calibrar gerador de carga"
        Write-Host "19 Proxima rodada oficial (perfil de taxa fixa)"
        Write-Host "20 Abrir Grafana completo"
        Write-Host "0  Voltar"
        Write-Host ""
        $choice = Read-Host "Escolha"
        switch ($choice) {
            "1" { Invoke-Action "postgres"; Read-Host "Enter para continuar" }
            "2" { Invoke-Action "prepare-db"; Read-Host "Enter para continuar" }
            "3" { Invoke-Action "payloads"; Read-Host "Enter para continuar" }
            "4" { Invoke-Action "validate-db"; Read-Host "Enter para continuar" }
            "5" { Invoke-Action "test-payloads"; Read-Host "Enter para continuar" }
            "6" { Invoke-Action "warmup"; Read-Host "Enter para continuar" }
            "7" { Invoke-Action "python"; Read-Host "Enter para continuar" }
            "8" { Invoke-Action "node"; Read-Host "Enter para continuar" }
            "9" { Invoke-Action "java"; Read-Host "Enter para continuar" }
            "10" { Invoke-Action "go"; Read-Host "Enter para continuar" }
            "11" { Invoke-Action "dotnet"; Read-Host "Enter para continuar" }
            "12" { Invoke-Action "all"; Read-Host "Enter para continuar" }
            "13" { Invoke-Action "summarize"; Read-Host "Enter para continuar" }
            "14" { Invoke-Action "verify"; Read-Host "Enter para continuar" }
            "15" { Invoke-Action "charts"; Read-Host "Enter para continuar" }
            "16" { Invoke-Action "capacity-100"; Read-Host "Enter para continuar" }
            "17" { Invoke-Action "capacity-200"; Read-Host "Enter para continuar" }
            "18" { Invoke-Action "calibrate"; Read-Host "Enter para continuar" }
            "19" { Invoke-Action "official-next"; Read-Host "Enter para continuar" }
            "20" { Invoke-Action "grafana"; Read-Host "Enter para continuar" }
            "0" { break }
            default { Write-Host "Opcao invalida"; Start-Sleep -Seconds 1 }
        }
    }
}

function Show-SimpleMenu {
    while ($true) {
        Clear-Host
        Write-Host "TCC Benchmark - inicio rapido"
        Write-Host ""
        Show-OfficialStatus
        Write-Host ""
        Write-Host "1  Verificar projeto"
        Write-Host "2  Calibrar gerador de carga"
        Write-Host "3  Executar proxima rodada oficial"
        Write-Host "4  Abrir Grafana"
        Write-Host "5  Menu avancado"
        Write-Host "0  Sair"
        Write-Host ""
        $choice = Read-Host "Escolha"
        switch ($choice) {
            "1" { Invoke-Action "verify"; Read-Host "Enter para continuar" }
            "2" { Invoke-Action "calibrate"; Read-Host "Enter para continuar" }
            "3" { Invoke-Action "official-next"; Read-Host "Enter para continuar" }
            "4" { Invoke-Action "grafana"; Read-Host "Enter para continuar" }
            "5" { Show-AdvancedMenu }
            "0" { break }
            default { Write-Host "Opcao invalida"; Start-Sleep -Seconds 1 }
        }
    }
}

if ($Action) {
    Invoke-Action $Action
    exit $LASTEXITCODE
}

Show-SimpleMenu
