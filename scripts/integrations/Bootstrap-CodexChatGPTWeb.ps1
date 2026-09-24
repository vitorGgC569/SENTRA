param(
    [string]$Ref = "",
    [switch]$Update
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/miuuyy/codex-chatgpt-web.git"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ManifestPath = Join-Path $Root "integrations\codex_chatgpt_web\upstream.json"
$Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($Ref)) {
    $Ref = [string]$Manifest.ref
}
$Dest = Join-Path $Root ([string]$Manifest.development_checkout)
$StateDir = Join-Path $Root ".sentra\integrations\codex-chatgpt-web"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git failed: git $($Args -join ' ')"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to bootstrap codex-chatgpt-web."
}

if (-not (Test-Path -LiteralPath $Dest)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest -Parent) | Out-Null
    Invoke-Git clone --depth 1 --branch $Ref $RepoUrl $Dest
} else {
    $GitDir = Join-Path $Dest ".git"
    if (-not (Test-Path -LiteralPath $GitDir)) {
        throw "Destination exists but is not a Git checkout: $Dest"
    }
    $Origin = (& git -C $Dest remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or $Origin -ne $RepoUrl) {
        throw "Unexpected upstream remote at ${Dest}: $Origin"
    }
    if ($Update) {
        Invoke-Git -C $Dest fetch --tags --prune origin
        if ((& git -C $Dest status --porcelain)) {
            throw "Upstream checkout has local changes; refusing update."
        }
        Invoke-Git -C $Dest checkout --detach $Ref
    }
}

$OriginFinal = (& git -C $Dest remote get-url origin).Trim()
$Commit = (& git -C $Dest rev-parse HEAD).Trim()
$HeadRef = (& git -C $Dest describe --tags --always --dirty).Trim()
if ($OriginFinal -ne $RepoUrl) {
    throw "Upstream provenance mismatch: $OriginFinal"
}
if ($Commit -ne [string]$Manifest.commit) {
    throw "Upstream commit mismatch: expected $($Manifest.commit), found $Commit"
}
if ((& git -C $Dest status --porcelain)) {
    throw "Upstream checkout must be clean before integration."
}

$PackagePath = Join-Path $Dest "package.json"
$LicensePath = Join-Path $Dest "LICENSE"
if (-not (Test-Path -LiteralPath $PackagePath) -or -not (Test-Path -LiteralPath $LicensePath)) {
    throw "Upstream checkout is incomplete."
}

$Package = Get-Content -Raw -LiteralPath $PackagePath | ConvertFrom-Json
if ($Package.name -ne "codex-chatgpt-web") {
    throw "Unexpected upstream package name: $($Package.name)"
}
if ($Package.license -ne "MIT") {
    throw "Unexpected upstream license: $($Package.license)"
}

$State = [ordered]@{
    repository = $RepoUrl
    requested_ref = $Ref
    commit = $Commit
    describe = $HeadRef
    package_version = [string]$Package.version
    path = $Dest
    verified_at = (Get-Date).ToString("o")
}
$State | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $StateDir "checkout.json")
Write-Host "codex-chatgpt-web ready"
Write-Host "  ref:     $Ref"
Write-Host "  commit:  $Commit"
Write-Host "  version: $($Package.version)"
Write-Host "  path:    $Dest"
