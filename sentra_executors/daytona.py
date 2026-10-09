"""Optional Daytona SDK adapter bound to an existing private sandbox.

No installation, sandbox creation, stop, deletion, snapshotting or credential
logging. Creation/administration requires a separately authorized lifecycle.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ._base import GuardedExecutor
from .rpa import effect_checkpoint


@dataclass(frozen=True)
class DaytonaBinding:
    capability_id: str
    sandbox_id: str
    allowed_commands: tuple[str, ...]
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if (not self.capability_id or not self.sandbox_id or
                not self.allowed_commands or
                not all(isinstance(s, str) and s.strip() for s in self.allowed_commands) or
                not 0 < self.timeout_seconds <= 120):
            raise ValueError("invalid_daytona_binding")


class DaytonaSDKBackend:
    def __init__(self, client=None):
        self._client = client

    def run(self, binding: DaytonaBinding, args: dict) -> dict:
        if self._client is None:
            try:
                from daytona import Daytona
            except ImportError as exc:
                raise RuntimeError("daytona_sdk_not_installed") from exc
            client = Daytona()  # SDK reads existing env configuration; never log it
        else:
            client = self._client
        effect_checkpoint()
        sandbox = client.get(binding.sandbox_id)
        if (str(getattr(sandbox, "id", "")) != binding.sandbox_id or
                getattr(sandbox, "public", None) is not False or
                getattr(sandbox, "network_block_all", None) is not True):
            raise RuntimeError("sandbox_not_private_or_network_blocked")
        state = getattr(sandbox, "state", None)
        if getattr(state, "value", state) != "started":
            raise RuntimeError("sandbox_not_started")
        effect_checkpoint()
        response = sandbox.process.exec(args["command"],
                                        timeout=max(1, int(binding.timeout_seconds)))
        code = response.exit_code
        if type(code) is not int:
            raise RuntimeError("missing_exit_code")
        output = str(getattr(response, "result", "") or "")
        evidence = {"sandbox_id": binding.sandbox_id, "exit_code": code,
                    "output_length": len(output),
                    "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest()}
        if code != 0:
            raise RuntimeError("command_failed")
        return evidence


class DaytonaExecutor(GuardedExecutor):
    kind = "daytona"

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: tuple[DaytonaBinding, ...], policy=None, backend=None):
        if len({b.capability_id for b in bindings}) != len(bindings):
            raise ValueError("duplicate_capability")
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={b.capability_id: b for b in bindings}, policy=policy)
        self.backend = backend if backend is not None else DaytonaSDKBackend()

    def _validate(self, request, binding: DaytonaBinding) -> dict:
        args = dict(request.arguments)
        if (set(args) != {"action", "sandbox_id", "command"} or
                args["action"] != "exec" or
                args["sandbox_id"] != binding.sandbox_id or
                args["command"] not in binding.allowed_commands):
            raise ValueError("command_or_sandbox_not_permitted")
        return args

    def _execute(self, binding: DaytonaBinding, arguments: dict) -> dict:
        return self.backend.run(binding, arguments)
