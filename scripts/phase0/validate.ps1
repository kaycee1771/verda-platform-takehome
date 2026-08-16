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

function Read-WorkspaceFile {
    param([Parameter(Mandatory)][string]$RelativePath)

    return Get-Content -LiteralPath (Join-Path $workspaceRoot $RelativePath) -Raw
}

$requiredFiles = @(
    'README.md',
    'IMPLEMENTATION_STATUS.md',
    'SECURITY.md',
    '.env.example',
    '.gitignore',
    'versions.lock.yaml',
    'config/phase0.json',
    'docs/acceptance-matrix.md',
    'docs/architecture.md',
    'docs/operations-model.md',
    'docs/known-limitations.md',
    'docs/assumptions.md',
    'docs/risk-register.md',
    'docs/cost.md',
    'docs/reports/verda-discovery.md',
    'docs/phase-0-exit-review.md',
    'docs/references.md',
    'docs/ai-usage.md',
    'docs/adr/README.md',
    'docs/adr/template.md',
    'evidence/manifests/phase-0-acceptance-matrix.md',
    'evidence/phase-0/README.md',
    'evidence/phase-0/provider-schema-summary.md',
    'evidence/phase-0/verda-account-discovery.md',
    'evidence/phase-0/network-capability-surface.md',
    'evidence/phase-0/stage-a-cost-envelope.md',
    'evidence/phase-0/validation-summary.md',
    'scripts/phase0/discover-tools.ps1',
    'scripts/phase0/discover-verda.ps1',
    'scripts/phase0/export-provider-schema.ps1',
    'infra/terraform/provider-discovery/versions.tf',
    'infra/terraform/provider-discovery/.terraform.lock.hcl'
)

foreach ($relativePath in $requiredFiles) {
    Add-CheckResult `
        -Condition (Test-Path -LiteralPath (Join-Path $workspaceRoot $relativePath) -PathType Leaf) `
        -Success "Required Phase 0 artifact exists: $relativePath" `
        -Failure "Missing required Phase 0 artifact: $relativePath"
}

$config = $null
try {
    $config = Read-WorkspaceFile -RelativePath 'config/phase0.json' | ConvertFrom-Json
    $passes.Add('config/phase0.json is valid JSON')
}
catch {
    $failures.Add("config/phase0.json is invalid: $($_.Exception.Message)")
}

if ($config) {
    Add-CheckResult -Condition ($config.project.phase -eq 0) -Success 'Active implementation phase is 0' -Failure 'Configuration must remain on Phase 0'
    Add-CheckResult -Condition ($config.project.decision -in @('blocked', 'complete')) -Success 'Phase 0 decision uses a recognized state' -Failure 'Phase 0 decision must be blocked or complete'
    Add-CheckResult -Condition (-not $config.project.cloudMutationAuthorized) -Success 'Cloud mutation is disabled for Phase 0' -Failure 'Phase 0 must never authorize cloud mutation'
    Add-CheckResult -Condition ($config.topology.deliveryStrategy -eq 'stage-a-then-stage-b') -Success 'Two-stage delivery strategy is recorded' -Failure 'Expected Stage A then Stage B delivery strategy'
    Add-CheckResult -Condition ($config.topology.nodesPerCluster -eq 3) -Success 'Three schedulable servers per cluster are recorded' -Failure 'Expected three servers per cluster'

    $registeredAdrs = @($config.adrs)
    Add-CheckResult -Condition ($registeredAdrs.Count -ge 11) -Success 'Minimum initial ADR set is registered' -Failure "Expected at least 11 initial ADRs, found $($registeredAdrs.Count)"
    foreach ($adr in $registeredAdrs) {
        $adrPath = Join-Path $workspaceRoot ([string]$adr)
        $exists = Test-Path -LiteralPath $adrPath -PathType Leaf
        Add-CheckResult -Condition $exists -Success "Registered ADR exists: $adr" -Failure "Registered ADR is missing: $adr"
        if ($exists) {
            $adrText = Get-Content -LiteralPath $adrPath -Raw
            Add-CheckResult -Condition ($adrText -match '(?m)^- \*\*Status:\*\* (Accepted|Proposed|Superseded|Rejected)$') -Success "ADR has a recognized status: $adr" -Failure "ADR has missing or invalid status: $adr"
            foreach ($section in @('Context', 'Decision', 'Alternatives considered', 'Consequences', 'Validation evidence', 'Production evolution')) {
                Add-CheckResult -Condition ($adrText -match "(?m)^## $([regex]::Escape($section))$") -Success "ADR contains ${section}: $adr" -Failure "ADR missing '$section': $adr"
            }
        }
    }

    $blockedGates = @($config.openGates | Where-Object { $_.status -eq 'blocked' })
    if ($config.project.decision -eq 'blocked') {
        Add-CheckResult -Condition ($blockedGates.Count -gt 0) -Success 'Blocked Phase 0 has explicit blocking gates' -Failure 'Blocked Phase 0 must identify at least one blocking gate'
    }
    if ($config.project.decision -eq 'complete') {
        $phase1Blockers = @($config.openGates | Where-Object { $_.blocksPhase -le 1 -and $_.status -ne 'pass' })
        $failedExitCriteria = @($config.phase0ExitCriteria | Where-Object { $_.status -ne 'pass' })
        Add-CheckResult -Condition ($phase1Blockers.Count -eq 0) -Success 'Completed Phase 0 has no open Phase 1 gate' -Failure 'Completed Phase 0 still has a Phase 1 blocker'
        Add-CheckResult -Condition ($failedExitCriteria.Count -eq 0) -Success 'All Phase 0 exit criteria pass' -Failure 'Completed Phase 0 has a failed exit criterion'
        Add-CheckResult -Condition ($config.verifiedAccount.selectedStageA.instanceType -eq 'CPU.4V.16G') -Success 'Selected Stage A instance type is pinned' -Failure 'Stage A instance type is not pinned to the verified selection'
        Add-CheckResult -Condition ($config.verifiedAccount.selectedStageA.imageConfigurationId -eq '77edfb23-bb0d-41cc-a191-dccae45d96fd') -Success 'Selected Stage A image configuration is pinned' -Failure 'Stage A image configuration does not match discovery'
        Add-CheckResult -Condition ($config.verifiedAccount.costEnvelope.reviewHours -eq 168) -Success 'Seven-day review window is encoded' -Failure 'Expected a 168-hour Stage A review window'
        Add-CheckResult -Condition ($config.verifiedAccount.costEnvelope.stageAEnvelopeUsd -lt $config.verifiedAccount.balanceUsd) -Success 'Stage A envelope is below verified balance' -Failure 'Stage A envelope does not fit the verified balance'
        $selectedStageA = $config.verifiedAccount.selectedStageA
        $costEnvelope = $config.verifiedAccount.costEnvelope
        $knownCompute = 3 * [double]$selectedStageA.onDemandUsdPerHour * [double]$costEnvelope.reviewHours
        $knownStorage = 3 * ([double]$selectedStageA.rootVolumeGiBPerNode + [double]$selectedStageA.dataVolumeGiBPerNode) * [double]$selectedStageA.nvmeUsdPerGiBMonth * ([double]$costEnvelope.reviewHours / 730)
        $calculatedEnvelope = ($knownCompute + $knownStorage + [double]$costEnvelope.serviceAllowanceUsd) * (1 + ([double]$costEnvelope.contingencyPercent / 100))
        $roundedUpEnvelope = [math]::Ceiling($calculatedEnvelope * 100) / 100
        $calculatedRemaining = [math]::Round([double]$config.verifiedAccount.balanceUsd - $roundedUpEnvelope, 2)
        Add-CheckResult -Condition ([math]::Abs($roundedUpEnvelope - [double]$costEnvelope.stageAEnvelopeUsd) -lt 0.001) -Success 'Stage A envelope recomputes from pinned rates and sizing' -Failure 'Recorded Stage A envelope does not match pinned-rate calculation'
        Add-CheckResult -Condition ([math]::Abs($calculatedRemaining - [double]$costEnvelope.remainingBalanceAfterEnvelopeUsd) -lt 0.001) -Success 'Remaining balance recomputes from verified balance and envelope' -Failure 'Recorded remaining balance does not match the envelope'
    }
}

$matrixText = Read-WorkspaceFile -RelativePath 'docs/acceptance-matrix.md'
$requirementIds = [regex]::Matches($matrixText, '\| (R\d{2}) \|') | ForEach-Object { $_.Groups[1].Value }
$uniqueRequirementIds = @($requirementIds | Sort-Object -Unique)
$expectedRequirementIds = 1..22 | ForEach-Object { 'R{0:d2}' -f $_ }
Add-CheckResult -Condition ($uniqueRequirementIds.Count -eq 22) -Success 'Acceptance matrix contains 22 unique requirement IDs' -Failure "Expected 22 unique R01-R22 IDs, found $($uniqueRequirementIds.Count)"
foreach ($id in $expectedRequirementIds) {
    Add-CheckResult -Condition ($id -in $uniqueRequirementIds) -Success "Acceptance requirement is traceable: $id" -Failure "Acceptance requirement is missing: $id"
}

$statusText = Read-WorkspaceFile -RelativePath 'IMPLEMENTATION_STATUS.md'
Add-CheckResult -Condition ($statusText -match 'Active phase: Phase 0') -Success 'Status ledger identifies Phase 0' -Failure 'Status ledger does not identify Phase 0'
Add-CheckResult -Condition ($statusText -match '(?m)^\| 1 .*\| NOT STARTED \|') -Success 'Status ledger confirms Phase 1 has not started' -Failure 'Phase 1 must remain NOT STARTED'
Add-CheckResult -Condition ($statusText -match 'Cloud mutation authorized: No') -Success 'Status ledger prohibits cloud mutation' -Failure 'Status ledger must prohibit cloud mutation'
if ($config -and $config.project.decision -eq 'complete') {
    Add-CheckResult -Condition ($statusText -match 'Phase status: PASS') -Success 'Status ledger records Phase 0 PASS' -Failure 'Completed Phase 0 must be PASS in the status ledger'
}

$architectureText = Read-WorkspaceFile -RelativePath 'docs/architecture.md'
foreach ($architectureMarker in @('Stage A', 'Stage B', 'verda-mgmt', 'verda-workload', 'fixed registration/API endpoint')) {
    Add-CheckResult -Condition $architectureText.Contains($architectureMarker) -Success "Architecture records: $architectureMarker" -Failure "Architecture is missing: $architectureMarker"
}

$discoveryReport = Read-WorkspaceFile -RelativePath 'docs/reports/verda-discovery.md'
foreach ($capabilityMarker in @('zero data sources', 'private network', 'load balancer', 'object-storage', 'UNVERIFIED', 'Path B')) {
    Add-CheckResult -Condition ($discoveryReport -match [regex]::Escape($capabilityMarker)) -Success "Discovery report treats capability explicitly: $capabilityMarker" -Failure "Discovery report missing capability state: $capabilityMarker"
}

$versionLockText = Read-WorkspaceFile -RelativePath 'versions.lock.yaml'
Add-CheckResult -Condition ($versionLockText -match '(?m)^\s+version: "1\.1\.2"$') -Success 'Verda provider 1.1.2 is pinned in versions.lock.yaml' -Failure 'Verda provider must be pinned to 1.1.2'
Add-CheckResult -Condition ($versionLockText -notmatch '(?i)version:\s*["'']?(latest|main)["'']?') -Success 'No floating latest/main version is present in versions.lock.yaml' -Failure 'Floating latest/main version found in versions.lock.yaml'

$providerConfigText = Read-WorkspaceFile -RelativePath 'infra/terraform/provider-discovery/versions.tf'
Add-CheckResult -Condition ($providerConfigText -match 'version\s*=\s*"= 1\.1\.2"') -Success 'Discovery provider constraint is exact' -Failure 'Discovery provider must use exact constraint = 1.1.2'
$providerLockText = Read-WorkspaceFile -RelativePath 'infra/terraform/provider-discovery/.terraform.lock.hcl'
Add-CheckResult -Condition ($providerLockText -match 'version\s*=\s*"1\.1\.2"') -Success 'Dependency lock selects provider 1.1.2' -Failure 'Dependency lock must select provider 1.1.2'

$localSchemaPath = Join-Path $workspaceRoot 'evidence/phase-0/provider-schema.local.json'
if (Test-Path -LiteralPath $localSchemaPath -PathType Leaf) {
    try {
        $schema = Get-Content -LiteralPath $localSchemaPath -Raw | ConvertFrom-Json
        $provider = $schema.provider_schemas.'registry.terraform.io/verda-cloud/verda'
        $resources = @($provider.resource_schemas.PSObject.Properties.Name | Sort-Object)
        $dataSources = @()
        if ($provider.PSObject.Properties.Name -contains 'data_source_schemas') {
            $dataSources = @($provider.data_source_schemas.PSObject.Properties.Name | Sort-Object)
        }
        $expectedResources = @('verda_container', 'verda_container_registry_credentials', 'verda_instance', 'verda_serverless_job', 'verda_ssh_key', 'verda_startup_script', 'verda_volume', 'verda_volume_attachment') | Sort-Object
        Add-CheckResult -Condition (($resources -join ',') -eq ($expectedResources -join ',')) -Success 'Local provider schema has the reviewed eight-resource surface' -Failure "Provider resource surface changed: $($resources -join ', ')"
        Add-CheckResult -Condition ($dataSources.Count -eq 0) -Success 'Local provider schema exposes zero data sources' -Failure "Provider data-source surface changed: $($dataSources -join ', ')"
    }
    catch {
        $failures.Add("Local provider schema cannot be parsed: $($_.Exception.Message)")
    }
}
else {
    $passes.Add('Local provider schema is absent; committed sanitized summary remains available')
}

$sourceFiles = Get-ChildItem -LiteralPath $workspaceRoot -Recurse -File | Where-Object {
    $_.FullName -notmatch '[\\/]\.git[\\/]' -and
    $_.FullName -notmatch '[\\/]\.terraform[\\/]' -and
    $_.FullName -notmatch '[\\/]\.local[\\/]' -and
    $_.Name -notlike '*.local.json' -and
    $_.Name -ne 'VERDA_PLATFORM_TAKEHOME_MASTER_BLUEPRINT.md'
}

$powerShellFiles = @($sourceFiles | Where-Object { $_.Extension -eq '.ps1' })
foreach ($file in $powerShellFiles) {
    $tokens = $null
    $parseErrors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
    $relative = $file.FullName.Substring($workspaceRoot.Length + 1)
    Add-CheckResult -Condition ($parseErrors.Count -eq 0) -Success "PowerShell syntax is valid: $relative" -Failure "PowerShell syntax error in $relative`: $($parseErrors -join '; ')"
}

$discoveryScriptText = Read-WorkspaceFile -RelativePath 'scripts/phase0/discover-verda.ps1'
$mutatingVerdaPatterns = @(
    '(?i)arguments\s*=.*\bvm\b.*\b(create|start|shutdown|hibernate|delete|rm|action)\b',
    '(?i)arguments\s*=.*\bvolume\b.*\b(create|delete|rm|attach|detach|action)\b',
    '(?i)arguments\s*=.*\bobject-storage\b.*\b(rm|rb|mv|mb|cp|sync)\b',
    '(?i)arguments\s*=.*\bssh-key\b.*\b(create|delete|rm)\b'
)
$mutatingDiscoveryCommandFound = $false
foreach ($pattern in $mutatingVerdaPatterns) {
    if ($discoveryScriptText -match $pattern) {
        $failures.Add("Mutating Verda command pattern found in discovery script: $pattern")
        $mutatingDiscoveryCommandFound = $true
    }
}
if (-not $mutatingDiscoveryCommandFound) {
    $passes.Add('Verda discovery script contains only recognized read-only query families')
}

$forbiddenFilePatterns = @(
    '(?i)(^|[\\/])terraform\.tfstate(\..*)?$',
    '(?i)(^|[\\/])kubeconfig[^\\/]*$',
    '(?i)\.(pem|p12|pfx)$',
    '(?i)(^|[\\/])id_(rsa|ed25519)[^\\/]*$'
)
$forbiddenFileFound = $false
foreach ($file in $sourceFiles) {
    foreach ($pattern in $forbiddenFilePatterns) {
        if ($file.FullName -match $pattern) {
            $failures.Add("Forbidden sensitive filename found: $($file.FullName)")
            $forbiddenFileFound = $true
        }
    }
}
if (-not $forbiddenFileFound) {
    $passes.Add('No forbidden sensitive filenames found')
}

$secretMarkerPatterns = @(
    '-----BEGIN [A-Z ]*PRIVATE KEY-----',
    '(?i)VERDA_CLIENT_SECRET\s*=\s*[^\s#]+',
    '(?i)client_secret\s*[=:]\s*["''][^"'']+["'']'
)
$secretMarkerFound = $false
foreach ($file in $sourceFiles | Where-Object { $_.Extension -in @('.md', '.json', '.tf', '.hcl', '.yaml', '.yml', '.ps1', '.example') }) {
    $content = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($pattern in $secretMarkerPatterns) {
        if ($content -match $pattern) {
            $failures.Add("Potential secret material found: $($file.FullName)")
            $secretMarkerFound = $true
            break
        }
    }
}
if (-not $secretMarkerFound) {
    $passes.Add('No private-key or populated Verda client-secret markers found')
}

foreach ($pass in $passes) {
    Write-Output "[PASS] $pass"
}
foreach ($failure in $failures) {
    Write-Output "[FAIL] $failure"
}

Write-Output "Phase 0 repository validation: $($passes.Count) passed, $($failures.Count) failed"
Write-Output 'Note: repository validation enforces the recorded Phase 0 contract but does not replace referenced live evidence.'

if ($failures.Count -gt 0) {
    exit 1
}
