[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Target,
    [string]$Arguments = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logDirectory = Join-Path $repoRoot '.local\logs'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$phaseMapPath = Join-Path $repoRoot 'config\phase-map.json'
$phaseMap = Get-Content -LiteralPath $phaseMapPath -Raw | ConvertFrom-Json -Depth 20
$targetProperty = $phaseMap.target_owners.PSObject.Properties[$Target]
if ($null -eq $targetProperty) {
    throw "Unknown Make target '$Target'."
}

$clusterMatch = [regex]::Match($Arguments, '(?:^|\s)CLUSTER=([^\s]*)')
$cluster = if ($clusterMatch.Success -and $clusterMatch.Groups[1].Value) {
    $clusterMatch.Groups[1].Value
} else {
    'management'
}
$owner = $targetProperty.Value
$clusterOwner = $owner.PSObject.Properties[$cluster]
$defaultOwner = $owner.PSObject.Properties['default']
if ($null -ne $clusterOwner) {
    $requiredPhase = [int]$clusterOwner.Value
} elseif ($null -ne $defaultOwner) {
    $requiredPhase = [int]$defaultOwner.Value
} else {
    throw "Target '$Target' is not defined for CLUSTER=$cluster."
}

$activePhase = [int]$phaseMap.active_phase
$enabledTargets = @($phaseMap.enabled_phase_targets)
if ($requiredPhase -eq $activePhase -and $Target -in $enabledTargets) {
    if ($cluster -ne 'management') {
        throw "Phase 3 authorizes only CLUSTER=management; Stage B is prohibited."
    }
    $phase3Script = Join-Path $repoRoot 'scripts\host\phase3.ps1'
    if (-not (Test-Path -LiteralPath $phase3Script -PathType Leaf)) {
        throw 'The Phase 3 host orchestrator is absent; no action was taken.'
    }
    $phase3Target = if ($Target -eq 'configure') { 'configure' } else { 'verify' }
    & pwsh -NoLogo -NoProfile -NonInteractive -File $phase3Script -Target $phase3Target -Cluster $cluster
    exit $LASTEXITCODE
}

$message = "[phase $activePhase] target=$Target BLOCKED: owned by Phase $requiredPhase; arguments=[$Arguments]. No action was taken."
$message | Set-Content -LiteralPath (Join-Path $logDirectory "$Target.log") -Encoding utf8NoBOM
[Console]::Error.WriteLine($message)
exit 64
