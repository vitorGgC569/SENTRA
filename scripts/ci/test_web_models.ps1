param([Parameter(Mandatory=$true)][string]$Bun)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Manifest = Get-Content -Raw (Join-Path $Root 'integrations\codex_chatgpt_web\upstream.json') | ConvertFrom-Json
$Checkout = Join-Path $Root $Manifest.development_checkout
$Patch = Join-Path $Root $Manifest.integration_patch
if (-not (Test-Path -LiteralPath $Bun -PathType Leaf)) { throw 'Pinned Bun executable missing' }
$Bun = (Resolve-Path -LiteralPath $Bun).Path
if ((& $Bun --version).Trim() -ne '1.4.0') { throw 'Bun 1.4.0 required' }
& (Join-Path $Root 'scripts\integrations\Bootstrap-CodexChatGPTWeb.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Upstream bootstrap failed' }
$TempParent = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { Join-Path $Root '.tmp' }
$Worktree = Join-Path $TempParent ("sentra-ci-web-$PID")
try {
    & git -C $Checkout apply --check --unidiff-zero $Patch
    if ($LASTEXITCODE -ne 0) { throw 'Pinned upstream patch does not apply' }
    & git -C $Checkout worktree add --detach $Worktree $Manifest.commit
    if ($LASTEXITCODE -ne 0) { throw 'Could not create clean upstream test worktree' }
    & git -C $Worktree apply --unidiff-zero $Patch
    if ($LASTEXITCODE -ne 0) { throw 'Cannot apply SENTRA integration' }
    Push-Location $Worktree
    try {
        & $Bun install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Root dependency lock install failed' }
        & $Bun run typecheck
        if ($LASTEXITCODE -ne 0) { throw 'Web Models TypeScript failed' }
        & $Bun test tests/chatgpt-web-models.test.ts tests/chatgpt-model-selection.test.ts tests/model-catalog.test.ts tests/server-models.test.ts tests/gemini-web.test.ts tests/gemini-web-adapter.test.ts
        if ($LASTEXITCODE -ne 0) { throw 'Web Models integration regression failed' }
        Push-Location launcher
        try {
            & $Bun install --frozen-lockfile
            if ($LASTEXITCODE -ne 0) { throw 'Electron dependency lock install failed' }
            & $Bun run build
            if ($LASTEXITCODE -ne 0) { throw 'Electron renderer/TypeScript build failed' }
        } finally { Pop-Location }
        Write-Output 'SENTRA_WEB_MODELS_CI_OK'
    } finally { Pop-Location }
} finally {
    if (Test-Path -LiteralPath $Worktree) {
        & git -C $Checkout worktree remove --force $Worktree
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Ephemeral upstream CI worktree cleanup failed' }
    }
}
