"""Durable remote candidate production for multi-node OMA scheduling."""
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from typing import Any

from .models import Candidate, Task
from workspace.paths import resolve_workspace_path


_REMOTE_TERMINAL = {"COMPLETED", "FAILED", "UNCERTAIN", "CANCELLED"}


def _target_hashes(root: Path, task: Task) -> dict[str, str | None]:
    base = Path(root).resolve(strict=True)
    hashes: dict[str, str | None] = {}
    for relative in task.target_files:
        path = resolve_workspace_path(base, relative)
        if not path.exists():
            hashes[str(relative)] = None
            continue
        if not path.is_file():
            raise ValueError(f"target file is not a regular file: {relative}")
        hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


class RemoteCandidateProducer:
    """Use RemoteGatewayService to obtain a patch proposal from one device.

    The producer never applies the returned patch. It validates correlation and
    relevant-file hashes, then returns a Candidate to the central OMA pipeline,
    which remains responsible for verification, review, rebase and integration.
    """

    def __init__(
        self,
        gateway: Any,
        *,
        principal: str,
        device_id: str,
        workspace: str | None = None,
        provider: str | None = None,
        poll_interval_s: float = 0.25,
        max_wait_s: float = 600.0,
    ) -> None:
        self.gateway = gateway
        self.principal = str(principal or "").strip()
        self.device_id = str(device_id or "").strip()
        self.workspace = workspace
        self.provider = provider
        self.poll_interval_s = max(0.02, float(poll_interval_s))
        self.max_wait_s = max(5.0, min(float(max_wait_s), 3600.0))
        if not self.principal:
            raise ValueError("remote candidate principal is required")
        if not self.device_id:
            raise ValueError("remote candidate device_id is required")

    async def _wait_terminal(
        self,
        initial: dict[str, Any],
        *,
        deadline: float,
    ) -> dict[str, Any]:
        state = str(initial.get("state") or "")
        current = dict(initial)
        job_id = str(current.get("job_id") or "")
        if not job_id:
            return current
        while state not in _REMOTE_TERMINAL and time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval_s)
            current = await asyncio.to_thread(
                self.gateway.result,
                self.principal,
                job_id,
            )
            state = str(current.get("state") or "")
        return current

    @staticmethod
    def _response_data(remote: dict[str, Any]) -> dict[str, Any]:
        state = str(remote.get("state") or "")
        if state == "UNCERTAIN":
            raise RuntimeError(
                "REMOTE_CANDIDATE_UNCERTAIN: remote execution may have started; "
                "reconcile the persisted job before any new attempt"
            )
        if state == "CANCELLED":
            raise RuntimeError("REMOTE_CANDIDATE_CANCELLED")
        if state != "COMPLETED":
            if state == "FAILED":
                raise RuntimeError(
                    "REMOTE_CANDIDATE_FAILED: " + str(remote.get("error") or "")[:1000]
                )
            raise RuntimeError(
                "REMOTE_CANDIDATE_PENDING_RECONCILE: remote job is still running"
            )
        envelope = remote.get("result")
        if not isinstance(envelope, dict):
            raise RuntimeError("REMOTE_CANDIDATE_PROTOCOL: result envelope missing")
        if envelope.get("ok") is not True:
            error = envelope.get("error")
            raise RuntimeError(
                "REMOTE_CANDIDATE_TOOL_FAILED: " + str(error or "")[:1000]
            )
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("REMOTE_CANDIDATE_PROTOCOL: data object missing")
        if data.get("status") != "CANDIDATE_READY":
            raise RuntimeError(
                "REMOTE_CANDIDATE_PROTOCOL: candidate is not ready"
            )
        return data

    async def produce_candidate(
        self,
        task: Task,
        *,
        context_summary: str,
        workspace_path: Path,
    ) -> Candidate:
        local_hashes = _target_hashes(Path(workspace_path), task)
        timeout_s = int(max(5, min(float(task.timeout_s), self.max_wait_s, 3600.0)))
        idempotency_key = (
            f"{task.idempotency_key}:remote-candidate:{self.device_id}"
        )
        arguments = {
            "workspace": self.workspace,
            "task": task.to_dict(),
            "context_summary": str(context_summary or "")[:12000],
            "provider": self.provider,
        }
        initial = await asyncio.to_thread(
            self.gateway.invoke,
            self.principal,
            self.device_id,
            "sentra_oma_candidate_generate",
            arguments,
            timeout_s=timeout_s,
            wait_s=min(25.0, float(timeout_s)),
            idempotency_key=idempotency_key,
        )
        remote = await self._wait_terminal(
            initial,
            deadline=time.monotonic() + timeout_s,
        )
        data = self._response_data(remote)

        remote_hashes = data.get("target_hashes")
        if not isinstance(remote_hashes, dict):
            raise RuntimeError(
                "REMOTE_CANDIDATE_PROTOCOL: target hashes are required"
            )
        normalized_remote = {
            str(key): (None if value is None else str(value))
            for key, value in remote_hashes.items()
        }
        if normalized_remote != local_hashes:
            raise RuntimeError(
                "REMOTE_BASE_CHANGED: remote target files differ from the "
                "central integration baseline"
            )

        raw_candidate = data.get("candidate")
        if not isinstance(raw_candidate, dict):
            raise RuntimeError("REMOTE_CANDIDATE_PROTOCOL: candidate object missing")
        candidate = Candidate.from_dict(raw_candidate)
        if candidate.task_id != task.id:
            raise RuntimeError(
                f"REMOTE_CANDIDATE_TASK_MISMATCH: expected {task.id}, "
                f"got {candidate.task_id}"
            )
        candidate.run_id = task.run_id
        candidate.created_by = (
            candidate.created_by
            or f"remote:{self.device_id}"
        )
        return candidate
