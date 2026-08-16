[CmdletBinding()]
param(
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))

function Resolve-SafeWorkspaceOutput {
    param([Parameter(Mandatory)][string]$Path)

    $candidate = if ([System.IO.Path]::IsPathRooted($Path)) {
        [System.IO.Path]::GetFullPath($Path)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $workspaceRoot $Path))
    }

    $workspacePrefix = $workspaceRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($workspacePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Output path must remain inside the workspace: $candidate"
    }

    return $candidate
}

$toolSpecs = @(
    [PSCustomObject]@{ name = 'pwsh'; requiredBy = 'phase-0'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'git'; requiredBy = 'phase-0'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'terraform'; requiredBy = 'phase-1'; arguments = @('version') },
    [PSCustomObject]@{ name = 'tofu'; requiredBy = 'phase-1-alternative'; arguments = @('version') },
    [PSCustomObject]@{ name = 'verda'; requiredBy = 'phase-0-gate'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'ansible'; requiredBy = 'phase-2'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'ansible-lint'; requiredBy = 'phase-1'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'tflint'; requiredBy = 'phase-1'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'checkov'; requiredBy = 'phase-1'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'helm'; requiredBy = 'phase-4'; arguments = @('version', '--short') },
    [PSCustomObject]@{ name = 'kubectl'; requiredBy = 'phase-4'; arguments = @('version', '--client=true') },
    [PSCustomObject]@{ name = 'kustomize'; requiredBy = 'phase-5'; arguments = @('version') },
    [PSCustomObject]@{ name = 'kubeconform'; requiredBy = 'phase-1'; arguments = @('-v') },
    [PSCustomObject]@{ name = 'trivy'; requiredBy = 'phase-6'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'shellcheck'; requiredBy = 'phase-1'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'yamllint'; requiredBy = 'phase-1'; arguments = @('--version') },
    [PSCustomObject]@{ name = 'cosign'; requiredBy = 'bonus'; arguments = @('version') }
)

$results = foreach ($spec in $toolSpecs) {
    $command = Get-Command $spec.name -ErrorAction SilentlyContinue
    $version = $null
    $versionExitCode = $null

    if ($command) {
        try {
            $arguments = [string[]]$spec.arguments
            $rawVersion = & $command.Source @arguments 2>&1
            $versionExitCode = $LASTEXITCODE
            $version = (($rawVersion | Out-String).Trim() -split "`r?`n" | Select-Object -First 1)
        }
        catch {
            $version = "version probe failed: $($_.Exception.Message)"
            $versionExitCode = 1
        }
    }

    [PSCustomObject]@{
        name = $spec.name
        requiredBy = $spec.requiredBy
        available = [bool]$command
        path = if ($command) { $command.Source } else { $null }
        version = $version
        versionProbeExitCode = $versionExitCode
    }
}

$report = [PSCustomObject]@{
    schemaVersion = '1.0.0'
    collectedAtUtc = [DateTime]::UtcNow.ToString('o')
    workspace = $workspaceRoot
    operatingSystem = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
    architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    tools = $results
}

$json = $report | ConvertTo-Json -Depth 6

if ($OutputPath) {
    $safeOutput = Resolve-SafeWorkspaceOutput -Path $OutputPath
    $parent = Split-Path -Parent $safeOutput
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    Set-Content -LiteralPath $safeOutput -Value $json -Encoding utf8NoBOM
    Write-Output "Wrote tooling discovery to $safeOutput"
}
else {
    Write-Output $json
}
