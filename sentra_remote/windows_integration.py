"""Per-user launch shortcuts with target ownership checks and literal paths."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


SCRIPT=r'''
param([string]$PayloadPath)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$data=Get-Content -LiteralPath $PayloadPath -Raw | ConvertFrom-Json
$shell=New-Object -ComObject WScript.Shell
$programs=[Environment]::GetFolderPath('Programs')
$desktop=[Environment]::GetFolderPath('DesktopDirectory')
if($data.programs_dir) {$programs=$data.programs_dir}
if($data.desktop_dir) {$desktop=$data.desktop_dir}
$folder=Join-Path $programs 'SENTRA'
$items=@(
 @{path=(Join-Path $folder 'SENTRA Desktop.lnk'); exe='sentra-human.exe'},
 @{path=(Join-Path $folder 'SENTRA Canvas.lnk'); exe='sentra-canvas.exe'}
)
if(-not $data.desktop_executable) {
 $items+=@{path=(Join-Path $desktop 'SENTRA.lnk'); exe='sentra-canvas.exe'}
} elseif($data.action -eq 'register') {
 $legacy=Join-Path $desktop 'SENTRA.lnk'
 if(Test-Path -LiteralPath $legacy -PathType Leaf) {
  $link=$shell.CreateShortcut($legacy)
  $owned=[IO.Path]::GetFullPath((Join-Path $data.install_dir 'sentra-canvas.exe'))
  if([string]::Equals($link.TargetPath,$owned,[StringComparison]::OrdinalIgnoreCase)) {
   Remove-Item -LiteralPath $legacy
  }
 }
}
$changed=@()
foreach($item in $items) {
 $target=[IO.Path]::GetFullPath((Join-Path $data.install_dir $item.exe))
 if($data.action -eq 'register') {
  if(-not (Test-Path -LiteralPath $target -PathType Leaf)) {throw 'Shortcut target is missing'}
  $parent=[IO.Path]::GetDirectoryName($item.path)
  [IO.Directory]::CreateDirectory($parent) | Out-Null
  $link=$shell.CreateShortcut($item.path)
  $link.TargetPath=$target
  $link.WorkingDirectory=$data.install_dir
  $link.IconLocation=$target+',0'
  $link.Description='SENTRA'
  $link.Save()
  $changed+=$item.path
 } elseif($data.action -eq 'unregister') {
  if(Test-Path -LiteralPath $item.path -PathType Leaf) {
   $link=$shell.CreateShortcut($item.path)
   if([string]::Equals($link.TargetPath,$target,[StringComparison]::OrdinalIgnoreCase)) {
    $resolved=[IO.Path]::GetFullPath($item.path)
    Remove-Item -LiteralPath $resolved -Force
    $changed+=$resolved
   }
  }
 } else {throw 'Unsupported shortcut action'}
}
@{paths=@($changed);action=$data.action;desktop_dir=$desktop} | ConvertTo-Json -Compress
'''


def shortcuts(install_dir:Path,*,remove=False,programs_dir:Path|None=None,desktop_dir:Path|None=None,desktop_executable=False):
    if os.name!="nt":return {"paths":[],"supported":False}
    shell=shutil.which("powershell") or shutil.which("pwsh")
    if shell is None:raise RuntimeError("Windows PowerShell is unavailable for shortcuts")
    install_dir=Path(install_dir).resolve()
    with tempfile.TemporaryDirectory(prefix="sentra-shortcuts-") as temporary:
        root=Path(temporary)
        script=root/"shortcuts.ps1";payload=root/"payload.json"
        script.write_text(SCRIPT,encoding="utf-8-sig")
        payload.write_text(json.dumps({"install_dir":str(install_dir),
            "action":"unregister" if remove else "register",
            "desktop_executable": desktop_executable,
            "programs_dir":str(Path(programs_dir).resolve()) if programs_dir else None,
            "desktop_dir":str(Path(desktop_dir).resolve()) if desktop_dir else None}),encoding="utf-8-sig")
        result=subprocess.run([shell,"-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
            "-File",str(script),str(payload)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=30,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode:
            raise RuntimeError("Windows shortcut registration failed")
        value = json.loads(result.stdout.decode("utf-8-sig"))
        if desktop_executable:
            entry = install_desktop_executable(install_dir, Path(value["desktop_dir"]), remove=remove)
            if entry:
                value["paths"].append(str(entry))
        return value


def install_desktop_executable(install_dir: Path, desktop_dir: Path, *, remove=False):
    """Publish/remove only our registered launcher; never replace an unrelated EXE."""
    from .installer_preflight import file_hash
    install_dir, desktop_dir = Path(install_dir).resolve(), Path(desktop_dir).resolve()
    target = desktop_dir / "SENTRA.exe"
    receipt = install_dir / "desktop-launcher.json"
    previous = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
    old_digest = file_hash(target) if target.is_file() and not target.is_symlink() else None
    owned = (previous.get("target") == str(target) and old_digest is not None
             and old_digest in (previous.get("sha256"), previous.get("previous_sha256")))
    if remove:
        if owned:
            target.unlink()
            receipt.unlink(missing_ok=True)
            return target
        return None
    source = install_dir / "sentra-launcher.exe"
    if not source.is_file():
        raise FileNotFoundError("SENTRA desktop executable is missing from the installation")
    if target.exists() and not owned:
        raise FileExistsError("SENTRA.exe already exists on the desktop and is not owned by this installation")
    desktop_dir.mkdir(parents=True, exist_ok=True)
    fd, staged_name = tempfile.mkstemp(prefix=".sentra-launcher-", suffix=".tmp", dir=desktop_dir)
    os.close(fd)
    staged = Path(staged_name)
    try:
        shutil.copy2(source, staged)
        digest = file_hash(staged)
        # Persist identity before publishing, so a crash immediately after
        # replacement remains repairable with these same verified bytes.
        pending = receipt.with_suffix(".tmp")
        pending.write_text(json.dumps({"target": str(target), "sha256": digest,
                                      "previous_sha256": old_digest if owned else None}), encoding="utf-8")
        pending.replace(receipt)
        staged.replace(target)
    finally:
        staged.unlink(missing_ok=True)
    return target
