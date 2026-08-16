[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$gitDirectory = Join-Path $repoRoot '.git'
if (-not (Test-Path -LiteralPath $gitDirectory -PathType Container)) {
    throw 'A Git working tree is required to install hooks.'
}
$destination = Join-Path $gitDirectory 'hooks\pre-commit'
Copy-Item -LiteralPath (Join-Path $repoRoot 'scripts\quality\pre-commit-hook.sh') -Destination $destination -Force
Write-Host '[phase 1] target=install-hooks'
Write-Host "[PASS] Installed $destination; it delegates to the canonical 'make pre-commit' target."
