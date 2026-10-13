"""Non-interactive CLI runners and verifiable inference receipt builders.

Executes SENTRA CLI, OpenCode and Codex in non-interactive modes:
- sentra-cli: -p / --prompt-stdin
- opencode: opencode run --standalone --model <m> --auto --format json
- codex: codex exec -C <workspace> --json

Distinguishes genuine model inference from terminal/PTY input echo via a
cryptographic / transformed nonce challenge.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import uuid
from typing import Any, Callable

from .adapters import resolve as resolve_adapters


def generate_nonce(prefix: str = "NONCE") -> str:
    """Generate a high-entropy hex nonce."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def compute_nonce_transformations(nonce: str) -> dict[str, str]:
    """Compute deterministic transformations for the nonce challenge.
    
    A dumb terminal/PTY echo repeats the input string.
    Only an agent performing inference can compute and output the reverse
    or SHA-256 hash requested by the verification instruction.
    """
    clean_nonce = str(nonce).strip()
    return {
        "raw": clean_nonce,
        "reverse": clean_nonce[::-1],
        "sha256": hashlib.sha256(clean_nonce.encode("utf-8")).hexdigest(),
    }


def build_dispatch_prompt(instruction: str, nonce: str | None = None) -> tuple[str, dict[str, str]]:
    """Compose instruction with strict nonce verification challenge."""
    if not nonce:
        nonce = generate_nonce()
    transforms = compute_nonce_transformations(nonce)
    challenge = (
        f"\n\n[SENTRA_NONCE_CHALLENGE]\n"
        f"NONCE_TOKEN: {transforms['raw']}\n"
        f"INSTRUÇÃO DE VERIFICAÇÃO OBRIGATÓRIA: Para comprovar inferência autêntica e distinguir "
        f"de mero eco de terminal, inverta mentalmente os caracteres de NONCE_TOKEN. "
        f"Não use ferramentas, arquivos nem terminal para este desafio. O hash é opcional.\n"
        f"Inclua explicitamente na resposta final as seguintes marcações:\n"
        f"REVERSE_NONCE=<o inverso que você calculou>\n"
        f"SHA256_NONCE=<o hash que você calculou, se puder calculá-lo>\n"
        f"[/SENTRA_NONCE_CHALLENGE]\n"
    )
    full_prompt = str(instruction).strip() + challenge
    return full_prompt, transforms


def build_cli_command(
    project_dir: Path,
    workspace: Path,
    tool: str,
    prompt: str,
    model: str | None = None,
    effort: str | None = None,
    session_id: str | None = None,
) -> list[str]:
    """Build the non-interactive argv for the requested tool."""
    adapters = resolve_adapters(project_dir)
    tool_key = tool.lower().replace("_", "-")
    if tool_key not in {"sentra-cli", "opencode", "codex"}:
        raise ValueError(f"unsupported or unverified tool: {tool}")
    source_root = Path(__file__).resolve().parents[1]
    source_cli = source_root / 'sentra_cli' / '__main__.py'
    if tool_key not in adapters and not (tool_key == 'sentra-cli' and source_cli.is_file()):
        raise FileNotFoundError(f"executable for tool '{tool_key}' not found on host")
    
    executable = adapters.get(tool_key, [sys.executable])[0]
    ws_path = str(workspace.resolve())

    if tool_key == "sentra-cli":
        if model not in {None, 'sentra/chatgpt-web/gpt-6'} or effort not in {None, 'high'}:
            raise ValueError('Dot SENTRA CLI requires GPT-6 Web high')
        if source_cli.is_file() and not getattr(sys, 'frozen', False):
            console = Path(sys.executable)
            if console.name.lower().startswith('pythonw'):
                console = console.with_name(console.name.replace('pythonw', 'python'))
            bootstrap = 'import sys;sys.path.insert(0,' + repr(str(source_root)) + ');from sentra_cli.__main__ import main;sys.exit(main())'
            argv = [str(console), '-u', '-c', bootstrap]
        else:
            argv = [executable]
        argv.extend(["-p", prompt, "-w", ws_path, "--no-auto-start", '-m', 'sentra/chatgpt-web/gpt-6', '--effort', 'high'])
        if session_id:
            argv.extend(['--session-id', session_id, '--state-dir', str(workspace / '.sentra')])
        return argv

    if tool_key == "codex":
        argv = [executable, "exec", "-C", ws_path, "--json"]
        if model:
            argv.extend(["-m", model])
        argv.append(prompt)
        return argv

    if tool_key == "opencode":
        if model not in {None, 'opencode/muse-spark-1.3-contributor-free#high'} or effort not in {None, 'high'}:
            raise ValueError('Dot OpenCode requires Muse Spark 1.3 free high')
        chosen_model = model or "opencode/muse-spark-1.3-contributor-free#high"
        if Path(executable).suffix.lower() == ".cmd":
            cmd_exe = adapters.get("cmd", ["cmd.exe"])[0]
            return [
                cmd_exe, "/D", "/C", executable, "run",
                "--standalone", "--model", chosen_model, "--format", "json",
                prompt,
            ]
        return [
            executable, "run",
            "--standalone", "--model", chosen_model, "--format", "json",
            prompt,
        ]

    raise ValueError(f"unrecognized tool: {tool_key}")


def verify_receipt(
    tool: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    nonce_info: dict[str, str],
    oid: str,
    wid: str,
    request_key: str,
    effective_model: str | None = None,
    assistant_text: str | None = None,
) -> dict[str, Any]:
    """Evaluate non-interactive CLI execution and build verifiable receipt."""
    stdout_text = stdout or ""
    stdout_bytes = stdout_text.encode("utf-8")
    stdout_sha256 = hashlib.sha256(stdout_bytes).hexdigest()

    raw_nonce = nonce_info.get("raw", "")
    expected_reverse = nonce_info.get("reverse", "")
    expected_sha256 = nonce_info.get("sha256", "")

    # Structured CLIs may include user inputs in logs. Only assistant text
    # contributes to the challenge, never arbitrary serialized stdout.
    answer_text = stdout_text if assistant_text is None else assistant_text
    if tool == 'opencode' and any(line.lstrip().startswith('{') for line in stdout_text.splitlines()):
        answers = []
        for line in stdout_text.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(event, dict) and event.get('type') == 'text':
                part = event.get('part', {})
                if isinstance(part, dict) and part.get('type') == 'text' and isinstance(part.get('text'), str):
                    answers.append(part['text'])
        answer_text = '\n'.join(answers)
    if tool == 'codex' and any(line.lstrip().startswith('{') for line in stdout_text.splitlines()):
        answers = []
        for line in stdout_text.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(event, dict) and event.get('type') == 'item.completed':
                item = event.get('item', {})
                if isinstance(item, dict) and item.get('type') == 'agent_message' and isinstance(item.get('text'), str):
                    answers.append(item['text'])
        answer_text = '\n'.join(answers)
    answer_text = re.sub(r'\\([_*`])', r'\1', answer_text)
    has_reverse = bool(expected_reverse and re.search(r'REVERSE_NONCE\s*=\s*' + re.escape(expected_reverse) + r'(?![A-Za-z0-9_])', answer_text))
    has_sha256 = bool(expected_sha256 and re.search(r'SHA256_NONCE\s*=\s*' + re.escape(expected_sha256) + r'(?![A-Za-z0-9_])', answer_text))
    transformed_found = has_reverse or has_sha256

    has_raw = bool(raw_nonce and raw_nonce in stdout_text)
    echo_only_detected = bool(has_raw and not transformed_found)

    # Effective model inference
    inferred_model = effective_model
    if not inferred_model:
        if tool in {"sentra-cli", "sentra_cli"}:
            inferred_model = "sentra/chatgpt-web/gpt-6"
        elif tool == "opencode":
            inferred_model = "opencode/muse-spark-1.3-contributor-free#high"
        elif tool == "codex":
            inferred_model = "codex/interactive"

    # Try to parse JSON output if present
    for line in stdout_text.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            try:
                data = json.loads(trimmed)
                if isinstance(data, dict):
                    if data.get("model"):
                        inferred_model = str(data["model"])
            except Exception:
                pass

    verified = bool((exit_code == 0) and transformed_found and not echo_only_detected)

    return {
        "operation_id": oid,
        "work_item_id": wid,
        "request_key": request_key,
        "tool": tool,
        "exit_code": exit_code,
        "stdout_sha256": stdout_sha256,
        "effective_model": inferred_model,
        "nonce": raw_nonce,
        "expected_reverse": expected_reverse,
        "expected_sha256": expected_sha256,
        "transformed_nonce_found": transformed_found,
        "echo_only_detected": echo_only_detected,
        "verified": verified,
        "output_chars": len(stdout_text),
    }


def execute_non_interactive_tool(
    project_dir: Path,
    workspace: Path,
    tool: str,
    instruction: str,
    oid: str,
    wid: str,
    request_key: str,
    nonce: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    timeout_s: float = 30.0,
    runner: Callable[[list[str], str, dict[str, str]], tuple[int, str, str]] | None = None,
) -> dict[str, Any]:
    """Execute a non-interactive CLI turn and return the evaluated receipt.
    
    If runner is provided (e.g. in test doubles), it is invoked with
    (argv, prompt, nonce_info) -> (exit_code, stdout, stderr), preventing
    accidental execution against real models.
    """
    prompt, nonce_info = build_dispatch_prompt(instruction, nonce)
    session_id = 'dot-tool-' + hashlib.sha256(json.dumps([oid,wid,request_key]).encode()).hexdigest()[:32]
    
    try:
        argv = build_cli_command(project_dir, workspace, tool, prompt, model=model, effort=effort,
            session_id=session_id if tool in {'sentra-cli', 'sentra_cli'} else None)
    except FileNotFoundError as exc:
        # Tool provably did not start
        return {
            "operation_id": oid,
            "work_item_id": wid,
            "request_key": request_key,
            "tool": tool,
            "exit_code": -1,
            "stdout_sha256": None,
            "effective_model": model,
            "nonce": nonce_info["raw"],
            "expected_reverse": nonce_info["reverse"],
            "expected_sha256": nonce_info["sha256"],
            "transformed_nonce_found": False,
            "echo_only_detected": False,
            "verified": False,
            "launch_failed": True,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "operation_id": oid,
            "work_item_id": wid,
            "request_key": request_key,
            "tool": tool,
            "exit_code": -1,
            "stdout_sha256": None,
            "effective_model": model,
            "nonce": nonce_info["raw"],
            "expected_reverse": nonce_info["reverse"],
            "expected_sha256": nonce_info["sha256"],
            "transformed_nonce_found": False,
            "echo_only_detected": False,
            "verified": False,
            "launch_failed": True,
            "error": str(exc),
        }

    if runner is not None:
        try:
            exit_code, stdout, stderr = runner(argv, prompt, nonce_info)
        except Exception as exc:
            # Runner failed during execution -> UNCERTAIN (may have started)
            return {
                "operation_id": oid,
                "work_item_id": wid,
                "request_key": request_key,
                "tool": tool,
                "exit_code": -1,
                "stdout_sha256": None,
                "effective_model": model,
                "nonce": nonce_info["raw"],
                "expected_reverse": nonce_info["reverse"],
                "expected_sha256": nonce_info["sha256"],
                "transformed_nonce_found": False,
                "echo_only_detected": False,
                "verified": False,
                "execution_uncertain": True,
                "error": str(exc),
            }
    else:
        try:
            proc = subprocess.run(
                argv,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
            exit_code, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            return {
                "operation_id": oid,
                "work_item_id": wid,
                "request_key": request_key,
                "tool": tool,
                "exit_code": -1,
                "stdout_sha256": None,
                "effective_model": model,
                "nonce": nonce_info["raw"],
                "expected_reverse": nonce_info["reverse"],
                "expected_sha256": nonce_info["sha256"],
                "transformed_nonce_found": False,
                "echo_only_detected": False,
                "verified": False,
                "execution_uncertain": True,
                "error": f"process timed out after {timeout_s}s",
            }
        except Exception as exc:
            return {
                "operation_id": oid,
                "work_item_id": wid,
                "request_key": request_key,
                "tool": tool,
                "exit_code": -1,
                "stdout_sha256": None,
                "effective_model": model,
                "nonce": nonce_info["raw"],
                "expected_reverse": nonce_info["reverse"],
                "expected_sha256": nonce_info["sha256"],
                "transformed_nonce_found": False,
                "echo_only_detected": False,
                "verified": False,
                "execution_uncertain": True,
                "error": str(exc),
            }

    assistant_text = None
    journal_confirmed = None
    if runner is None and tool in {'sentra-cli','sentra_cli'}:
        from sentra_core.conversations import ConversationStore
        try:
            journal = ConversationStore(workspace / '.sentra')
            status = journal.status(session_id)
            answers = [item['content'] for item in journal.messages(session_id) if item['role'] == 'assistant']
            with journal._connect() as db:
                provider_calls = db.execute("SELECT state FROM calls WHERE conversation_id=? AND kind='provider'", (session_id,)).fetchall()
            journal_confirmed = bool(exit_code == 0 and not status['uncertain_calls'] and answers
                and provider_calls and all(row['state'] == 'completed' for row in provider_calls))
            assistant_text = answers[-1] if journal_confirmed else ''
        except (ValueError, OSError, PermissionError, KeyError):
            journal_confirmed = False; assistant_text = ''
    receipt = verify_receipt(
        tool=tool,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        nonce_info=nonce_info,
        oid=oid,
        wid=wid,
        request_key=request_key,
        effective_model=model,
        assistant_text=assistant_text,
    )
    if journal_confirmed is not None:
        receipt['provider_journal_confirmed'] = journal_confirmed
        receipt['provider_session_id'] = session_id
        receipt['verified'] = bool(receipt['verified'] and journal_confirmed)
    return receipt
