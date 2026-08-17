[CmdletBinding()]
param(
    [ValidateSet('configure', 'verify')]
    [string]$Target = 'configure'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-ProcessSecret {
    param([Parameter(Mandatory)][string]$Prompt)

    $secureValue = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$adminCidrs = Read-Host -Prompt 'Approved administrative IPv4 CIDR(s), comma-separated'
if ([string]::IsNullOrWhiteSpace($adminCidrs)) {
    throw 'At least one explicitly approved administrative CIDR is required.'
}

$clientId = $null
$clientSecret = $null
$exitCode = 1
try {
    [Environment]::SetEnvironmentVariable('PHASE3_ADMIN_CIDRS', $adminCidrs, 'Process')
    if ($Target -eq 'configure') {
        $clientId = Read-ProcessSecret -Prompt 'Temporary Verda client ID (input hidden)'
        $clientSecret = Read-ProcessSecret -Prompt 'Temporary Verda client secret (input hidden)'
        if ([string]::IsNullOrWhiteSpace($clientId) -or [string]::IsNullOrWhiteSpace($clientSecret)) {
            throw 'Both process-only Verda credential values are required for the read-only cloud preflight.'
        }
        [Environment]::SetEnvironmentVariable('VERDA_CLIENT_ID', $clientId, 'Process')
        [Environment]::SetEnvironmentVariable('VERDA_CLIENT_SECRET', $clientSecret, 'Process')
    }

    Push-Location $repoRoot
    try {
        & make $Target 'CLUSTER=management'
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in @('VERDA_CLIENT_ID', 'VERDA_CLIENT_SECRET', 'PHASE3_ADMIN_CIDRS')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $clientId = $null
    $clientSecret = $null
    $adminCidrs = $null
}

exit $exitCode
