[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9._-]+$')]
    [string]$Distribution = 'Ubuntu'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $IsWindows) {
    throw 'The one-time DPAPI migration bridge must run on the existing Windows control host.'
}

function Invoke-WslText {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [int[]]$AcceptedExitCodes = @(0)
    )

    $output = & wsl.exe -d $Distribution -- @Arguments 2>&1
    if ($LASTEXITCODE -notin $AcceptedExitCodes) {
        throw "The Linux state migration command failed: $($Arguments[0])."
    }
    ($output -join "`n").Trim()
}

function Start-WslBinary {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [byte[]]$InputBytes,
        [switch]$CaptureOutput
    )

    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = 'wsl.exe'
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $null -ne $InputBytes
    $start.RedirectStandardOutput = $CaptureOutput.IsPresent
    $start.RedirectStandardError = $true
    $start.ArgumentList.Add('-d')
    $start.ArgumentList.Add($Distribution)
    $start.ArgumentList.Add('--')
    foreach ($argument in $Arguments) { $start.ArgumentList.Add($argument) }

    $process = [Diagnostics.Process]::Start($start)
    try {
        if ($null -ne $InputBytes) {
            $process.StandardInput.BaseStream.Write($InputBytes, 0, $InputBytes.Length)
            $process.StandardInput.BaseStream.Flush()
            $process.StandardInput.Close()
        }
        $captured = [IO.MemoryStream]::new()
        if ($CaptureOutput) { $process.StandardOutput.BaseStream.CopyTo($captured) }
        $errorText = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "The Linux GPG boundary refused the migration; diagnostic withheld (exit $($process.ExitCode))."
        }
        if ($CaptureOutput) { return $captured.ToArray() }
        return [byte[]]::new(0)
    } finally {
        $process.Dispose()
    }
}

$repository = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$externalBase = if ($env:VERDA_TAKEHOME_CONFIG_DIR) {
    [IO.Path]::GetFullPath($env:VERDA_TAKEHOME_CONFIG_DIR)
} else {
    Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'VerdaPlatformTakehome'
}
$sealedState = Join-Path $externalBase 'terraform\management.tfstate.dpapi'
$plaintextState = Join-Path $externalBase 'terraform\management.tfstate'
if (-not (Test-Path -LiteralPath $sealedState -PathType Leaf) -or (Test-Path -LiteralPath $plaintextState)) {
    throw 'The canonical sealed state is absent or an ambiguous plaintext state exists.'
}
$repoPrefix = $repository.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if ([IO.Path]::GetFullPath($sealedState).StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The migration source must remain outside the repository.'
}

Add-Type -AssemblyName System.Security.Cryptography.ProtectedData
$entropy = [Text.Encoding]::UTF8.GetBytes('verda-platform-takehome-phase2-state-v1')
$sealedBytes = [IO.File]::ReadAllBytes($sealedState)
$stateBytes = [Security.Cryptography.ProtectedData]::Unprotect(
    $sealedBytes,
    $entropy,
    [Security.Cryptography.DataProtectionScope]::CurrentUser
)
try {
    $state = [Text.Encoding]::UTF8.GetString($stateBytes) | ConvertFrom-Json -Depth 100
    if ($state.lineage -notmatch '^[0-9a-f-]{36}$' -or [int64]$state.serial -lt 0) {
        throw 'The decrypted Terraform state lineage or serial is invalid.'
    }

    $linuxUser = Invoke-WslText -Arguments @('id', '-un')
    if ($linuxUser -notmatch '^[a-z_][a-z0-9_-]*$') { throw 'The Ubuntu control identity is invalid.' }
    $linuxHome = "/home/$linuxUser"
    $stateDirectory = "$linuxHome/.local/state/verda-takehome/terraform"
    $gpgHome = "$linuxHome/.config/verda-takehome/gnupg"
    $encryptedState = "$stateDirectory/management.tfstate.gpg"
    $temporaryState = "$encryptedState.tmp"

    Invoke-WslText -Arguments @('install', '-d', '-m', '0700', $stateDirectory, $gpgHome) | Out-Null
    $fingerprint = Invoke-WslText -Arguments @(
        'gpg', '--homedir', $gpgHome, '--batch', '--with-colons', '--list-secret-keys',
        'phase6-state@verda.invalid'
    ) -AcceptedExitCodes @(0, 2)
    $fingerprint = @($fingerprint -split "`n" | Where-Object { $_ -like 'fpr:*' } |
        ForEach-Object { ($_ -split ':')[9] } | Where-Object { $_ -match '^[0-9A-F]{40}$' }) | Select-Object -First 1
    if (-not $fingerprint) {
        Invoke-WslText -Arguments @(
            'gpg', '--homedir', $gpgHome, '--batch', '--pinentry-mode', 'loopback',
            '--passphrase-file', '/dev/null', '--quick-generate-key',
            'Verda Phase 6 State <phase6-state@verda.invalid>', 'ed25519', 'cert', '0'
        ) | Out-Null
        $listing = Invoke-WslText -Arguments @(
            'gpg', '--homedir', $gpgHome, '--batch', '--with-colons', '--list-secret-keys',
            'phase6-state@verda.invalid'
        )
        $fingerprint = @($listing -split "`n" | Where-Object { $_ -like 'fpr:*' } |
            ForEach-Object { ($_ -split ':')[9] } | Where-Object { $_ -match '^[0-9A-F]{40}$' }) | Select-Object -First 1
        if (-not $fingerprint) { throw 'The Linux state-encryption key was not created.' }
        Invoke-WslText -Arguments @(
            'gpg', '--homedir', $gpgHome, '--batch', '--pinentry-mode', 'loopback',
            '--passphrase-file', '/dev/null', '--quick-add-key',
            $fingerprint, 'cv25519', 'encr', '0'
        ) | Out-Null
    }

    Invoke-WslText -Arguments @('rm', '-f', $temporaryState) | Out-Null
    Start-WslBinary -Arguments @(
        'gpg', '--homedir', $gpgHome, '--batch', '--yes', '--trust-model', 'always',
        '--recipient', $fingerprint, '--output', $temporaryState, '--encrypt'
    ) -InputBytes $stateBytes | Out-Null
    Invoke-WslText -Arguments @('chmod', '0600', $temporaryState) | Out-Null
    Invoke-WslText -Arguments @('mv', '-f', $temporaryState, $encryptedState) | Out-Null

    $roundTrip = Start-WslBinary -Arguments @(
        'gpg', '--homedir', $gpgHome, '--batch', '--quiet', '--decrypt', $encryptedState
    ) -CaptureOutput
    $expectedHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($stateBytes)).ToLowerInvariant()
    $actualHash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($roundTrip)).ToLowerInvariant()
    if ($actualHash -cne $expectedHash) { throw 'Linux encrypted-state round-trip verification failed.' }

    [ordered]@{
        schema_version = 1
        status = 'LINUX_STATE_MIGRATION_VERIFIED'
        state_lineage_sha256 = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes([string]$state.lineage))
        ).ToLowerInvariant()
        state_serial = [int64]$state.serial
        state_sha256 = $expectedHash
        linux_distribution = $Distribution
        linux_state_path = $encryptedState
        original_dpapi_state_preserved = $true
        raw_values_recorded = $false
    } | ConvertTo-Json -Compress
} finally {
    [Array]::Clear($stateBytes, 0, $stateBytes.Length)
    [Array]::Clear($sealedBytes, 0, $sealedBytes.Length)
}
