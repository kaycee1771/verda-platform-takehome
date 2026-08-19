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
$enabledCompletedTargets = @($phaseMap.enabled_completed_phase_targets)
$currentPhaseTarget = $requiredPhase -eq $activePhase -and $Target -in $enabledTargets
$completedPrerequisiteTarget = $requiredPhase -lt $activePhase -and $Target -in $enabledCompletedTargets

if ($currentPhaseTarget -or $completedPrerequisiteTarget) {
    if ($cluster -ne 'management') {
        throw "Phase $activePhase authorizes only CLUSTER=management; Stage B is prohibited."
    }

    $scriptPath = $null
    $scriptArguments = @()
    switch ($Target) {
        'infra-plan' {
            $scriptPath = Join-Path $repoRoot 'scripts\infra\phase2.ps1'
            $scriptArguments = @('-Target', 'plan', '-Cluster', $cluster)
        }
        'infra-lifecycle-check' {
            $scriptPath = Join-Path $repoRoot 'scripts\infra\phase2.ps1'
            $scriptArguments = @('-Target', 'lifecycle-check', '-Cluster', $cluster)
        }
        'inventory' {
            $scriptPath = Join-Path $repoRoot 'scripts\infra\phase2.ps1'
            $scriptArguments = @('-Target', 'inventory', '-Cluster', $cluster)
        }
        'configure' {
            $scriptPath = Join-Path $repoRoot 'scripts\host\phase3.ps1'
            $scriptArguments = @('-Target', 'configure', '-Cluster', $cluster)
        }
        'verify-hosts' {
            $scriptPath = Join-Path $repoRoot 'scripts\host\phase3.ps1'
            $scriptArguments = @('-Target', 'verify', '-Cluster', $cluster)
        }
        'cluster-bootstrap' {
            $scriptPath = Join-Path $repoRoot 'scripts\cluster\phase4.ps1'
            $scriptArguments = @('-Target', 'bootstrap', '-Cluster', $cluster)
        }
        'verify-cluster' {
            $scriptPath = Join-Path $repoRoot 'scripts\cluster\phase4.ps1'
            $scriptArguments = @('-Target', 'verify', '-Cluster', $cluster)
        }
        'bootstrap-gitops' {
            $scriptPath = Join-Path $repoRoot 'scripts\bootstrap-gitops.sh'
        }
        default {
            throw "Target '$Target' has no approved Phase $activePhase dispatcher route; no action was taken."
        }
    }

    if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
        throw "The approved orchestrator for '$Target' is absent; no action was taken."
    }
    if ([IO.Path]::GetExtension($scriptPath) -eq '.sh') {
        & bash $scriptPath @scriptArguments
    } else {
        & pwsh -NoLogo -NoProfile -NonInteractive -File $scriptPath @scriptArguments
    }
    exit $LASTEXITCODE
}

$message = "[phase $activePhase] target=$Target BLOCKED: owned by Phase $requiredPhase; arguments=[$Arguments]. No action was taken."
$message | Set-Content -LiteralPath (Join-Path $logDirectory "$Target.log") -Encoding utf8NoBOM
[Console]::Error.WriteLine($message)
exit 64
