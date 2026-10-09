param([switch]$RequireEdge)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $Root
try {
    if ($RequireEdge) {
        $pf86 = [Environment]::GetFolderPath('ProgramFilesX86')
        $pf = [Environment]::GetFolderPath('ProgramFiles')
        $Candidates = @(
            (Join-Path $pf86 'Microsoft\Edge\Application\msedge.exe'),
            (Join-Path $pf 'Microsoft\Edge\Application\msedge.exe'),
            (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
        )
        if (-not ($Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1)) {
            throw 'CI requires Microsoft Edge to test the WebView2-compatible Canvas DOM'
        }
    }
    foreach ($script in @(
        'sentra_canvas/static/native.js',
        'sentra_canvas/static/app.js',
        'sentra_canvas/static/fractal-grid.js',
        'sentra_canvas/static/rope-physics.js'
    )) {
        & node --check $script
        if ($LASTEXITCODE -ne 0) { throw "Canvas JavaScript syntax failed: $script" }
    }
    & node --test tests/js/canvas_cable_physics.cjs
    if ($LASTEXITCODE -ne 0) { throw 'Canvas cable physics failed' }
    $e2eOutput = @(& python -B -m pytest -q tests/e2e/test_canvas_web_cult_ui.py tests/e2e/test_sentra_canvas_native_ui.py tests/e2e/test_sentra_canvas_ui.py)
    $e2eCode = $LASTEXITCODE
    $e2eOutput | ForEach-Object { Write-Output $_ }
    if ($e2eCode -ne 0) { throw 'Canvas Edge E2E failed' }
    $summary = $e2eOutput -join ' '
    if ($RequireEdge -and ($summary -match '\b[1-9][0-9]* skipped\b' -or $summary -notmatch '\b[1-9][0-9]* passed\b')) {
        throw 'Canvas Edge E2E did not execute all required tests'
    }
    Write-Output 'SENTRA_CANVAS_CI_OK'
} finally { Pop-Location }
