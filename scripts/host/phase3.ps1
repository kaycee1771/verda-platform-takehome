[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('configure', 'verify')]
    [string]$Target,
    [ValidateSet('management')]
    [string]$Cluster = 'management'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$inventorySource = Join-Path $repoRoot 'infra\ansible\inventories\generated\management.yaml'
$runtimeRoot = Join-Path $repoRoot '.local\phase3'
$reportRoot = Join-Path $repoRoot '.local\reports\phase3'
$logRoot = Join-Path $repoRoot '.local\logs\phase3'
$rootInventory = Join-Path $runtimeRoot 'inventory-root.yaml'
$adminInventory = Join-Path $runtimeRoot 'inventory-admin.yaml'
$runtimeVars = Join-Path $runtimeRoot 'runtime-vars.json'
$runtimeMetadata = Join-Path $runtimeRoot 'runtime-metadata.json'
$qualityImage = 'verda-platform-quality:phase1-2026-08-16'
New-Item -ItemType Directory -Force -Path $runtimeRoot, $reportRoot, $logRoot | Out-Null

function Get-ExternalPaths {
    $base = if ($env:VERDA_TAKEHOME_CONFIG_DIR) {
        $env:VERDA_TAKEHOME_CONFIG_DIR
    } else {
        Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'VerdaPlatformTakehome'
    }
    $base = [IO.Path]::GetFullPath($base)
    $backupBase = if ($IsWindows) {
        if ($env:VERDA_TF_BACKUP_DIR) {
            $env:VERDA_TF_BACKUP_DIR
        } else {
            Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'VerdaPlatformTakehome\state-backups'
        }
    } else {
        if ($env:VERDA_TF_BACKUP_DIR) {
            $env:VERDA_TF_BACKUP_DIR
        } else {
            $stateHome = if ($env:XDG_STATE_HOME) { $env:XDG_STATE_HOME } else { Join-Path $env:HOME '.local/state' }
            Join-Path $stateHome 'verda-takehome-backups'
        }
    }
    $backupBase = [IO.Path]::GetFullPath($backupBase)
    $repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    foreach ($candidate in @($base, $backupBase)) {
        if ($candidate.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Phase 3 state, keys, backups, and pinned host identities must remain outside the repository.'
        }
    }
    return [pscustomobject]@{
        Base = $base
        BackupDirectory = $backupBase
        PrivateKey = Join-Path $base 'ssh\id_ed25519'
        PublicKey = Join-Path $base 'ssh\id_ed25519.pub'
        KnownHosts = Join-Path $base 'ssh\known_hosts_phase3'
        SealedState = Join-Path $base 'terraform\management.tfstate.dpapi'
    }
}

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is unavailable."
    }
}

function Assert-Phase3Prerequisites {
    param([Parameter(Mandatory)]$Paths)
    foreach ($command in @('docker', 'python', 'pwsh', 'ssh', 'ssh-keygen')) {
        Assert-Command -Name $command
    }
    foreach ($file in @($inventorySource, $Paths.PrivateKey, $Paths.PublicKey, $Paths.SealedState)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "A required external Phase 2 artifact is absent: $([IO.Path]::GetFileName($file))."
        }
    }
    & docker image inspect $qualityImage 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Pinned quality image '$qualityImage' is missing; run make bootstrap-tools."
    }
}

function Assert-CloudCredentials {
    foreach ($name in @('VERDA_CLIENT_ID', 'VERDA_CLIENT_SECRET')) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))) {
            throw "$name is required in process memory for the read-only Phase 2 boundary check."
        }
    }
}

function Invoke-Phase2ReadOnlyPreflight {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][object[]]$Nodes
    )
    Assert-CloudCredentials
    $phase2 = Join-Path $repoRoot 'scripts\infra\phase2.ps1'
    foreach ($phase2Target in @('plan', 'state-audit', 'cost-report', 'inventory')) {
        Write-Host "[phase 3] preflight=$phase2Target cloud-mutation=false"
        & pwsh -NoLogo -NoProfile -NonInteractive -File $phase2 `
            -Target $phase2Target -Cluster management
        if ($LASTEXITCODE -ne 0) {
            throw "Read-only Phase 2 preflight '$phase2Target' failed."
        }
    }
    $planSummaryPath = Join-Path $repoRoot '.local\reports\phase2\plan-summary.json'
    $stateAuditPath = Join-Path $repoRoot '.local\reports\phase2\state-audit.json'
    $costPath = Join-Path $repoRoot '.local\reports\phase2\live-cost.json'
    $planSummary = Get-Content -LiteralPath $planSummaryPath -Raw | ConvertFrom-Json
    $stateAudit = Get-Content -LiteralPath $stateAuditPath -Raw | ConvertFrom-Json
    $cost = Get-Content -LiteralPath $costPath -Raw | ConvertFrom-Json
    $expectedNodes = @(1..3 | ForEach-Object { 'verda-mgmt-server-{0:d2}' -f $_ })
    $expectedDataVolumes = @(1..3 | ForEach-Object { 'verda-mgmt-data-{0:d2}' -f $_ })
    $nodeNames = @($Nodes | ForEach-Object { $_.name } | Sort-Object)
    $uniqueEndpoints = @($Nodes | ForEach-Object { $_.public_address } | Sort-Object -Unique)
    if ($planSummary.mode -ne 'no-drift' -or
        $stateAudit.total_resources -ne 7 -or $stateAudit.ssh_keys -ne 1 -or
        $stateAudit.instances -ne 3 -or $stateAudit.data_volumes -ne 3 -or
        (Compare-Object $expectedNodes @($planSummary.instance_names | Sort-Object)) -or
        (Compare-Object $expectedDataVolumes @($planSummary.data_volume_names | Sort-Object)) -or
        (Compare-Object $expectedNodes $nodeNames) -or $uniqueEndpoints.Count -ne 3 -or
        $cost.resource_count_status -ne 'PASS' -or $cost.rate_reconciliation_status -ne 'PASS') {
        throw 'The live Phase 2 resource, state, drift, or cost boundary is not green.'
    }
    $backups = @(Get-ChildItem -LiteralPath $Paths.BackupDirectory -Filter '*.tfstate.dpapi' -File |
        Sort-Object LastWriteTimeUtc -Descending)
    if ($backups.Count -lt 1) {
        throw 'No independent encrypted Terraform state backup is present.'
    }
    $latestBackup = $backups[0]
    $checksumPath = "$($latestBackup.FullName).sha256"
    if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
        throw 'The latest encrypted Terraform state backup has no checksum sidecar.'
    }
    $expectedHash = (Get-Content -LiteralPath $checksumPath -Raw).Split([char[]]" `t`r`n", 2)[0].ToLowerInvariant()
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $latestBackup.FullName).Hash.ToLowerInvariant()
    if ($expectedHash -ne $actualHash) {
        throw 'The latest encrypted Terraform state backup checksum does not match.'
    }
    [ordered]@{
        schema_version = 1
        checked_at = (Get-Date).ToUniversalTime().ToString('o')
        terraform_mode = $planSummary.mode
        state_resources = $stateAudit.total_resources
        instance_count = $stateAudit.instances
        volume_count = $stateAudit.instances + $stateAudit.data_volumes
        unique_endpoint_count = $uniqueEndpoints.Count
        encrypted_state_backup_verified = $true
        expected_hourly_usd = $cost.expected_total_hourly
        reported_hourly_usd = $cost.verda_reported_burn_hourly
        balance_usd = $cost.balance_at_reconciliation
        cloud_mutation = $false
        credentials_persisted = $false
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'preflight.json') -Encoding utf8NoBOM
    Write-Host '[PASS] Live Phase 2 boundary: 3 instances, 6 volumes, 3 endpoints, zero drift, state backup, and cost green.'
}

function Get-KnownHostKeyMaterial {
    param(
        [Parameter(Mandatory)][string]$Address,
        [Parameter(Mandatory)][string]$KnownHosts
    )
    $lines = @(& ssh-keygen -F $Address -f $KnownHosts 2>$null | Where-Object { $_ -notmatch '^#' })
    if ($LASTEXITCODE -ne 0 -or $lines.Count -lt 1) {
        throw 'A current endpoint is absent from the pinned host-key boundary.'
    }
    return @($lines | ForEach-Object {
        $fields = $_ -split '\s+'
        if ($fields.Count -lt 3) { throw 'A pinned host-key entry is malformed.' }
        "$($fields[1]) $($fields[2])"
    } | Sort-Object -Unique)
}

function Initialize-PinnedKnownHosts {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][object[]]$Nodes
    )
    $phase2KnownHosts = Join-Path $repoRoot '.local\ssh\known_hosts'
    if (-not (Test-Path -LiteralPath $phase2KnownHosts -PathType Leaf)) {
        throw 'The Phase 2 pinned known-hosts file is absent; refuse unauthenticated key discovery.'
    }
    if (-not (Test-Path -LiteralPath $Paths.KnownHosts -PathType Leaf)) {
        $entries = foreach ($node in $Nodes) {
            @(& ssh-keygen -F $node.public_address -f $phase2KnownHosts 2>$null | Where-Object { $_ -notmatch '^#' })
        }
        if ($entries.Count -lt 3) {
            throw 'Unable to promote all Phase 2 host identities into the external Phase 3 boundary.'
        }
        $entries | Sort-Object -Unique | Set-Content -LiteralPath $Paths.KnownHosts -Encoding utf8NoBOM
    }
    foreach ($node in $Nodes) {
        $phase2Key = Get-KnownHostKeyMaterial -Address $node.public_address -KnownHosts $phase2KnownHosts
        $phase3Key = Get-KnownHostKeyMaterial -Address $node.public_address -KnownHosts $Paths.KnownHosts
        if (Compare-Object -ReferenceObject $phase2Key -DifferenceObject $phase3Key) {
            throw "Pinned host identity changed for $($node.name); manual recovery verification is required."
        }
    }
    Write-Host '[PASS] All three SSH identities match the Phase 2 pins; strict checking is mandatory.'
}

function New-Phase3Runtime {
    param([Parameter(Mandatory)][string]$AdminCidrs)
    $runtimePreparationOutput = @(& python (Join-Path $repoRoot 'scripts\host\prepare-runtime.py') `
        --inventory $inventorySource `
        --root-output $rootInventory `
        --admin-output $adminInventory `
        --vars-output $runtimeVars `
        --metadata-output $runtimeMetadata `
        --admin-cidrs $AdminCidrs)
    if ($LASTEXITCODE -ne 0) {
        throw 'Strict Phase 3 runtime generation failed.'
    }
    $metadata = Get-Content -LiteralPath $runtimeMetadata -Raw | ConvertFrom-Json
    if (@($metadata.nodes).Count -ne 3 -or @($metadata.nodes.public_address | Sort-Object -Unique).Count -ne 3) {
        throw 'Phase 3 runtime does not contain exactly three unique endpoints.'
    }
    if ($runtimePreparationOutput.Count -lt 1 -or $runtimePreparationOutput[-1] -notmatch '^\[PASS\]') {
        throw 'Strict Phase 3 runtime generation did not emit its success contract.'
    }
    Write-Host '[PASS] Prepared strict ignored Phase 3 runtime for exactly three hosts.'
    return @($metadata.nodes)
}

function Invoke-AnsiblePlaybook {
    param(
        [Parameter(Mandatory)][string]$Inventory,
        [Parameter(Mandatory)][string]$Playbook,
        [Parameter(Mandatory)][string]$LogName,
        [string]$Limit = ''
    )
    $paths = Get-ExternalPaths
    $inventoryRelative = ((Resolve-Path $Inventory -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $playbookRelative = ((Resolve-Path $Playbook -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $varsRelative = ((Resolve-Path $runtimeVars -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $groupVars = Join-Path $repoRoot 'infra\ansible\inventories\group_vars\management_servers.yml'
    $groupVarsRelative = ((Resolve-Path $groupVars -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $inventoryContainer = "/workspace/$inventoryRelative"
    $playbookContainer = "/workspace/$playbookRelative"
    $varsContainer = "/workspace/$varsRelative"
    $groupVarsContainer = "/workspace/$groupVarsRelative"
    $command = "install -d -m 0700 /tmp/home && " +
        "install -m 0600 /run/source/phase3-ssh-key /tmp/phase3-ssh-key && " +
        "exec ansible-playbook --inventory '$inventoryContainer' '$playbookContainer' " +
        "--extra-vars '@$groupVarsContainer' --extra-vars '@$varsContainer'"
    if ($Limit) {
        $command += " --limit '$Limit'"
    }
    $dockerArgs = @(
        'run', '--rm', '--network', 'bridge', '--read-only',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
        '--pids-limit', '512',
        '--volume', "${repoRoot}:/workspace",
        '--volume', "$($paths.PrivateKey):/run/source/phase3-ssh-key:ro",
        '--volume', "$($paths.PublicKey):/run/secrets/phase3_ssh_key.pub:ro",
        '--volume', "$($paths.KnownHosts):/run/config/known_hosts:ro",
        '--workdir', '/workspace',
        '--env', 'HOME=/tmp/home',
        '--env', 'ANSIBLE_CONFIG=/workspace/infra/ansible/ansible.cfg',
        '--env', 'ANSIBLE_LOCAL_TEMP=/tmp/ansible-local',
        $qualityImage, 'bash', '-lc', $command
    )
    $logPath = Join-Path $logRoot $LogName
    & docker @dockerArgs 2>&1 | Tee-Object -FilePath $logPath
    if ($LASTEXITCODE -ne 0) {
        throw "Ansible playbook failed; see ignored log $logPath."
    }
}

function Invoke-StrictSsh {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)]$Node,
        [Parameter(Mandatory)][string]$User,
        [Parameter(Mandatory)][string]$RemoteCommand
    )
    $result = @(& ssh -i $Paths.PrivateKey -o BatchMode=yes -o IdentitiesOnly=yes `
        -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$($Paths.KnownHosts)" `
        -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 `
        "$User@$($Node.public_address)" $RemoteCommand 2>&1)
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($result -join "`n") }
}

function Test-AccountAccess {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)]$Node,
        [Parameter(Mandatory)][string]$User
    )
    $privilegeCheck = if ($User -eq 'root') { 'true' } else { 'sudo -n true' }
    $remote = 'test "$(hostname)" = ''{0}'' && {1}' -f $Node.name, $privilegeCheck
    return (Invoke-StrictSsh -Paths $Paths -Node $Node -User $User -RemoteCommand $remote).ExitCode -eq 0
}

function Assert-HardenedAccess {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][object[]]$Nodes
    )
    foreach ($node in $Nodes) {
        if (-not (Test-AccountAccess -Paths $Paths -Node $node -User 'platform-admin')) {
            throw "Named administrator access failed for $($node.name)."
        }
        if ((Invoke-StrictSsh -Paths $Paths -Node $node -User 'root' -RemoteCommand 'true').ExitCode -eq 0) {
            throw "Direct root SSH remains enabled for $($node.name)."
        }
        $passwordAttempt = @(& ssh -o BatchMode=yes -o PubkeyAuthentication=no `
            -o PreferredAuthentications=password,keyboard-interactive `
            -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$($Paths.KnownHosts)" `
            -o ConnectTimeout=5 "platform-admin@$($node.public_address)" 'true' 2>&1)
        if ($LASTEXITCODE -eq 0) {
            throw "Password-only SSH unexpectedly succeeded for $($node.name)."
        }
        Write-Host "[PASS] $($node.name): strict key admin succeeds; root and password-only SSH are denied."
    }
}

function Assert-SecondRunClean {
    param(
        [Parameter(Mandatory)][string[]]$LogNames,
        [string]$Description = 'Second complete convergence'
    )
    foreach ($logName in $LogNames) {
        $text = Get-Content -LiteralPath (Join-Path $logRoot $logName) -Raw
        $recaps = [regex]::Matches($text, '(?m)^verda-mgmt-server-0[1-3]\s+:.*changed=(\d+)')
        if ($recaps.Count -ne 3) {
            throw "Unable to parse all three Ansible recaps from $logName."
        }
        foreach ($recap in $recaps) {
            if ([int]$recap.Groups[1].Value -ne 0) {
                throw "Second convergence was not clean in $logName."
            }
        }
    }
    Write-Host "[PASS] $Description reported changed=0 on every host."
}

function Test-TcpPort {
    param([Parameter(Mandatory)][string]$Address, [Parameter(Mandatory)][int]$Port)
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $attempt = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $attempt.AsyncWaitHandle.WaitOne(1500)) { return $false }
        $client.EndConnect($attempt)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Assert-ExternalPortBoundary {
    param([Parameter(Mandatory)][object[]]$Nodes)
    $forbidden = @(80, 443, 2379, 2380, 2381, 4240, 6443, 9090, 9345, 10250, 30000, 31000, 32767)
    $scanRows = @()
    foreach ($node in $Nodes) {
        if (-not (Test-TcpPort -Address $node.public_address -Port 22)) {
            throw "Approved-source SSH is not reachable on $($node.name)."
        }
        foreach ($port in $forbidden) {
            if (Test-TcpPort -Address $node.public_address -Port $port) {
                throw "Forbidden public TCP port $port is reachable on $($node.name)."
            }
        }
        $scanRows += [ordered]@{
            node = $node.name
            allowed_tcp = @{ '22' = 'open' }
            denied_tcp = [ordered]@{ }
        }
        foreach ($port in $forbidden) {
            $scanRows[-1].denied_tcp["$port"] = 'filtered-or-closed'
        }
        Write-Host "[PASS] $($node.name): SSH allowed; HTTP/S, API, supervisor, etcd, kubelet, and NodePort probes denied."
    }
    [ordered]@{
        schema_version = 1
        scanned_at = (Get-Date).ToUniversalTime().ToString('o')
        source = 'approved-phase3-operator-path'
        endpoint_values_recorded = $false
        nodes = $scanRows
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reportRoot 'external-port-scan.json') -Encoding utf8NoBOM
}

function Assert-PeerReachabilityMatrix {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][object[]]$Nodes
    )
    $matrix = @()
    foreach ($source in $Nodes) {
        foreach ($destination in @($Nodes | Where-Object { $_.name -ne $source.name })) {
            $command = "ping -I wg-mgmt -c 3 -W 2 -M do -s 1392 $($destination.wireguard_address) >/dev/null"
            $probe = Invoke-StrictSsh -Paths $Paths -Node $source -User 'platform-admin' -RemoteCommand $command
            if ($probe.ExitCode -ne 0) {
                throw "WireGuard no-fragment reachability failed from $($source.name) to $($destination.name)."
            }
            $matrix += [ordered]@{
                source = $source.name
                destination = $destination.name
                status = 'PASS'
                payload_bytes = 1392
                fragmentation = 'forbidden'
            }
        }
    }
    [ordered]@{
        schema_version = 1
        tested_at = (Get-Date).ToUniversalTime().ToString('o')
        wireguard_mtu = 1420
        endpoint_values_recorded = $false
        paths = $matrix
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'peer-reachability.json') -Encoding utf8NoBOM
    Write-Host '[PASS] All six directed WireGuard peer paths pass the no-fragment payload test.'
}

function Get-Sha256Text {
    param([Parameter(Mandatory)][string]$Value)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        return [Convert]::ToHexString($sha256.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))).ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
}

function Export-MountReport {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][object[]]$Nodes
    )
    $rows = @()
    $command = 'set -eu; uuid=$(findmnt -n -o UUID -T /var/lib/longhorn); ' +
        'set -- $(df -B1 --output=size,avail /var/lib/longhorn | tail -n 1); size=$1; avail=$2; ' +
        'set -- $(stat -c "%u %g %a" /var/lib/longhorn); uid=$1; gid=$2; mode=$3; ' +
        'grep -Eq "^UUID=${uuid}[[:space:]]+/var/lib/longhorn[[:space:]]+ext4" /etc/fstab; ' +
        'printf "%s|%s|%s|%s|%s|%s\n" "$uuid" "$size" "$avail" "$uid" "$gid" "$mode"'
    foreach ($node in $Nodes) {
        $probe = Invoke-StrictSsh -Paths $Paths -Node $node -User 'platform-admin' -RemoteCommand $command
        if ($probe.ExitCode -ne 0) { throw "Persistent data-mount reporting failed for $($node.name)." }
        $fields = $probe.Output.Trim() -split '\|'
        if ($fields.Count -ne 6 -or [int64]$fields[1] -lt 102005473280 -or
            [int64]$fields[2] -lt 96636764160 -or $fields[3] -ne '0' -or
            $fields[4] -ne '0' -or $fields[5] -ne '750') {
            throw "Persistent data-mount contract failed for $($node.name)."
        }
        $rows += [ordered]@{
            node = $node.name
            mount = '/var/lib/longhorn'
            filesystem = 'ext4'
            fstab_source = 'UUID'
            uuid_sha256 = Get-Sha256Text -Value $fields[0]
            size_bytes = [int64]$fields[1]
            available_bytes = [int64]$fields[2]
            owner = 'root:root'
            mode = '0750'
            status = 'PASS'
        }
    }
    [ordered]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        raw_uuid_recorded = $false
        nodes = $rows
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'mount-uuid-report.json') -Encoding utf8NoBOM
    Write-Host '[PASS] All data filesystems are UUID-mounted, owned, sufficiently free, and sanitized in the report.'
}

function Export-AnsibleRecaps {
    $logNames = @(
        'first-prepare-hosts.log', 'first-configure-network.log', 'first-verify-hosts.log',
        'second-prepare-hosts.log', 'second-configure-network.log', 'second-verify-hosts.log',
        'final-verify-hosts.log'
    )
    $reports = @()
    foreach ($logName in $logNames) {
        $logPath = Join-Path $logRoot $logName
        if (-not (Test-Path -LiteralPath $logPath -PathType Leaf)) { continue }
        $logText = Get-Content -LiteralPath $logPath -Raw
        $matches = [regex]::Matches(
            $logText,
            '(?m)^(verda-mgmt-server-0[1-3])\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)'
        )
        if ($matches.Count -lt 1) { throw "No Ansible recap could be sanitized from $logName." }
        foreach ($match in $matches) {
            $reports += [ordered]@{
                run = $logName
                node = $match.Groups[1].Value
                ok = [int]$match.Groups[2].Value
                changed = [int]$match.Groups[3].Value
                unreachable = [int]$match.Groups[4].Value
                failed = [int]$match.Groups[5].Value
            }
        }
    }
    [ordered]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        raw_logs_recorded = $false
        recaps = $reports
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'ansible-recaps.json') -Encoding utf8NoBOM
}

function Assert-SustainedWireGuardTraffic {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][object[]]$Nodes
    )
    $measurements = @()
    $runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmssfff')
    for ($index = 0; $index -lt $Nodes.Count; $index++) {
        $source = $Nodes[$index]
        $destination = $Nodes[($index + 1) % $Nodes.Count]
        $unit = "phase3-iperf-$runId-$($index + 1)"
        $serverCommand = "sudo -n systemd-run --quiet --collect --unit=$unit --property=RuntimeMaxSec=20 " +
            "/usr/bin/iperf3 -s -1 -B $($destination.wireguard_address)"
        $server = Invoke-StrictSsh -Paths $Paths -Node $destination -User 'platform-admin' `
            -RemoteCommand $serverCommand
        if ($server.ExitCode -ne 0) { throw 'Unable to start a bounded node-local throughput listener.' }
        Start-Sleep -Seconds 1
        $clientCommand = "/usr/bin/iperf3 -c $($destination.wireguard_address) -t 5 -J"
        $client = Invoke-StrictSsh -Paths $Paths -Node $source -User 'platform-admin' `
            -RemoteCommand $clientCommand
        if ($client.ExitCode -ne 0) { throw 'Sustained WireGuard throughput test failed.' }
        $json = $client.Output | ConvertFrom-Json -Depth 50
        $bitsPerSecond = [double]$json.end.sum_received.bits_per_second
        if ($bitsPerSecond -lt 1000000) { throw 'Sustained WireGuard throughput is below the 1 Mbit/s validity floor.' }
        $measurements += [ordered]@{
            source = $source.name
            destination = $destination.name
            duration_seconds = 5
            received_mbit_per_second = [Math]::Round($bitsPerSecond / 1000000, 2)
        }
    }
    [ordered]@{
        schema_version = 1
        tested_at = (Get-Date).ToUniversalTime().ToString('o')
        private_key_retrieved = $false
        paths = $measurements
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'wireguard-throughput.json') -Encoding utf8NoBOM
    Write-Host '[PASS] Sustained WireGuard traffic passed on the three-node ring; sanitized rates recorded.'
}

function Restart-NodeSerially {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)]$Node
    )
    Write-Host "[phase 3] controlled-reboot=$($Node.name) serial=true"
    $bootBefore = Invoke-StrictSsh -Paths $Paths -Node $Node -User 'platform-admin' `
        -RemoteCommand 'cat /proc/sys/kernel/random/boot_id'
    if ($bootBefore.ExitCode -ne 0 -or $bootBefore.Output.Trim() -notmatch '^[0-9a-f-]{36}$') {
        throw "Unable to capture the pre-reboot kernel identity for $($Node.name)."
    }
    $reboot = Invoke-StrictSsh -Paths $Paths -Node $Node -User 'platform-admin' `
        -RemoteCommand 'sudo -n systemd-run --quiet --on-active=2s --unit=phase3-controlled-reboot /usr/bin/systemctl reboot'
    if ($reboot.ExitCode -ne 0) { throw "Unable to schedule reboot for $($Node.name)." }
    $recoveryWindow = [Diagnostics.Stopwatch]::StartNew()
    while ($recoveryWindow.Elapsed -lt [TimeSpan]::FromMinutes(5)) {
        if (Test-AccountAccess -Paths $Paths -Node $Node -User 'platform-admin') {
            $bootAfter = Invoke-StrictSsh -Paths $Paths -Node $Node -User 'platform-admin' `
                -RemoteCommand 'cat /proc/sys/kernel/random/boot_id'
            if ($bootAfter.ExitCode -eq 0 -and
                $bootAfter.Output.Trim() -match '^[0-9a-f-]{36}$' -and
                $bootAfter.Output.Trim() -ne $bootBefore.Output.Trim()) {
                $cloudInit = Invoke-StrictSsh -Paths $Paths -Node $Node -User 'platform-admin' `
                    -RemoteCommand 'sudo -n cloud-init status --wait --long >/dev/null'
                if ($cloudInit.ExitCode -ne 0) {
                    throw "Cloud-init did not settle cleanly after reboot on $($Node.name)."
                }
                Write-Host "[PASS] $($Node.name) returned under a new kernel boot identity; cloud-init settled and strict administrator access works."
                return
            }
        }
        Start-Sleep -Seconds 5
    }
    throw "$($Node.name) did not prove a new kernel boot identity within the five-minute recovery window."
}

$paths = Get-ExternalPaths
Write-Host "[phase 3] target=$Target cluster=$Cluster cloud-mutation=false rke2=false serial=true"
Assert-Phase3Prerequisites -Paths $paths

$adminCidrs = [Environment]::GetEnvironmentVariable('PHASE3_ADMIN_CIDRS', 'Process')
if ([string]::IsNullOrWhiteSpace($adminCidrs)) {
    throw 'PHASE3_ADMIN_CIDRS is required as a comma-separated approved IPv4 CIDR allowlist.'
}

$nodes = New-Phase3Runtime -AdminCidrs $adminCidrs
if ($Target -eq 'configure') {
    Invoke-Phase2ReadOnlyPreflight -Paths $paths -Nodes $nodes
}
Initialize-PinnedKnownHosts -Paths $paths -Nodes $nodes

if ($Target -eq 'configure') {
    $bootstrapNodes = @()
    foreach ($node in $nodes) {
        $adminAccessible = Test-AccountAccess -Paths $paths -Node $node -User 'platform-admin'
        $rootAccessible = Test-AccountAccess -Paths $paths -Node $node -User 'root'
        if ($adminAccessible -and -not $rootAccessible) { continue }
        if (-not $rootAccessible) {
            throw "Neither the hardened administrator nor recovery root can reach $($node.name)."
        }
        $bootstrapNodes += $node.name
    }
    if ($bootstrapNodes.Count) {
        Invoke-AnsiblePlaybook -Inventory $rootInventory `
            -Playbook (Join-Path $repoRoot 'infra\ansible\playbooks\bootstrap-access.yml') `
            -LogName 'bootstrap-access.log' -Limit ($bootstrapNodes -join ',')
    }
    Assert-HardenedAccess -Paths $paths -Nodes $nodes

    $firstRuns = @(
        @{ Playbook = 'prepare-hosts.yml'; Log = 'first-prepare-hosts.log' },
        @{ Playbook = 'configure-network.yml'; Log = 'first-configure-network.log' },
        @{ Playbook = 'verify-hosts.yml'; Log = 'first-verify-hosts.log' }
    )
    foreach ($run in $firstRuns) {
        Invoke-AnsiblePlaybook -Inventory $adminInventory `
            -Playbook (Join-Path $repoRoot "infra\ansible\playbooks\$($run.Playbook)") `
            -LogName $run.Log
    }

    $secondRuns = @(
        @{ Playbook = 'prepare-hosts.yml'; Log = 'second-prepare-hosts.log' },
        @{ Playbook = 'configure-network.yml'; Log = 'second-configure-network.log' },
        @{ Playbook = 'verify-hosts.yml'; Log = 'second-verify-hosts.log' }
    )
    foreach ($run in $secondRuns) {
        Invoke-AnsiblePlaybook -Inventory $adminInventory `
            -Playbook (Join-Path $repoRoot "infra\ansible\playbooks\$($run.Playbook)") `
            -LogName $run.Log
    }
    Assert-SecondRunClean -LogNames @($secondRuns.Log)

    Assert-ExternalPortBoundary -Nodes $nodes
    Assert-SustainedWireGuardTraffic -Paths $paths -Nodes $nodes

    foreach ($node in $nodes) {
        Restart-NodeSerially -Paths $paths -Node $node
        Invoke-AnsiblePlaybook -Inventory $adminInventory `
            -Playbook (Join-Path $repoRoot 'infra\ansible\playbooks\verify-hosts.yml') `
            -LogName "post-reboot-$($node.name).log" -Limit $node.name
    }

    $postRebootRuns = @(
        @{ Playbook = 'prepare-hosts.yml'; Log = 'post-reboot-prepare-hosts.log' },
        @{ Playbook = 'configure-network.yml'; Log = 'post-reboot-configure-network.log' }
    )
    foreach ($run in $postRebootRuns) {
        Invoke-AnsiblePlaybook -Inventory $adminInventory `
            -Playbook (Join-Path $repoRoot "infra\ansible\playbooks\$($run.Playbook)") `
            -LogName $run.Log
    }
    Assert-SecondRunClean -LogNames @($postRebootRuns.Log) `
        -Description 'Post-reboot convergence'
}

Assert-HardenedAccess -Paths $paths -Nodes $nodes
Invoke-AnsiblePlaybook -Inventory $adminInventory `
    -Playbook (Join-Path $repoRoot 'infra\ansible\playbooks\verify-hosts.yml') `
    -LogName 'final-verify-hosts.log'
Assert-ExternalPortBoundary -Nodes $nodes
Assert-PeerReachabilityMatrix -Paths $paths -Nodes $nodes
Assert-SustainedWireGuardTraffic -Paths $paths -Nodes $nodes
Export-MountReport -Paths $paths -Nodes $nodes
Export-AnsibleRecaps
Write-Host "[PASS] Phase 3 target '$Target' completed without cloud or Kubernetes mutation."
