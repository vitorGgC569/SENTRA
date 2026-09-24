param([string]$Bun = "", [string]$Dist = "", [string]$StageRoot = "")

$ErrorActionPreference = "Stop"

function Test-GitPatchApply {
    param(
        [Parameter(Mandatory=$true)][string]$Worktree,
        [Parameter(Mandatory=$true)][string]$PatchPath,
        [switch]$Reverse
    )
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        # A failed --check is a normal probe result here, not a build failure.
        # Windows PowerShell can surface native stderr as a terminating
        # NativeCommandError while ErrorActionPreference is Stop.
        $ErrorActionPreference = "SilentlyContinue"
        if ($Reverse) {
            & git -C $Worktree apply --reverse --check $PatchPath 2>$null | Out-Null
        } else {
            & git -C $Worktree apply --check $PatchPath 2>$null | Out-Null
        }
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Manifest = Get-Content -Raw -LiteralPath (Join-Path $Root "integrations\codex_chatgpt_web\upstream.json") | ConvertFrom-Json
$Checkout = [IO.Path]::GetFullPath((Join-Path $Root ([string]$Manifest.development_checkout)))
$StateRoot = if ($StageRoot) { [IO.Path]::GetFullPath($StageRoot) } else { [IO.Path]::GetFullPath((Join-Path $Root ".sentra\integrations\codex-chatgpt-web")) }
$Source = [IO.Path]::GetFullPath((Join-Path $StateRoot "source\6.0.0"))
$Runtime = [IO.Path]::GetFullPath((Join-Path $StateRoot "runtime\6.0.0"))
$Output = if ($Dist) { [IO.Path]::GetFullPath((Join-Path $Dist "web-models")) } else { Join-Path $Root "dist\web-models" }
$Patch = [IO.Path]::GetFullPath((Join-Path $Root ([string]$Manifest.integration_patch)))
if (-not $Checkout.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Checkout escaped workspace" }
$LocalBuild = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "SENTRA\Build"))
foreach ($Path in @($Source, $Runtime, $Output)) {
    if (-not $Path.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -and
        -not $Path.StartsWith($LocalBuild + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build path escaped the workspace and local build root: $Path"
    }
}
if (-not (Test-Path -LiteralPath $Checkout)) {
    & (Join-Path $PSScriptRoot "Bootstrap-CodexChatGPTWeb.ps1")
}
if ((& git -C $Checkout rev-parse HEAD).Trim() -ne [string]$Manifest.commit) { throw "Upstream commit mismatch" }
if ((& git -C $Checkout status --porcelain)) { throw "Upstream checkout must remain clean" }
if (-not (Test-Path -LiteralPath $Patch)) { throw "SENTRA upstream patch missing" }
if (-not $Manifest.patch_files -or @($Manifest.patch_files).Count -lt 1) { throw "Integration manifest must declare patch_files" }
if (-not $Bun) {
    $Found = Get-Command bun -ErrorAction SilentlyContinue
    if ($Found) { $Bun = $Found.Source }
}
if (-not $Bun) {
    $Local = Join-Path $Root ".sentra\toolchain\node_modules\bun\bin\bun.exe"
    if (Test-Path -LiteralPath $Local) { $Bun = $Local }
}
if (-not $Bun -or -not (Test-Path -LiteralPath $Bun)) { throw "Bun 1.4.0 is required" }
if ((& $Bun --version).Trim() -ne "1.4.0") { throw "Expected Bun 1.4.0" }

New-Item -ItemType Directory -Force -Path (Split-Path $Source -Parent), (Split-Path $Runtime -Parent), (Split-Path $Output -Parent), $StateRoot | Out-Null
$ExpectedHash = (Get-FileHash -LiteralPath $Patch -Algorithm SHA256).Hash
$ApprovedPatch = Join-Path $StateRoot "approved.patch"
$LegacyAppliedPatch = Join-Path $StateRoot "applied.patch"
if (-not (Test-Path -LiteralPath $Source)) {
    & git -C $Checkout worktree add --detach $Source ([string]$Manifest.commit)
    if ($LASTEXITCODE -ne 0) { throw "Could not create pinned integration worktree" }
}
if ((& git -C $Source rev-parse HEAD).Trim() -ne [string]$Manifest.commit) { throw "Integration worktree commit mismatch" }

$CurrentPatchAlreadyApplied = Test-GitPatchApply -Worktree $Source -PatchPath $Patch -Reverse
if (-not $CurrentPatchAlreadyApplied) {
    $PreviousPatch = if (Test-Path -LiteralPath $ApprovedPatch) {
        $ApprovedPatch
    } elseif (Test-Path -LiteralPath $LegacyAppliedPatch) {
        $LegacyAppliedPatch
    } else {
        $null
    }
    if ($PreviousPatch) {
        $PreviousHash = (Get-FileHash -LiteralPath $PreviousPatch -Algorithm SHA256).Hash
        if ($PreviousHash -ne $ExpectedHash) {
            if (Test-GitPatchApply -Worktree $Source -PatchPath $PreviousPatch -Reverse) {
                & git -C $Source apply --reverse $PreviousPatch
                if ($LASTEXITCODE -ne 0) { throw "Could not remove the previously approved integration patch" }
            }
        }
    }
}
if (-not (Test-GitPatchApply -Worktree $Source -PatchPath $Patch -Reverse)) {
    if (-not (Test-GitPatchApply -Worktree $Source -PatchPath $Patch)) {
        # The integration source is a disposable pinned worktree. A previous
        # failed build may have left an older approved patch applied. Restore
        # tracked files to the pinned commit, then validate the current patch.
        & git -C $Source reset --hard ([string]$Manifest.commit) | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not restore the pinned integration worktree" }
        if (-not (Test-GitPatchApply -Worktree $Source -PatchPath $Patch)) {
            throw "SENTRA patch does not apply cleanly to the pinned upstream"
        }
    }
    & git -C $Source apply $Patch
    if ($LASTEXITCODE -ne 0) { throw "SENTRA patch application failed" }
}
& git -C $Source diff --check
if ($LASTEXITCODE -ne 0) { throw "Patched upstream contains whitespace errors" }
$ChangedFiles = @(& git -C $Source diff --name-only) | ForEach-Object { $_.Trim().Replace("\", "/") } | Where-Object { $_ } | Sort-Object -Unique
$ExpectedFiles = @($Manifest.patch_files) | ForEach-Object { ([string]$_).Replace("\", "/") } | Sort-Object -Unique
$Unexpected = @(Compare-Object -ReferenceObject $ExpectedFiles -DifferenceObject $ChangedFiles)
if ($Unexpected.Count -ne 0) {
    throw "Integration worktree changed an unexpected file set: $($Unexpected | Out-String)"
}
$Applied = Join-Path $StateRoot "applied.diff"
& git -C $Source diff --binary "--output=$Applied"
if ($LASTEXITCODE -ne 0) { throw "Could not capture applied integration diff" }
$AppliedHash = (Get-FileHash -LiteralPath $Applied -Algorithm SHA256).Hash
Copy-Item -Force -LiteralPath $Patch -Destination $ApprovedPatch
Set-Content -Encoding ASCII -NoNewline -LiteralPath (Join-Path $StateRoot "approved-patch.sha256") -Value $ExpectedHash

Push-Location $Source
try {
    & $Bun install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "Root dependency install failed" }
    & $Bun run typecheck
    if ($LASTEXITCODE -ne 0) { throw "Patched upstream typecheck failed" }
    Push-Location (Join-Path $Source "launcher")
    try {
        & $Bun install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw "Electron dependency install failed" }
    } finally { Pop-Location }
    & $Bun run scripts/build-runtime-bundle.ts $Runtime
    if ($LASTEXITCODE -ne 0) { throw "Runtime build failed" }
    Push-Location (Join-Path $Source "launcher")
    try {
        & $Bun run build
        if ($LASTEXITCODE -ne 0) { throw "Electron renderer build failed" }
        $env:CODEX_WEB_GPT_BUN = $Bun
        & $Bun run build:runtime
        if ($LASTEXITCODE -ne 0) { throw "Electron runtime build failed" }
        & $Bun x --no-install electron-builder --dir --win --publish never "--config.directories.output=$Output"
        if ($LASTEXITCODE -ne 0) { throw "Electron directory packaging failed" }
    } finally {
        Pop-Location
        Remove-Item Env:CODEX_WEB_GPT_BUN -ErrorAction SilentlyContinue
    }
} finally {
    Pop-Location
}
$Executable = Join-Path $Output "win-unpacked\Codex Web GPT.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "Packaged Electron executable missing: $Executable" }
$NoticeDir = Join-Path $Output "licenses\codex-chatgpt-web"
New-Item -ItemType Directory -Force -Path $NoticeDir | Out-Null
Copy-Item -Force -LiteralPath (Join-Path $Checkout "LICENSE") -Destination (Join-Path $NoticeDir "LICENSE")
Copy-Item -Force -LiteralPath (Join-Path $Root "integrations\codex_chatgpt_web\upstream.json") -Destination (Join-Path $NoticeDir "upstream.json")
Copy-Item -Force -LiteralPath $Patch -Destination (Join-Path $NoticeDir "sentra-upstream.patch")
$State = [ordered]@{
    commit = [string]$Manifest.commit
    ref = [string]$Manifest.ref
    patch_sha256 = $ExpectedHash.ToLower()
    applied_diff_sha256 = $AppliedHash.ToLower()
    patch_files = @($ExpectedFiles)
    runtime = $Runtime
    electron = $Executable
    built_at = (Get-Date).ToString("o")
}
$StateJson = $State | ConvertTo-Json -Depth 4
$StateJson | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $StateRoot "runtime-build.json")
$StateJson | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $Output "integration-build.json")
Write-Host "SENTRA Web runtime and Electron ready: $Executable"
