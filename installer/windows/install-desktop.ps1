param(
  [string]$InstallDir = "$env:LOCALAPPDATA\SENTRA\Desktop",
  [string]$SourceRoot = "",
  [string]$CanvasExe = "",
  [string]$IconPath = "",
  [string]$ProductVersion = "0.1.0",
  [string]$AppUserModelId = "SENTRA.Desktop",
  [string]$ShortcutDir = "",
  [switch]$Upgrade,
  [switch]$DryRun,
  [switch]$Launch
)

$ErrorActionPreference = "Stop"

function Assert-SafeInstallDir([string]$Path) {
  if ([IO.Path]::IsPathRooted($Path)) { $full = [IO.Path]::GetFullPath($Path) }
  else { $full = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path)) }
  $segments = $full.Split([char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar))
  foreach ($part in $segments) {
    if ($part -eq ".sentra" -or $part -eq ".oma") { throw "Recusando instalar dentro de dados do usuário: $full" }
  }
  if ($full -match '(?i)[\\/](dot-vms|virtualbox)[\\/]') { throw "Recusando instalar sobre VMs: $full" }
  return $full
}

function Assert-PlainPath([string]$Path, [string]$Label) {
  if ($Path -and $Path -match '["|&<>]') { throw "$Label contém um caractere não suportado." }
}

function Set-SentraShortcutAppId([string]$Path, [string]$AppId) {
  if (-not ("SentraShortcutProperty" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class SentraShortcutProperty {
  [StructLayout(LayoutKind.Sequential, Pack = 4)]
  public struct PropertyKey {
    public Guid fmtid;
    public uint pid;
    public PropertyKey(Guid format, uint property) { fmtid = format; pid = property; }
  }
  [StructLayout(LayoutKind.Explicit)]
  public struct PropVariant {
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pointer;
  }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IPropertyStore {
    uint GetCount(out uint count);
    uint GetAt(uint index, out PropertyKey key);
    uint GetValue(ref PropertyKey key, out PropVariant value);
    uint SetValue(ref PropertyKey key, ref PropVariant value);
    uint Commit();
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
  public static extern int SHGetPropertyStoreFromParsingName(string path, IntPtr bind, uint flags, ref Guid iid, out IPropertyStore store);
  public static void Apply(string path, string appId) {
    Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
    IPropertyStore store;
    int hr = SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, ref iid, out store);
    if (hr != 0) throw new InvalidOperationException("property store " + hr);
    PropertyKey key = new PropertyKey(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
    PropVariant value = new PropVariant();
    value.vt = 31;
    value.pointer = Marshal.StringToCoTaskMemUni(appId);
    try {
      uint set = store.SetValue(ref key, ref value);
      if (set != 0) throw new InvalidOperationException("set " + set);
      uint commit = store.Commit();
      if (commit != 0) throw new InvalidOperationException("commit " + commit);
    } finally {
      if (value.pointer != IntPtr.Zero) Marshal.FreeCoTaskMem(value.pointer);
      Marshal.ReleaseComObject(store);
    }
  }
}
"@
  }
  [SentraShortcutProperty]::Apply($Path, $AppId)
}

if ($AppUserModelId -notin @("SENTRA.Desktop", "SENTRA.Desktop.Electron")) { throw "AppUserModelID não suportado." }
if ($ProductVersion -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]{0,40}$') { throw "Versão de produto inválida." }
Assert-PlainPath $SourceRoot "SourceRoot"
Assert-PlainPath $CanvasExe "CanvasExe"
Assert-PlainPath $IconPath "IconPath"
$InstallDir = Assert-SafeInstallDir $InstallDir
if ($ShortcutDir) { $ShortcutDir = Assert-SafeInstallDir $ShortcutDir }

$existing = $null
$markerPath = Join-Path $InstallDir "installation.json"
if (Test-Path -LiteralPath $markerPath) {
  $existing = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
$installationId = if ($existing.installation_id) { [string]$existing.installation_id } else { [guid]::NewGuid().ToString() }
if ($existing -and [string]$existing.product_version -eq $ProductVersion) {
  @{ apply = $false; kind = "installed_update"; data_refresh = $false; code_reload = $false; installation_id = $installationId; product_version = $ProductVersion; reason = "A versão instalada já é $ProductVersion. Nenhum dado foi atualizado." } | ConvertTo-Json -Compress
  return
}
if ($existing -and -not $Upgrade) {
  throw "A versão do pacote é diferente da instalada. Use -Upgrade. Dados, VMs e conversas não foram alterados."
}
if (-not $IconPath) { throw "Informe -IconPath com o ícone do Dot." }
if (-not (Test-Path -LiteralPath $IconPath)) { throw "Ícone não encontrado: $IconPath" }
$resolvedIcon = [IO.Path]::GetFullPath($IconPath)
if (-not $CanvasExe -and -not $SourceRoot) { throw "Informe -CanvasExe ou -SourceRoot." }
if ($CanvasExe -and -not (Test-Path -LiteralPath $CanvasExe)) { throw "Executável não encontrado: $CanvasExe" }

$target = if ($CanvasExe) { [IO.Path]::GetFullPath($CanvasExe) } else { Join-Path $InstallDir "SENTRA-Desktop.cmd" }
$plan = [ordered]@{
  apply = $true; kind = "installed_update"; data_refresh = $false; code_reload = $false
  install_dir = $InstallDir; product_version = $ProductVersion; installation_id = $installationId
  app_user_model_id = $AppUserModelId; icon = $resolvedIcon; target = $target
}
$plan | ConvertTo-Json -Compress
if ($DryRun) { return }

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$iconDest = Join-Path $InstallDir "SENTRA-DOT.ico"
Copy-Item -LiteralPath $resolvedIcon -Destination $iconDest -Force
if (-not $CanvasExe) {
  $root = [IO.Path]::GetFullPath($SourceRoot)
  $launcher = "@echo off`r`ncd /d `"$root`"`r`npy -3 -m sentra_canvas --root `"$root`" --ui native --surface shell-home`r`n"
  [IO.File]::WriteAllText($target, $launcher, (New-Object System.Text.UTF8Encoding $false))
}
$marker = @{
  schema = 1; kind = "installed_update"; installation_id = $installationId; product_version = $ProductVersion
  code_reload = $false; data_refresh = $false; app_user_model_id = $AppUserModelId
} | ConvertTo-Json
[IO.File]::WriteAllText($markerPath, $marker, (New-Object System.Text.UTF8Encoding $false))

$dirs = @()
if ($ShortcutDir) { $dirs = @([IO.Path]::GetFullPath($ShortcutDir)) }
else {
  $dirs = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "SENTRA")
  )
}
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in $dirs) {
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $lnk = Join-Path $dir "SENTRA.lnk"
  $shortcut = $shell.CreateShortcut($lnk)
  $shortcut.TargetPath = $target
  $shortcut.WorkingDirectory = if ($SourceRoot) { [IO.Path]::GetFullPath($SourceRoot) } else { $InstallDir }
  $shortcut.IconLocation = "$iconDest,0"
  $shortcut.Description = "SENTRA"
  $shortcut.WindowStyle = 1
  $shortcut.Save()
  Set-SentraShortcutAppId $lnk $AppUserModelId
}
if ($Launch -and -not $DryRun) { Start-Process -FilePath $target }
