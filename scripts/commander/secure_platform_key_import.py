"""Safely rotate SENTRA's OpenAI tunnel key via private stdin.

No plaintext secret in command arguments, environment variables, UI output,
logs or saved temporary files. An existing DPAPI-protected key is backed up
temporarily and restored if verification of the new tunnel fails.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUNTIME_KEY = re.compile(r"sk-[A-Za-z0-9_-]{20,256}\Z")


def _atomic_write(path: Path, data: bytes) -> None:
    staged = path.with_name(path.name + ".rotation-temp")
    try:
        with staged.open("xb") as fd:
            fd.write(data)
            fd.flush()
            os.fsync(fd.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def rotate_runtime_key(
    paths: Any,
    new_key: str,
    *,
    approved: bool,
    runtime: Any,
    clock: Any = time.monotonic,
    sleep: Any = time.sleep,
) -> dict[str, Any]:
    from sentra_remote.product import tunnel_key_update
    if not approved:
        raise PermissionError("explicit approval required for API key rotation")
    with tunnel_key_update(paths):
        if paths.tunnel_config.with_name("tunnel.json.enrollment-rollback").exists():
            raise RuntimeError("prior incomplete enrollment requires recovery before proceeding")
        return _rotate_runtime_key(paths, new_key, approved=approved, runtime=runtime, clock=clock, sleep=sleep)


def _rotate_runtime_key(
    paths: Any, new_key: str, *, approved: bool, runtime: Any,
    clock: Any, sleep: Any,
) -> dict[str, Any]:
    from sentra_remote.product import (
        configure_tunnel, load_tunnel_config, tunnel_credential_storage,
    )

    if not approved:
        raise PermissionError("explicit approval required for API key rotation")
    if not isinstance(new_key, str) or not RUNTIME_KEY.fullmatch(new_key):
        raise ValueError("invalid Runtime API key format")
    previous = load_tunnel_config(paths)
    if not tunnel_credential_storage(paths).get("ok"):
        raise ValueError("prior credential storage needs repair before rotation")
    tunnel_id = str(previous.get("tunnel_id") or "")
    if not tunnel_id.startswith("tunnel_"):
        raise ValueError("configured SENTRA tunnel missing")
    config_path = paths.tunnel_config
    original = config_path.read_bytes()
    backup = config_path.with_name(config_path.name + ".rotation-rollback")
    if backup.exists():
        raise RuntimeError("prior incomplete rotation requires recovery before proceeding")

    # Old value is encrypted with Windows DPAPI in the backup, not plaintext.
    with backup.open("xb") as fd:
        fd.write(original)
        fd.flush()
        os.fsync(fd.fileno())

    running_before = False
    try:
        running_before = bool(runtime.status().get("tunnel", {}).get("ok"))
        configure_tunnel(paths, tunnel_id, new_key)
        if tunnel_credential_storage(paths).get("ok") is not True:
            raise RuntimeError("DPAPI-protected storage could not be validated")
        if running_before and not runtime.stop("tunnel"):
            raise RuntimeError("could not stop the managed prior tunnel safely")
        started = runtime.start_tunnel()
        if not started.get("ok"):
            raise RuntimeError("new tunnel process failed to start")
        deadline = clock() + 25
        while clock() < deadline:
            if runtime.status().get("tunnel", {}).get("ok"):
                backup.unlink()
                return {
                    "ok": True, "rotated": True,
                    "dpapi": True, "tunnel_verified": True,
                    "old_tunnel_replaced": running_before,
                }
            sleep(0.4)
        raise RuntimeError("new tunnel did not become healthy")
    except Exception:
        # Stop only the new owned tunnel, restore the original encrypted
        # configuration atomically and revive the old instance.
        try:
            runtime.stop("tunnel")
        except Exception:
            pass
        try:
            _atomic_write(config_path, original)
            restored = (
                bool(runtime.start_tunnel().get("ok"))
                if running_before else True
            )
            restored = restored and (
                bool(runtime.status().get("tunnel", {}).get("ok"))
                if running_before else True
            )
        except Exception:
            restored = False
        if restored:
            backup.unlink(missing_ok=True)
        return {
            "ok": False, "rotated": False, "rollback_restored": restored,
            "reason": "verification_failed",
            "manual_recovery_available": backup.exists(),
        }


def main(argv: list[str] | None = None) -> int:
    from sentra_remote.local_runtime import LocalRuntime
    from sentra_remote.product import ProductPaths, ProductSettings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-rotation", action="store_true")
    parser.add_argument("--install-dir", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    # The ciphertext backup/rotation must not start without explicit approval
    # and must never read the key from command-line arguments.
    if not args.approve_rotation:
        print('{"ok":false,"reason":"approval_required"}')
        return 2
    try:
        raw = sys.stdin.buffer.read(2048)
        if len(raw) >= 2048:
            raise ValueError("key input too large")
        payload = json.loads(raw)
        key = payload["runtime_key"] if isinstance(payload, dict) else None
        paths = ProductPaths.default(args.install_dir.resolve())
        settings = ProductSettings.load(paths.settings)
        result = rotate_runtime_key(
            paths, key, approved=True,
            runtime=LocalRuntime(paths, settings),
        )
    except Exception as exc:
        # Never return the exception message: it may contain the input key.
        result = {"ok": False, "reason": type(exc).__name__}
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
