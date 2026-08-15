param(
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $Root

function First-Line([string]$Path) {
    return (Get-Content $Path -TotalCount 1).Trim()
}

function Invoke-ApiRequest {
    param(
        [string]$Name,
        [int]$ExpectedStatus,
        [string]$Method,
        [string]$Url,
        [string]$BodyPath = ""
    )

    $temp = New-TemporaryFile
    $args = @("-sS", "-o", $temp.FullName, "-w", "%{http_code}", "-X", $Method, $Url)
    if ($BodyPath) {
        $args += @("-H", "Content-Type: application/json", "--data", "@$BodyPath")
    }
    $status = & curl.exe @args
    Write-Host "[$status] $Name"
    if ([int]$status -ne $ExpectedStatus) {
        Write-Host "Esperado HTTP $ExpectedStatus, recebido HTTP $status"
        Get-Content $temp.FullName
        Remove-Item $temp.FullName -Force
        throw "Falha em $Name"
    }
    Remove-Item $temp.FullName -Force
}

$customerId = First-Line "common/payloads/ids_customers.jsonl"
$categoryId = First-Line "common/payloads/ids_categories.jsonl"
$orderId = First-Line "common/payloads/ids_orders.jsonl"

$customerCreate = New-TemporaryFile
$customerUpdate = New-TemporaryFile
$orderCreate = New-TemporaryFile
Get-Content "common/payloads/customers_create.jsonl" -TotalCount 1 | Set-Content $customerCreate.FullName
Get-Content "common/payloads/customers_update.jsonl" -TotalCount 1 | Set-Content $customerUpdate.FullName
Get-Content "common/payloads/orders_create.jsonl" -TotalCount 1 | Set-Content $orderCreate.FullName

try {
    Invoke-ApiRequest "GET /health" 200 "GET" "$BaseUrl/health"
    Invoke-ApiRequest "GET /customers/{id}" 200 "GET" "$BaseUrl/customers/$customerId"
    Invoke-ApiRequest "GET /customers?page=1&pageSize=50" 200 "GET" "$BaseUrl/customers?page=1&pageSize=50"
    Invoke-ApiRequest "POST /customers" 201 "POST" "$BaseUrl/customers" $customerCreate.FullName
    Invoke-ApiRequest "PUT /customers/{id}" 200 "PUT" "$BaseUrl/customers/$customerId" $customerUpdate.FullName
    Invoke-ApiRequest "GET /products?categoryId={id}" 200 "GET" "$BaseUrl/products?categoryId=$categoryId"
    Invoke-ApiRequest "POST /orders" 201 "POST" "$BaseUrl/orders" $orderCreate.FullName
    Invoke-ApiRequest "GET /orders/{id}" 200 "GET" "$BaseUrl/orders/$orderId"
    Write-Host "Validacao manual de payloads concluida com sucesso."
}
finally {
    Remove-Item $customerCreate.FullName, $customerUpdate.FullName, $orderCreate.FullName -Force -ErrorAction SilentlyContinue
}
