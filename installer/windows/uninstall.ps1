param(
  [string]$InstallDir = "$env:LOCALAPPDATA\SENTRA\Commander",
  [switch]$KeepConfig,
  [switch]$NoStartupCleanup,
  [string]$TaskName = "SENTRA Commander",
  [string]$StartupFileName = "SENTRA-Commander.cmd"
)

$ErrorActionPreference = "Stop"
if ([IO.Path]::IsPathRooted($InstallDir)) {
  $ResolvedInstallDir = [IO.Path]::GetFullPath($InstallDir)
} else {
  $ResolvedInstallDir = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $InstallDir))
}

# Stop only SENTRA Commander processes executing from this installation.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {
    $_.ExecutablePath -and
    $_.ExecutablePath.StartsWith($ResolvedInstallDir, [StringComparison]::OrdinalIgnoreCase)
  } |
  ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
  }

if (-not $NoStartupCleanup) {
  try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop } catch {}
  try {
    $Startup = [Environment]::GetFolderPath("Startup")
    Remove-Item -Force (Join-Path $Startup $StartupFileName) -ErrorAction Stop
  } catch {}
}

if (Test-Path $ResolvedInstallDir) {
  $removed = $false
  for ($attempt = 1; $attempt -le 8; $attempt++) {
    try {
      Remove-Item -Recurse -Force $ResolvedInstallDir -ErrorAction Stop
      $removed = -not (Test-Path $ResolvedInstallDir)
      if ($removed) { break }
    } catch {
      if ($attempt -eq 8) { throw }
    }
    Start-Sleep -Milliseconds 500
  }
  if (-not $removed) { throw "Failed to remove install directory: $ResolvedInstallDir" }
}

if (-not $KeepConfig) {
  $ConfigDir = Join-Path $env:USERPROFILE ".sentra"
  if (Test-Path $ConfigDir) {
    Remove-Item -Recurse -Force $ConfigDir -ErrorAction Stop
  }
}

Write-Host "SENTRA Commander uninstalled"
