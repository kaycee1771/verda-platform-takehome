[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Target,
    [string]$Arguments = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$requiredPhases = @{
    'infra-init'          = 2
    'infra-plan'          = 2
    'infra-apply'         = 2
    'inventory'           = 2
    'configure'           = 3
    'verify-hosts'        = 3
    'verify-cluster'      = 3
    'stage-a-verify'      = 3
    'bootstrap-gitops'    = 4
    'platform-status'     = 4
    'register-clusters'   = 4
    'stage-b-verify'      = 4
    'backup'              = 5
    'restore-test'        = 5
    'app-test'            = 6
    'app-build'           = 6
    'supply-chain-verify' = 6
    'promote'             = 6
    'cost-report'         = 7
    'verify'              = 8
    'fault'               = 8
    'collect-evidence'    = 9
    'sanitize-evidence'   = 9
    'destroy'             = 9
}

if (-not $requiredPhases.ContainsKey($Target)) {
    throw "Unknown Make target '$Target'."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logDirectory = Join-Path $repoRoot '.local\logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$message = "[phase 1] target=$Target BLOCKED: requires Phase $($requiredPhases[$Target]); arguments=[$Arguments]. No action was taken."
$message | Tee-Object -FilePath (Join-Path $logDirectory "$Target.log") | Write-Error
exit 64
