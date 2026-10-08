param([string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path, [string]$Output = '')
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path $Root).Path
if (-not $Output) { $Output = Join-Path $Root '.sentra\canvas\native-next' }
$Builder = Join-Path $Root 'scripts\commander\build_canvas.py'
Push-Location $Root
try {
    & python $Builder --dist $Output
    if ($LASTEXITCODE -ne 0) { throw "Canvas builder returned exit code $LASTEXITCODE" }
    $Exe = Join-Path $Output 'sentra-canvas.exe'
    $File = Get-Item $Exe
    Write-Output "SENTRA_NATIVE_BUILD_OK=$($File.FullName)"
    Write-Output "SENTRA_NATIVE_BYTES=$($File.Length)"
    Write-Output 'Review and test before replacing an active application.'
} finally { Pop-Location }
