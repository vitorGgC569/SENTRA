$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = $Root + ';' + $env:PYTHONPATH
} else {
    $env:PYTHONPATH = $Root
}
Push-Location $Root
try {
    & python -B -m sentra_cli @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}