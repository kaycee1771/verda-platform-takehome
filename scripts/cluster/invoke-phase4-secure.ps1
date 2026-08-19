[CmdletBinding()]
param(
    [ValidateSet('bootstrap', 'verify')]
    [string]$Target = 'bootstrap'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-ProcessSecret {
    param([Parameter(Mandatory)][string]$Prompt, [switch]$Optional)
    $secureValue = Read-Host -Prompt $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if (-not $Optional -and [string]::IsNullOrWhiteSpace($value)) {
            throw "$Prompt is required."
        }
        return $value
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$values = @{}
$exitCode = 1
try {
    $values.PHASE3_ADMIN_CIDRS = Read-Host -Prompt 'Approved administrative IPv4 CIDR(s), comma-separated'
    $values.PHASE4_S3_ENDPOINT = Read-Host -Prompt 'Existing S3-compatible HTTPS endpoint (authority only)'
    $values.PHASE4_S3_BUCKET = Read-Host -Prompt 'Existing off-cluster snapshot bucket'
    $values.PHASE4_S3_REGION = Read-Host -Prompt 'S3 region'
    $values.PHASE4_S3_ACCESS_KEY = Read-ProcessSecret -Prompt 'Temporary S3 access key (input hidden)'
    $values.PHASE4_S3_SECRET_KEY = Read-ProcessSecret -Prompt 'Temporary S3 secret key (input hidden)'
    $values.PHASE4_S3_SESSION_TOKEN = Read-ProcessSecret -Prompt 'Optional S3 session token (input hidden)' -Optional
    if ($Target -eq 'bootstrap') {
        $values.VERDA_CLIENT_ID = Read-ProcessSecret -Prompt 'Temporary Verda client ID for read-only preflight (input hidden)'
        $values.VERDA_CLIENT_SECRET = Read-ProcessSecret -Prompt 'Temporary Verda client secret for read-only preflight (input hidden)'
    }
    foreach ($entry in $values.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
    Push-Location $repoRoot
    try {
        $makeTarget = if ($Target -eq 'bootstrap') { 'cluster-bootstrap' } else { 'verify-cluster' }
        & make $makeTarget 'CLUSTER=management'
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $values.Keys) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        $values[$name] = $null
    }
    $values.Clear()
}

exit $exitCode
