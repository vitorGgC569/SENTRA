from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from browser.pool import BrowserPool


class FakeSession:
    def __init__(self, role: str, gate=None, fail: bool = False):
        self.role = role
        self.gate = gate
        self.fail = fail
        self.started = False
        self.closed = False
        self.cdp_url = None
        self.browser_channel = "msedge"
        self.user_data_dir = Path("profiles") / role
        self.target_url = "https://chatgpt.com"
        self.headless = False
        self.adapter = object()
        self.page = object()

    @property
    def is_live(self):
        return self.started and not self.closed and not self.fail

    async def initialize(self, target_url="https://chatgpt.com"):
        self.target_url = target_url
        self.started = True
        if self.gate is not None:
            self.gate["started"].append(self.role)
            if len(self.gate["started"]) == self.gate["expected"]:
                self.gate["event"].set()
            await self.gate["event"].wait()
        if self.fail:
            raise RuntimeError(f"{self.role} failed")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_initialize_all_starts_independent_profiles_concurrently():
    gate = {"started": [], "expected": 3, "event": asyncio.Event()}
    sessions = {
        role: FakeSession(role, gate=gate)
        for role in ("builder", "reviewer", "judge")
    }
    pool = BrowserPool(sessions)
    await asyncio.wait_for(pool.initialize_all(), timeout=0.5)
    assert set(gate["started"]) == set(sessions)
    assert all(session.is_live for session in sessions.values())


@pytest.mark.asyncio
async def test_initialize_failure_closes_partial_pool():
    sessions = {
        "builder": FakeSession("builder"),
        "reviewer": FakeSession("reviewer", fail=True),
    }
    pool = BrowserPool(sessions)
    with pytest.raises(RuntimeError, match="browser pool initialization failed"):
        await pool.initialize_all()
    assert all(session.closed for session in sessions.values())


def test_resource_manifest_exposes_scheduler_friendly_capabilities():
    cdp = FakeSession("builder")
    cdp.cdp_url = "http://127.0.0.1:9222"
    cdp.started = True
    pool = BrowserPool({"builder": cdp})

    manifest = pool.resource_manifest()
    assert manifest["resource_type"] == "browser"
    assert manifest["max_concurrency"] == 1
    item = manifest["resources"][0]
    assert item["resource_id"] == "browser:builder"
    assert item["engine"] == "cdp"
    assert item["state"] == "READY"
    assert item["capacity"] == 1
    assert item["capabilities"]["persistent_profile"] is True
    assert item["capabilities"]["cdp_attach"] is True
    assert item["capabilities"]["chat"] is True
