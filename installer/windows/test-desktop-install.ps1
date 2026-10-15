$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "install-desktop.ps1"
$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$icon = Join-Path $repo "sentra_canvas\assets\SENTRA-DOT.ico"
if (-not (Test-Path -LiteralPath $icon)) { throw "Ícone do Dot ausente: $icon" }
if (Test-Path -LiteralPath (Join-Path $env:USERPROFILE ".sentra")) { $userDataExisted = $true } else { $userDataExisted = $false }

$base = Join-Path $env:LOCALAPPDATA "SENTRA-lumen-install-test"
$temp = Join-Path $base ([guid]::NewGuid().ToString("n"))
$install = Join-Path $temp "Desktop"
$shortcuts = Join-Path $temp "shortcuts"
$exe = Join-Path $temp "SENTRA-Canvas.exe"
New-Item -ItemType Directory -Force -Path $temp | Out-Null
New-Item -ItemType File -Force -Path $exe | Out-Null

function Invoke-DesktopInstall {
  param([string[]]$InstallerArgs)
  $stamp = [guid]::NewGuid().ToString("n")
  $outFile = Join-Path $temp ("out-" + $stamp + ".txt")
  $errFile = Join-Path $temp ("err-" + $stamp + ".txt")
  $quoted = foreach ($arg in $InstallerArgs) {
    if ($arg -match '[\s"]') { '"' + ($arg -replace '"', '\"') + '"' } else { $arg }
  }
  $argumentList = "-NoProfile -ExecutionPolicy Bypass -File `"$script`" " + ($quoted -join " ")
  $proc = Start-Process -FilePath powershell.exe -ArgumentList $argumentList -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $outFile -RedirectStandardError $errFile
  $text = ""
  if (Test-Path -LiteralPath $outFile) { $text += [IO.File]::ReadAllText($outFile) }
  if (Test-Path -LiteralPath $errFile) { $text += [IO.File]::ReadAllText($errFile) }
  return @{ code = $proc.ExitCode; text = $text }
}

try {
  $dry = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", $install, "-CanvasExe", $exe, "-IconPath", $icon,
    "-ShortcutDir", $shortcuts, "-ProductVersion", "0.1.0", "-DryRun"
  )
  if ($dry.code -ne 0) { throw "Dry-run falhou: $($dry.text)" }
  if ($dry.text -notmatch '"apply":true') { throw "Dry-run não planejou a instalação: $($dry.text)" }
  if (Test-Path -LiteralPath (Join-Path $install "installation.json")) { throw "Dry-run gravou installation.json" }

  $unsafe = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", (Join-Path $temp ".sentra\app"), "-CanvasExe", $exe, "-IconPath", $icon,
    "-ShortcutDir", $shortcuts, "-ProductVersion", "0.1.0"
  )
  if ($unsafe.code -eq 0) { throw "Instalação dentro de .sentra foi aceita." }
  if (Test-Path -LiteralPath (Join-Path $temp ".sentra\app\installation.json")) { throw "Instalação gravou dados dentro de .sentra" }

  $vmPath = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", (Join-Path $temp "virtualbox\app"), "-CanvasExe", $exe, "-IconPath", $icon,
    "-ProductVersion", "0.1.0", "-DryRun"
  )
  if ($vmPath.code -eq 0) { throw "Instalação sobre virtualbox foi aceita." }

  $omaShortcut = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", $install, "-CanvasExe", $exe, "-IconPath", $icon,
    "-ShortcutDir", (Join-Path $temp ".oma\links"), "-ProductVersion", "0.1.0", "-DryRun"
  )
  if ($omaShortcut.code -eq 0) { throw "Atalho dentro de .oma foi aceito." }

  $first = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", $install, "-CanvasExe", $exe, "-IconPath", $icon,
    "-ShortcutDir", $shortcuts, "-ProductVersion", "0.1.0"
  )
  if ($first.code -ne 0) { throw "Instalação falhou: $($first.text)" }
  $markerPath = Join-Path $install "installation.json"
  $marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($marker.kind -ne "installed_update") { throw "Marcador sem kind installed_update" }
  if ($marker.product_version -ne "0.1.0") { throw "Versão gravada incorreta" }
  if ($marker.code_reload -ne $false -or $marker.data_refresh -ne $false) { throw "Marcador misturou manutenção" }
  if ($marker.PSObject.Properties.Name -contains "frontend_stale") { throw "Marcador de versão carrega frontend_stale" }
  if (-not $marker.installation_id) { throw "installation_id ausente" }
  if (-not (Test-Path -LiteralPath (Join-Path $install "SENTRA-DOT.ico"))) { throw "Ícone do Dot não foi copiado" }
  if (Test-Path -LiteralPath (Join-Path $install "SENTRA-Desktop.cmd")) { throw "Launcher foi gravado mesmo com executável informado" }
  $lnk = Join-Path $shortcuts "SENTRA.lnk"
  if (-not (Test-Path -LiteralPath $lnk)) { throw "Atalho não foi criado" }
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($lnk)
  if ($shortcut.TargetPath -ne $exe) { throw "Atalho aponta para $($shortcut.TargetPath)" }
  if ($shortcut.Description -ne "SENTRA") { throw "Descrição do atalho incorreta" }
  $id = [string]$marker.installation_id

  $same = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", $install, "-CanvasExe", $exe, "-IconPath", $icon,
    "-ShortcutDir", $shortcuts, "-ProductVersion", "0.1.0"
  )
  if ($same.code -ne 0) { throw "Mesma versão falhou: $($same.text)" }
  if ($same.text -notmatch '"apply":false') { throw "Mesma versão aplicou bits: $($same.text)" }
  $again = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$again.installation_id -ne $id) { throw "installation_id mudou na mesma versão" }
  if ([string]$again.product_version -ne "0.1.0") { throw "Versão mudou sem upgrade" }

  $blocked = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", $install, "-CanvasExe", $exe, "-IconPath", $icon,
    "-ShortcutDir", $shortcuts, "-ProductVersion", "0.9.0"
  )
  if ($blocked.code -eq 0) { throw "Versão diferente sem -Upgrade foi aceita." }
  $still = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$still.product_version -ne "0.1.0") { throw "Versão mudou sem -Upgrade" }

  $up = Invoke-DesktopInstall -InstallerArgs @(
    "-InstallDir", $install, "-CanvasExe", $exe, "-IconPath", $icon,
    "-ShortcutDir", $shortcuts, "-ProductVersion", "0.2.0", "-Upgrade"
  )
  if ($up.code -ne 0) { throw "Upgrade falhou: $($up.text)" }
  if ($up.text -notmatch '"apply":true') { throw "Upgrade não aplicou: $($up.text)" }
  $upgraded = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$upgraded.product_version -ne "0.2.0") { throw "Upgrade não gravou 0.2.0" }
  if ([string]$upgraded.installation_id -ne $id) { throw "Upgrade trocou installation_id" }
  if ($upgraded.code_reload -ne $false -or $upgraded.data_refresh -ne $false) { throw "Upgrade misturou data refresh ou code reload" }

  if (-not $userDataExisted -and (Test-Path -LiteralPath (Join-Path $env:USERPROFILE ".sentra"))) {
    throw "O teste criou $env:USERPROFILE\.sentra"
  }
  Write-Output "SENTRA_DESKTOP_INSTALL_OK installation_id=$id"
} finally {
  if ($temp.StartsWith($base) -and (Test-Path -LiteralPath $temp)) {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
  }
  if ((Test-Path -LiteralPath $base) -and -not (Get-ChildItem -LiteralPath $base -Force -ErrorAction SilentlyContinue | Select-Object -First 1)) {
    Remove-Item -LiteralPath $base -Force -ErrorAction SilentlyContinue
  }
}
