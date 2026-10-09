param([string]$Destination = "", [switch]$WriteGitHubEnv)
$ErrorActionPreference = 'Stop'
$Version = '1.4.0'
$ExpectedSha256 = 'e6f093d39da486b20262ca8cdd5ed6a9e8bc9c2f275b78e6d3a0c5b28cc95901'
if (-not $Destination) { $Destination = Join-Path $env:RUNNER_TEMP 'sentra-bun-1.4.0' }
$Destination = [IO.Path]::GetFullPath($Destination)
$Archive = Join-Path (Split-Path $Destination -Parent) 'bun-windows-x64-1.4.0.zip'
New-Item -ItemType Directory -Force (Split-Path $Destination -Parent) | Out-Null
Invoke-WebRequest -Uri 'https://github.com/oven-sh/bun/releases/download/bun-v1.4.0/bun-windows-x64.zip' -OutFile $Archive
$Hash = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Hash -ne $ExpectedSha256) { throw "Bun integrity violation: expected $ExpectedSha256, got $Hash" }
if (Test-Path $Destination) { Remove-Item -Recurse -Force $Destination }
Expand-Archive -LiteralPath $Archive -DestinationPath $Destination
$Bun = Get-ChildItem -LiteralPath $Destination -Recurse -Filter bun.exe -File | Select-Object -First 1
if (-not $Bun) { throw 'Pinned Bun executable not found' }
if ((& $Bun.FullName --version).Trim() -ne $Version) { throw 'Pinned Bun version mismatch' }
if ($WriteGitHubEnv) {
    if (-not $env:GITHUB_ENV) { throw 'GITHUB_ENV unavailable' }
    "SENTRA_BUN=$($Bun.FullName)" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}
Write-Output "SENTRA_PINNED_BUN_OK=$($Bun.FullName)"
