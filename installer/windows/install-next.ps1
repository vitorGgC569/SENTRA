param(
  [switch]$Next,
  [string]$SetupPath = "",
  [string]$InstallDir = "",
  [switch]$NoLaunch,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
# This wrapper invokes the complete native Inno Setup. It does not copy a
# checkout or establish the package's version, signature, or contents itself.
if (-not $SetupPath) { $SetupPath = Join-Path $PSScriptRoot "SENTRA-Setup.exe" }
$setup = [IO.Path]::GetFullPath($SetupPath)
if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) {
  throw "Pacote completo ausente. Coloque SENTRA-Setup.exe junto deste script ou informe -SetupPath."
}
if ([IO.Path]::GetExtension($setup) -ne ".exe") { throw "Selecione o executavel SENTRA-Setup.exe." }

$info = [Diagnostics.FileVersionInfo]::GetVersionInfo($setup)
$original = if ($info.OriginalFilename) { $info.OriginalFilename.Trim().TrimEnd([char]0) } else { "" }
$installArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-')
if ($InstallDir) { $installArgs += '/DIR="' + [IO.Path]::GetFullPath($InstallDir) + '"' }
if ($NoLaunch) { $installArgs += '/NO-LAUNCH' }

if ($DryRun) {
  [pscustomobject]@{ executable = $setup; arguments = $installArgs;
    original_filename = $original; file_version = $info.FileVersion;
    package_verified = $false } | ConvertTo-Json -Compress
  return
}

if ($original -ne 'SENTRA-Inno-Setup.exe') {
  throw "O executavel selecionado nao identifica o Setup Inno do SENTRA. Confira o pacote baixado."
}
$process = Start-Process -FilePath $setup -ArgumentList $installArgs -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw "A instalacao precisa de atencao. Codigo: $($process.ExitCode). Abra o Setup para reparar." }
Write-Output "SENTRA_INSTALL_COMPLETE"
