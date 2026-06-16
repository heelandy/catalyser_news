[CmdletBinding()]
param(
    [string]$PostgresVersion = "17",
    [string]$DatabaseName = "market_catalyst",
    [string]$DatabaseUser = "market_catalyst_app",
    [int]$Port = 5433,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $projectRoot "web"
$envExample = Join-Path $webRoot ".env.example"
$envLocal = Join-Path $webRoot ".env.local"
$dataDirectory = Join-Path $webRoot ".postgres-data"
$postgresLog = Join-Path $dataDirectory "postgresql.log"

function New-SafePassword {
    param([int]$ByteCount = 24)

    $bytes = New-Object byte[] $ByteCount
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    return ([BitConverter]::ToString($bytes) -replace "-", "").ToLowerInvariant()
}

function Find-PostgresBin {
    $psql = Get-Command psql.exe -ErrorAction SilentlyContinue
    if ($psql -and $psql.Source -match "\\PostgreSQL\\\d+\\bin\\psql\.exe$") {
        return Split-Path -Parent $psql.Source
    }

    $postgresRoot = Join-Path $env:ProgramFiles "PostgreSQL"
    $candidates = Get-ChildItem -Path $postgresRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object {
            $candidate = Join-Path $_.FullName "bin\psql.exe"
            if (Test-Path -LiteralPath $candidate) {
                Get-Item -LiteralPath $candidate
            }
        }

    if ($candidates) {
        return Split-Path -Parent $candidates[0].FullName
    }

    return $null
}

function Set-DatabaseUrl {
    param([string]$Url)

    $lines = if (Test-Path -LiteralPath $envLocal) {
        Get-Content -LiteralPath $envLocal
    } else {
        Get-Content -LiteralPath $envExample
    }

    $updated = $false
    $result = foreach ($line in $lines) {
        if ($line -match "^DATABASE_URL=") {
            "DATABASE_URL=$Url"
            $updated = $true
        } else {
            $line
        }
    }

    if (-not $updated) {
        $result += "DATABASE_URL=$Url"
    }

    Set-Content -LiteralPath $envLocal -Value $result -Encoding utf8
}

function Get-ExistingDatabaseUrl {
    if (-not (Test-Path -LiteralPath $envLocal)) {
        return $null
    }

    $line = Get-Content -LiteralPath $envLocal |
        Where-Object { $_ -match "^DATABASE_URL=.+" } |
        Select-Object -First 1

    if ($line) {
        return $line.Substring("DATABASE_URL=".Length)
    }

    return $null
}

$postgresBin = Find-PostgresBin

if (-not $postgresBin) {
    if ($SkipInstall) {
        throw "PostgreSQL is not installed and -SkipInstall was supplied."
    }

    $winget = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\winget.exe"
    if (-not (Test-Path -LiteralPath $winget)) {
        throw "Windows Package Manager was not found."
    }

    & $winget install `
        --id "PostgreSQL.PostgreSQL.$PostgresVersion" `
        --exact `
        --silent `
        --accept-package-agreements `
        --accept-source-agreements

    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL installation failed with exit code $LASTEXITCODE."
    }

    $postgresBin = Find-PostgresBin
    if (-not $postgresBin) {
        throw "PostgreSQL installed, but its command-line tools were not found."
    }
}

$psql = Join-Path $postgresBin "psql.exe"
$initdb = Join-Path $postgresBin "initdb.exe"
$pgCtl = Join-Path $postgresBin "pg_ctl.exe"
$pgIsReady = Join-Path $postgresBin "pg_isready.exe"
$createdb = Join-Path $postgresBin "createdb.exe"

$existingUrl = Get-ExistingDatabaseUrl
if ($existingUrl) {
    $postgresConnectionUrl = $existingUrl.Split("?")[0]
    & $pgIsReady --dbname $postgresConnectionUrl --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Existing Market Catalyst PostgreSQL database is ready."
        return
    }
}

$appPassword = New-SafePassword

if (-not (Test-Path -LiteralPath (Join-Path $dataDirectory "PG_VERSION"))) {
    New-Item -ItemType Directory -Force -Path $dataDirectory | Out-Null
    $passwordFile = Join-Path $env:TEMP "market-catalyst-postgres-$PID.pw"
    try {
        Set-Content -LiteralPath $passwordFile -Value $appPassword -Encoding ascii
        & $initdb `
            --pgdata $dataDirectory `
            --username $DatabaseUser `
            --pwfile $passwordFile `
            --auth-host scram-sha-256 `
            --auth-local scram-sha-256 `
            --encoding UTF8 `
            --no-locale

        if ($LASTEXITCODE -ne 0) {
            throw "Failed to initialize the project-local PostgreSQL cluster."
        }
    } finally {
        Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
    }
} elseif (-not $existingUrl) {
    throw "The project-local PostgreSQL cluster exists, but web/.env.local has no DATABASE_URL."
}

& $pgCtl `
    --pgdata $dataDirectory `
    --log $postgresLog `
    --options "-p $Port" `
    start

if ($LASTEXITCODE -ne 0) {
    throw "Failed to start the project-local PostgreSQL cluster."
}

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    & $pgIsReady --host 127.0.0.1 --port $Port --quiet
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $ready) {
    throw "The project-local PostgreSQL cluster did not become ready."
}

$env:PGPASSWORD = $appPassword
try {
    $databaseExists = & $psql `
        --host 127.0.0.1 `
        --port $Port `
        --username $DatabaseUser `
        --dbname postgres `
        --tuples-only `
        --no-align `
        --command "SELECT 1 FROM pg_database WHERE datname = '$DatabaseName';"

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect the project-local PostgreSQL cluster."
    }

    if (($databaseExists | Out-String).Trim() -ne "1") {
        & $createdb `
            --host 127.0.0.1 `
            --port $Port `
            --username $DatabaseUser `
            --owner $DatabaseUser `
            $DatabaseName

        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the Market Catalyst development database."
        }
    }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

$databaseUrl = "postgresql://${DatabaseUser}:${appPassword}@127.0.0.1:${Port}/${DatabaseName}?schema=public"
Set-DatabaseUrl -Url $databaseUrl

Write-Host "Project-local PostgreSQL is ready."
Write-Host "Database: $DatabaseName"
Write-Host "Port: $Port"
Write-Host "Connection saved to web/.env.local (ignored by Git)."
