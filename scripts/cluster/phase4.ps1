[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('bootstrap', 'verify')]
    [string]$Target,
    [ValidateSet('management')]
    [string]$Cluster = 'management'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRoot = Join-Path $repoRoot '.local\phase4'
$reportRoot = Join-Path $repoRoot '.local\reports\phase4'
$logRoot = Join-Path $repoRoot '.local\logs\phase4'
$inventorySource = Join-Path $repoRoot 'infra\ansible\inventories\generated\management.yaml'
$inventory = Join-Path $runtimeRoot 'inventory-admin.yaml'
$unusedRootInventory = Join-Path $runtimeRoot 'inventory-root-unused.yaml'
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
    $backupBase = if ($env:VERDA_TF_BACKUP_DIR) {
        $env:VERDA_TF_BACKUP_DIR
    } else {
        Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'VerdaPlatformTakehome\state-backups'
    }
    $base = [IO.Path]::GetFullPath($base)
    $backupBase = [IO.Path]::GetFullPath($backupBase)
    $repoPrefix = $repoRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    foreach ($candidate in @($base, $backupBase)) {
        if ($candidate.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Phase 4 recovery material, credentials, kubeconfigs, and state must remain outside the repository.'
        }
    }
    return [pscustomobject]@{
        Base = $base
        BackupDirectory = $backupBase
        PrivateKey = Join-Path $base 'ssh\id_ed25519'
        PublicKey = Join-Path $base 'ssh\id_ed25519.pub'
        KnownHosts = Join-Path $base 'ssh\known_hosts_phase3'
        SealedState = Join-Path $base 'terraform\management.tfstate.dpapi'
        SealedToken = Join-Path $base 'rke2\management-token.dpapi'
        KubeconfigDirectory = Join-Path $base 'kubeconfigs\management'
    }
}

function Protect-ExternalDirectory {
    param([Parameter(Mandatory)][string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    if ($IsWindows) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $Path '/inheritance:r' '/grant:r' "${identity}:(OI)(CI)F" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict the external Phase 4 directory ACL.' }
    } else {
        & chmod 700 $Path
        if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict the external Phase 4 directory mode.' }
    }
}

function Protect-BytesForCurrentUser {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    if (-not $IsWindows) { throw 'The current Phase 4 controller requires Windows DPAPI for recovery-token sealing.' }
    Add-Type -AssemblyName System.Security.Cryptography.ProtectedData
    $entropy = [Text.Encoding]::UTF8.GetBytes('verda-platform-takehome-phase4-rke2-token-v1')
    return [Security.Cryptography.ProtectedData]::Protect(
        $Bytes,
        $entropy,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
}

function Unprotect-BytesForCurrentUser {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    Add-Type -AssemblyName System.Security.Cryptography.ProtectedData
    $entropy = [Text.Encoding]::UTF8.GetBytes('verda-platform-takehome-phase4-rke2-token-v1')
    return [Security.Cryptography.ProtectedData]::Unprotect(
        $Bytes,
        $entropy,
        [Security.Cryptography.DataProtectionScope]::CurrentUser
    )
}

function Get-ClusterToken {
    param([Parameter(Mandatory)]$Paths)
    Protect-ExternalDirectory -Path (Split-Path -Parent $Paths.SealedToken)
    if (Test-Path -LiteralPath $Paths.SealedToken -PathType Leaf) {
        $bytes = Unprotect-BytesForCurrentUser -Bytes ([IO.File]::ReadAllBytes($Paths.SealedToken))
        $token = [Text.Encoding]::UTF8.GetString($bytes)
        [Array]::Clear($bytes, 0, $bytes.Length)
        if ($token -notmatch '^[A-Za-z0-9_-]{64,}$') { throw 'The sealed RKE2 token does not satisfy the lineage contract.' }
        Write-Host '[PASS] Existing DPAPI-sealed RKE2 recovery-token lineage opened in process memory.'
        return $token
    }
    $random = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Fill($random)
    $token = [Convert]::ToBase64String($random).Replace('+', '-').Replace('/', '_').TrimEnd('=')
    [Array]::Clear($random, 0, $random.Length)
    $plaintext = [Text.Encoding]::UTF8.GetBytes($token)
    try {
        $sealed = Protect-BytesForCurrentUser -Bytes $plaintext
        $temporary = "$($Paths.SealedToken).new"
        [IO.File]::WriteAllBytes($temporary, $sealed)
        $roundTrip = Unprotect-BytesForCurrentUser -Bytes ([IO.File]::ReadAllBytes($temporary))
        if ([Text.Encoding]::UTF8.GetString($roundTrip) -cne $token) {
            Remove-Item -LiteralPath $temporary -Force
            throw 'DPAPI RKE2 token round-trip verification failed.'
        }
        Move-Item -LiteralPath $temporary -Destination $Paths.SealedToken -Force
        [Array]::Clear($roundTrip, 0, $roundTrip.Length)
    } finally {
        [Array]::Clear($plaintext, 0, $plaintext.Length)
    }
    Write-Host '[PASS] Generated a cryptographic RKE2 token and retained only its DPAPI-sealed external recovery copy.'
    return $token
}

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is unavailable."
    }
}

function Assert-ProcessValues {
    param([Parameter(Mandatory)][bool]$RequireCloud)
    $required = @(
        'PHASE3_ADMIN_CIDRS', 'PHASE4_S3_ENDPOINT', 'PHASE4_S3_BUCKET',
        'PHASE4_S3_REGION', 'PHASE4_S3_ACCESS_KEY', 'PHASE4_S3_SECRET_KEY'
    )
    if ($RequireCloud) { $required += @('VERDA_CLIENT_ID', 'VERDA_CLIENT_SECRET') }
    foreach ($name in $required) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))) {
            throw "$name is required in process memory through the secure Phase 4 launcher."
        }
    }
    if ($env:PHASE4_S3_ENDPOINT -notmatch '^https://[^/]+(?::[0-9]+)?$') {
        throw 'The S3 endpoint must use HTTPS and contain only the authority, without a path.'
    }
}

function Assert-Prerequisites {
    param([Parameter(Mandatory)]$Paths)
    foreach ($command in @('docker', 'python', 'pwsh', 'ssh', 'scp', 'ssh-keygen', 'tar')) {
        Assert-Command -Name $command
    }
    foreach ($file in @($inventorySource, $Paths.PrivateKey, $Paths.PublicKey, $Paths.KnownHosts, $Paths.SealedState)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Required external predecessor artifact is absent: $([IO.Path]::GetFileName($file))."
        }
    }
    & docker image inspect $qualityImage 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Pinned quality image '$qualityImage' is unavailable." }
}

function New-Phase4Runtime {
    $arguments = @(
        (Join-Path $repoRoot 'scripts\host\prepare-runtime.py'),
        '--inventory', $inventorySource,
        '--root-output', $unusedRootInventory,
        '--admin-output', $inventory,
        '--vars-output', $runtimeVars,
        '--metadata-output', $runtimeMetadata,
        '--admin-cidrs', $env:PHASE3_ADMIN_CIDRS,
        '--enable-phase4-firewall'
    )
    # Capture the helper's status text so it cannot become an accidental fourth
    # pipeline object in this function's return value. PowerShell otherwise
    # mixes native stdout with the three node objects returned below.
    $runtimeOutput = @(& python @arguments 2>&1)
    $runtimeExitCode = $LASTEXITCODE
    foreach ($line in $runtimeOutput) { Write-Host $line }
    if ($runtimeExitCode -ne 0) { throw 'Strict Phase 4 runtime generation failed.' }
    $metadata = Get-Content -LiteralPath $runtimeMetadata -Raw | ConvertFrom-Json -Depth 20
    if (@($metadata.nodes).Count -ne 3 -or @($metadata.nodes.public_address | Sort-Object -Unique).Count -ne 3) {
        throw 'The Phase 4 runtime does not describe exactly three unique endpoints.'
    }
    return @($metadata.nodes)
}

function Invoke-Phase2Boundary {
    param([Parameter(Mandatory)]$Paths)
    $phase2 = Join-Path $repoRoot 'scripts\infra\phase2.ps1'
    foreach ($phase2Target in @('plan', 'state-audit', 'cost-report', 'inventory')) {
        Write-Host "[phase 4] predecessor-check=$phase2Target cloud-mutation=false"
        & pwsh -NoLogo -NoProfile -NonInteractive -File $phase2 -Target $phase2Target -Cluster management
        if ($LASTEXITCODE -ne 0) { throw "Read-only predecessor check '$phase2Target' failed." }
    }
    $plan = Get-Content -LiteralPath (Join-Path $repoRoot '.local\reports\phase2\plan-summary.json') -Raw | ConvertFrom-Json
    $state = Get-Content -LiteralPath (Join-Path $repoRoot '.local\reports\phase2\state-audit.json') -Raw | ConvertFrom-Json
    $cost = Get-Content -LiteralPath (Join-Path $repoRoot '.local\reports\phase2\live-cost.json') -Raw | ConvertFrom-Json
    if ($plan.mode -ne 'no-drift' -or $state.total_resources -ne 7 -or $state.instances -ne 3 -or
        $state.data_volumes -ne 3 -or $cost.resource_count_status -ne 'PASS' -or
        $cost.rate_reconciliation_status -ne 'PASS') {
        throw 'The live resource, state, drift, cost, or expiry predecessor boundary is not green.'
    }
    $backups = @(Get-ChildItem -LiteralPath $Paths.BackupDirectory -Filter '*.tfstate.dpapi' -File |
        Sort-Object LastWriteTimeUtc -Descending)
    if ($backups.Count -lt 1) { throw 'No independent encrypted Terraform state backup is present.' }
    $checksumPath = "$($backups[0].FullName).sha256"
    if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) { throw 'The latest state backup checksum is absent.' }
    $expected = (Get-Content -LiteralPath $checksumPath -Raw).Split([char[]]" `t`r`n", 2)[0].ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $backups[0].FullName).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw 'The latest encrypted state backup checksum differs.' }
    Write-Host '[PASS] Live Verda boundary: 3 instances, 6 volumes, zero drift, current cost, expiry, and encrypted state backup green.'
}

function Invoke-Phase3Boundary {
    $phase3 = Join-Path $repoRoot 'scripts\host\phase3.ps1'
    & pwsh -NoLogo -NoProfile -NonInteractive -File $phase3 -Target verify -Cluster management
    if ($LASTEXITCODE -ne 0) { throw 'The complete Phase 3 host, access, WireGuard, storage, firewall, or SSH-pin boundary failed.' }
    Write-Host '[PASS] Phase 3 boundary revalidated immediately before RKE2 preparation.'
}

function Get-PreparedRke2HostCount {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)][object[]]$Nodes)
    $preparedCount = 0
    foreach ($node in $Nodes) {
        $probe = Invoke-StrictSsh -Paths $Paths -Node $node `
            -RemoteCommand "if test -x /usr/local/bin/rke2; then printf prepared; else printf absent; fi"
        if ($probe.ExitCode -ne 0) { throw "Unable to inspect the Phase 4 preparation state on $($node.name)." }
        switch ($probe.Output.Trim()) {
            'prepared' { $preparedCount++ }
            'absent' { }
            default { throw "Unexpected Phase 4 preparation state on $($node.name)." }
        }
    }
    return $preparedCount
}

function Get-CurrentEtcdMemberCount {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)]$Primary)
    $probe = Invoke-StrictSsh -Paths $Paths -Node $Primary -RemoteCommand (
        'if systemctl is-active --quiet rke2-server.service; then ' +
        'timeout 30 sudo -n /usr/local/libexec/verda-phase4/etcdctl-local ' +
        '--endpoints=https://127.0.0.1:2379 ' +
        '--cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt ' +
        '--cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt ' +
        '--key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key member list | wc -l; ' +
        'else printf 0; fi'
    )
    if ($probe.ExitCode -ne 0 -or $probe.Output.Trim() -notmatch '^[0-3]$') {
        throw 'Unable to establish the bounded etcd membership floor before serial convergence.'
    }
    return [int]$probe.Output.Trim()
}

function Invoke-Phase4HostBoundary {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)][object[]]$Nodes)
    $preparedCount = Get-PreparedRke2HostCount -Paths $Paths -Nodes $Nodes
    if ($preparedCount -eq 0) {
        Invoke-Phase3Boundary
        return
    }
    Write-Host "[phase 4] resume-state=prepared-rke2 hosts=$preparedCount strict-phase3-absence-gate=preserved"
    Invoke-AnsiblePlaybook -Paths $Paths -Playbook 'verify-hosts.yml' -LogName 'predecessor-resume.log' `
        -ExtraVariables @{ phase3_require_rke2_absent = 'false' }
    Write-Host '[PASS] Hardened-host boundary revalidated in Phase 4 resume mode; the Phase 3 absence gate remains the default.'
}

function Invoke-StrictSsh {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)]$Node,
        [Parameter(Mandatory)][string]$RemoteCommand
    )
    $output = @(& ssh -i $Paths.PrivateKey -o BatchMode=yes -o IdentitiesOnly=yes `
        -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$($Paths.KnownHosts)" `
        -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 `
        "platform-admin@$($Node.public_address)" $RemoteCommand 2>&1)
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($output -join "`n") }
}

function Assert-CidrBoundary {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][object[]]$Nodes
    )
    $routeArgs = [Collections.Generic.List[string]]::new()
    foreach ($route in @(Get-NetRoute -AddressFamily IPv4 -ErrorAction Stop)) {
        $routeArgs.Add('--route')
        $routeArgs.Add("controller=$($route.DestinationPrefix)")
    }
    foreach ($node in $Nodes) {
        $probe = Invoke-StrictSsh -Paths $Paths -Node $node -RemoteCommand 'ip -j -4 route show table main'
        if ($probe.ExitCode -ne 0) { throw "Unable to inspect routes on $($node.name)." }
        foreach ($route in @($probe.Output | ConvertFrom-Json -Depth 20)) {
            $destination = if ($route.dst) { $route.dst } else { 'default' }
            $routeArgs.Add('--route')
            $routeArgs.Add("$($node.name)=$destination")
            if ($destination -match '^10\.42\.' -and $route.dev -match '^cilium_(host|net|vxlan)$') {
                $routeArgs.Add('--owned-route')
                $routeArgs.Add("$($node.name)=$destination")
            }
        }
    }
    $routeArgs.Add('--route')
    $routeArgs.Add('wireguard=10.250.0.0/24')
    $arguments = [Collections.Generic.List[string]]::new()
    $arguments.Add((Join-Path $repoRoot 'scripts\cluster\assert-cidr-plan.py'))
    foreach ($plan in @(
        'management-pods=10.42.0.0/16', 'management-services=10.43.0.0/16',
        'workload-pods=10.44.0.0/16', 'workload-services=10.45.0.0/16'
    )) {
        $arguments.Add('--planned')
        $arguments.Add($plan)
    }
    foreach ($item in $routeArgs) { $arguments.Add($item) }
    $arguments.Add('--output')
    $arguments.Add((Join-Path $reportRoot 'cidr-overlap.json'))
    & python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'The immutable cluster CIDR plan overlaps an active controller or node route.' }
}

function Invoke-AnsiblePlaybook {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)][string]$Playbook,
        [Parameter(Mandatory)][string]$LogName,
        [Parameter(Mandatory)][hashtable]$ExtraVariables,
        [string]$Limit = ''
    )
    $inventoryRelative = ((Resolve-Path $inventory -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $playbookPath = Join-Path $repoRoot "infra\ansible\playbooks\$Playbook"
    $playbookRelative = ((Resolve-Path $playbookPath -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $varsRelative = ((Resolve-Path $runtimeVars -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $groupVarsPath = Join-Path $repoRoot 'infra\ansible\inventories\group_vars\management_servers.yml'
    $groupVarsRelative = ((Resolve-Path $groupVarsPath -Relative) -replace '^\.[\\/]', '') -replace '\\', '/'
    $extraArguments = @()
    foreach ($entry in $ExtraVariables.GetEnumerator() | Sort-Object Key) {
        if ($entry.Value -notmatch '^[A-Za-z0-9_.-]+$') { throw 'An Ansible control value is malformed.' }
        $extraArguments += "--extra-vars '$($entry.Key)=$($entry.Value)'"
    }
    $command = "install -d -m 0700 /tmp/home && " +
        "install -m 0600 /run/source/phase4-ssh-key /tmp/phase3-ssh-key && " +
        "exec ansible-playbook --inventory '/workspace/$inventoryRelative' '/workspace/$playbookRelative' " +
        "--extra-vars '@/workspace/$groupVarsRelative' --extra-vars '@/workspace/$varsRelative' " +
        ($extraArguments -join ' ')
    if ($Limit) { $command += " --limit '$Limit'" }
    $dockerArgs = @(
        'run', '--rm', '--network', 'bridge', '--read-only',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--pids-limit', '512',
        '--volume', "${repoRoot}:/workspace:ro",
        '--volume', "$($Paths.PrivateKey):/run/source/phase4-ssh-key:ro",
        '--volume', "$($Paths.KnownHosts):/run/config/known_hosts:ro",
        '--workdir', '/workspace',
        '--env', 'HOME=/tmp/home',
        '--env', 'ANSIBLE_CONFIG=/workspace/infra/ansible/ansible.cfg',
        '--env', 'ANSIBLE_LOCAL_TEMP=/tmp/ansible-local',
        '--env', 'PHASE4_RKE2_TOKEN',
        '--env', 'PHASE4_S3_ENDPOINT', '--env', 'PHASE4_S3_BUCKET', '--env', 'PHASE4_S3_REGION',
        '--env', 'PHASE4_S3_ACCESS_KEY', '--env', 'PHASE4_S3_SECRET_KEY', '--env', 'PHASE4_S3_SESSION_TOKEN',
        $qualityImage, 'bash', '-lc', $command
    )
    $logPath = Join-Path $logRoot $LogName
    & docker @dockerArgs 2>&1 | Tee-Object -FilePath $logPath
    if ($LASTEXITCODE -ne 0) { throw "Ansible failed; inspect ignored log $logPath." }
}

function Assert-CommonConfigParity {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)][object[]]$Nodes)
    $hashes = @()
    foreach ($node in $Nodes) {
        $probe = Invoke-StrictSsh -Paths $Paths -Node $node `
            -RemoteCommand 'sudo -n sha256sum /etc/rancher/rke2/config.yaml.d/10-common.yaml'
        if ($probe.ExitCode -ne 0 -or $probe.Output -notmatch '^([0-9a-f]{64})\s') {
            throw "Unable to prove common configuration hash on $($node.name)."
        }
        $hashes += $Matches[1]
    }
    if (@($hashes | Sort-Object -Unique).Count -ne 1) { throw 'Common critical RKE2 configuration differs between servers.' }
    [ordered]@{
        schema_version = 1
        status = 'PASS'
        node_count = 3
        common_config_sha256 = $hashes[0]
        secret_values_hashed = $false
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot 'common-config-parity.json') -Encoding utf8NoBOM
    Write-Host '[PASS] All three servers share one sanitized immutable common-config hash.'
}

function Wait-ClusterStage {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)]$Primary,
        [Parameter(Mandatory)][string]$NodeName,
        [Parameter(Mandatory)][int]$MinimumMembers
    )
    $remote = "sudo -n bash -lc 'set -e; " +
        "/var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml wait " +
        "node/$NodeName --for=condition=Ready --timeout=10m >/dev/null; " +
        "test `"`$(/usr/local/libexec/verda-phase4/etcdctl-local --endpoints=https://127.0.0.1:2379 " +
        "--cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt " +
        "--cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt " +
        "--key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key member list | wc -l)`" -ge $MinimumMembers; " +
        "/usr/local/libexec/verda-phase4/etcdctl-local --endpoints=https://127.0.0.1:2379 " +
        "--cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt " +
        "--cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt " +
        "--key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key endpoint health >/dev/null'"
    $deadline = [Diagnostics.Stopwatch]::StartNew()
    do {
        $probe = Invoke-StrictSsh -Paths $Paths -Node $Primary -RemoteCommand $remote
        if ($probe.ExitCode -eq 0) {
            Write-Host "[PASS] stage-node=$NodeName ready=true etcd-members-minimum=$MinimumMembers health=true"
            return
        }
        Start-Sleep -Seconds 10
    } while ($deadline.Elapsed -lt [TimeSpan]::FromMinutes(15))
    throw "The staged cluster did not reach Ready and etcd health for $NodeName."
}

function Export-ProtectedKubeconfigs {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)][object[]]$Nodes)
    Protect-ExternalDirectory -Path $Paths.KubeconfigDirectory
    $source = Invoke-StrictSsh -Paths $Paths -Node $Nodes[0] `
        -RemoteCommand 'sudo -n cat /etc/rancher/rke2/rke2.yaml'
    if ($source.ExitCode -ne 0 -or $source.Output -notmatch 'client-key-data:') {
        throw 'Unable to retrieve the protected administrator kubeconfig through strict SSH.'
    }
    $targets = @(
        @{ Name = 'management-primary.kubeconfig'; Endpoint = "$($Nodes[0].public_address).sslip.io" }
    )
    foreach ($node in $Nodes) {
        # Direct recovery paths use certificate-covered public addresses and do
        # not inherit the named default endpoint's external DNS dependency.
        $targets += @{ Name = "$($node.name)-direct.kubeconfig"; Endpoint = $node.public_address }
    }
    foreach ($target in $targets) {
        $content = $source.Output -replace 'server:\s+https://127\.0\.0\.1:6443', "server: https://$($target.Endpoint):6443"
        $destination = Join-Path $Paths.KubeconfigDirectory $target.Name
        [IO.File]::WriteAllText($destination, $content + "`n", [Text.UTF8Encoding]::new($false))
        if ($IsWindows) {
            $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            & icacls.exe $destination '/inheritance:r' '/grant:r' "${identity}:F" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict a protected kubeconfig ACL.' }
        } else {
            & chmod 600 $destination
        }
    }
    $source = $null
    Write-Host '[PASS] Primary and three direct-node kubeconfigs retained only in the protected external boundary.'
}

function Invoke-ExternalKubectl {
    param(
        [Parameter(Mandatory)][string]$Kubeconfig,
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$HostAlias,
        [string]$HostAddress
    )
    $aquaConfig = Join-Path $repoRoot 'aqua.yaml'
    if (-not (Test-Path -LiteralPath $aquaConfig -PathType Leaf)) {
        throw 'The locked Aqua tool manifest is absent from the repository boundary.'
    }
    $aliasRequested = -not [string]::IsNullOrWhiteSpace($HostAlias)
    if ($aliasRequested -xor (-not [string]::IsNullOrWhiteSpace($HostAddress))) {
        throw 'A protected endpoint host alias and address must be supplied together.'
    }
    if ($aliasRequested) {
        $parsedAddress = $null
        if (-not [Net.IPAddress]::TryParse($HostAddress, [ref]$parsedAddress) -or
            $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
            $HostAlias -cne "$HostAddress.sslip.io") {
            throw 'The protected default-endpoint mapping is not the accepted IPv4-derived alias contract.'
        }
    }
    $dockerArgs = @(
        'run', '--rm', '--network', 'bridge', '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true'
    )
    if ($aliasRequested) {
        $dockerArgs += @('--add-host', "${HostAlias}:${HostAddress}")
    }
    $dockerArgs += @(
        '--volume', "${aquaConfig}:/workspace/aqua.yaml:ro",
        '--volume', "${Kubeconfig}:/run/config/kubeconfig:ro",
        $qualityImage, 'kubectl', '--kubeconfig', '/run/config/kubeconfig'
    ) + $Arguments
    $output = @(& docker @dockerArgs 2>&1)
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($output -join "`n") }
}

function Test-TcpPort {
    param([Parameter(Mandatory)][string]$Address, [Parameter(Mandatory)][int]$Port)
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $attempt = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $attempt.AsyncWaitHandle.WaitOne(2000)) { return $false }
        $client.EndConnect($attempt)
        return $true
    } catch { return $false } finally { $client.Dispose() }
}

function Assert-ExternalPortBoundary {
    param([Parameter(Mandatory)][object[]]$Nodes)
    $denied = @(
        80, 443, 2379, 2380, 2381, 4240, 4244, 4245, 4250,
        6060, 6061, 6062, 9345, 9878, 9879, 9890, 9891, 9893, 9901,
        9962, 9963, 9964, 9965, 9966, 10250, 10257, 10259,
        30000, 31000, 32767
    )
    foreach ($node in $Nodes) {
        foreach ($allowed in @(22, 6443)) {
            if (-not (Test-TcpPort -Address $node.public_address -Port $allowed)) {
                throw "Intended administrator TCP port $allowed is not reachable on $($node.name)."
            }
        }
        foreach ($port in $denied) {
            if (Test-TcpPort -Address $node.public_address -Port $port) {
                throw "Forbidden public TCP port $port is reachable on $($node.name)."
            }
        }
    }
    [ordered]@{
        schema_version = 1
        status = 'PASS'
        source = 'approved-administrator-path'
        node_count = 3
        allowed_tcp = @(22, 6443)
        denied_tcp = $denied
        full_nodeport_range_denial_basis = 'live nftables default-drop precedes later CNI chains; representative low/middle/high ports sampled'
        udp_cilium_denial_basis = 'live exact-peer firewall contract; no public UDP 8472 accept rule'
        endpoint_values_recorded = $false
        non_allowlisted_source_test = 'not-practical-from-current-single-controller'
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reportRoot 'external-port-scan.json') -Encoding utf8NoBOM
    Write-Host '[PASS] Public boundary: only SSH and administrator API are reachable; supervisor, etcd, Cilium, kubelet, metrics, HTTP/S, and NodePorts remain denied.'
}

function Assert-PrepareIdempotency {
    param([Parameter(Mandatory)]$Paths)
    $logName = 'idempotency-prepare.log'
    Invoke-AnsiblePlaybook -Paths $Paths -Playbook 'install-rke2.yml' -LogName $logName `
        -ExtraVariables @{ phase4_action = 'prepare' }
    $logPath = Join-Path $logRoot $logName
    $content = Get-Content -LiteralPath $logPath -Raw
    $recaps = [regex]::Matches(
        $content,
        '(?m)^verda-mgmt-server-0[123]\s+:\s+ok=\d+\s+changed=0\s+unreachable=0\s+failed=0\b'
    )
    if ($recaps.Count -ne 3) {
        throw 'The active-cluster prepare convergence replay was not idempotent on all three servers.'
    }
    [ordered]@{
        schema_version = 1
        status = 'PASS'
        hosts = 3
        changed = 0
        unreachable = 0
        failed = 0
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot 'prepare-idempotency.json') -Encoding utf8NoBOM
    Write-Host '[PASS] Active-cluster prepare convergence replay changed zero resources on all three servers.'
}

function Invoke-RemoteChecked {
    param(
        [Parameter(Mandatory)]$Paths,
        [Parameter(Mandatory)]$Node,
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string]$Failure,
        [string]$OutputPath = ''
    )
    $probe = Invoke-StrictSsh -Paths $Paths -Node $Node -RemoteCommand $Command
    if ($OutputPath) {
        $probe.Output | Set-Content -LiteralPath $OutputPath -Encoding utf8NoBOM
    }
    if ($probe.ExitCode -ne 0) { throw $Failure }
    return $probe.Output
}

function Stop-Rke2ForFailureDrill {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)]$Node)
    $command = 'sudo -n bash -lc ''set -euo pipefail; ' +
        'test -x /usr/local/bin/rke2-killall.sh; ' +
        'systemctl stop rke2-server.service; ' +
        '/usr/local/bin/rke2-killall.sh >/dev/null; ' +
        'if systemctl is-active --quiet rke2-server.service; then exit 1; fi'''
    Invoke-RemoteChecked -Paths $Paths -Node $Node -Command $command `
        -Failure "Unable to stop the bounded RKE2 node and its residual pinned-release containers on $($Node.name)." | Out-Null
}

function Wait-CiliumStackAfterFailureDrill {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)]$ControlNode)
    Invoke-RemoteChecked -Paths $Paths -Node $ControlNode `
        -Command "sudo -n /usr/local/libexec/verda-phase4/reconcile-cilium-agent 'post-drill-ready'" `
        -Failure 'The post-drill API and exact Cilium/Hubble stack did not recover without pod replacement.' | Out-Null
    Write-Host '[PASS] Post-drill API and exact Cilium/Hubble stack recovered without erasing expected restart history.'
}

function Reconcile-CiliumComponentsBeforeVerification {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)]$ControlNode)
    Invoke-RemoteChecked -Paths $Paths -Node $ControlNode `
        -Command "sudo -n /usr/local/libexec/verda-phase4/reconcile-cilium-agent 'all'" `
        -Failure 'The Cilium/Hubble stack could not reach a bounded zero-restart baseline before verification.' | Out-Null
    Write-Host '[PASS] Cilium and Hubble entered verification with a zero-restart component baseline.'
}

function Remove-CiliumTestNamespaces {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)]$Primary)
    $command = 'sudo -n /usr/local/libexec/verda-phase4/cleanup-test-namespaces cilium'
    Invoke-RemoteChecked -Paths $Paths -Node $Primary -Command $command `
        -Failure 'Cilium connectivity-test namespace cleanup or absence proof failed.' | Out-Null
    Write-Host '[PASS] Cilium connectivity-test namespaces are absent after cleanup.'
}

function Remove-NetworkTestNamespace {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)]$ControlNode)
    $command = 'sudo -n /usr/local/libexec/verda-phase4/cleanup-test-namespaces network-smoke'
    Invoke-RemoteChecked -Paths $Paths -Node $ControlNode -Command $command `
        -Failure 'Phase 4 network-test namespace cleanup or absence proof failed.' | Out-Null
    Write-Host '[PASS] Phase 4 network-test namespace is absent after cleanup.'
}

function Invoke-SingleNodeFailureTests {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)][object[]]$Nodes)
    $primaryConfig = Join-Path $Paths.KubeconfigDirectory 'management-primary.kubeconfig'
    $directConfigs = @($Nodes | ForEach-Object {
        Join-Path $Paths.KubeconfigDirectory "$($_.name)-direct.kubeconfig"
    })
    $directTwo = $directConfigs[1]
    $primaryAlias = "$($Nodes[0].public_address).sslip.io"
    if ((Invoke-ExternalKubectl -Kubeconfig $primaryConfig -Arguments @('get', '--raw=/readyz') `
            -HostAlias $primaryAlias -HostAddress $Nodes[0].public_address).ExitCode -ne 0) {
        throw 'The protected named default-endpoint kubeconfig failed before fault injection.'
    }
    foreach ($config in $directConfigs) {
        if ((Invoke-ExternalKubectl -Kubeconfig $config -Arguments @('get', '--raw=/readyz')).ExitCode -ne 0) {
            throw 'A protected direct-address kubeconfig failed before fault injection.'
        }
    }
    $failureReport = [ordered]@{
        schema_version = 1
        non_primary = [ordered]@{}
        primary_endpoint = [ordered]@{}
        two_node_loss_tested = $false
    }
    try {
        Stop-Rke2ForFailureDrill -Paths $Paths -Node $Nodes[2]
        Start-Sleep -Seconds 30
        $remaining = 'sudo -n bash -lc ''set -euo pipefail; ' +
            'deadline=$((SECONDS + 120)); until ' +
            '/var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml get --raw=/readyz >/dev/null; ' +
            'do (( SECONDS < deadline )) || exit 21; sleep 5; done; echo api=true; ' +
            'deadline=$((SECONDS + 120)); until ' +
            '/usr/local/libexec/verda-phase4/etcdctl-local --endpoints=https://10.250.0.11:2379,https://10.250.0.12:2379 ' +
            '--cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt ' +
            '--cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt ' +
            '--key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key endpoint health >/dev/null; ' +
            'do (( SECONDS < deadline )) || exit 22; sleep 5; done; echo quorum=true; ' +
            'for node in verda-mgmt-server-01 verda-mgmt-server-02; do ' +
            '/var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml -n kube-system ' +
            'wait --for=condition=Ready pod --selector=k8s-app=cilium ' +
            '--field-selector="spec.nodeName=${node}" --timeout=2m >/dev/null; done; echo cilium=true; ' +
            'client=$(/var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml -n phase4-network-test get pod ' +
            '-l app=phase4-client --field-selector spec.nodeName=verda-mgmt-server-01 -o jsonpath={.items[0].metadata.name}); ' +
            'deadline=$((SECONDS + 120)); until ' +
            '/var/lib/rancher/rke2/bin/kubectl --kubeconfig /etc/rancher/rke2/rke2.yaml -n phase4-network-test exec "$client" -- ' +
            'curl -fsS --max-time 10 http://echo/index.html 2>/dev/null | grep -qx phase4-ok; ' +
            'do (( SECONDS < deadline )) || exit 23; sleep 5; done; echo workload=true'''
        Invoke-RemoteChecked -Paths $Paths -Node $Nodes[0] -Command $remaining `
            -Failure 'API, etcd quorum, Cilium, or replicated test service failed during non-primary loss; inspect the ignored bounded marker report.' `
            -OutputPath (Join-Path $reportRoot 'non-primary-outage.txt') | Out-Null
        $failureReport.non_primary = [ordered]@{
            status = 'PASS'; stopped_nodes = 1; api = $true; quorum = $true
            cilium_remaining_nodes = $true; workload = $true
        }
    } finally {
        Invoke-StrictSsh -Paths $Paths -Node $Nodes[2] -RemoteCommand 'sudo -n systemctl start rke2-server.service' | Out-Null
    }
    Wait-ClusterStage -Paths $Paths -Primary $Nodes[0] -NodeName $Nodes[2].name -MinimumMembers 3
    Wait-CiliumStackAfterFailureDrill -Paths $Paths -ControlNode $Nodes[0]

    try {
        Stop-Rke2ForFailureDrill -Paths $Paths -Node $Nodes[0]
        # Static-pod containers can outlive the systemd unit briefly while RKE2
        # performs its orderly stop. Prove the named endpoint becomes unavailable
        # within a bounded window instead of relying on one timing-sensitive sample.
        $endpointLossDeadline = [Diagnostics.Stopwatch]::StartNew()
        $defaultEndpointUnavailable = $false
        do {
            $defaultProbe = Invoke-ExternalKubectl -Kubeconfig $primaryConfig `
                -Arguments @('--request-timeout=3s', 'get', '--raw=/readyz') `
                -HostAlias $primaryAlias -HostAddress $Nodes[0].public_address
            if ($defaultProbe.ExitCode -ne 0) {
                $defaultEndpointUnavailable = $true
                break
            }
            Start-Sleep -Seconds 5
        } while ($endpointLossDeadline.Elapsed -lt [TimeSpan]::FromMinutes(2))
        if (-not $defaultEndpointUnavailable) {
            throw 'The documented primary endpoint did not become unavailable within the bounded loss window.'
        }
        $directProbe = Invoke-ExternalKubectl -Kubeconfig $directTwo -Arguments @('--request-timeout=10s', 'get', '--raw=/readyz')
        if ($directProbe.ExitCode -ne 0) { throw 'The protected direct-node API path failed during primary endpoint loss.' }
        $remaining = 'sudo -n bash -lc ''set -e; ' +
            '/usr/local/libexec/verda-phase4/etcdctl-local --endpoints=https://10.250.0.12:2379,https://10.250.0.13:2379 ' +
            '--cacert=/var/lib/rancher/rke2/server/tls/etcd/server-ca.crt ' +
            '--cert=/var/lib/rancher/rke2/server/tls/etcd/server-client.crt ' +
            '--key=/var/lib/rancher/rke2/server/tls/etcd/server-client.key endpoint health >/dev/null'''
        Invoke-RemoteChecked -Paths $Paths -Node $Nodes[1] -Command $remaining `
            -Failure 'Etcd quorum failed during designated primary endpoint loss.' | Out-Null
        $failureReport.primary_endpoint = [ordered]@{
            status = 'PASS'; default_endpoint_failed_as_documented = $true
            direct_node_path = $true; quorum = $true; stopped_nodes = 1
        }
    } finally {
        Invoke-StrictSsh -Paths $Paths -Node $Nodes[0] -RemoteCommand 'sudo -n systemctl start rke2-server.service' | Out-Null
    }
    Wait-ClusterStage -Paths $Paths -Primary $Nodes[0] -NodeName $Nodes[0].name -MinimumMembers 3
    if ((Invoke-ExternalKubectl -Kubeconfig $primaryConfig `
            -Arguments @('--request-timeout=10s', 'get', '--raw=/readyz') `
            -HostAlias $primaryAlias -HostAddress $Nodes[0].public_address).ExitCode -ne 0) {
        throw 'The protected named default API path failed after designated-primary recovery.'
    }
    foreach ($config in $directConfigs) {
        if ((Invoke-ExternalKubectl -Kubeconfig $config -Arguments @('--request-timeout=10s', 'get', '--raw=/readyz')).ExitCode -ne 0) {
            throw 'A protected direct-node API path failed after designated-primary recovery.'
        }
    }
    Wait-CiliumStackAfterFailureDrill -Paths $Paths -ControlNode $Nodes[1]
    $failureReport.primary_endpoint.recovery = [ordered]@{
        default_endpoint = $true; direct_node_paths = 3; cilium = $true
    }
    $failureReport.status = 'PASS'
    $failureReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $reportRoot 'single-node-failure.json') -Encoding utf8NoBOM
    Write-Host '[PASS] Non-primary service loss and designated-primary endpoint loss retained one-node quorum safety; two-node loss was not tested.'
}

function Export-SanitizedSupportBundle {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)]$Primary)
    $destination = Join-Path $reportRoot 'verda-rke2-support.tgz'
    $validated = $false
    try {
        try {
            Invoke-RemoteChecked -Paths $Paths -Node $Primary `
                -Command 'sudo -n rm -rf /var/tmp/verda-rke2-support /var/tmp/verda-rke2-support.tgz; sudo -n /usr/local/libexec/verda-phase4/collect-diagnostics /var/tmp/verda-rke2-support >/dev/null; sudo -n tar -C /var/tmp -czf /var/tmp/verda-rke2-support.tgz verda-rke2-support; sudo -n chown platform-admin:platform-admin /var/tmp/verda-rke2-support.tgz; sudo -n chmod 0600 /var/tmp/verda-rke2-support.tgz' `
                -Failure 'Remote sanitized support bundle generation failed.' | Out-Null
            & scp -q -i $Paths.PrivateKey -o BatchMode=yes -o IdentitiesOnly=yes `
                -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$($Paths.KnownHosts)" `
                "platform-admin@$($Primary.public_address):/var/tmp/verda-rke2-support.tgz" $destination
            if ($LASTEXITCODE -ne 0) { throw 'Unable to retrieve the sanitized support bundle.' }
        } finally {
            $cleanup = Invoke-StrictSsh -Paths $Paths -Node $Primary `
                -RemoteCommand 'sudo -n rm -rf /var/tmp/verda-rke2-support /var/tmp/verda-rke2-support.tgz'
            if ($cleanup.ExitCode -ne 0) { throw 'Remote support-bundle cleanup failed.' }
        }
        Assert-SanitizedSupportBundle -Archive $destination
        $validated = $true
    } finally {
        if (-not $validated) {
            & python (Join-Path $repoRoot 'scripts\cluster\check_support_bundle.py') `
                --archive $destination --remove-unvalidated
            if ($LASTEXITCODE -ne 0) {
                throw 'Unvalidated local support-bundle cleanup failed closed.'
            }
        }
    }
    Write-Host '[PASS] Sanitized support bundle captured locally and removed from the server.'
}

function Assert-SanitizedSupportBundle {
    param([Parameter(Mandatory)][string]$Archive)
    & python (Join-Path $repoRoot 'scripts\cluster\check_support_bundle.py') --archive $Archive
    if ($LASTEXITCODE -ne 0) {
        throw 'The support bundle failed the bounded fail-closed safety checker.'
    }
}

function Invoke-FullVerification {
    param([Parameter(Mandatory)]$Paths, [Parameter(Mandatory)][object[]]$Nodes)
    Reconcile-CiliumComponentsBeforeVerification -Paths $Paths -ControlNode $Nodes[0]
    Remove-CiliumTestNamespaces -Paths $Paths -Primary $Nodes[0]
    try {
        Invoke-RemoteChecked -Paths $Paths -Node $Nodes[0] `
            -Command 'sudo -n /usr/local/libexec/verda-phase4/verify-management' `
            -Failure 'Management control-plane, etcd, certificate, Cilium, or connectivity verification failed.' `
            -OutputPath (Join-Path $reportRoot 'management-verification.txt') | Out-Null
    } finally {
        Remove-CiliumTestNamespaces -Paths $Paths -Primary $Nodes[0]
    }

    $networkNamespaceCleanupRequired = $true
    try {
        Invoke-RemoteChecked -Paths $Paths -Node $Nodes[0] `
            -Command 'sudo -n env PHASE4_KEEP_TEST_NAMESPACE=true /usr/local/libexec/verda-phase4/network-smoke' `
            -Failure 'DNS, service, pod, NetworkPolicy, Traefik, egress, or MTU smoke verification failed.' `
            -OutputPath (Join-Path $reportRoot 'network-smoke.txt') | Out-Null
        foreach ($node in $Nodes) {
            Invoke-RemoteChecked -Paths $Paths -Node $node `
                -Command 'sudo -n /usr/local/libexec/verda-phase4/cis-self-assessment' `
                -Failure "The focused CIS self-assessment failed on $($node.name)." `
                -OutputPath (Join-Path $reportRoot "cis-self-assessment-$($node.name).txt") | Out-Null
        }
        Invoke-AnsiblePlaybook -Paths $Paths -Playbook 'configure-etcd-backup.yml' -LogName 'snapshot.log' `
            -ExtraVariables @{ phase4_snapshot_action = 'snapshot' }
        Invoke-AnsiblePlaybook -Paths $Paths -Playbook 'configure-etcd-backup.yml' -LogName 'snapshot-verify.log' `
            -ExtraVariables @{ phase4_snapshot_action = 'verify' }
        Invoke-RemoteChecked -Paths $Paths -Node $Nodes[0] `
            -Command 'sudo -n /usr/local/libexec/verda-phase4/snapshot-evidence' `
            -Failure 'Sanitized local/off-cluster snapshot evidence failed.' `
            -OutputPath (Join-Path $reportRoot 'management-snapshots.json') | Out-Null
        Assert-ExternalPortBoundary -Nodes $Nodes
        Export-ProtectedKubeconfigs -Paths $Paths -Nodes $Nodes
        Invoke-SingleNodeFailureTests -Paths $Paths -Nodes $Nodes
        Remove-NetworkTestNamespace -Paths $Paths -ControlNode $Nodes[1]
        $networkNamespaceCleanupRequired = $false
        Export-SanitizedSupportBundle -Paths $Paths -Primary $Nodes[0]
    } finally {
        if ($networkNamespaceCleanupRequired) {
            Remove-NetworkTestNamespace -Paths $Paths -ControlNode $Nodes[1]
        }
    }
    Invoke-RemoteChecked -Paths $Paths -Node $Nodes[0] `
        -Command 'sudo -n /usr/local/libexec/verda-phase4/stability-window' `
        -Failure 'The five-minute post-drill stability window failed.' `
        -OutputPath (Join-Path $reportRoot 'stability-window.json') | Out-Null
}

$paths = Get-ExternalPaths
$token = $null
try {
    Write-Host "[phase 4] target=$Target cluster=$Cluster cloud-mutation=false host-scope=rke2-only serial=true"
    Assert-Prerequisites -Paths $paths
    Assert-ProcessValues -RequireCloud ($Target -eq 'bootstrap')
    $nodes = New-Phase4Runtime
    $token = Get-ClusterToken -Paths $paths
    [Environment]::SetEnvironmentVariable('PHASE4_RKE2_TOKEN', $token, 'Process')

    if ($Target -eq 'bootstrap') {
        Invoke-Phase2Boundary -Paths $paths
        Invoke-Phase4HostBoundary -Paths $paths -Nodes $nodes
        Assert-CidrBoundary -Paths $paths -Nodes $nodes
        Invoke-AnsiblePlaybook -Paths $paths -Playbook 'install-rke2.yml' -LogName 'prepare.log' `
            -ExtraVariables @{ phase4_action = 'prepare' }
        Assert-CommonConfigParity -Paths $paths -Nodes $nodes
        $existingMembers = Get-CurrentEtcdMemberCount -Paths $paths -Primary $nodes[0]
        for ($index = 0; $index -lt $nodes.Count; $index++) {
            Invoke-AnsiblePlaybook -Paths $paths -Playbook 'install-rke2.yml' `
                -LogName "start-$($nodes[$index].name).log" -ExtraVariables @{ phase4_action = 'start' } `
                -Limit $nodes[$index].name
            $minimumMembers = [Math]::Max($existingMembers, $index + 1)
            Wait-ClusterStage -Paths $paths -Primary $nodes[0] -NodeName $nodes[$index].name `
                -MinimumMembers $minimumMembers
            if ($index -eq 0) {
                Invoke-AnsiblePlaybook -Paths $paths -Playbook 'configure-etcd-backup.yml' `
                    -LogName 'snapshot-secret.log' -ExtraVariables @{ phase4_snapshot_action = 'configure' }
            }
        }
        Invoke-FullVerification -Paths $paths -Nodes $nodes
        Assert-PrepareIdempotency -Paths $paths
        Write-Host '[PASS] Phase 4 staged bootstrap and complete verification finished without Verda resource mutation.'
    } else {
        Assert-CommonConfigParity -Paths $paths -Nodes $nodes
        Invoke-AnsiblePlaybook -Paths $paths -Playbook 'install-rke2.yml' -LogName 'verify-role.log' `
            -ExtraVariables @{ phase4_action = 'verify' }
        Invoke-FullVerification -Paths $paths -Nodes $nodes
        Write-Host '[PASS] Phase 4 verification cycle completed.'
    }
} finally {
    [Environment]::SetEnvironmentVariable('PHASE4_RKE2_TOKEN', $null, 'Process')
    $token = $null
}
