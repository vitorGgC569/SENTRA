#!/usr/bin/env python3
"""Validate an existing SENTRA Edge bridge, or launch an isolated browser only on explicit request.

Default behavior never launches Edge. It waits for the OMA Browser Bridge that is
already installed/paired in the user's normal Edge profile. The isolated Playwright
profile remains available only for CI/manual diagnostics via --isolated-test.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RELAY = "http://127.0.0.1:8765"


def _relay_health() -> dict:
    with urllib.request.urlopen(RELAY + "/health", timeout=3) as response:
        return json.loads(response.read())


def _terminate_stale_profile_browsers(profile: Path) -> None:
    """Kill only orphaned Edge processes using SENTRA's isolated test profile."""
    if os.name != "nt":
        return
    env = os.environ.copy()
    env["SENTRA_EDGE_PROFILE"] = str(profile.resolve())
    script = r"""
$target = [IO.Path]::GetFullPath($env:SENTRA_EDGE_PROFILE)
Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" |
  Where-Object {
    $_.CommandLine -and
    $_.CommandLine.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0
  } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    time.sleep(1.0)


async def _wait_existing(timeout_s: int, hold_s: int) -> int:
    deadline = time.monotonic() + max(1, timeout_s)
    health: dict = {}
    while time.monotonic() < deadline:
        try:
            health = await asyncio.to_thread(_relay_health)
        except Exception:
            health = {}
        workers = health.get("workers_online") or []
        if workers:
            print(json.dumps({
                "ready": True,
                "mode": "existing-edge",
                "workers_online": workers,
                "workers_ever_seen": health.get("workers_ever_seen"),
                "browser_launched": False,
            }), flush=True)
            if hold_s > 0:
                await asyncio.sleep(hold_s)
            return 0
        await asyncio.sleep(1)
    print(json.dumps({
        "ready": False,
        "mode": "existing-edge",
        "workers_online": health.get("workers_online", []),
        "workers_ever_seen": health.get("workers_ever_seen"),
        "browser_launched": False,
        "hint": "Enable the installed OMA Browser Bridge in the normal Edge profile.",
    }), flush=True)
    return 3


async def _extension_id(context) -> str:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for worker in context.service_workers:
            url = worker.url
            if url.startswith("chrome-extension://"):
                return url.split("/")[2]
        await asyncio.sleep(0.25)
    raise RuntimeError("extension service worker did not start")


async def _isolated_test(profile: Path, hold_s: int) -> int:
    """Explicit diagnostic-only browser. Never used by the normal SENTRA flow."""
    from playwright.async_api import async_playwright
    from browser.bot_profile import launch_persistent_with_cookies

    extension = (ROOT / "edge_extension").resolve()
    auth = ROOT / "auth.json"
    token_path = ROOT / ".oma" / "relay-token"
    if not auth.exists():
        raise RuntimeError("auth.json is required for isolated live E2E")
    if not token_path.exists():
        raise RuntimeError(".oma/relay-token is required; start the relay first")
    token = token_path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("relay token is invalid")

    profile.mkdir(parents=True, exist_ok=True)
    _terminate_stale_profile_browsers(profile)

    async with async_playwright() as pw:
        context = await launch_persistent_with_cookies(
            pw,
            profile,
            channel="msedge",
            headless=False,
            storage_state_path=auth,
            args=[
                f"--disable-extensions-except={extension}",
                f"--load-extension={extension}",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-minimized",
            ],
        )
        try:
            ext_id = await _extension_id(context)
            options = await context.new_page()
            await options.goto(
                f"chrome-extension://{ext_id}/options.html",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            result = await options.evaluate(
                """async ({token}) => {
                    const response = await fetch("http://127.0.0.1:8765/auth/check", {
                      headers: {Authorization: "Bearer " + token}
                    });
                    if (!response.ok) throw new Error("relay auth " + response.status);
                    await chrome.storage.local.set({
                      oma_relay_token: token,
                      oma_enabled: true,
                      oma_pool_size: 1
                    });
                    return {ok: true, version: chrome.runtime.getManifest().version};
                }""",
                {"token": token},
            )
            print(json.dumps({
                "paired": True,
                "mode": "isolated-test",
                "extension_id": ext_id,
                **result,
            }), flush=True)

            deadline = time.monotonic() + 45
            health: dict = {}
            while time.monotonic() < deadline:
                try:
                    health = await asyncio.to_thread(_relay_health)
                except Exception:
                    health = {}
                workers = health.get("workers_online") or []
                if workers:
                    print(json.dumps({
                        "ready": True,
                        "mode": "isolated-test",
                        "workers_online": workers,
                        "profile": str(profile),
                    }), flush=True)
                    break
                await asyncio.sleep(1)
            else:
                return 3

            if hold_s > 0:
                await asyncio.sleep(hold_s)
            return 0
        finally:
            await context.close()


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--wait-seconds", type=int, default=45)
    parser.add_argument(
        "--isolated-test",
        action="store_true",
        help="Explicitly launch a disposable Edge profile for diagnostics only.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(
            Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            / "SENTRA"
            / "edge-extension-live"
        ),
    )
    args = parser.parse_args(argv)

    if not args.isolated_test:
        return await _wait_existing(args.wait_seconds, args.hold_seconds)

    if os.environ.get("SENTRA_ALLOW_ISOLATED_EDGE_TEST") != "1":
        print(json.dumps({
            "ready": False,
            "mode": "isolated-test-blocked",
            "browser_launched": False,
            "error": (
                "isolated Edge diagnostics are disabled by default; "
                "set SENTRA_ALLOW_ISOLATED_EDGE_TEST=1 explicitly"
            ),
        }), flush=True)
        return 4

    return await _isolated_test(Path(args.profile_dir).resolve(), args.hold_seconds)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
