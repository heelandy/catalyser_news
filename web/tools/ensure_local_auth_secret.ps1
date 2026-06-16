$ErrorActionPreference = "Stop"

$environmentPath = Join-Path $PSScriptRoot "..\.env.local"
if (-not (Test-Path -LiteralPath $environmentPath)) {
    throw "Missing web/.env.local. Create it from .env.example first."
}

$content = Get-Content -LiteralPath $environmentPath
$existing = $content | Where-Object { $_ -match '^AUTH_SECRET=(.+)$' } | Select-Object -First 1
if ($existing) {
    Write-Output "AUTH_SECRET is already configured."
    exit 0
}

$secretBytes = New-Object byte[] 48
$random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($secretBytes)
$random.Dispose()
$secret = [Convert]::ToBase64String($secretBytes)
$updated = $content | ForEach-Object {
    if ($_ -match '^AUTH_SECRET=') {
        "AUTH_SECRET=$secret"
    } else {
        $_
    }
}

Set-Content -LiteralPath $environmentPath -Value $updated -Encoding utf8
Write-Output "Generated a local AUTH_SECRET without printing it."
