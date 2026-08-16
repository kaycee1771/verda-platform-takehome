[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$failures = [System.Collections.Generic.List[string]]::new()
$passes = [System.Collections.Generic.List[string]]::new()

function Add-CheckResult {
    param(
        [Parameter(Mandatory)][bool]$Condition,
        [Parameter(Mandatory)][string]$Success,
        [Parameter(Mandatory)][string]$Failure
    )

    if ($Condition) {
        $passes.Add($Success)
    }
    else {
        $failures.Add($Failure)
    }
}

$requiredFiles = @(
    'README.md',
    '.gitattributes',
    'SECURITY.md',
    'config/phase0.json',
    'docs/requirements-matrix.md',
    'docs/architecture.md',
    'docs/assumptions.md',
    'docs/risk-register.md',
    'docs/cost-model.md',
    'docs/phase-0-exit-review.md',
    'docs/references.md',
    'docs/ai-usage.md',
    'docs/access.md',
    'docs/one-page-summary.md',
    'docs/evidence/phase-0/validation-summary.md',
    'docs/evidence/phase-0/provider-capability-summary.md',
    'docs/evidence/phase-0/read-only-discovery-summary.md',
    'docs/adr/README.md',
    'scripts/phase0/discover-tools.ps1',
    'scripts/phase0/discover-verda.ps1',
    'scripts/phase0/export-provider-schema.ps1',
    'infra/terraform/provider-discovery/versions.tf'
)

foreach ($relativePath in $requiredFiles) {
    $exists = Test-Path -LiteralPath (Join-Path $workspaceRoot $relativePath) -PathType Leaf
    Add-CheckResult -Condition $exists -Success "Required file exists: $relativePath" -Failure "Missing required file: $relativePath"
}

$configPath = Join-Path $workspaceRoot 'config/phase0.json'
$config = $null
try {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $passes.Add('config/phase0.json is valid JSON')
}
catch {
    $failures.Add("config/phase0.json is invalid: $($_.Exception.Message)")
}

if ($config) {
    Add-CheckResult -Condition ($config.project.decision -eq 'conditional-go') -Success 'Phase 0 decision is explicitly conditional-go' -Failure 'Phase 0 decision must remain conditional-go until account gates close'
    Add-CheckResult -Condition (-not $config.project.cloudMutationAuthorized) -Success 'Cloud mutation is disabled in Phase 0' -Failure 'Phase 0 must not authorize cloud mutation'
    Add-CheckResult -Condition ($config.topology.nodeCount -eq 3) -Success 'Three-node topology is recorded' -Failure 'Expected a three-node topology'

    $groups = @('deliverables', 'core', 'bonus', 'evaluation')
    $allRequirementIds = [System.Collections.Generic.List[string]]::new()
    foreach ($group in $groups) {
        foreach ($id in $config.requirements.$group) {
            $allRequirementIds.Add([string]$id)
        }
    }
    Add-CheckResult -Condition ($allRequirementIds.Count -eq 21) -Success 'All 21 requirement and evaluation IDs are registered' -Failure "Expected 21 requirement/evaluation IDs, found $($allRequirementIds.Count)"
    Add-CheckResult -Condition ((@($allRequirementIds | Sort-Object -Unique)).Count -eq $allRequirementIds.Count) -Success 'Requirement IDs are unique' -Failure 'Duplicate requirement IDs found'

    $matrix = Get-Content -LiteralPath (Join-Path $workspaceRoot 'docs/requirements-matrix.md') -Raw
    foreach ($id in $allRequirementIds) {
        Add-CheckResult -Condition $matrix.Contains($id) -Success "Requirement is traceable: $id" -Failure "Requirement missing from matrix: $id"
    }

    foreach ($adr in $config.adrs) {
        $adrPath = Join-Path $workspaceRoot ([string]$adr)
        $exists = Test-Path -LiteralPath $adrPath -PathType Leaf
        Add-CheckResult -Condition $exists -Success "ADR exists: $adr" -Failure "Registered ADR is missing: $adr"
        if ($exists) {
            $adrText = Get-Content -LiteralPath $adrPath -Raw
            $recognizedStatus = $adrText -match '(?m)^- \*\*Status:\*\* (Accepted|Proposed|Superseded|Rejected)$'
            Add-CheckResult -Condition $recognizedStatus -Success "ADR has recognized status: $adr" -Failure "ADR has missing or invalid status: $adr"
        }
    }

    $openGates = @($config.openGates | Where-Object { $_.status -eq 'blocked' })
    Add-CheckResult -Condition ($openGates.Count -gt 0) -Success 'Blocking account gates remain visible' -Failure 'Phase 0 must not silently clear unverified account gates'

    $exitBlocked = @($config.phase0ExitCriteria | Where-Object { $_.status -eq 'blocked' })
    Add-CheckResult -Condition ($exitBlocked.Count -gt 0) -Success 'Exit review retains unverified controls' -Failure 'At least one Phase 0 exit control should remain blocked until account discovery'
}

$assumptionText = Get-Content -LiteralPath (Join-Path $workspaceRoot 'docs/assumptions.md') -Raw
$assumptionIds = [regex]::Matches($assumptionText, '\| (A-\d{3}) \|') | ForEach-Object { $_.Groups[1].Value }
Add-CheckResult -Condition ($assumptionIds.Count -ge 10) -Success 'Assumption register has sufficient coverage' -Failure 'Assumption register must contain at least 10 tracked assumptions'
Add-CheckResult -Condition ((@($assumptionIds | Sort-Object -Unique)).Count -eq $assumptionIds.Count) -Success 'Assumption IDs are unique' -Failure 'Duplicate assumption IDs found'

$riskText = Get-Content -LiteralPath (Join-Path $workspaceRoot 'docs/risk-register.md') -Raw
$riskIds = [regex]::Matches($riskText, '\| (R-\d{3}) \|') | ForEach-Object { $_.Groups[1].Value }
Add-CheckResult -Condition ($riskIds.Count -ge 10) -Success 'Risk register has sufficient coverage' -Failure 'Risk register must contain at least 10 tracked risks'
Add-CheckResult -Condition ((@($riskIds | Sort-Object -Unique)).Count -eq $riskIds.Count) -Success 'Risk IDs are unique' -Failure 'Duplicate risk IDs found'

$sourceFiles = Get-ChildItem -LiteralPath $workspaceRoot -Recurse -File | Where-Object {
    $_.FullName -notmatch '[\\/]\.git[\\/]' -and
    $_.FullName -notmatch '[\\/]tmp[\\/]'
}

$powerShellFiles = @($sourceFiles | Where-Object { $_.Extension -eq '.ps1' })
foreach ($file in $powerShellFiles) {
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName,
        [ref]$tokens,
        [ref]$parseErrors
    )
    Add-CheckResult -Condition ($parseErrors.Count -eq 0) -Success "PowerShell syntax is valid: $($file.FullName.Substring($workspaceRoot.Length + 1))" -Failure "PowerShell syntax error in $($file.FullName): $($parseErrors -join '; ')"
}

$discoveryScriptText = Get-Content -LiteralPath (Join-Path $workspaceRoot 'scripts/phase0/discover-verda.ps1') -Raw
$mutatingVerdaPatterns = @(
    '(?i)\bvm\s+(create|start|shutdown|hibernate|delete|rm|action)\b',
    '(?i)\bvolume(s)?\s+(create|delete|rm|attach|detach)\b',
    '(?i)\bobject-storage\s+(rm|rb|mv|mb)\b',
    '(?i)\bssh-keys?\s+(create|delete|rm)\b'
)
$mutatingDiscoveryCommandFound = $false
foreach ($pattern in $mutatingVerdaPatterns) {
    if ($discoveryScriptText -match $pattern) {
        $failures.Add("Mutating Verda command pattern found in discovery script: $pattern")
        $mutatingDiscoveryCommandFound = $true
    }
}
if (-not $mutatingDiscoveryCommandFound) {
    $passes.Add('Verda discovery script contains no recognized mutating command')
}

$forbiddenFilePatterns = @(
    '(?i)(^|[\\/])terraform\.tfstate(\..*)?$',
    '(?i)(^|[\\/])kubeconfig[^\\/]*$',
    '(?i)\.(pem|p12|pfx)$',
    '(?i)(^|[\\/])id_(rsa|ed25519)[^\\/]*$'
)
foreach ($file in $sourceFiles) {
    foreach ($pattern in $forbiddenFilePatterns) {
        if ($file.FullName -match $pattern) {
            $failures.Add("Forbidden sensitive filename found: $($file.FullName)")
        }
    }
}
if (-not ($failures | Where-Object { $_ -like 'Forbidden sensitive filename*' })) {
    $passes.Add('No forbidden sensitive filenames found')
}

$privateKeyFinding = $false
foreach ($file in $sourceFiles | Where-Object { $_.Extension -in @('.md', '.json', '.tf', '.yaml', '.yml', '.ps1') }) {
    $content = Get-Content -LiteralPath $file.FullName -Raw
    if ($content -match '-----BEGIN [A-Z ]*PRIVATE KEY-----') {
        $failures.Add("Private key material marker found: $($file.FullName)")
        $privateKeyFinding = $true
    }
}
if (-not $privateKeyFinding) {
    $passes.Add('No private key material markers found')
}

foreach ($pass in $passes) {
    Write-Output "[PASS] $pass"
}
foreach ($failure in $failures) {
    Write-Output "[FAIL] $failure"
}

Write-Output "Phase 0 validation: $($passes.Count) passed, $($failures.Count) failed"

if ($failures.Count -gt 0) {
    exit 1
}
