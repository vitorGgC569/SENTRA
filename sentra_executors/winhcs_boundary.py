"""Windows HCS typed boundary, driven ONLY by an explicitly injected provider.

No native hcsshim/HCS imports, host-process launch, privilege elevation,
PowerShell fallback, image pull or container creation by default.
"""
from __future__ import annotations

import re
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable

from sentra_runtime.contracts import Capability, Machine, PolicyDecision
from ._base import GuardedExecutor


@dataclass(frozen=True)
class HCSBinding:
    capability_id: str
    container_id: str
    image_digest: str
    allowed_actions: tuple[str, ...] = ("status", "terminate")
    timeout_seconds: float = 5.0

    def __post_init__(self):
        if (not self.capability_id or not re.fullmatch(r"sentra-lab-[a-z0-9-]{3,48}", self.container_id)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_digest)
                or not self.allowed_actions or len(set(self.allowed_actions)) != len(self.allowed_actions)
                or set(self.allowed_actions) - {"status", "terminate", "create"}
                or not 0 < self.timeout_seconds <= 20):
            raise ValueError("invalid_hcs_binding")


class HCSBoundaryExecutor(GuardedExecutor):
    kind = "winhcs_boundary"

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: tuple[HCSBinding, ...], policy, provider: Any = None,
                 allow_create=False, approve_create: Callable | None = None,
                 platform: str | None = None):
        if len({b.capability_id for b in bindings}) != len(bindings):
            raise ValueError("duplicate_hcs_capability")
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={b.capability_id: b for b in bindings}, policy=policy)
        self.provider = provider
        self.allow_create = bool(allow_create)
        self.approve_create = approve_create
        self.platform = platform if platform is not None else sys.platform
        self._effect_lock = threading.RLock()
        self._terminated: set[str] = set()
        self._created: set[str] = set()
        self._uncertain: set[str] = set()

    def _validate(self, request, binding):
        args = dict(request.arguments)
        if (set(args) != {"action", "container_id", "image_digest"} or
                args["action"] not in binding.allowed_actions
                or args["container_id"] != binding.container_id
                or args["image_digest"] != binding.image_digest):
            raise ValueError("hcs_preapproved_scope_required")
        return args

    def _execute(self, binding, args):
        if self.platform != "win32" or self.provider is None:
            raise RuntimeError("windows_hcs_provider_not_authorized_or_unsupported")
        action, cid = args["action"], binding.container_id
        with self._effect_lock:
            if cid in self._uncertain:
                raise RuntimeError("hcs_uncertain_manual_reconcile")
            if action == "create":
                if (not self.allow_create or
                        not callable(self.approve_create) or
                        self.approve_create(cid, binding.image_digest) is not True):
                    raise PermissionError("hcs_create_not_independently_approved")
                if cid in self._created:
                    return {"container_id": cid, "state": "created"}
                # Even an injected provider receives ONLY an immutable
                # ID and pinned digest. No volume, network or host commands.
                self._uncertain.add(cid)
                result = self.provider.create(cid, binding.image_digest)
                if result != "created":
                    raise RuntimeError("hcs_create_result_invalid")
                self._created.add(cid)
                self._uncertain.discard(cid)
                return {"container_id": cid, "state": "created"}
            if action == "status":
                if cid in self._terminated:
                    return {"container_id": cid, "state": "terminated"}
                state = self.provider.status(cid)
                if state not in ("running", "stopped", "terminated"):
                    raise RuntimeError("hcs_status_result_invalid")
                return {"container_id": cid, "state": state}
            if cid in self._terminated:
                return {"container_id": cid, "state": "terminated"}
            # Only exact authorized existing ID; no wildcard/list/host kill.
            state = self.provider.status(cid)
            if state not in ("running", "stopped", "terminated"):
                raise RuntimeError("hcs_status_result_invalid")
            if state == "terminated":
                self._terminated.add(cid)
                return {"container_id": cid, "state": "terminated"}
            self._uncertain.add(cid)
            result = self.provider.terminate(cid)
            if result != "terminated":
                raise RuntimeError("hcs_terminate_result_invalid")
            self._terminated.add(cid)
            self._uncertain.discard(cid)
            return {"container_id": cid, "state": "terminated"}


def declare_winhcs_machine(*, machine_id: str, owner_principal_id: str,
                           bindings: tuple[HCSBinding, ...], policy,
                           provider=None, allow_create=False,
                           approve_create=None, platform=None):
    from .discovery import MachineDeclaration
    machine = Machine(machine_id, "winhcs_boundary", owner_principal_id, tuple(
        Capability(b.capability_id, "Pinned WinHCS status/terminate boundary", "critical")
        for b in bindings))
    return MachineDeclaration(machine, HCSBoundaryExecutor(
        machine_id=machine_id, owner_principal_id=owner_principal_id,
        bindings=bindings, policy=policy, provider=provider,
        allow_create=allow_create, approve_create=approve_create,
        platform=platform))
