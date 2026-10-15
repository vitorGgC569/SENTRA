"""ChatGPT Web and Gemini Web pins for the single fleet admission.

Reading the pin does not launch a browser, send a prompt, or touch an account.
A commit hash is not an inference.
"""
from __future__ import annotations

import json
from pathlib import Path


def web_provider_lanes(root: Path | None = None) -> list[dict]:
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    pin_path = base / "integrations" / "codex_chatgpt_web" / "upstream.json"
    pin: dict = {}
    pin_error = None
    try:
        loaded = json.loads(pin_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            pin = loaded
        else:
            pin_error = "upstream pin is not an object"
    except (OSError, ValueError) as exc:
        pin_error = type(exc).__name__
    ref = str(pin.get("ref") or "")
    commit = str(pin.get("commit") or "")
    reason = (
        "integration pin is present; live inference is not verified by this catalog"
        if ref and commit and pin_error is None
        else "ChatGPT Web integration pin is unavailable"
    )
    if pin_error and ref and commit:
        reason = "ChatGPT Web integration pin is unavailable"
    shared = {
        "kind": "provider",
        "installed": bool(ref and commit and pin_error is None),
        "authenticated": "not-checked",
        "inference_verified": False,
        "availability": "present-unverified" if ref and commit and pin_error is None else "unavailable",
        "reason": reason,
        "upstream_ref": ref or None,
        "upstream_commit": commit or None,
        "gui_launch_counts_as_inference": False,
    }
    return [
        {**shared, "id": "chatgpt-web", "model_prefix": "sentra/chatgpt-web/"},
        {**shared, "id": "gemini-web", "model_prefix": "sentra/gemini-web/"},
    ]
