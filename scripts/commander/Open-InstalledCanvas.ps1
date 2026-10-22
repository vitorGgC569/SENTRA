# Open once through the interactive Windows task service, outside the developer
# app's nested kill-on-close jobs. There are no triggers or recurring tasks.
param([Parameter(Mandatory=$true)][string]$InstallDirectory)
$ErrorActionPreference = 'Stop'
$sentraResolvedInstall = (Resolve-Path -LiteralPath $InstallDirectory).Path
$sentraCanvasBinary = Join-Path $sentraResolvedInstall 'sentra-canvas.exe'
if (-not (Test-Path -LiteralPath $sentraCanvasBinary -PathType Leaf)) { throw 'SENTRA Canvas is not installed here.' }
$sentraService = New-Object -ComObject Schedule.Service
$sentraService.Connect()
$sentraFolder = $sentraService.GetFolder('\')
$sentraDefinition = $sentraService.NewTask(0)
$sentraDefinition.RegistrationInfo.Description = 'One-time interactive SENTRA launch; registration removed immediately.'
$sentraDefinition.Principal.UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$sentraDefinition.Principal.LogonType = 3 # current interactive token, no saved password
$sentraDefinition.Principal.RunLevel = 0 # ordinary user, no elevation
$sentraDefinition.Settings.Enabled = $true
$sentraDefinition.Settings.AllowDemandStart = $true
$sentraDefinition.Settings.DisallowStartIfOnBatteries = $false
$sentraDefinition.Settings.StopIfGoingOnBatteries = $false
$sentraDefinition.Settings.ExecutionTimeLimit = 'PT0S'
$sentraAction = $sentraDefinition.Actions.Create(0)
$sentraAction.Path = $sentraCanvasBinary
$sentraAction.Arguments = '--ui electron --windows-interactive-launch'
$sentraAction.WorkingDirectory = $sentraResolvedInstall
$sentraLaunchName = 'SENTRA-Open-Once-' + [guid]::NewGuid().ToString('N')
$sentraRegistered = $null
try {
    $sentraRegistered = $sentraFolder.RegisterTaskDefinition($sentraLaunchName, $sentraDefinition, 6, $null, $null, 3)
    $sentraRegistered.Run($null) | Out-Null
    Write-Output 'Installed SENTRA launch dispatched outside the development app.'
} finally {
    if ($sentraRegistered) { $sentraFolder.DeleteTask($sentraLaunchName, 0) }
}
