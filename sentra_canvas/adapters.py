"""Explicit allowlisted external terminal adapters for SENTRA Canvas.

Never execute a user-supplied executable path or invoke a shell for launch.
Presence means installed, not authenticated or ready for model inference.
"""
from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path

BUILTIN = {
    "powershell": "Windows PowerShell",
    "cmd": "Prompt de comando · CMD",
    "pwsh": "PowerShell 7",
}
AGENT_TOOLS = {"sentra-cli":"SENTRA CLI","codex":"OpenAI Codex CLI"}

def _which(name: str) -> Path | None:
    value=shutil.which(name)
    return Path(value).resolve() if value else None

def resolve(project_root: Path) -> dict:
    root=Path(project_root).resolve()
    commands={}
    for shell,program in (("cmd","cmd.exe"),("powershell","powershell.exe"),("pwsh","pwsh.exe")):
        found=_which(program)
        if found: commands[shell]=[str(found)]
    choices=[
        root/"dist"/"sentra-cli.exe",
        root/"sentra-cli.exe",
        Path(sys.executable).parent/"sentra-cli.exe",
    ]
    sentra=next((p.resolve() for p in choices if p.is_file()),None)
    if not sentra:
        candidate=_which("sentra-cli.exe") or _which("sentra-cli")
        if candidate and candidate.suffix.lower()==".exe":
            sentra=candidate
    if sentra:commands["sentra-cli"]=[str(sentra)]
    codex=_which("codex.exe")
    if not codex:
        candidate=_which("codex")
        if candidate and candidate.suffix.lower()==".exe":codex=candidate
    if not codex and os.name=="nt":
        candidate=Path.home()/"AppData"/"Local"/"Programs"/"OpenAI"/"Codex"/"bin"/"codex.exe"
        if candidate.is_file():codex=candidate.resolve()
    if codex:commands["codex"]=[str(codex)]
    antigravity=(Path.home()/"AppData"/"Local"/"Programs"/"antigravity"/"Antigravity.exe")
    if not antigravity.is_file():
        antigravity=Path(os.environ.get("LOCALAPPDATA",""))/"Programs"/"antigravity"/"Antigravity.exe"
    if antigravity.is_file():commands["antigravity-app"]=[str(antigravity.resolve())]
    return commands

def catalog(root:Path) -> list[dict]:
    available=resolve(root)
    rows=[]
    for key,label in [*BUILTIN.items(),*AGENT_TOOLS.items(),
                      ("antigravity-app","Antigravity · aplicativo externo")]:
        ready=key in available
        rows.append({
            "id":key,"name":label,"installed":ready,
            "mode":"external-app" if key=="antigravity-app" else "conpty",
            "session_compatible":key in AGENT_TOOLS and ready,
            "reason":("Disponível (autenticação não verificada)" if key in AGENT_TOOLS and ready
                      else "Instalado como aplicativo gráfico, sem CLI de agente verificado"
                      if key=="antigravity-app" and ready
                      else "Não encontrado no computador" if not ready else "Disponível")
        })
    return rows

def cli_argv(root:Path, workspace:Path, shell:str)->list[str]:
    found=resolve(root)
    if shell not in found or shell=="antigravity-app":
        raise ValueError(f"unsupported shell or unavailable CLI: {shell}")
    command=found[shell]
    if shell=="cmd":return [*command,"/Q","/K"]
    if shell in ("powershell","pwsh"):return [*command,"-NoLogo","-NoProfile"]
    if shell=="sentra-cli":
        return [*command,"--workspace",str(workspace),"--no-auto-start"]
    if shell=="codex":
        # Let Codex decide interactive model/auth; its own sandbox prompts apply.
        return [*command,"-C",str(workspace)]
    raise ValueError("unsupported terminal adapter")
