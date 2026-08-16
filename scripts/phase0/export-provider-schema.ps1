[CmdletBinding()]
param(
    [switch]$AllowProviderDownload,
    [string]$OutputPath = 'docs/evidence/phase-0/provider-schema.local.json'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$workspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$discoveryRoot = Join-Path $workspaceRoot 'infra\terraform\provider-discovery'

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

$engine = Get-Command terraform -ErrorAction SilentlyContinue
if (-not $engine) {
    $engine = Get-Command tofu -ErrorAction SilentlyContinue
}
if (-not $engine) {
    Write-Error 'Terraform or OpenTofu must be installed before exporting the provider schema.' -ErrorAction Continue
    exit 2
}
if (-not $AllowProviderDownload) {
    Write-Error 'Provider initialization downloads a plugin. Re-run with -AllowProviderDownload after reviewing infra/terraform/provider-discovery.' -ErrorAction Continue
    exit 2
}

$safeOutput = Resolve-SafeWorkspaceOutput -Path $OutputPath
$parent = Split-Path -Parent $safeOutput
New-Item -ItemType Directory -Force -Path $parent | Out-Null

$previousAutomationValue = $env:TF_IN_AUTOMATION
$env:TF_IN_AUTOMATION = '1'

try {
    Push-Location $discoveryRoot

    & $engine.Source init -backend=false -input=false
    if ($LASTEXITCODE -ne 0) {
        throw "$($engine.Name) init failed with exit code $LASTEXITCODE"
    }

    $schema = & $engine.Source providers schema -json
    if ($LASTEXITCODE -ne 0) {
        throw "$($engine.Name) providers schema failed with exit code $LASTEXITCODE"
    }
    if ([string]::IsNullOrWhiteSpace(($schema | Out-String))) {
        throw 'Provider schema command returned no data.'
    }

    Set-Content -LiteralPath $safeOutput -Value ($schema | Out-String) -Encoding utf8NoBOM
    Write-Output "Wrote provider schema to $safeOutput"
}
finally {
    Pop-Location
    if ($null -eq $previousAutomationValue) {
        Remove-Item Env:TF_IN_AUTOMATION -ErrorAction SilentlyContinue
    }
    else {
        $env:TF_IN_AUTOMATION = $previousAutomationValue
    }
}
