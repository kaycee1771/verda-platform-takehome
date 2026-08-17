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
    'infra-repair-node-02-plan' = 2
    'infra-repair-node-02-apply' = 2
    'infra-lifecycle-check' = 2
    'inventory'           = 2
    'configure'           = 3
    'verify-hosts'        = 2
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
    'cost-report'         = 2
    'verify'              = 8
    'fault'               = 8
    'collect-evidence'    = 9
    'sanitize-evidence'   = 9
    'destroy'             = 2
}

if (-not $requiredPhases.ContainsKey($Target)) {
    throw "Unknown Make target '$Target'."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logDirectory = Join-Path $repoRoot '.local\logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

if ($requiredPhases[$Target] -eq 2) {
    $targetMap = @{
        'infra-init'            = 'init'
        'infra-plan'            = 'plan'
        'infra-apply'           = 'apply'
        'infra-repair-node-02-plan' = 'repair-node-02-plan'
        'infra-repair-node-02-apply' = 'repair-node-02-apply'
        'infra-lifecycle-check' = 'lifecycle-check'
        'inventory'             = 'inventory'
        'verify-hosts'          = 'verify-hosts'
        'cost-report'           = 'cost-report'
        'destroy'               = 'destroy'
    }
    $clusterMatch = [regex]::Match($Arguments, '(?:^|\s)CLUSTER=([^\s]*)')
    $cluster = if ($clusterMatch.Success -and $clusterMatch.Groups[1].Value) {
        $clusterMatch.Groups[1].Value
    } else {
        'management'
    }
    if ($cluster -ne 'management') {
        throw "Phase 2 authorizes only CLUSTER=management; Stage B is prohibited."
    }
    $phase2Script = Join-Path $repoRoot 'scripts\infra\phase2.ps1'
    $phase2Arguments = @('-NoLogo', '-NoProfile', '-NonInteractive', '-File', $phase2Script,
        '-Target', $targetMap[$Target], '-Cluster', $cluster)
    if ($Target -in @('destroy', 'infra-repair-node-02-plan', 'infra-repair-node-02-apply') -and
        $Arguments -match '(?:^|\s)CONFIRM=--confirm(?:\s|$)') {
        $phase2Arguments += '-Confirm'
    }
    & pwsh @phase2Arguments
    exit $LASTEXITCODE
}

$message = "[phase 2] target=$Target BLOCKED: requires Phase $($requiredPhases[$Target]); arguments=[$Arguments]. No action was taken."
$message | Tee-Object -FilePath (Join-Path $logDirectory "$Target.log") | Write-Error
exit 64
