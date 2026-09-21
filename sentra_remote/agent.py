"""Outbound SENTRA Remote Agent.

The agent never listens on a public port. It authenticates outbound to the relay,
maintains heartbeats, leases one job at a time, and dispatches through the local
SENTRA MCP server so local policy remains authoritative.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import platform
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp import Client

from sentra_mcp.config import MCPConfig
from sentra_mcp.server import SentraMCPServer
from sentra_version import SERVER_VERSION

from .agent_config import AgentConfig


def _safe_relay_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.rstrip("/"))
    if parsed.scheme == "https":
        return url.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return url.rstrip("/")
    raise ValueError("remote relay must use HTTPS unless it is loopback")


class RelayClient:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.base = _safe_relay_url(config.relay_url)

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float = 15,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if auth:
            headers["Authorization"] = "Device " + self.config.device_token
            headers["X-Sentra-Device"] = self.config.device_id
        data = None
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read(4 * 1024 * 1024)
                return json.loads(raw or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(65536)).get("error", str(exc))
            except Exception:
                detail = str(exc)
            raise RuntimeError(f"relay HTTP {exc.code}: {detail}") from exc

    def heartbeat(self, capabilities: dict[str, Any]) -> dict[str, Any]:
        return self._request("/v1/agent/heartbeat", method="POST", payload={"capabilities": capabilities})

    def poll(self) -> dict[str, Any] | None:
        return self._request("/v1/agent/jobs/poll").get("job")

    def progress(self, job_id: str, lease_token: str, phase: str) -> dict[str, Any]:
        return self._request("/v1/agent/jobs/progress", method="POST", payload={
            "job_id": job_id, "lease_token": lease_token, "phase": phase,
        })

    def result(self, job_id: str, lease_token: str, result: dict[str, Any], *, failed: bool = False) -> None:
        raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) <= 2 * 1024 * 1024:
            self._request("/v1/agent/jobs/result", method="POST", payload={
                "job_id": job_id, "lease_token": lease_token, "result": result, "failed": failed,
            }, timeout=30)
            return
        chunk_size = 512 * 1024
        chunks = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
        for index, chunk in enumerate(chunks):
            self._request("/v1/agent/jobs/chunk", method="POST", payload={
                "job_id": job_id,
                "lease_token": lease_token,
                "index": index,
                "sha256": hashlib.sha256(chunk).hexdigest(),
                "data_b64": base64.b64encode(chunk).decode("ascii"),
            }, timeout=30)
        self._request("/v1/agent/jobs/finalize", method="POST", payload={
            "job_id": job_id,
            "lease_token": lease_token,
            "chunks": len(chunks),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "failed": failed,
        }, timeout=30)

    def rotate(self) -> dict[str, Any]:
        result = self._request("/v1/agent/token/rotate", method="POST", payload={})
        self.config.device_token = str(result["device_token"])
        return result


class AgentRuntime:
    def __init__(self, config: AgentConfig, config_path: Path) -> None:
        self.config = config
        self.config_path = config_path
        self.relay = RelayClient(config)
        audit_path = Path(config.audit_log)
        mcp_config = MCPConfig(
            allowed_roots=tuple(Path(item) for item in config.allowed_roots),
            audit_log=audit_path,
            remote_store_path=audit_path.with_name("agent-remote.sqlite3"),
        )
        self.server = SentraMCPServer(mcp_config)
        self.client = Client(self.server.mcp)
        self.stop_event = asyncio.Event()

    def capabilities(self) -> dict[str, Any]:
        return {
            "agent_version": SERVER_VERSION,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "hostname": platform.node(),
            "mcp": "2026-07-28",
        }

    async def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self.relay.heartbeat, self.capabilities())
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    async def _lease_heartbeat(self, job_id: str, lease: str, done: asyncio.Event) -> None:
        while not done.is_set():
            try:
                await asyncio.to_thread(self.relay.progress, job_id, lease, "executing")
            except Exception:
                pass
            try:
                await asyncio.wait_for(done.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    async def _execute(self, job: dict[str, Any]) -> None:
        job_id = str(job["job_id"])
        lease = str(job["lease_token"])
        tool = str(job["tool"])
        args = dict(job.get("arguments") or {})
        await asyncio.to_thread(self.relay.progress, job_id, lease, "preparing")
        if tool == "system.shutdown_agent":
            await asyncio.to_thread(
                self.relay.result,
                job_id,
                lease,
                {"ok": True, "data": {"status": "SHUTTING_DOWN"}},
            )
            self.stop_event.set()
            return
        cloud_control = {
            "sentra_pair_device", "sentra_list_devices", "sentra_ping", "sentra_who_am_i",
            "sentra_set_device_tools", "sentra_disconnect_device", "sentra_shutdown_remote",
            "sentra_remote_call", "sentra_remote_result", "sentra_remote_cancel",
        }
        if tool in cloud_control or tool.startswith("sentra_remote_"):
            await asyncio.to_thread(
                self.relay.result,
                job_id,
                lease,
                {"ok": False, "error": {"code": "forbidden", "message": "nested remote-control tools are disabled on agents"}},
                failed=True,
            )
            return
        await asyncio.to_thread(self.relay.progress, job_id, lease, "executing")
        done = asyncio.Event()
        beat = asyncio.create_task(self._lease_heartbeat(job_id, lease, done))
        try:
            result = await self.client.call_tool(tool, args)
            payload: dict[str, Any]
            if result.structured_content is not None:
                payload = dict(result.structured_content)
            else:
                payload = {
                    "ok": not result.is_error,
                    "content": [getattr(item, "text", str(item)) for item in result.content],
                }
            await asyncio.to_thread(self.relay.result, job_id, lease, payload, failed=bool(result.is_error))
        except Exception as exc:
            await asyncio.to_thread(
                self.relay.result,
                job_id,
                lease,
                {"ok": False, "error": {"code": "agent_error", "message": str(exc)[:1000]}},
                failed=True,
            )
        finally:
            done.set()
            await beat

    async def run(self) -> None:
        backoff = 1.0
        async with self.client:
            heartbeat = asyncio.create_task(self._heartbeat_loop())
            try:
                while not self.stop_event.is_set():
                    try:
                        job = await asyncio.to_thread(self.relay.poll)
                        backoff = 1.0
                        if job:
                            await self._execute(job)
                            continue
                        await asyncio.sleep(0.5)
                    except Exception:
                        await asyncio.sleep(backoff + random.random() * 0.25)
                        backoff = min(30.0, backoff * 2)
            finally:
                self.stop_event.set()
                await heartbeat
                self.server.processes.shutdown()


def pair_agent(relay_url: str, pairing_code: str, name: str, config_path: Path, roots: list[str]) -> AgentConfig:
    base = _safe_relay_url(relay_url)
    body = json.dumps({"pairing_code": pairing_code, "name": name}).encode("utf-8")
    req = urllib.request.Request(
        base + "/v1/pair",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read(1024 * 1024))
    config = AgentConfig(
        relay_url=base,
        device_id=str(data["device_id"]),
        device_token=str(data["device_token"]),
        name=name,
        allowed_roots=roots or [str(Path.cwd())],
        audit_log=str(Path.home() / ".sentra" / "agent-audit.jsonl"),
    )
    config.save(config_path)
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentra-agent")
    parser.add_argument("--config", default=str(Path.home() / ".sentra" / "agent.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair")
    pair.add_argument("--relay", required=True)
    pair.add_argument("--code", required=True)
    pair.add_argument("--name", default=platform.node() or "SENTRA Device")
    pair.add_argument("--allowed-root", action="append", default=[])
    sub.add_parser("run")
    rotate = sub.add_parser("rotate-token")
    args = parser.parse_args(argv)
    path = Path(args.config).expanduser()
    if args.command == "pair":
        config = pair_agent(args.relay, args.code, args.name, path, args.allowed_root)
        print(json.dumps({"device_id": config.device_id, "name": config.name}))
        return 0
    config = AgentConfig.load(path)
    if args.command == "rotate-token":
        result = RelayClient(config).rotate()
        config.save(path)
        print(json.dumps({"token_expires_at": result["token_expires_at"]}))
        return 0
    asyncio.run(AgentRuntime(config, path).run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
