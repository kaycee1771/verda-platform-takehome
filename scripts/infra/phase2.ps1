[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('init', 'plan', 'apply', 'repair-node-02-plan', 'repair-node-02-apply', 'inventory', 'verify-hosts', 'lifecycle-check', 'cost-report', 'state-audit', 'destroy', 'phase6-resize-plan', 'phase6-resize-apply', 'phase6-resize-output')]
    [string]$Target,
    [ValidateSet('management')]
    [string]$Cluster = 'management',
    [switch]$Confirm,
    [string]$SavedPlan = '',
    [string]$ExpectedPlanSha256 = '',
    [string]$ExpectedStateLineageSha256 = '',
    [long]$ExpectedStateSerial = -1,
    [string]$OperationId = '',
    [string]$InventoryOutput = '',
    [string]$KnownHosts = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$terraformRoot = Join-Path $repoRoot 'infra\terraform\environments\management'
$reportRoot = Join-Path $repoRoot '.local\reports\phase2'
$logRoot = Join-Path $repoRoot '.local\logs\phase2'
$inventoryPath = Join-Path $repoRoot 'infra\ansible\inventories\generated\management.yaml'
$costConfig = Join-Path $terraformRoot 'cost-envelope.json'
$planSummary = Join-Path $reportRoot 'plan-summary.json'
$costSummary = Join-Path $reportRoot 'cost-envelope.json'
$noDriftSummary = Join-Path $reportRoot 'no-drift-summary.json'
$rollbackSummary = Join-Path $reportRoot 'compute-rollback-summary.json'
$repairSummary = Join-Path $reportRoot 'node-02-replacement-summary.json'
New-Item -ItemType Directory -Force -Path $reportRoot, $logRoot | Out-Null

function Get-CanonicalBoundaryPath {
    param([Parameter(Mandatory)][string]$Path)

    $full = [IO.Path]::GetFullPath($Path)
    $ancestor = $full
    while (-not (Test-Path -LiteralPath $ancestor) -and $ancestor -ne [IO.Path]::GetPathRoot($ancestor)) {
        $ancestor = Split-Path -Parent $ancestor
    }
    $resolvedAncestor = (Resolve-Path -LiteralPath $ancestor).Path
    $relative = [IO.Path]::GetRelativePath($ancestor, $full)
    [IO.Path]::GetFullPath((Join-Path $resolvedAncestor $relative))
}

function Assert-OutsideRepository {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Label)

    $repo = Get-CanonicalBoundaryPath -Path $repoRoot
    foreach ($candidate in @([IO.Path]::GetFullPath($Path), (Get-CanonicalBoundaryPath -Path $Path))) {
        $prefix = $repo.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        if ($candidate.Equals($repo, [StringComparison]::OrdinalIgnoreCase) -or
            $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Label must resolve outside the repository."
        }
    }
}

function Get-ExternalPaths {
    if ($IsWindows) {
        $base = if ($env:VERDA_TAKEHOME_CONFIG_DIR) {
            $env:VERDA_TAKEHOME_CONFIG_DIR
        } else {
            Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'VerdaPlatformTakehome'
        }
        $backupBase = if ($env:VERDA_TF_BACKUP_DIR) {
            $env:VERDA_TF_BACKUP_DIR
        } else {
            Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'VerdaPlatformTakehome\state-backups'
        }
    } else {
        $stateHome = if ($env:XDG_STATE_HOME) { $env:XDG_STATE_HOME } else { Join-Path $env:HOME '.local/state' }
        $configHome = if ($env:XDG_CONFIG_HOME) { $env:XDG_CONFIG_HOME } else { Join-Path $env:HOME '.config' }
        $base = if ($env:VERDA_TAKEHOME_CONFIG_DIR) {
            $env:VERDA_TAKEHOME_CONFIG_DIR
        } else {
            Join-Path $configHome 'verda-takehome'
        }
        $backupBase = if ($env:VERDA_TF_BACKUP_DIR) {
            $env:VERDA_TF_BACKUP_DIR
        } else {
            Join-Path $stateHome 'verda-takehome-backups'
        }
    }

    $base = [IO.Path]::GetFullPath($base)
    $backupBase = [IO.Path]::GetFullPath($backupBase)
    Assert-OutsideRepository -Path $base -Label 'Phase 2 state/key base'
    Assert-OutsideRepository -Path $backupBase -Label 'Phase 2 backup directory'

    $statePath = if ($env:VERDA_TF_STATE_PATH) {
        [IO.Path]::GetFullPath($env:VERDA_TF_STATE_PATH)
    } else {
        Join-Path $base 'terraform\management.tfstate'
    }
    Assert-OutsideRepository -Path $statePath -Label 'Terraform state'
    $planPath = Join-Path $base 'terraform\management.tfplan'
    $rollbackPlanPath = Join-Path $base 'terraform\management-compute-rollback.tfplan'
    $repairPlanPath = Join-Path $base 'terraform\management-node-02-replacement.tfplan'
    $sshPrivateKey = Join-Path $base 'ssh\id_ed25519'

    return [pscustomobject]@{
        Base             = $base
        BackupDirectory  = $backupBase
        StatePath        = $statePath
        EncryptedStatePath = "$statePath.dpapi"
        PlanPath         = $planPath
        RollbackPlanPath = $rollbackPlanPath
        RepairPlanPath   = $repairPlanPath
        SshPrivateKey    = $sshPrivateKey
        SshPublicKey     = "$sshPrivateKey.pub"
    }
}

function Protect-Directory {
    param([Parameter(Mandatory)][string]$Path)

    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    if ($IsWindows) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $Path '/inheritance:r' '/grant:r' "${identity}:(OI)(CI)F" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to restrict ACLs on the external Phase 2 directory."
        }
        # EFS is opportunistic because some managed Windows editions disable it.
        # DPAPI sealing below remains mandatory and is the canonical state-at-rest control.
        & cipher.exe /E /A $Path 2>$null | Out-Null
    } else {
        & chmod 700 $Path
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to restrict the external Phase 2 directory to mode 0700."
        }
        if ($env:VERDA_STATE_ENCRYPTION_VERIFIED -ne 'yes') {
            throw "Set VERDA_STATE_ENCRYPTION_VERIFIED=yes only after verifying the backing filesystem is encrypted."
        }
    }
}

function Initialize-LocalBoundary {
    param([Parameter(Mandatory)]$Paths)

    Protect-Directory -Path $Paths.Base
    Protect-Directory -Path (Split-Path -Parent $Paths.StatePath)
    Protect-Directory -Path $Paths.BackupDirectory
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Paths.SshPrivateKey) | Out-Null

    if (-not (Test-Path -LiteralPath $Paths.SshPrivateKey -PathType Leaf)) {
        & ssh-keygen -q -t ed25519 -N '' -C 'verda-platform-phase2-20260817' -f $Paths.SshPrivateKey
        if ($LASTEXITCODE -ne 0) {
            throw "Dedicated Phase 2 Ed25519 key generation failed."
        }
    }
    if (-not (Test-Path -LiteralPath $Paths.SshPublicKey -PathType Leaf)) {
        throw "Dedicated Phase 2 SSH public key is missing."
    }
    $publicKey = (Get-Content -LiteralPath $Paths.SshPublicKey -Raw).Trim()
    if ($publicKey -notmatch '^ssh-ed25519\s+[A-Za-z0-9+/=]+\s+') {
        throw "Dedicated Phase 2 public key is not valid OpenSSH Ed25519 text."
    }
    if ($IsWindows) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $Paths.SshPrivateKey '/inheritance:r' '/grant:r' "${identity}:F" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to restrict the dedicated SSH private key ACL."
        }
    } else {
        & chmod 600 $Paths.SshPrivateKey
    }
    $env:TF_VAR_ssh_public_key_path = $Paths.SshPublicKey
}

function Protect-BytesForCurrentUser {
    param([Parameter(Mandatory)][byte[]]$Bytes)

    if (-not $IsWindows) {
        throw "DPAPI byte protection is available only on Windows."
    }
    Add-Type -AssemblyName System.Security.Cryptography.ProtectedData
    $entropy = [Text.Encoding]::UTF8.GetBytes('verda-platform-takehome-phase2-state-v1')
    return [Security.Cryptography.ProtectedData]::Protect(
        $Bytes,
        $entropy,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
}

function Unprotect-BytesForCurrentUser {
    param([Parameter(Mandatory)][byte[]]$Bytes)

    if (-not $IsWindows) {
        throw "DPAPI byte unprotection is available only on Windows."
    }
    Add-Type -AssemblyName System.Security.Cryptography.ProtectedData
    $entropy = [Text.Encoding]::UTF8.GetBytes('verda-platform-takehome-phase2-state-v1')
    return [Security.Cryptography.ProtectedData]::Unprotect(
        $Bytes,
        $entropy,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
}

function Test-ByteArraysEqual {
    param(
        [Parameter(Mandatory)][byte[]]$Left,
        [Parameter(Mandatory)][byte[]]$Right
    )

    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $leftHash = [Convert]::ToBase64String($sha256.ComputeHash($Left))
        $rightHash = [Convert]::ToBase64String($sha256.ComputeHash($Right))
        return $leftHash -ceq $rightHash
    } finally {
        $sha256.Dispose()
    }
}

function Open-SealedState {
    param([Parameter(Mandatory)]$Paths)

    if (-not $IsWindows) {
        return
    }
    if ((Test-Path -LiteralPath $Paths.EncryptedStatePath) -and (Test-Path -LiteralPath $Paths.StatePath)) {
        throw "Both sealed and plaintext Terraform state exist; refusing an ambiguous state lineage."
    }
    if (Test-Path -LiteralPath $Paths.EncryptedStatePath -PathType Leaf) {
        $encrypted = [IO.File]::ReadAllBytes($Paths.EncryptedStatePath)
        $plaintext = Unprotect-BytesForCurrentUser -Bytes $encrypted
        [IO.File]::WriteAllBytes($Paths.StatePath, $plaintext)
        Write-Host "[PASS] Terraform state opened in the protected runtime boundary; contents withheld."
    }
}

function Close-SealedState {
    param([Parameter(Mandatory)]$Paths)

    if (-not $IsWindows) {
        return
    }
    foreach ($plaintextPath in @($Paths.StatePath, "$($Paths.StatePath).backup")) {
        if (-not (Test-Path -LiteralPath $plaintextPath -PathType Leaf)) {
            continue
        }
        $bytes = [IO.File]::ReadAllBytes($plaintextPath)
        $encrypted = Protect-BytesForCurrentUser -Bytes $bytes
        $destination = "$plaintextPath.dpapi"
        $temporary = "$destination.new"
        [IO.File]::WriteAllBytes($temporary, $encrypted)
        $roundTrip = Unprotect-BytesForCurrentUser -Bytes ([IO.File]::ReadAllBytes($temporary))
        if (-not (Test-ByteArraysEqual -Left $bytes -Right $roundTrip)) {
            Remove-Item -LiteralPath $temporary -Force
            throw "DPAPI state sealing round-trip verification failed."
        }
        Move-Item -LiteralPath $temporary -Destination $destination -Force
        Remove-Item -LiteralPath $plaintextPath -Force
    }
    Write-Host "[PASS] Terraform state is DPAPI-sealed at rest; plaintext runtime state removed."
}

function Assert-Credentials {
    foreach ($name in @('VERDA_CLIENT_ID', 'VERDA_CLIENT_SECRET')) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "$name is required in process memory; do not place it in a file or command argument."
        }
    }
}

function Invoke-JsonCommand {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$FailureMessage
    )

    $raw = & $Command @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
    try {
        return (($raw -join "`n") | ConvertFrom-Json -Depth 100)
    } catch {
        throw "$FailureMessage The command did not return valid JSON."
    }
}

function Assert-LiveContract {
    Assert-Credentials
    $status = Invoke-JsonCommand -Command 'verda' -Arguments @('--agent', '--output', 'json', 'status') `
        -FailureMessage 'Verda authentication/status verification failed; raw diagnostic withheld.'
    if ([double]$status.financials.balance -lt 45.0) {
        throw "Verified account balance is below the hard seven-day Stage A budget."
    }
    $availability = Invoke-JsonCommand -Command 'verda' -Arguments @(
        '--agent', '--output', 'json', 'availability', '--type', 'CPU.4V.16G', '--location', 'FIN-03'
    ) -FailureMessage 'Unable to verify CPU.4V.16G availability in FIN-03.'
    if (-not $availability.available -or $availability.spot) {
        throw "CPU.4V.16G on-demand capacity is not available in FIN-03."
    }
    $types = Invoke-JsonCommand -Command 'verda' -Arguments @(
        '--agent', '--output', 'json', 'instance-types', '--cpu'
    ) -FailureMessage 'Unable to verify the live CPU catalog.'
    $selectedType = @($types | Where-Object { $_.instance_type -eq 'CPU.4V.16G' })
    if ($selectedType.Count -ne 1 -or [double]$selectedType[0].price_per_hour -ne 0.0279) {
        throw "The live CPU.4V.16G catalog entry or price contradicts the accepted contract."
    }
    $images = Invoke-JsonCommand -Command 'verda' -Arguments @(
        '--agent', '--output', 'json', 'images', '--type', 'CPU.4V.16G', '--category', 'ubuntu'
    ) -FailureMessage 'Unable to verify the live Ubuntu image catalog.'
    $selectedImage = @($images | Where-Object { $_.id -eq '77edfb23-bb0d-41cc-a191-dccae45d96fd' })
    if ($selectedImage.Count -ne 1 -or $selectedImage[0].image_type -ne 'ubuntu-24.04') {
        throw "The pinned Ubuntu 24.04 Minimal image is absent or changed."
    }
    Write-Host "[PASS] Live contract: auth valid; FIN-03 capacity available; image/flavor/rate unchanged; balance sufficient."
}

function Invoke-Terraform {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$LogName,
        [int[]]$AcceptedExitCodes = @(0)
    )

    $env:NO_COLOR = '1'
    $logPath = Join-Path $logRoot $LogName
    & terraform "-chdir=$terraformRoot" @Arguments 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -notin $AcceptedExitCodes) {
        throw "Terraform failed with exit code $exitCode. See ignored log $logPath."
    }
    return $exitCode
}

function Initialize-Terraform {
    param([Parameter(Mandatory)]$Paths)

    $env:TF_PLUGIN_CACHE_DIR = Join-Path $repoRoot '.local\terraform-plugin-cache'
    New-Item -ItemType Directory -Force -Path $env:TF_PLUGIN_CACHE_DIR | Out-Null
    Invoke-Terraform -Arguments @(
        'init', '-reconfigure', '-input=false', '-lockfile=readonly',
        "-backend-config=path=$($Paths.StatePath)"
    ) -LogName 'init.log' | Out-Null
    Write-Host "[PASS] Terraform initialized with external encrypted local state and local locking."
}

function Assert-Plan {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][string]$Mode,
        [Parameter(Mandatory)][string]$SummaryPath
    )

    & python (Join-Path $repoRoot 'scripts\infra\assert-plan.py') `
        --root $terraformRoot --plan $Paths.PlanPath --summary $SummaryPath --mode $Mode
    if ($LASTEXITCODE -ne 0) {
        throw "The sanitized Phase 2 plan assertion failed."
    }
}

function Assert-CostEnvelope {
    param([Parameter(Mandatory)][string]$SummaryPath)

    & python (Join-Path $repoRoot 'scripts\infra\cost-envelope.py') `
        --config $costConfig --plan-summary $SummaryPath --output $costSummary
    if ($LASTEXITCODE -ne 0) {
        throw "The Phase 2 cost envelope failed."
    }
}

function Assert-DestructiveConfirmation {
    if (-not $Confirm -or $env:CONFIRM_DESTRUCTIVE_ACTION -ne 'yes') {
        throw "Node replacement requires both -Confirm and CONFIRM_DESTRUCTIVE_ACTION=yes."
    }
}

function Invoke-Node02RepairPlan {
    param([Parameter(Mandatory)]$Paths)

    Assert-DestructiveConfirmation
    Backup-State -Paths $Paths

    $expectedAddresses = @(
        'module.management.module.data_volume["01"].verda_volume.this',
        'module.management.module.data_volume["02"].verda_volume.this',
        'module.management.module.data_volume["03"].verda_volume.this',
        'module.management.module.node["01"].verda_instance.this',
        'module.management.module.node["02"].verda_instance.this',
        'module.management.module.node["03"].verda_instance.this',
        'verda_ssh_key.management'
    )
    $actualAddresses = @(& terraform "-chdir=$terraformRoot" state list 2>$null | Sort-Object)
    if ($LASTEXITCODE -ne 0 -or (Compare-Object $expectedAddresses $actualAddresses)) {
        throw "Recovery refused because the Terraform state address set differs from the seven-resource contract."
    }

    foreach ($node in @('01', '03')) {
        $address = "module.management.module.node[`"$node`"].verda_instance.this"
        & terraform "-chdir=$terraformRoot" untaint $address 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to clear the provider-error taint from healthy node $node."
        }
    }

    $node02Address = 'module.management.module.node["02"].verda_instance.this'
    Invoke-Terraform -Arguments @(
        'plan', '-input=false', '-lock-timeout=60s', '-detailed-exitcode',
        "-replace=$node02Address", "-out=$($Paths.RepairPlanPath)"
    ) -LogName 'node-02-replacement-plan.log' -AcceptedExitCodes @(2) | Out-Null

    $originalPlanPath = $Paths.PlanPath
    try {
        $Paths.PlanPath = $Paths.RepairPlanPath
        Assert-Plan -Paths $Paths -Mode 'node-02-replacement' -SummaryPath $repairSummary
        Assert-CostEnvelope -SummaryPath $repairSummary
    } finally {
        $Paths.PlanPath = $originalPlanPath
    }
    Backup-State -Paths $Paths
    Write-Host "[PASS] Recovery plan is bounded to node 02 compute/OS replacement; the existing data volume is unchanged."
}

function Invoke-Node02RepairApply {
    param([Parameter(Mandatory)]$Paths)

    Assert-DestructiveConfirmation
    if (-not (Test-Path -LiteralPath $Paths.RepairPlanPath -PathType Leaf)) {
        throw "No reviewed node-02 recovery plan exists; run the guarded recovery-plan target first."
    }

    $originalPlanPath = $Paths.PlanPath
    try {
        $Paths.PlanPath = $Paths.RepairPlanPath
        Assert-Plan -Paths $Paths -Mode 'node-02-replacement' -SummaryPath $repairSummary
        Assert-CostEnvelope -SummaryPath $repairSummary
    } finally {
        $Paths.PlanPath = $originalPlanPath
    }

    Backup-State -Paths $Paths
    try {
        Invoke-Terraform -Arguments @(
            'apply', '-input=false', '-lock-timeout=60s', '-auto-approve', $Paths.RepairPlanPath
        ) -LogName 'node-02-replacement-apply.log' | Out-Null
    } finally {
        if (Test-Path -LiteralPath $Paths.StatePath -PathType Leaf) {
            Backup-State -Paths $Paths
        }
    }
    Write-Host "[PASS] Node 02 compute/OS replacement applied; protected data-volume state remains managed."
}

function Backup-State {
    param([Parameter(Mandatory)]$Paths)

    if (-not (Test-Path -LiteralPath $Paths.StatePath -PathType Leaf)) {
        throw "Terraform state is absent; encrypted backup cannot be created."
    }
    $stateBytes = [IO.File]::ReadAllBytes($Paths.StatePath)
    $timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ')
    $backupNonce = [Guid]::NewGuid().ToString('N').Substring(0, 8)
    $backupPath = Join-Path $Paths.BackupDirectory "management-$timestamp-$backupNonce.tfstate.dpapi"
    if ($IsWindows) {
        $encrypted = Protect-BytesForCurrentUser -Bytes $stateBytes
        [IO.File]::WriteAllBytes($backupPath, $encrypted)
        $roundTrip = Unprotect-BytesForCurrentUser -Bytes $encrypted
        if (-not (Test-ByteArraysEqual -Left $stateBytes -Right $roundTrip)) {
            throw "DPAPI backup verification failed."
        }
    } else {
        if (-not (Get-Command age -ErrorAction SilentlyContinue) -or -not $env:VERDA_STATE_AGE_RECIPIENT) {
            throw "Linux state backup requires age and VERDA_STATE_AGE_RECIPIENT."
        }
        & age --recipient $env:VERDA_STATE_AGE_RECIPIENT --output $backupPath $Paths.StatePath
        if ($LASTEXITCODE -ne 0) {
            throw "age-encrypted state backup failed."
        }
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backupPath).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$backupPath.sha256" -Value "$hash  $(Split-Path -Leaf $backupPath)" -Encoding utf8NoBOM
    Write-Host "[PASS] Independent encrypted state backup created and round-trip verified; path/value withheld."
}

function Get-Phase6StateReceipt {
    param([Parameter(Mandatory)]$Paths)

    if (-not (Test-Path -LiteralPath $Paths.StatePath -PathType Leaf)) {
        throw 'Terraform state is absent.'
    }
    $bytes = [IO.File]::ReadAllBytes($Paths.StatePath)
    try {
        $document = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json -Depth 100
    } catch {
        throw 'Terraform state is not valid JSON.'
    }
    if ($document.lineage -notmatch '^[0-9a-f-]{36}$' -or [int64]$document.serial -lt 0) {
        throw 'Terraform state lineage or serial is invalid.'
    }
    [ordered]@{
        state_sha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
        lineage_sha256 = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes([string]$document.lineage))
        ).ToLowerInvariant()
        serial = [int64]$document.serial
    }
}

function Assert-Phase6ControlArguments {
    param([switch]$RequirePlanHash)
    if ($OperationId -notmatch '^[0-9a-f]{64}$') { throw 'Phase 6 operation ID must be a SHA-256 nonce.' }
    if (-not $SavedPlan) { throw 'An external Phase 6 saved plan path is required.' }
    $script:SavedPlan = [IO.Path]::GetFullPath($SavedPlan)
    Assert-OutsideRepository -Path $script:SavedPlan -Label 'Phase 6 saved plan'
    if ($RequirePlanHash -and $ExpectedPlanSha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'Expected plan SHA-256 is invalid.'
    }
    if ($ExpectedStateLineageSha256 -notmatch '^[0-9a-f]{64}$' -or $ExpectedStateSerial -lt 0) {
        throw 'Expected Terraform state lineage/serial is invalid.'
    }
}

function Invoke-Phase6Terraform {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$LogName,
        [int[]]$AcceptedExitCodes = @(0)
    )

    Protect-Directory -Path $logRoot
    $env:NO_COLOR = '1'
    $logPath = Join-Path $logRoot $LogName
    & terraform "-chdir=$terraformRoot" @Arguments *> $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -notin $AcceptedExitCodes) {
        throw "Protected Terraform command failed with exit code $exitCode; raw diagnostic withheld."
    }
    $exitCode
}

function Initialize-Phase6Terraform {
    param([Parameter(Mandatory)]$Paths)

    $env:TF_PLUGIN_CACHE_DIR = Join-Path $repoRoot '.local\terraform-plugin-cache'
    New-Item -ItemType Directory -Force -Path $env:TF_PLUGIN_CACHE_DIR | Out-Null
    Invoke-Phase6Terraform -Arguments @(
        'init', '-reconfigure', '-input=false', '-lockfile=readonly',
        "-backend-config=path=$($Paths.StatePath)"
    ) -LogName 'phase6-init.log' | Out-Null
}

function Invoke-Phase6ResizePlan {
    param([Parameter(Mandatory)]$Paths)

    Assert-Phase6ControlArguments
    Assert-Credentials
    $receipt = Get-Phase6StateReceipt -Paths $Paths
    if ($receipt.lineage_sha256 -ne $ExpectedStateLineageSha256 -or $receipt.serial -ne $ExpectedStateSerial) {
        throw 'Terraform state lineage/serial differs from the reviewed planning boundary.'
    }
    Backup-State -Paths $Paths
    $exitCode = Invoke-Phase6Terraform -Arguments @(
        'plan', '-input=false', '-lock-timeout=60s', '-detailed-exitcode', "-out=$SavedPlan"
    ) -LogName "phase6-plan-$OperationId.log" -AcceptedExitCodes @(2)
    if ($exitCode -ne 2) { throw 'Phase 6 plan must contain exactly the reviewed non-empty change.' }
    $planHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $SavedPlan).Hash.ToLowerInvariant()
    [ordered]@{
        schema_version = 1
        status = 'PLAN_CREATED_REVIEW_REQUIRED'
        operation_id = $OperationId
        plan_sha256 = $planHash
        state_lineage_sha256 = $receipt.lineage_sha256
        state_serial = $receipt.serial
        raw_values_recorded = $false
    } | ConvertTo-Json -Compress
}

function Invoke-Phase6ResizeApply {
    param([Parameter(Mandatory)]$Paths)

    Assert-Phase6ControlArguments -RequirePlanHash
    Assert-DestructiveConfirmation
    Assert-Credentials
    if (-not (Test-Path -LiteralPath $SavedPlan -PathType Leaf)) { throw 'Reviewed saved plan is absent.' }
    $planStream = [IO.File]::Open($SavedPlan, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $planHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($planStream)).ToLowerInvariant()
        if ($planHash -ne $ExpectedPlanSha256) { throw 'Saved plan bytes differ from independent review.' }
        $before = Get-Phase6StateReceipt -Paths $Paths
        if ($before.lineage_sha256 -ne $ExpectedStateLineageSha256 -or $before.serial -ne $ExpectedStateSerial) {
            throw 'Terraform state lineage/serial differs from the reviewed apply boundary.'
        }
        Backup-State -Paths $Paths
        try {
            Invoke-Phase6Terraform -Arguments @(
                'apply', '-input=false', '-lock-timeout=60s', $SavedPlan
            ) -LogName "phase6-apply-$OperationId.log" | Out-Null
        } finally {
            if (Test-Path -LiteralPath $Paths.StatePath -PathType Leaf) { Backup-State -Paths $Paths }
        }
        $after = Get-Phase6StateReceipt -Paths $Paths
        if ($after.lineage_sha256 -ne $before.lineage_sha256 -or $after.serial -le $before.serial) {
            throw 'Post-apply state lineage changed or serial did not advance.'
        }
        [ordered]@{
            schema_version = 1
            status = 'APPLY_COMPLETE_RECOVERY_REQUIRED'
            operation_id = $OperationId
            plan_sha256 = $planHash
            state_lineage_sha256 = $after.lineage_sha256
            state_serial_before = $before.serial
            state_serial_after = $after.serial
            raw_values_recorded = $false
        } | ConvertTo-Json -Compress
    } finally {
        $planStream.Dispose()
    }
}

function Invoke-Phase6ResizeOutput {
    param([Parameter(Mandatory)]$Paths)

    if ($OperationId -notmatch '^[0-9a-f]{64}$') { throw 'Phase 6 operation ID must be a SHA-256 nonce.' }
    if ($ExpectedStateLineageSha256 -notmatch '^[0-9a-f]{64}$' -or $ExpectedStateSerial -lt 0) {
        throw 'Expected Terraform state lineage/serial is invalid.'
    }
    if (-not $InventoryOutput -or -not $KnownHosts) { throw 'External inventory and known-hosts paths are required.' }
    $inventoryDestination = [IO.Path]::GetFullPath($InventoryOutput)
    $knownHostsPath = [IO.Path]::GetFullPath($KnownHosts)
    Assert-OutsideRepository -Path $inventoryDestination -Label 'Phase 6 recovery inventory'
    Assert-OutsideRepository -Path $knownHostsPath -Label 'Phase 6 known-hosts file'
    Protect-Directory -Path (Split-Path -Parent $inventoryDestination)
    if (-not (Test-Path -LiteralPath $knownHostsPath -PathType Leaf)) { throw 'Verified known-hosts file is absent.' }
    if (-not (Test-Path -LiteralPath $Paths.SshPrivateKey -PathType Leaf)) { throw 'Protected SSH private key is absent.' }
    if ($IsWindows) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $acl = Get-Acl -LiteralPath $Paths.SshPrivateKey
        if (-not $acl.Owner.Equals($identity, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'SSH private-key ownership differs from the protected operator identity.'
        }
        $unexpectedAllow = @($acl.Access | Where-Object {
            $_.AccessControlType -eq 'Allow' -and
            $_.IdentityReference.Value -notin @($identity, 'NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators')
        })
        if ($acl.AreAccessRulesProtected -ne $true -or $unexpectedAllow.Count -ne 0) {
            throw 'SSH private-key ACL is not owner-exclusive.'
        }
    } else {
        $protection = (& stat -c '%u:%a' -- $Paths.SshPrivateKey 2>$null).Trim()
        $statExit = $LASTEXITCODE
        $currentUid = (& id -u 2>$null).Trim()
        $idExit = $LASTEXITCODE
        if ($statExit -ne 0 -or $idExit -ne 0 -or $protection -notin @("${currentUid}:600", "${currentUid}:400")) {
            throw 'SSH private-key owner or mode is not exact 0600/0400.'
        }
    }
    $receipt = Get-Phase6StateReceipt -Paths $Paths
    if ($receipt.lineage_sha256 -ne $ExpectedStateLineageSha256 -or $receipt.serial -ne $ExpectedStateSerial) {
        throw 'Terraform state lineage/serial differs from the reviewed inventory boundary.'
    }
    $generatorOutput = & python (Join-Path $repoRoot 'scripts\phase6\generate-resize-inventory.py') `
        --repository $repoRoot --terraform-root $terraformRoot --output $inventoryDestination `
        --private-key $Paths.SshPrivateKey --known-hosts $knownHostsPath 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Strict post-replacement inventory generation failed; raw diagnostic withheld.' }
    $publicKey = & ssh-keygen -y -f $Paths.SshPrivateKey 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $publicKey) { throw 'Unable to derive SSH public-key metadata.' }
    $publicKeyFingerprint = [Convert]::ToHexString(
        [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes(($publicKey -join "`n").Trim()))
    ).ToLowerInvariant()
    [ordered]@{
        schema_version = 1
        status = 'STRICT_INVENTORY_CREATED_REVIEW_REQUIRED'
        operation_id = $OperationId
        state_lineage_sha256 = $receipt.lineage_sha256
        state_serial = $receipt.serial
        inventory_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $inventoryDestination).Hash.ToLowerInvariant()
        known_hosts_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $knownHostsPath).Hash.ToLowerInvariant()
        private_key_public_sha256 = $publicKeyFingerprint
        raw_values_recorded = $false
    } | ConvertTo-Json -Compress
}

function Invoke-Inventory {
    param([Parameter(Mandatory)]$Paths)

    & python (Join-Path $repoRoot 'scripts\infra\generate-inventory.py') `
        --root $terraformRoot --output $inventoryPath --private-key $Paths.SshPrivateKey
    if ($LASTEXITCODE -ne 0) {
        throw "Inventory generation failed."
    }
}

function Verify-Hosts {
    param([Parameter(Mandatory)]$Paths)

    $nodes = Invoke-JsonCommand -Command 'terraform' -Arguments @(
        "-chdir=$terraformRoot", 'output', '-json', 'nodes'
    ) -FailureMessage 'Unable to read node outputs for SSH verification.'
    if (@($nodes.PSObject.Properties).Count -ne 3) {
        throw "Terraform does not report exactly three management nodes."
    }
    $publicAddresses = @($nodes.PSObject.Properties.Value | ForEach-Object { $_.public_address })
    if (@($publicAddresses | Sort-Object -Unique).Count -ne 3) {
        throw "Verda does not report a unique public address for every management node."
    }
    $knownHosts = Join-Path $repoRoot '.local\ssh\known_hosts'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $knownHosts) | Out-Null
    foreach ($property in ($nodes.PSObject.Properties | Sort-Object Name)) {
        $node = $property.Value
        if ($node.attachment_instance_id -ne $node.id) {
            throw "Persistent volume attachment verification failed for $($property.Name)."
        }
        $verified = $false
        $remoteCommand = 'test "$(hostname)" = ''{0}'' && printf phase2-ssh-ok' -f $property.Name
        for ($attempt = 1; $attempt -le 40; $attempt++) {
            $sshOutput = & ssh -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes `
                -o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile=$knownHosts" `
                -i $Paths.SshPrivateKey "root@$($node.public_address)" `
                $remoteCommand 2>&1
            if ($LASTEXITCODE -eq 0 -and ($sshOutput -join "`n") -match 'phase2-ssh-ok') {
                $verified = $true
                break
            }
            Start-Sleep -Seconds 15
        }
        if (-not $verified) {
            throw "SSH verification failed for $($property.Name) after the bounded retry window."
        }
        Write-Host "[PASS] SSH key authentication and hostname verified for $($property.Name)."
    }
}

function Write-LiveCostReport {
    $status = Invoke-JsonCommand -Command 'verda' -Arguments @('--agent', '--output', 'json', 'status') `
        -FailureMessage 'Unable to read the live Verda cost status.'
    $nodes = Invoke-JsonCommand -Command 'terraform' -Arguments @(
        "-chdir=$terraformRoot", 'output', '-json', 'nodes'
    ) -FailureMessage 'Unable to read Terraform node outputs for cost reconciliation.'
    $compute = 0.0
    foreach ($node in $nodes.PSObject.Properties.Value) {
        $compute += [double]$node.compute_price_per_hour
    }
    $storage = 540.0 * 0.2 / 730.0
    $expected = $compute + $storage
    $reportedBurn = [double]$status.financials.burn_rate_hourly
    $report = [ordered]@{
        schema_version                = 1
        generated_at                  = (Get-Date).ToUniversalTime().ToString('o')
        currency                      = 'USD'
        provider_compute_hourly       = [Math]::Round($compute, 5)
        modeled_storage_hourly        = [Math]::Round($storage, 5)
        expected_total_hourly         = [Math]::Round($expected, 5)
        verda_reported_burn_hourly    = [Math]::Round($reportedBurn, 5)
        expected_daily                = [Math]::Round($expected * 24, 5)
        balance_at_reconciliation     = [Math]::Round([double]$status.financials.balance, 2)
        resource_count_status         = if ($status.instances.total -eq 3 -and $status.volumes.total -eq 6) { 'PASS' } else { 'FAIL' }
        rate_reconciliation_tolerance = 0.001
        rate_reconciliation_status    = if ([Math]::Abs($reportedBurn - $expected) -le 0.001) { 'PASS' } else { 'FAIL' }
    }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'live-cost.json') -Encoding utf8NoBOM
    if ($report.resource_count_status -ne 'PASS' -or $report.rate_reconciliation_status -ne 'PASS') {
        throw "Live cost/resource reconciliation failed."
    }
    Write-Host "[PASS] Live resource count and hourly cost reconcile within the documented tolerance."
}

$paths = Get-ExternalPaths
$phase6ProtectedTarget = $Target -in @('phase6-resize-plan', 'phase6-resize-apply', 'phase6-resize-output')
$phase6StateOpened = $false
if (-not $phase6ProtectedTarget) {
    Write-Host "[phase 2] target=$Target cluster=$Cluster credentials=process-only cloud-mutation=$($Target -in @('apply', 'repair-node-02-apply', 'destroy'))"
}

try {
switch ($Target) {
    'phase6-resize-plan' {
        Assert-Credentials
        Initialize-LocalBoundary -Paths $paths 6>$null
        Open-SealedState -Paths $paths 6>$null
        $phase6StateOpened = $true
        Initialize-Phase6Terraform -Paths $paths 6>$null
        Invoke-Phase6ResizePlan -Paths $paths 6>$null
    }
    'phase6-resize-apply' {
        throw 'Phase 6 apply is intentionally disabled until trusted collectors, pinned container recovery, and journal integration are complete.'
    }
    'phase6-resize-output' {
        Assert-Credentials
        Initialize-LocalBoundary -Paths $paths 6>$null
        Open-SealedState -Paths $paths 6>$null
        $phase6StateOpened = $true
        Initialize-Phase6Terraform -Paths $paths 6>$null
        Invoke-Phase6ResizeOutput -Paths $paths 6>$null
    }
    'init' {
        Assert-Credentials
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Initialize-Terraform -Paths $paths
    }
    'plan' {
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        Invoke-Terraform -Arguments @(
            'plan', '-input=false', '-lock-timeout=60s', '-detailed-exitcode', "-out=$($paths.PlanPath)"
        ) -LogName 'plan.log' -AcceptedExitCodes @(0, 2) | Out-Null
        Assert-Plan -Paths $paths -Mode 'auto' -SummaryPath $planSummary
        Assert-CostEnvelope -SummaryPath $planSummary
    }
    'apply' {
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        if (-not (Test-Path -LiteralPath $paths.PlanPath -PathType Leaf)) {
            throw "No reviewed external saved plan exists; run make infra-plan CLUSTER=management first."
        }
        Assert-Plan -Paths $paths -Mode 'auto' -SummaryPath $planSummary
        Assert-CostEnvelope -SummaryPath $planSummary
        Invoke-Terraform -Arguments @('apply', '-input=false', '-lock-timeout=60s', '-auto-approve', $paths.PlanPath) `
            -LogName 'apply.log' | Out-Null
        Backup-State -Paths $paths
    }
    'repair-node-02-plan' {
        Assert-DestructiveConfirmation
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        Invoke-Node02RepairPlan -Paths $paths
    }
    'repair-node-02-apply' {
        Assert-DestructiveConfirmation
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        Invoke-Node02RepairApply -Paths $paths
    }
    'inventory' {
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Initialize-Terraform -Paths $paths
        Invoke-Inventory -Paths $paths
    }
    'verify-hosts' {
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        Verify-Hosts -Paths $paths
    }
    'lifecycle-check' {
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        $fullDestroyLog = Join-Path $logRoot 'full-destroy-rejection.log'
        & terraform "-chdir=$terraformRoot" plan -destroy -input=false -lock-timeout=60s 2>&1 |
            Tee-Object -FilePath $fullDestroyLog | Out-Null
        if ($LASTEXITCODE -eq 0) {
            throw "Full destroy was not rejected by persistent-volume prevent_destroy."
        }
        $fullDestroyText = Get-Content -LiteralPath $fullDestroyLog -Raw
        if ($fullDestroyText -notmatch 'prevent_destroy') {
            throw "Full destroy failed for an unexpected reason."
        }
        Write-Host "[PASS] Negative lifecycle gate: unreviewed full destroy is rejected."
        Invoke-Terraform -Arguments @(
            'plan', '-destroy', '-input=false', '-lock-timeout=60s',
            '-target=module.management.module.node', "-out=$($paths.RollbackPlanPath)"
        ) -LogName 'compute-rollback-plan.log' | Out-Null
        $originalPlanPath = $paths.PlanPath
        $paths.PlanPath = $paths.RollbackPlanPath
        Assert-Plan -Paths $paths -Mode 'compute-rollback' -SummaryPath $rollbackSummary
        $paths.PlanPath = $originalPlanPath
    }
    'cost-report' {
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        Write-LiveCostReport
    }
    'state-audit' {
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Initialize-Terraform -Paths $paths
        $addresses = @(& terraform "-chdir=$terraformRoot" state list 2>$null)
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to enumerate Terraform state addresses."
        }
        $audit = [ordered]@{
            schema_version = 1
            generated_at = (Get-Date).ToUniversalTime().ToString('o')
            total_resources = $addresses.Count
            ssh_keys = @($addresses | Where-Object { $_ -match '(^|\.)verda_ssh_key\.' }).Count
            instances = @($addresses | Where-Object { $_ -match '\.verda_instance\.' }).Count
            data_volumes = @($addresses | Where-Object { $_ -match '\.verda_volume\.' }).Count
            resource_addresses = @($addresses | Sort-Object)
            resource_ids_in_report = $false
        }
        $audit | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'state-audit.json') -Encoding utf8NoBOM
        Backup-State -Paths $paths
        Write-Host "[PASS] State audit and independent encrypted backup completed; IDs and state contents withheld."
    }
    'destroy' {
        if (-not $Confirm -or $env:CONFIRM_DESTRUCTIVE_ACTION -ne 'yes') {
            throw "Compute rollback requires both -Confirm and CONFIRM_DESTRUCTIVE_ACTION=yes."
        }
        Initialize-LocalBoundary -Paths $paths
        Open-SealedState -Paths $paths
        Assert-LiveContract
        Initialize-Terraform -Paths $paths
        Invoke-Terraform -Arguments @(
            'destroy', '-auto-approve', '-input=false', '-lock-timeout=60s',
            '-target=module.management.module.node'
        ) -LogName 'compute-rollback.log' | Out-Null
        Backup-State -Paths $paths
        Write-Host "[PASS] Compute-only rollback completed; protected data volumes remain managed."
    }
}
} finally {
    if ($phase6ProtectedTarget -and $phase6StateOpened) {
        Close-SealedState -Paths $paths 6>$null
    } elseif (-not $phase6ProtectedTarget) {
        Close-SealedState -Paths $paths
    }
}
