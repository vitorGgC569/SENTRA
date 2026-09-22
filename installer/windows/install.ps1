param(
  [string]$InstallDir = "$env:LOCALAPPDATA\SENTRA\Commander",
  [string]$RelayUrl = "",
  [string]$PairingCode = "",
  [string]$DeviceName = $env:COMPUTERNAME,
  [string[]]$AllowedRoot = @(),
  [ValidateSet("sandbox","workspace","unrestricted")]
  [string]$ProcessMode = "workspace",
  [string]$UpdateManifestUrl = "",
  [switch]$AutoUpdate,
  [switch]$AllowUnsignedUpdates,
  [switch]$Upgrade,
  [switch]$NoStartup,
  [switch]$NoLaunch,
  [string]$TaskName = "SENTRA Commander",
  [string]$StartupFileName = "SENTRA-Commander.cmd",
  [int]$WaitPid = 0
)

$ErrorActionPreference = "Stop"
if ($WaitPid -gt 0) { Wait-Process -Id $WaitPid -ErrorAction SilentlyContinue }
if ([IO.Path]::IsPathRooted($InstallDir)) {
  $InstallDir = [IO.Path]::GetFullPath($InstallDir)
} else {
  $InstallDir = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $InstallDir))
}
$PackageRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$ConfigDir = Join-Path $env:USERPROFILE ".sentra"
$ConfigPath = Join-Path $ConfigDir "agent.json"
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

$AgentSource = Join-Path $PackageRoot "sentra-agent.exe"
$TraySource = Join-Path $PackageRoot "sentra-tray.exe"
$DiagSource = Join-Path $PackageRoot "sentra-diagnostics.exe"
foreach ($source in @($AgentSource,$TraySource,$DiagSource)) {
  if (-not (Test-Path $source)) { throw "Missing release binary: $source" }
}
Copy-Item -Force $AgentSource (Join-Path $InstallDir "sentra-agent.exe")
Copy-Item -Force $TraySource (Join-Path $InstallDir "sentra-tray.exe")
Copy-Item -Force $DiagSource (Join-Path $InstallDir "sentra-diagnostics.exe")

if ($PairingCode) {
  if (-not $RelayUrl) { throw "RelayUrl is required when PairingCode is supplied" }
  $pairArgs = @("--config",$ConfigPath,"pair","--relay",$RelayUrl,"--code",$PairingCode,"--name",$DeviceName)
  foreach ($root in $AllowedRoot) { $pairArgs += @("--allowed-root",$root) }
  $pairArgs += @("--process-mode",$ProcessMode)
  & (Join-Path $InstallDir "sentra-agent.exe") @pairArgs
  if ($LASTEXITCODE -ne 0) { throw "Device pairing failed" }
}

$TrayExe = Join-Path $InstallDir "sentra-tray.exe"
$LaunchArgs = @("--config", $ConfigPath)
$ScheduledArgs = @("--config", ([char]34 + $ConfigPath + [char]34))
if ($UpdateManifestUrl) {
  $LaunchArgs += @("--manifest-url", $UpdateManifestUrl)
  $ScheduledArgs += @("--manifest-url", ([char]34 + $UpdateManifestUrl + [char]34))
}
if ($AutoUpdate) { $LaunchArgs += "--auto-update"; $ScheduledArgs += "--auto-update" }
if ($AllowUnsignedUpdates) { $LaunchArgs += "--allow-unsigned-updates"; $ScheduledArgs += "--allow-unsigned-updates" }
$TrayArguments = $ScheduledArgs -join " "
$TaskCreated = $false
$StartupMode = "disabled"
if (-not $NoStartup) {
  try {
    $Action = New-ScheduledTaskAction -Execute $TrayExe -Argument $TrayArguments
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "SENTRA Commander tray and remote agent" -Force | Out-Null
    $TaskCreated = $true
    $StartupMode = "Scheduled Task"
  } catch {
    $Startup = [Environment]::GetFolderPath("Startup")
    $Cmd = Join-Path $Startup $StartupFileName
    $cmdLine = "@echo off" + [Environment]::NewLine + "start " + [char]34 + [char]34 + " " + [char]34 + $TrayExe + [char]34 + " " + $TrayArguments
    $cmdLine | Set-Content -Encoding ASCII $Cmd
    $StartupMode = "Startup folder fallback"
  }
  if (-not $NoLaunch) { Start-Process $TrayExe -ArgumentList $LaunchArgs }
}
Write-Host "SENTRA Commander installed at $InstallDir"
Write-Host "Config: $ConfigPath"
Write-Host ("Startup: " + $StartupMode)
