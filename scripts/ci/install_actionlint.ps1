param([string]$Destination = "", [switch]$WriteGitHubEnv)
$ErrorActionPreference = "Stop"
$Version = '1.7.12'
$Release = "https://github.com/rhysd/actionlint/releases/download/v$Version"
$ChecksumName = "actionlint_$($Version)_checksums.txt"
$ExpectedChecksumSha256 = "433028cf0ba3c42163ea1a668dedce30fcdbe84fe912b1a5e288c006eab8a4f5"
$ArchiveName = "actionlint_$($Version)_windows_amd64.zip"
if (-not $Destination) {
    $Destination = Join-Path $(if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }) 'sentra-actionlint'
}
$Destination = [IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force $Destination | Out-Null
$ChecksumPath = Join-Path $Destination $ChecksumName
$Archive = Join-Path $Destination $ArchiveName
Invoke-WebRequest -Uri "$Release/$ChecksumName" -OutFile $ChecksumPath
$Actual = (Get-FileHash -LiteralPath $ChecksumPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $ExpectedChecksumSha256) { throw "actionlint checksum manifest integrity mismatch" }
$Rows = @(Get-Content $ChecksumPath | Where-Object { $_ -match "^[0-9a-fA-F]{64}\s+\*?actionlint_$($Version)_windows_amd64\.zip$" })
if ($Rows.Count -ne 1) { throw "Unique pinned actionlint Windows SHA-256 not found" }
$ArchiveHash = $Rows[0].Substring(0,64).ToLowerInvariant()
Invoke-WebRequest -Uri "$Release/$ArchiveName" -OutFile $Archive
if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ArchiveHash) {
    throw "actionlint Windows payload integrity mismatch"
}
Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
$Executable = Join-Path $Destination 'actionlint.exe'
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "actionlint executable missing" }
$version = & $Executable -version
if ($LASTEXITCODE -ne 0 -or -not (($version | Out-String) -match "1\.7\.12")) { throw "actionlint version mismatch" }
if ($WriteGitHubEnv) {
    if (-not $env:GITHUB_ENV) { throw "GITHUB_ENV missing" }
    "SENTRA_ACTIONLINT=$Executable" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}
Write-Host "SENTRA_ACTIONLINT_OK=$Executable"
