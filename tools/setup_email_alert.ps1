# Configures personal SMTP email alerts without writing the password to disk.
param(
    [ValidateSet("gmail", "outlook", "custom")]
    [string]$Provider = "gmail",
    [string]$Email = "",
    [string]$Recipient = "",
    [string]$Sender = "",
    [string]$SmtpHost = "",
    [int]$SmtpPort = 0,
    [string]$SmtpUser = "",
    [string]$PasswordEnv = "MACRO_ALERT_SMTP_PASSWORD",
    [switch]$NoStartTls,
    [switch]$SendTest
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$configPath = Join-Path $root "macro_alert_notify_config.json"

function Set-ObjectProperty {
    param($Object, [string]$Name, $Value)
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Object.$Name = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

if (-not $Email) {
    $Email = Read-Host "Personal email address"
}
if (-not $Recipient) {
    $Recipient = $Email
}
if (-not $Sender) {
    $Sender = $Email
}
if (-not $SmtpUser) {
    $SmtpUser = $Email
}

switch ($Provider) {
    "gmail" {
        if (-not $SmtpHost) { $SmtpHost = "smtp.gmail.com" }
        if ($SmtpPort -le 0) { $SmtpPort = 587 }
        Write-Output "Gmail requires 2-Step Verification and a 16-character App Password. Do not use the normal account password."
    }
    "outlook" {
        if (-not $SmtpHost) { $SmtpHost = "smtp-mail.outlook.com" }
        if ($SmtpPort -le 0) { $SmtpPort = 587 }
        Write-Output "Outlook may require an app password or SMTP AUTH enabled on the account."
    }
    "custom" {
        if (-not $SmtpHost) { $SmtpHost = Read-Host "SMTP host" }
        if ($SmtpPort -le 0) { $SmtpPort = [int](Read-Host "SMTP port (usually 587)") }
    }
}

$securePassword = Read-Host "SMTP app password (stored in your Windows user environment)" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if (-not $plainPassword) {
        throw "An SMTP app password is required."
    }
    [Environment]::SetEnvironmentVariable($PasswordEnv, $plainPassword, "User")
    Set-Item -LiteralPath "Env:$PasswordEnv" -Value $plainPassword
} finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

if (Test-Path $configPath) {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
} else {
    $config = [pscustomobject]@{}
}

$targets = @()
if ($config.PSObject.Properties.Name -contains "targets") {
    $targets = @($config.targets -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
foreach ($target in @("risk_lock", "popup", "email")) {
    if ($targets -notcontains $target) {
        $targets += $target
    }
}
Set-ObjectProperty $config "targets" ($targets -join ",")
# The dashboard popup accepts info, medium, and high alerts. Use the same
# threshold so every automatic popup signal is also eligible for email.
Set-ObjectProperty $config "min_severity" "info"

$emailConfig = [pscustomobject]@{
    to = $Recipient
    from = $Sender
    subject = "NQ Macro Catalyst alert"
}
$smtpConfig = [pscustomobject]@{
    host = $SmtpHost
    port = $SmtpPort
    timeout = 20
    user = $SmtpUser
    password_env = $PasswordEnv
    starttls = (-not $NoStartTls)
}
Set-ObjectProperty $config "email" $emailConfig
Set-ObjectProperty $config "smtp" $smtpConfig

$configJson = $config | ConvertTo-Json -Depth 8
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, $configJson, $utf8NoBom)
Write-Output "Updated $configPath"
Write-Output "Stored $PasswordEnv in the Windows user environment."

if ($SendTest) {
    Push-Location $root
    try {
        & python .\macro_alert_notify.py --config .\macro_alert_notify_config.json --targets email --test-email --test-recipient $Recipient
        if ($LASTEXITCODE -ne 0) {
            throw "Email test failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

Write-Output "Restart the dashboard server with STOP.bat and START.bat so it reads the new user environment."
