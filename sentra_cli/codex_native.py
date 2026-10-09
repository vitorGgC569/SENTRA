"""Model response transport through the user's authenticated Codex CLI.

No OAuth tokens are read/exported. The native harness is used for text only;
SENTRA directives execute afterwards through its protected tool journal.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from sentra_canvas.owned_process import TaskProcess
from sentra_core.telemetry import EventJournal

PREFIX="sentra/codex/"
MAX_OUTPUT=2*1024*1024


class NativeModelError(RuntimeError):
    pass


def find_cli():
    candidate=shutil.which("codex.exe")
    if candidate:return Path(candidate).resolve()
    candidate=Path(os.environ.get("LOCALAPPDATA",""))/"Programs/OpenAI/Codex/bin/codex.exe"
    return candidate.resolve() if candidate.is_file() else None


def authenticated():
    executable=find_cli()
    if executable is None:return False
    try:
        result=subprocess.run([str(executable),"login","status"],stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,timeout=5,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def parse_response(data,returncode):
    if len(data)>MAX_OUTPUT:raise NativeModelError("native model response exceeded its output limit")
    events=[]
    for line in data.decode("utf-8",errors="strict").splitlines():
        if not line.strip():continue
        event=json.loads(line)
        if not isinstance(event,dict):raise NativeModelError("invalid native model event")
        events.append(event)
    messages=[];completed=False;native_thread=None;usage={}
    for event in events:
        kind=event.get("type")
        if completed:raise NativeModelError("native model emitted data after its terminal event")
        if kind=="thread.started":native_thread=event.get("thread_id")
        if kind in {"error","turn.failed"}:raise NativeModelError("native model turn failed")
        item=event.get("item",{})
        if kind in {"item.started","item.updated","item.completed"} and isinstance(item,dict):
            if item.get("type") in {"command_execution","file_change","mcp_tool_call","web_search"}:
                raise NativeModelError("native harness used tools; no SENTRA directives will be executed")
            if kind=="item.completed" and item.get("type")=="agent_message":
                value=item.get("text")
                if not isinstance(value,str):raise NativeModelError("invalid native model message")
                messages.append(value)
        if kind=="turn.completed":
            completed=True
            raw=event.get("usage",{})
            if isinstance(raw,dict):usage={k:v for k,v in raw.items() if k in {"input_tokens","cached_input_tokens","output_tokens"} and type(v) is int and v>=0}
    if returncode!=0 or not completed or not messages or not messages[-1].strip():
        raise NativeModelError("native model response was incomplete")
    return messages[-1],native_thread,usage


def generate(config,messages,model,delivery,*,usage_callback=None):
    suffix=model.removeprefix(PREFIX)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}",suffix):
        raise NativeModelError("invalid native model selection")
    executable=find_cli()
    if executable is None or not authenticated():
        raise NativeModelError("authenticated Codex CLI is unavailable")
    prompt=("You are the text-only model transport for SENTRA. Do not use native Codex tools, "
            "shell commands, MCP, web search or file editing. Return only the assistant response "
            "following the supplied SENTRA system instructions and its [[DIRECTIVE|args]] syntax. "
            "SENTRA will execute those directives using its own durable journal. "
            "The JSON below is the complete ordered conversation context.\n"+
            json.dumps(messages,ensure_ascii=False))
    effort=config.reasoning_effort
    if effort not in {"low","medium","high","xhigh"}:
        raise NativeModelError("unsupported Codex reasoning effort")
    command=[str(executable),"exec","--ignore-user-config","--ephemeral","--json",
             "--sandbox","read-only","--skip-git-repo-check","-C",str(config.workspace),
             "-c",'approval_policy="never"',"-c",f'model_reasoning_effort="{effort}"']
    if suffix!="current":command.extend(["--model",suffix])
    command.append("-")
    ident="sentra-codex-"+uuid.uuid4().hex
    process=None
    delivery("codex-cli",ident,"submitted")
    try:
        process=TaskProcess(command,cwd=str(config.workspace),stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        deadline=time.monotonic()+config.timeout_s
        pending=prompt.encode("utf-8")
        while True:
            try:
                value=pending;pending=None
                output,_=process.communicate(input=value,timeout=min(.25,max(.01,deadline-time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic()>=deadline:
                    raise NativeModelError("native model deadline exceeded")
        text,native_thread,usage=parse_response(output,process.returncode)
        if usage_callback is not None:usage_callback("codex-cli",ident,model,usage)
        delivery("codex-cli",ident,"completed")
        try:
            EventJournal(config.state_root).append("cli","model.codex.completed","ok",
                {"turn_id":ident,"native_thread_id":native_thread,"model":model,"effort":effort,"usage":usage},correlation_id=ident)
        except Exception:pass # Protected conversation remains authoritative.
        return text
    except BaseException:
        if process is None:
            delivery("codex-cli",ident,"rejected")
        else:
            process.terminate_tree()
            try:process.communicate(timeout=5)
            except subprocess.TimeoutExpired:pass
            delivery("codex-cli",ident,"uncertain")
        raise
