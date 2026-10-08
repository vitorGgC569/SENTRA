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
 @{path=(Join-Path $folder 'SENTRA Canvas.lnk'); exe='sentra-canvas.exe'},
 @{path=(Join-Path $desktop 'SENTRA.lnk'); exe='sentra-human.exe'}
)
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
@{paths=@($changed);action=$data.action} | ConvertTo-Json -Compress
'''


def shortcuts(install_dir:Path,*,remove=False,programs_dir:Path|None=None,desktop_dir:Path|None=None):
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
            "programs_dir":str(Path(programs_dir).resolve()) if programs_dir else None,
            "desktop_dir":str(Path(desktop_dir).resolve()) if desktop_dir else None}),encoding="utf-8-sig")
        result=subprocess.run([shell,"-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
            "-File",str(script),str(payload)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            timeout=30,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode:
            raise RuntimeError("Windows shortcut registration failed")
        return json.loads(result.stdout.decode("utf-8-sig"))
