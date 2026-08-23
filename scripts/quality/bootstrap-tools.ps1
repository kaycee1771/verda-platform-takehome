[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$lockPath = Join-Path $repoRoot 'versions.lock.yaml'
$imageLine = Select-String -LiteralPath $lockPath -Pattern '^  quality_image: "([^"]+)"$'
if ($imageLine.Matches.Count -ne 1) {
    throw 'versions.lock.yaml must contain exactly one tool_delivery.quality_image value.'
}
$image = $imageLine.Matches[0].Groups[1].Value
$registryRefLine = Select-String -LiteralPath $lockPath -Pattern '^  aqua_registry_ref: "([^"]+)"$'
$registryCommitLine = Select-String -LiteralPath $lockPath -Pattern '^  aqua_registry_commit: "([0-9a-f]{40})"$'
if ($registryRefLine.Matches.Count -ne 1 -or $registryCommitLine.Matches.Count -ne 1) {
    throw 'versions.lock.yaml must contain exactly one Aqua registry ref and commit.'
}
$registryRef = $registryRefLine.Matches[0].Groups[1].Value
$registryCommit = $registryCommitLine.Matches[0].Groups[1].Value
$localRoot = Join-Path $repoRoot '.local'
$logRoot = Join-Path $localRoot 'logs'
$reportRoot = Join-Path $localRoot 'reports'
New-Item -ItemType Directory -Force -Path $logRoot, $reportRoot | Out-Null

Write-Host "[phase 1] target=bootstrap-tools image=$image"
Write-Host '[INFO] Host tools are detected and reported; no workstation package is installed or upgraded.'

$hostTools = @(
    'git', 'make', 'pwsh', 'docker', 'terraform', 'verda', 'ansible', 'kubectl',
    'helm', 'argocd', 'rancher', 'cilium', 'velero', 'trivy', 'cosign', 'syft',
    'kubeconform', 'kyverno', 'promtool', 'tflint', 'ansible-lint', 'yamllint',
    'shellcheck', 'gitleaks'
)
foreach ($tool in $hostTools) {
    $command = Get-Command $tool -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        Write-Host "[HOST] $tool=MISSING (provided by the quality image when required)"
    } else {
        Write-Host "[HOST] $tool=$($command.Source)"
    }
}

if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is required to bootstrap the pinned quality environment. Install/start Docker, then retry.'
}

$registryRefs = & git ls-remote https://github.com/aquaproj/aqua-registry.git `
    "refs/tags/$registryRef" "refs/tags/$registryRef^{}"
if ($LASTEXITCODE -ne 0 -or $registryRefs.Count -eq 0) {
    throw "Unable to resolve the public Aqua registry tag '$registryRef'."
}
$resolvedRegistryCommits = @($registryRefs | ForEach-Object { ($_ -split "`t")[0] })
if ($registryCommit -notin $resolvedRegistryCommits) {
    throw "Aqua registry tag '$registryRef' no longer resolves to locked commit '$registryCommit'."
}
Write-Host "[PASS] Aqua registry $registryRef resolves to immutable commit $registryCommit"

& docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker is installed but its Linux daemon is unavailable. Start Docker Desktop, then retry.'
}

$buildLog = Join-Path $logRoot 'bootstrap-image.log'
$dockerfilePath = Join-Path $repoRoot 'tooling\quality\Dockerfile'
$dockerfileSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $dockerfilePath).Hash.ToLowerInvariant()
$bootstrapMarkerPath = Join-Path $localRoot 'bootstrap.complete'
$reuseQualityImage = $false
& docker image inspect $image 2>$null | Out-Null
if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $bootstrapMarkerPath -PathType Leaf)) {
    $previousMarker = Get-Content -LiteralPath $bootstrapMarkerPath -Raw | ConvertFrom-StringData
    $reuseQualityImage = (
        $previousMarker.ContainsKey('quality_dockerfile_sha256') -and
        $previousMarker.quality_dockerfile_sha256 -eq $dockerfileSha256
    )
}
if ($reuseQualityImage) {
    Write-Host '[PASS] Existing pinned quality image matches the unchanged Dockerfile input.'
} else {
    # Every base/tool input is digest- or checksum-pinned, so a forced mutable
    # registry refresh adds no integrity and makes offline cache reuse impossible.
    & docker build --provenance=false --tag $image `
        --file $dockerfilePath $repoRoot 2>&1 |
        Tee-Object -FilePath $buildLog
    if ($LASTEXITCODE -ne 0) {
        throw "Quality image build failed. See $buildLog"
    }
}

Write-Host '[INFO] Warming version-pinned provider, schema, and Trivy caches. No cloud API is contacted.'
$cacheLog = Join-Path $logRoot 'bootstrap-cache.log'
$cacheOwner = '65532:65532'
if ($IsLinux) {
    $hostUid = (& id -u).Trim()
    if ($LASTEXITCODE -ne 0 -or $hostUid -notmatch '^\d+$') {
        throw 'Unable to determine the Linux host UID for writable cache ownership.'
    }
    # The runner owns generated files; the non-root validator retains group write access.
    $cacheOwner = "${hostUid}:65532"
}
$cacheCommand = "bash scripts/quality/bootstrap-cache.sh && " +
    "chown -R $cacheOwner /workspace/.local && " +
    'chmod -R u+rwX,g+rwX,o-rwx /workspace/.local'
$cacheArgs = @(
    'run', '--rm', '--user', '0:0',
    '--volume', "${repoRoot}:/workspace", '--workdir', '/workspace'
)
$githubToken = [Environment]::GetEnvironmentVariable('GITHUB_TOKEN')
if (-not [string]::IsNullOrWhiteSpace($githubToken)) {
    # Forward only the variable name. Docker reads its value from this process and the
    # short-lived --rm container is used solely for networked cache bootstrap.
    $cacheArgs += @('--env', 'GITHUB_TOKEN')
}
$cacheArgs += @($image, 'bash', '-c', $cacheCommand)
& docker @cacheArgs 2>&1 |
    Tee-Object -FilePath $cacheLog
if ($LASTEXITCODE -ne 0) {
    throw "Quality cache bootstrap failed. See $cacheLog"
}

$inspect = & docker image inspect $image | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $inspect.Count -ne 1) {
    throw 'Unable to inspect the completed quality image.'
}
$metadata = [ordered]@{
    schema_version = 1
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    image = $image
    image_id = $inspect[0].Id
    repo_digests = @($inspect[0].RepoDigests)
    size_bytes = $inspect[0].Size
    validation_network = 'none'
    cloud_credentials_forwarded = $false
    build_provenance_attestation = $false
    provenance_model = 'repository source locks and checksums'
}
$metadata | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reportRoot 'tool-image.json') -Encoding utf8NoBOM

$versionCheckArgs = @(
    'run', '--rm', '--network', 'none', '--read-only',
    '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m',
    '--volume', "${repoRoot}:/workspace:ro",
    '--workdir', '/workspace',
    '--env', 'HOME=/tmp/home',
    '--env', 'ANSIBLE_LOCAL_TEMP=/tmp/ansible-local',
    '--env', 'ANSIBLE_REMOTE_TEMP=/tmp/ansible-remote',
    $image, 'python', 'scripts/quality/check_versions.py'
)
& docker @versionCheckArgs
if ($LASTEXITCODE -ne 0) {
    throw 'The built image does not match versions.lock.yaml.'
}

Write-Host '[PASS] Phase 1 quality toolchain and offline caches are ready.'
