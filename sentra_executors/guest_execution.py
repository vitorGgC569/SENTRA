"""Proven guest execution.

A process id, a hash, or a host ``subprocess`` is not a guest. Callers that
require placement ``guest`` must receive an object with ``proven_guest`` and
``execute``. Anything else stays blocked and does not run on the host.

``InjectableGuestExecutor`` is a test double. Production guest turns use
``VirtualBoxGuestControlExecutor``, which only talks to an injected
``VirtualBoxClient`` via ``guestcontrol``.

A client that reports Guest Additions run level refuses ``guestcontrol``
until that level is 2 or 3. A missing probe is not treated as a named VM.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from typing import Any, Callable

class GuestExecutionRefused(ValueError):
    """The guest command was rejected before guestcontrol ran."""


_VM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def safe_vm_id(value: Any) -> str | None:
    """Accept a hypervisor id token. A path or shell fragment is not one."""
    if not isinstance(value, str) or ".." in value or _VM_ID.fullmatch(value) is None:
        return None
    return value


def _request_exposes_secret(secret: str, request: dict[str, Any]) -> bool:
    if len(secret) < 8:
        return False
    pieces: list[str] = []
    for key in ("command", "prompt", "guest_workspace", "workspace", "model"):
        value = request.get(key)
        if isinstance(value, str):
            pieces.append(value)
    argv = request.get("argv")
    if isinstance(argv, (list, tuple)):
        pieces.extend(item for item in argv if isinstance(item, str))
    return any(secret in piece for piece in pieces)


def _declared_timeout_ms(parts: tuple[Any, ...]) -> int | None:
    """Largest ``--timeout`` in a guestcontrol argv, in milliseconds."""
    found: int | None = None
    index = 0
    while index < len(parts):
        if parts[index] == "--timeout":
            if index + 1 >= len(parts):
                raise GuestExecutionRefused("guestcontrol timeout is not a bounded integer")
            raw = parts[index + 1]
            if type(raw) is int and raw >= 0:
                value = raw
            elif isinstance(raw, str) and raw.isdigit():
                value = int(raw)
            else:
                raise GuestExecutionRefused("guestcontrol timeout is not a bounded integer")
            found = value if found is None else max(found, value)
            index += 2
            continue
        index += 1
    return found


def is_proven_guest_executor(executor: Any) -> bool:
    """True only for an explicit guest executor. A PID mapping is not one."""
    execute = getattr(executor, "execute", None)
    return bool(
        getattr(executor, "proven_guest", False) is True
        and getattr(executor, "execution_surface", None) == "guest"
        and callable(execute)
    )


def guest_channel_unready(client: Any, vm_id: Any) -> bool:
    """True when the client itself says Guest Additions are not usable.

    A client without this probe is not blocked by a hardcoded VM name.
    Levels 2 and 3 are the VirtualBox guest-control channel.
    """
    probe = getattr(client, "guest_additions_runlevel", None)
    if not callable(probe) or not isinstance(vm_id, str) or not vm_id.strip() or "\0" in vm_id:
        return False
    return str(probe(vm_id)) not in {"2", "3"}


def _complete_guest_binding(vm_id: Any, username: Any, password: Any) -> bool:
    return bool(
        safe_vm_id(vm_id) is not None
        and isinstance(username, str) and username.strip() and "\0" not in username
        and isinstance(password, str) and password and "\0" not in password
        and "\n" not in password and "\r" not in password
    )


def resolve_guest_executor(
    executor: Any = None,
    *,
    vm_id: Any = None,
    username: Any = None,
    password: Any = None,
    os_family: Any = "linux",
    client: Any = None,
) -> Any:
    """Use a proven executor, or build the guestcontrol one from Dot credentials.

    Missing ``vm_id``, username or password keeps the turn blocked. A host
    process is never returned as a substitute.
    """
    if guest_channel_unready(client, vm_id) or guest_channel_unready(client, getattr(executor, "vm_id", None)):
        return None
    if is_proven_guest_executor(executor):
        return executor
    if not _complete_guest_binding(vm_id, username, password):
        return None
    if client is None:
        from sentra_executors.virtualbox_vm import VirtualBoxClient
        client = VirtualBoxClient()
    if guest_channel_unready(client, vm_id):
        return None
    return VirtualBoxGuestControlExecutor(
        client,
        vm_id=vm_id,
        username=username,
        password=password,
        os_family=os_family if isinstance(os_family, str) else "linux",
    )


def resolve_guest_executor_from_authority(authority: Any, executor: Any = None) -> Any:
    """Read vm_id, user and password from host authority, never from model intent."""
    if not isinstance(authority, dict):
        return resolve_guest_executor(executor)
    return resolve_guest_executor(
        executor,
        vm_id=authority.get("vm_id"),
        username=authority.get("username") or authority.get("guest_username"),
        password=authority.get("password") or authority.get("guest_password"),
        os_family=authority.get("os_family") or "linux",
        client=authority.get("virtualbox_client") or authority.get("guest_client"),
    )


class InjectableGuestExecutor:
    """Test double. The dispatch calls ``execute``; the result is guest, not host."""

    proven_guest = True
    execution_surface = "guest"

    def __init__(self, function: Callable[[dict[str, Any]], dict[str, Any]]):
        if not callable(function):
            raise TypeError("guest executor function required")
        self._function = function
        self.calls: list[dict[str, Any]] = []

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise TypeError("guest request must be an object")
        self.calls.append(dict(request))
        produced = self._function(dict(request))
        if not isinstance(produced, dict):
            raise TypeError("guest executor result must be an object")
        stamped = dict(produced)
        stamped["execution_surface"] = "guest"
        stamped["host_subprocess"] = False
        stamped.setdefault("claims_guest_execution", True)
        return stamped


class VirtualBoxGuestControlExecutor:
    """Production guest executor. ``guestcontrol`` only; never a host subprocess."""

    proven_guest = True
    execution_surface = "guest"

    def __init__(self, client: Any, *, vm_id: str, username: str, password: str,
                 os_family: str = "linux"):
        if guest_channel_unready(client, vm_id):
            raise ValueError("guest channel is not ready")
        if client is None or not callable(getattr(client, "run", None)):
            raise TypeError("VirtualBoxClient required")
        if not _complete_guest_binding(vm_id, username, password):
            raise ValueError("vm_id, username and password from the Dot registry are required")
        family = str(os_family or "linux").strip().lower()
        if family not in {"linux", "windows"}:
            raise ValueError("os_family must be linux or windows")
        self._client = client
        self.vm_id = vm_id.strip()
        self._username = username.strip()
        self._password = password
        self.os_family = family
        self.calls: list[dict[str, Any]] = []

    def execute(self, request: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise TypeError("guest request must be an object")
        if request.get("placement") not in {None, "guest"}:
            raise GuestExecutionRefused("guest executor refuses host placement")
        if guest_channel_unready(self._client, self.vm_id):
            raise GuestExecutionRefused("guest channel is not ready")
        requested = request.get("vm_id")
        if guest_channel_unready(self._client, requested):
            raise GuestExecutionRefused("guest channel is not ready")
        if isinstance(requested, str) and requested and requested != self.vm_id:
            raise GuestExecutionRefused("guest request targets a different VM")
        if _request_exposes_secret(self._password, request):
            raise GuestExecutionRefused("guest command included a credential and was not sent")
        timeout_s = request.get("timeout_s", 120)
        if type(timeout_s) not in {int, float} or timeout_s <= 0:
            timeout_s = 120
        timeout_s = min(float(timeout_s), 3600.0)
        try:
            argv = request.get("argv")
            if argv is not None:
                parts = self._bound_guestcontrol_argv(argv)
            else:
                parts = self._guestcontrol_run_argv(self._guest_command(request), timeout_s)
            if self._password in parts or "--password" in parts:
                raise GuestExecutionRefused("guestcontrol password must stay on stdin")
            declared_ms = _declared_timeout_ms(parts)
            if declared_ms is not None and declared_ms > int(timeout_s * 1000):
                raise GuestExecutionRefused("guestcontrol timeout exceeds the host wait")
        except GuestExecutionRefused:
            raise
        except ValueError as exc:
            raise GuestExecutionRefused(str(exc)) from exc
        self.calls.append({
            key: value for key, value in request.items()
            if key not in {"password", "workspace"}
        })
        try:
            output = self._client.run(*parts, password=self._password, timeout=timeout_s + 10)
        except subprocess.TimeoutExpired:
            return {
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "execution_surface": "guest",
                "host_subprocess": False,
                "claims_guest_execution": False,
                "vm_id": self.vm_id,
                "guest_witness": "guestcontrol",
                "execution_uncertain": True,
                "automatic_retry": False,
            }
        if not isinstance(output, str):
            output = "" if output is None else str(output)
        if len(self._password) >= 8 and self._password in output:
            return {
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "execution_surface": "guest",
                "host_subprocess": False,
                "claims_guest_execution": False,
                "vm_id": self.vm_id,
                "guest_witness": "guestcontrol",
                "credential_discarded": True,
            }
        return {
            "exit_code": 0,
            "stdout": output,
            "stderr": "",
            "execution_surface": "guest",
            "host_subprocess": False,
            "claims_guest_execution": True,
            "vm_id": self.vm_id,
            "guest_witness": "guestcontrol",
        }

    def _bound_guestcontrol_argv(self, argv: Any) -> tuple[str, ...]:
        if not isinstance(argv, (list, tuple)) or not argv:
            raise ValueError("guestcontrol argv required")
        parts = tuple(str(item) for item in argv)
        if parts[0] != "guestcontrol" or len(parts) < 3 or parts[1] != self.vm_id or parts[2] != "run":
            raise ValueError("guest executor only runs guestcontrol for the bound VM")
        if guest_channel_unready(self._client, parts[1]):
            raise ValueError("guest channel is not ready")
        return parts

    def _guestcontrol_run_argv(self, command: str, timeout_s: float) -> tuple[Any, ...]:
        timeout_ms = int(timeout_s * 1000)
        auth = ("--username", self._username, "--passwordfile", "stdin",
                "--wait-stdout", "--wait-stderr", "--timeout", timeout_ms, "--")
        if self.os_family == "windows":
            return ("guestcontrol", self.vm_id, "run", "--exe",
                    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
                    *auth, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command)
        return ("guestcontrol", self.vm_id, "run", "--exe", "/bin/sh",
                *auth, "-c", command)

    def _guest_command(self, request: dict[str, Any]) -> str:
        command = request.get("command")
        if isinstance(command, str) and command.strip():
            return command
        tool = str(request.get("tool") or "").strip()
        prompt = request.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("guest command or tool prompt required")
        host_workspace = request.get("workspace")
        guest_workspace = request.get("guest_workspace")
        if not isinstance(guest_workspace, str) or not guest_workspace.strip():
            guest_workspace = self._account_home()
        if isinstance(host_workspace, str) and host_workspace.strip() and guest_workspace == host_workspace:
            raise ValueError("guest workspace must not be the host workspace")
        guest_workspace = self._bound_guest_workspace(guest_workspace)
        model = request.get("model")
        effort = request.get("effort")
        slug = tool.lower().replace("_", "-")
        if slug == "sentra-cli":
            allowed = {None, "sentra/chatgpt-web/gpt-6", "sentra/grok/grok-4.7"}
            if model not in allowed or effort not in {None, "high"}:
                raise ValueError("Dot SENTRA CLI requires GPT-6 Web high or Grok 4.7 high")
            chosen = model or "sentra/chatgpt-web/gpt-6"
            parts = ["sentra-cli", "-p", prompt, "-w", guest_workspace, "--no-auto-start",
                     "-m", chosen, "--effort", "high"]
        elif slug == "opencode":
            if model not in {None, "opencode/muse-spark-1.3-contributor-free#high"} or effort not in {None, "high"}:
                raise ValueError("Dot OpenCode requires Muse Spark 1.3 free high")
            chosen = model or "opencode/muse-spark-1.3-contributor-free#high"
            parts = ["opencode", "run", "--standalone", "--model", chosen, "--format", "json", prompt]
        elif slug == "codex":
            parts = ["codex", "exec", "-C", guest_workspace, "--json"]
            if isinstance(model, str) and model.strip():
                parts.extend(["-m", model.strip()])
            elif model not in {None, ""}:
                raise ValueError("guest model must be text")
            parts.append(prompt)
        else:
            raise ValueError("unsupported guest tool")
        if self.os_family == "windows":
            quoted = " ".join("'" + part.replace("'", "''") + "'" for part in parts)
            location = guest_workspace.replace("'", "''")
            return (
                "Set-Location -LiteralPath '" + location + "' -ErrorAction Stop; "
                "if ((Get-Location).Path -ne '" + location + "') { exit 1 }; "
                + quoted
            )
        quoted = " ".join(shlex.quote(part) for part in parts)
        return "cd " + shlex.quote(guest_workspace) + " && " + quoted

    def _account_home(self) -> str:
        account = self._username
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,31}", account) or ".." in account:
            raise ValueError("guest workspace must stay in the Dot home")
        if self.os_family == "windows":
            return "C:\\Users\\" + account
        return "/home/" + account

    def _bound_guest_workspace(self, path: str) -> str:
        """Keep the three CLIs inside the Dot home, including an imported folder."""
        if ("\0" in path or any(char in path for char in "\n\r'\"$;`|&<>")
                or any(part == ".." for part in path.replace("\\", "/").split("/"))):
            raise ValueError("guest workspace must stay in the Dot home")
        prefix = self._account_home()
        separator = "\\" if self.os_family == "windows" else "/"
        if path != prefix and not path.startswith(prefix + separator):
            raise ValueError("guest workspace must stay in the Dot home")
        return path
