[CmdletBinding()]
param(
    [switch]$QueryAccount,
    [switch]$ConfirmReadOnly,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))

function Resolve-SafeWorkspaceOutput {
    param([Parameter(Mandatory)][string]$Path)

    $candidate = if ([System.IO.Path]::IsPathRooted($Path)) {
        [System.IO.Path]::GetFullPath($Path)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $Path))
    }

    $workspacePrefix = $workspaceRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Output path must remain inside the workspace: $candidate"
    }

    return $candidate
}

function Protect-SensitiveText {
    param([Parameter(Mandatory)][string]$Text)

    $protected = $Text
    $protected = $protected -replace '(?i)("(?:client[_-]?secret|secret[_-]?key|access[_-]?key|password|token|authorization)"\s*:\s*)"[^"]*"', '$1"[REDACTED]"'
    $protected = $protected -replace '(?i)((?:client[_-]?secret|secret[_-]?key|access[_-]?key|password|token|authorization)\s*[=:]\s*)[^\s,;]+', '$1[REDACTED]'
    $protected = $protected -replace '(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+=*', '$1[REDACTED]'
    return $protected
}

function Invoke-VerdaReadOnly {
    param(
        [Parameter(Mandatory)][System.Management.Automation.CommandInfo]$Command,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $raw = & $Command.Source @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $text = Protect-SensitiveText -Text (($raw | Out-String).Trim())
    $payload = $text

    if ($text) {
        try {
            $payload = $text | ConvertFrom-Json
        }
        catch {
            # Preserve only redacted text when a CLI response is not JSON.
        }
    }

    return [PSCustomObject]@{
        name = $Name
        readOnly = $true
        exitCode = $exitCode
        succeeded = ($exitCode -eq 0)
        payload = $payload
    }
}

$verda = Get-Command verda -ErrorAction SilentlyContinue
$terraform = Get-Command terraform -ErrorAction SilentlyContinue
$tofu = Get-Command tofu -ErrorAction SilentlyContinue

$report = [ordered]@{
    schemaVersion = '1.0.0'
    collectedAtUtc = [DateTime]::UtcNow.ToString('o')
    mode = if ($QueryAccount) { 'authenticated-read-only' } else { 'local-preflight' }
    safeguards = [ordered]@{
        cloudMutationAttempted = $false
        debugLoggingEnabled = $false
        secretValuesPrinted = $false
    }
    credentialPresence = [ordered]@{
        environmentClientIdSet = -not [string]::IsNullOrWhiteSpace($env:VERDA_CLIENT_ID)
        environmentClientSecretSet = -not [string]::IsNullOrWhiteSpace($env:VERDA_CLIENT_SECRET)
        valuesCaptured = $false
    }
    tooling = [ordered]@{
        verdaCliAvailable = [bool]$verda
        terraformAvailable = [bool]$terraform
        openTofuAvailable = [bool]$tofu
    }
    queries = @()
}

if ($QueryAccount) {
    if (-not $ConfirmReadOnly) {
        throw 'Account queries require -ConfirmReadOnly. The script contains list/status/doctor commands only.'
    }
    if (-not $verda) {
        throw 'The Verda CLI is not installed or not available on PATH.'
    }

    $querySpecs = @(
        [PSCustomObject]@{ name = 'doctor'; arguments = [string[]]@('--agent', 'doctor') },
        [PSCustomObject]@{ name = 'auth-status'; arguments = [string[]]@('--agent', 'auth', 'show') },
        [PSCustomObject]@{ name = 'locations'; arguments = [string[]]@('--agent', 'locations') },
        [PSCustomObject]@{ name = 'cpu-instance-types'; arguments = [string[]]@('--agent', 'instance-types', '--cpu') },
        [PSCustomObject]@{ name = 'images'; arguments = [string[]]@('--agent', 'images') },
        [PSCustomObject]@{ name = 'availability-fin-01'; arguments = [string[]]@('--agent', 'availability', '--location', 'FIN-01') },
        [PSCustomObject]@{ name = 'availability-fin-02'; arguments = [string[]]@('--agent', 'availability', '--location', 'FIN-02') },
        [PSCustomObject]@{ name = 'availability-fin-03'; arguments = [string[]]@('--agent', 'availability', '--location', 'FIN-03') },
        [PSCustomObject]@{ name = 'volumes'; arguments = [string[]]@('--agent', 'volume', 'list') },
        [PSCustomObject]@{ name = 'account-status'; arguments = [string[]]@('--agent', 'status') },
        [PSCustomObject]@{ name = 'running-cost'; arguments = [string[]]@('--agent', 'cost', 'running') },
        [PSCustomObject]@{ name = 'account-balance'; arguments = [string[]]@('--agent', 'cost', 'balance') },
        [PSCustomObject]@{ name = 'object-storage-status'; arguments = [string[]]@('--agent', 'object-storage', 'show') },
        [PSCustomObject]@{ name = 'registry-status'; arguments = [string[]]@('--agent', 'registry', 'show') }
    )

    $queries = foreach ($querySpec in $querySpecs) {
        Invoke-VerdaReadOnly -Command $verda -Name $querySpec.name -Arguments $querySpec.arguments
    }
    $report.queries = @($queries)
}

$json = [PSCustomObject]$report | ConvertTo-Json -Depth 30

if ($OutputPath) {
    $safeOutput = Resolve-SafeWorkspaceOutput -Path $OutputPath
    $parent = Split-Path -Parent $safeOutput
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Set-Content -LiteralPath $safeOutput -Value $json -Encoding utf8NoBOM
    Write-Output "Wrote redacted discovery output to $safeOutput"
}
else {
    Write-Output $json
}

if ($QueryAccount -and (@($report.queries | Where-Object { -not $_.succeeded }).Count -gt 0)) {
    exit 3
}
