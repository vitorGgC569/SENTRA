param(
  [switch]$Next,
  [string]$SetupPath = "",
  [string]$InstallDir = "",
  [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
# One installation engine. Never copy a partial Python checkout onto a client.
# The Setup executable carries this payload. This script only launches that package.
# product_version = "1.0.1"
# LICENSE
# docs/frentes-18/comercial/README.md
# docs/frentes-18/comercial/LICENCA.md
# docs/frentes-18/comercial/USUARIO.md
# docs/frentes-18/comercial/SUPORTE.md
# docs/frentes-18/comercial/PACOTE_LATCH.md
# sentra_quality/local_use_policy.py
# sentra_quality/production_audit.py
# sentra_quality/distribution_diagnosis.py
# sentra_quality/decision_receipt_audit.py
if (-not $SetupPath) { $SetupPath = Join-Path $PSScriptRoot "SENTRA-Setup.exe" }
$setup = [IO.Path]::GetFullPath($SetupPath)
if (-not (Test-Path -LiteralPath $setup -PathType Leaf)) {
  throw "Pacote completo ausente. Coloque SENTRA-Setup.exe junto deste script ou informe -SetupPath."
}
if ([IO.Path]::GetExtension($setup) -ne ".exe") { throw "Selecione o executavel SENTRA-Setup.exe." }
$installArgs = @("--silent")
if ($InstallDir) { $installArgs += @("--install-dir", [IO.Path]::GetFullPath($InstallDir)) }
if ($NoLaunch) { $installArgs += "--no-launch" }
# Direct invocation passes literal arguments (including folders with spaces).
& $setup @installArgs
if ($LASTEXITCODE -ne 0) { throw "A instalacao precisa de atencao. Codigo: $LASTEXITCODE. Abra o Setup para reparar." }
Write-Output "SENTRA_INSTALL_COMPLETE"
