[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('validate', 'negative', 'pre-commit', 'secret-scan', 'ci')]
    [string]$Target
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$lockPath = Join-Path $repoRoot 'versions.lock.yaml'
$imageLine = Select-String -LiteralPath $lockPath -Pattern '^  quality_image: "([^"]+)"$'
if ($imageLine.Matches.Count -ne 1) {
    throw 'versions.lock.yaml must contain exactly one tool_delivery.quality_image value.'
}
$image = $imageLine.Matches[0].Groups[1].Value
$scripts = @{
    validate      = 'scripts/quality/validate.sh'
    negative      = 'scripts/quality/negative-tests.sh'
    'pre-commit'  = 'scripts/quality/pre-commit.sh'
    'secret-scan' = 'scripts/quality/secret-scan.sh'
    ci            = 'scripts/quality/ci.sh'
}

$localRoot = Join-Path $repoRoot '.local'
$logRoot = Join-Path $localRoot 'logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

Write-Host "[phase 1] target=$Target image=$image network=none"
& docker image inspect $image 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Pinned quality image '$image' is missing. Run 'make bootstrap-tools' first."
}
$bootstrapMarker = Join-Path $localRoot 'bootstrap.complete'
if (-not (Test-Path -LiteralPath $bootstrapMarker)) {
    throw "Pinned offline caches are missing. Run 'make bootstrap-tools' first."
}
$marker = Get-Content -LiteralPath $bootstrapMarker -Raw | ConvertFrom-StringData
$lockedInputs = [ordered]@{
    versions_lock_sha256 = (Join-Path $repoRoot 'versions.lock.yaml')
    aqua_config_sha256 = (Join-Path $repoRoot 'aqua.yaml')
    schema_lock_sha256 = (Join-Path $repoRoot 'schemas\schema-sources.lock.yaml')
    quality_dockerfile_sha256 = (Join-Path $repoRoot 'tooling\quality\Dockerfile')
    requirements_quality_sha256 = (Join-Path $repoRoot 'requirements-quality.txt')
}
foreach ($entry in $lockedInputs.GetEnumerator()) {
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.Value).Hash.ToLowerInvariant()
    if (-not $marker.ContainsKey($entry.Key) -or $marker[$entry.Key] -ne $actual) {
        throw "Offline caches are stale for $($entry.Value). Run 'make bootstrap-tools' first."
    }
}

$dockerArgs = @(
    'run', '--rm', '--network', 'none', '--read-only',
    '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
    '--pids-limit', '512',
    '--volume', "${repoRoot}:/workspace",
    '--workdir', '/workspace',
    '--env', 'HOME=/tmp/home',
    '--env', 'ANSIBLE_LOCAL_TEMP=/tmp/ansible-local',
    '--env', 'ANSIBLE_REMOTE_TEMP=/tmp/ansible-remote',
    '--env', 'AQUA_LOG_LEVEL=error',
    '--env', 'PRE_COMMIT_HOME=/tmp/pre-commit',
    '--env', 'TF_PLUGIN_CACHE_DIR=/workspace/.local/terraform-plugin-cache',
    '--env', 'TRIVY_CACHE_DIR=/workspace/.local/trivy',
    $image, 'bash', $scripts[$Target]
)
$logPath = Join-Path $logRoot "$Target.log"
& docker @dockerArgs 2>&1 | Tee-Object -FilePath $logPath
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    Write-Error "Phase 1 target '$Target' failed with exit code $exitCode. See $logPath"
    exit $exitCode
}
Write-Host "[PASS] Phase 1 target '$Target' completed."
