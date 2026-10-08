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
            & git -C $Worktree apply --reverse --check --unidiff-zero $PatchPath 2>$null | Out-Null
        } else {
            & git -C $Worktree apply --check --unidiff-zero $PatchPath 2>$null | Out-Null
        }
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Get-LiveWebModelsProcesses {
    param([Parameter(Mandatory=$true)][string]$PayloadRoot)
    $Prefix = [IO.Path]::GetFullPath($PayloadRoot).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and
        ([IO.Path]::GetFullPath([string]$_.ExecutablePath)).StartsWith(
            $Prefix,
            [StringComparison]::OrdinalIgnoreCase
        )
    })
}

function Invoke-SentraWebRuntimeControl {
    param([Parameter(Mandatory=$true)][ValidateSet("Stop","Start")][string]$Action)
    $PreviousEncoding = $env:PYTHONIOENCODING
    try {
        $env:PYTHONIOENCODING = "utf-8"
        Push-Location $Root
        try {
            if ($Action -eq "Stop") {
                & python -c "from sentra_cli.config import CLIConfig; from sentra_cli.client import ModelClient; c=ModelClient(CLIConfig()); print(c._stop_headless_upstream()); print(c._stop_browser_host())"
            } else {
                & python -c "import sys; from sentra_cli.config import CLIConfig; from sentra_cli.client import ModelClient; c=ModelClient(CLIConfig()); b=c._spawn_browser_host(); u=c._spawn_headless_upstream(); print(b); print(u); sys.exit(0 if c._browser_host_ready() else 3)"
            }
            if ($LASTEXITCODE -ne 0) {
                throw "SENTRA Web runtime $Action helper failed with exit code $LASTEXITCODE"
            }
            if ($Action -eq "Start") {
                $Ready = $false
                $Deadline = (Get-Date).AddSeconds(30)
                while ((Get-Date) -lt $Deadline) {
                    try {
                        $Health = Invoke-RestMethod "http://127.0.0.1:17841/healthz" -TimeoutSec 2
                        if ($Health.status -eq "ok" -and $Health.accepting_turns -eq $true) {
                            $Ready = $true
                            break
                        }
                    } catch {
                        # Runtime may still be binding the loopback listener.
                    }
                    Start-Sleep -Milliseconds 250
                }
                if (-not $Ready) {
                    throw "SENTRA Web runtime did not become healthy after publish"
                }
            }
        } finally {
            Pop-Location
        }
    } finally {
        if ($null -eq $PreviousEncoding) {
            Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONIOENCODING = $PreviousEncoding
        }
    }
}

$Manifest = Get-Content -Raw -LiteralPath (Join-Path $Root "integrations\codex_chatgpt_web\upstream.json") | ConvertFrom-Json
$Checkout = [IO.Path]::GetFullPath((Join-Path $Root ([string]$Manifest.development_checkout)))
$StateRoot = if ($StageRoot) { [IO.Path]::GetFullPath($StageRoot) } else { [IO.Path]::GetFullPath((Join-Path $Root ".sentra\integrations\codex-chatgpt-web")) }
$UpstreamRef = ([string]$Manifest.ref).Trim()
if ($UpstreamRef -notmatch '^v(?<version>[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)$') {
    throw "Integration manifest ref must be an exact v-prefixed semantic version"
}
$UpstreamVersion = $Matches.version
$Source = [IO.Path]::GetFullPath((Join-Path $StateRoot ("source\" + $UpstreamVersion)))
$Runtime = [IO.Path]::GetFullPath((Join-Path $StateRoot ("runtime\" + $UpstreamVersion)))
$FinalOutput = if ($Dist) { [IO.Path]::GetFullPath((Join-Path $Dist "web-models")) } else { Join-Path $Root "dist\web-models" }
# Never build in-place over the live Web Models payload. A failed/clean build
# must not erase files used by an already-running launcher/daemon.
$Output = $FinalOutput + ".staging-" + [string]$PID
$Patch = [IO.Path]::GetFullPath((Join-Path $Root ([string]$Manifest.integration_patch)))
if (-not $Checkout.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Checkout escaped workspace" }
$LocalBuild = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "SENTRA\Build"))
foreach ($Path in @($Source, $Runtime, $FinalOutput, $Output)) {
    if (-not $Path.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -and
        -not $Path.StartsWith($LocalBuild + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Build path escaped the workspace and local build root: $Path"
    }
}
if (-not (Test-Path -LiteralPath $Checkout)) {
    & (Join-Path $PSScriptRoot "Bootstrap-CodexChatGPTWeb.ps1")
}
if ((& git -C $Checkout rev-parse HEAD).Trim() -ne [string]$Manifest.commit) {
    & (Join-Path $PSScriptRoot "Bootstrap-CodexChatGPTWeb.ps1") -Update
}
if ((& git -C $Checkout rev-parse HEAD).Trim() -ne [string]$Manifest.commit) { throw "Upstream commit mismatch after bootstrap update" }
if ((& git -C $Checkout status --porcelain)) { throw "Upstream checkout must remain clean" }
if (-not (Test-Path -LiteralPath $Patch)) { throw "SENTRA upstream patch missing" }
if (-not $Manifest.patch_files -or @($Manifest.patch_files).Count -lt 1) { throw "Integration manifest must declare patch_files" }
# Validate the authoritative patch against the pristine pinned checkout too.
# This catches whitespace errors in newly-created files, which git diff --check
# cannot see as long as those files are untracked in the applied worktree.
& git -C $Checkout apply --check --unidiff-zero $Patch
if ($LASTEXITCODE -ne 0) { throw "SENTRA patch failed pristine whitespace/apply validation" }
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
if (Test-Path -LiteralPath $Output) {
    Remove-Item -LiteralPath $Output -Recurse -Force
}
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
                & git -C $Source apply --reverse --unidiff-zero $PreviousPatch
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
    & git -C $Source apply --unidiff-zero $Patch
    if ($LASTEXITCODE -ne 0) { throw "SENTRA patch application failed" }
}
$NewFiles = @(& git -C $Source ls-files --others --exclude-standard)
if ($NewFiles.Count -gt 0) {
    # Make newly-created patch files visible to diff --check without committing
    # or permanently staging them. This closes the blind spot where whitespace
    # errors in untracked Gemini/model-catalog files escaped validation.
    & git -C $Source add --intent-to-add -- @NewFiles
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare new integration files for whitespace validation" }
}
& git -C $Source diff --check
if ($LASTEXITCODE -ne 0) { throw "Patched upstream contains whitespace errors" }
if ($NewFiles.Count -gt 0) {
    & git -C $Source reset --quiet HEAD -- @NewFiles
    if ($LASTEXITCODE -ne 0) { throw "Could not restore integration worktree index after validation" }
}
$TrackedChanges = @(& git -C $Source diff --name-only)
$NewFiles = @(& git -C $Source ls-files --others --exclude-standard)
$ChangedFiles = @($TrackedChanges + $NewFiles) |
    ForEach-Object { $_.Trim().Replace("\", "/") } |
    Where-Object { $_ } |
    Sort-Object -Unique
$ExpectedFiles = @($Manifest.patch_files) |
    ForEach-Object { ([string]$_).Replace("\", "/") } |
    Sort-Object -Unique
$Unexpected = @(Compare-Object -ReferenceObject $ExpectedFiles -DifferenceObject $ChangedFiles)
if ($Unexpected.Count -ne 0) {
    throw "Integration worktree changed an unexpected file set: $($Unexpected | Out-String)"
}
$Applied = Join-Path $StateRoot "applied.diff"
Copy-Item -Force -LiteralPath $Patch -Destination $Applied
$AppliedHash = (Get-FileHash -LiteralPath $Applied -Algorithm SHA256).Hash
Copy-Item -Force -LiteralPath $Patch -Destination $ApprovedPatch
Set-Content -Encoding ASCII -NoNewline -LiteralPath (Join-Path $StateRoot "approved-patch.sha256") -Value $ExpectedHash

Push-Location $Source
try {
    & $Bun install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "Root dependency install failed" }
    & $Bun run typecheck
    if ($LASTEXITCODE -ne 0) { throw "Patched upstream typecheck failed" }
    & $Bun test "tests/gemini-web.test.ts" "tests/gemini-web-adapter.test.ts"
    if ($LASTEXITCODE -ne 0) { throw "Patched Gemini Web integration tests failed" }
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

$RequiredPayloadFiles = @(
    $Executable,
    (Join-Path $Output "win-unpacked\resources\runtime\manifest.json"),
    (Join-Path $Output "win-unpacked\resources\runtime\app\cli.js"),
    (Join-Path $NoticeDir "LICENSE"),
    (Join-Path $NoticeDir "upstream.json"),
    (Join-Path $NoticeDir "sentra-upstream.patch")
)
foreach ($RequiredFile in $RequiredPayloadFiles) {
    if (-not (Test-Path -LiteralPath $RequiredFile -PathType Leaf)) {
        throw "Staged Web Models payload is incomplete: $RequiredFile"
    }
}

$FinalExecutable = Join-Path $FinalOutput "win-unpacked\Codex Web GPT.exe"
$State = [ordered]@{
    commit = [string]$Manifest.commit
    ref = [string]$Manifest.ref
    patch_sha256 = $ExpectedHash.ToLower()
    applied_diff_sha256 = $AppliedHash.ToLower()
    patch_files = @($ExpectedFiles)
    runtime = $Runtime
    electron = $FinalExecutable
    built_at = (Get-Date).ToString("o")
}
$StateJson = $State | ConvertTo-Json -Depth 4
$StateJson | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $Output "integration-build.json")

# Transactional live-safe publish. Windows cannot rename the payload while
# its Bun/Electron processes execute from that directory, so stop only the
# SENTRA-owned runtime after proving there are no active turns. External
# launchers are never terminated: their processes remain and make the publish
# fail closed below.
$RestartSentraWebRuntime = $false
$LivePayloadProcesses = @(Get-LiveWebModelsProcesses -PayloadRoot $FinalOutput)
if ($LivePayloadProcesses.Count -gt 0) {
    $Listener = Get-NetTCPConnection -State Listen -LocalPort 17841 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($Listener) {
        try {
            $Health = Invoke-RestMethod "http://127.0.0.1:17841/healthz" -TimeoutSec 3
        } catch {
            throw "Refusing live Web Models publish: the existing runtime is listening but its health cannot be verified"
        }
        $ActiveHttpTurns = if ($null -ne $Health.active_http_turns) { [int]$Health.active_http_turns } else { 0 }
        $ActiveBrowserTurns = if ($null -ne $Health.active_browser_turns) { [int]$Health.active_browser_turns } else { 0 }
        if ($ActiveHttpTurns -gt 0 -or $ActiveBrowserTurns -gt 0) {
            throw "Refusing live Web Models publish while turns are active (http=$ActiveHttpTurns browser=$ActiveBrowserTurns)"
        }
    }

    Invoke-SentraWebRuntimeControl -Action Stop
    Start-Sleep -Milliseconds 750
    $RemainingPayloadProcesses = @(Get-LiveWebModelsProcesses -PayloadRoot $FinalOutput)
    if ($RemainingPayloadProcesses.Count -gt 0) {
        $RemainingSummary = ($RemainingPayloadProcesses | ForEach-Object {
            "$($_.Name):$($_.ProcessId)"
        }) -join ", "
        throw "Refusing to replace a live Web Models payload that SENTRA does not exclusively own: $RemainingSummary"
    }
    $RestartSentraWebRuntime = $true
}

$BackupOutput = $FinalOutput + ".rollback-" + [string]$PID
if (Test-Path -LiteralPath $BackupOutput) {
    Remove-Item -LiteralPath $BackupOutput -Recurse -Force
}
$HadPreviousOutput = Test-Path -LiteralPath $FinalOutput
$PublishError = $null
try {
    if ($HadPreviousOutput) {
        Move-Item -LiteralPath $FinalOutput -Destination $BackupOutput
    }
    try {
        Move-Item -LiteralPath $Output -Destination $FinalOutput
    } catch {
        if ($HadPreviousOutput -and -not (Test-Path -LiteralPath $FinalOutput) -and (Test-Path -LiteralPath $BackupOutput)) {
            Move-Item -LiteralPath $BackupOutput -Destination $FinalOutput
        }
        throw
    }
} catch {
    $PublishError = $_.Exception.Message
}

if ($PublishError) {
    if ($RestartSentraWebRuntime) {
        try {
            Invoke-SentraWebRuntimeControl -Action Start
        } catch {
            $PublishError += "; previous runtime restart also failed: $($_.Exception.Message)"
        }
    }
    throw "Transactional Web Models publish failed; previous payload was preserved or restored: $PublishError"
}

if (Test-Path -LiteralPath $BackupOutput) {
    try {
        Remove-Item -LiteralPath $BackupOutput -Recurse -Force
    } catch {
        Write-Warning "Previous Web Models payload remains at $BackupOutput and can be removed after old processes exit"
    }
}
$StateJson | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $StateRoot "runtime-build.json")

if ($RestartSentraWebRuntime) {
    Invoke-SentraWebRuntimeControl -Action Start
}

Write-Host "SENTRA Web runtime and Electron ready: $FinalExecutable"
