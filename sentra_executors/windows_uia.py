"""Minimal Windows UI Automation adapter; no automatic app launch or elevation.

Inspired by UFO's app-scoped execution; uses pywinauto's documented Windows
UIA backend, without copying or executing UFO agent/orchestrator sources.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass

from ._base import GuardedExecutor
from .rpa import effect_checkpoint


@dataclass(frozen=True)
class WindowsUIABinding:
    capability_id: str
    pid: int
    hwnd: int
    window_title: str
    allowed_automation_ids: tuple[str, ...]
    allowed_control_types: tuple[str, ...] = ("Button", "Text")
    allowed_actions: tuple[str, ...] = ("read_text",)
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        if (self.pid <= 0 or self.hwnd <= 0 or not self.window_title or
                not self.allowed_automation_ids or not self.allowed_control_types or
                not self.allowed_actions or not 0 < self.timeout_seconds <= 60):
            raise ValueError("invalid_windows_binding")
        if set(self.allowed_actions) - {"invoke", "read_text", "read_window_title"}:
            raise ValueError("unsupported_windows_action")


class PywinautoUIABackend:
    """All UIA work remains in one worker thread to respect COM apartment use."""

    def run(self, binding: WindowsUIABinding, args: dict) -> dict:
        if sys.platform != "win32":
            raise RuntimeError("windows_only")
        try:
            from pywinauto.application import Application
        except ImportError as exc:
            raise RuntimeError("pywinauto_not_installed") from exc

        effect_checkpoint()
        app = Application(backend="uia").connect(process=binding.pid)
        window = app.window(handle=binding.hwnd).wrapper_object()
        info = window.element_info
        if (int(info.process_id) != binding.pid or
                int(info.handle) != binding.hwnd or
                window.window_text() != binding.window_title):
            raise RuntimeError("window_pid_or_title_mismatch")
        if args["action"] == "read_window_title":
            return {"pid": binding.pid, "hwnd": binding.hwnd,
                    "window_title_sha256": hashlib.sha256(
                        window.window_text().encode("utf-8")).hexdigest()}
        control = window.child_window(auto_id=args["automation_id"],
                                      control_type=args["control_type"]).wrapper_object()
        element = control.element_info
        if (int(element.process_id) != binding.pid or
                str(element.automation_id) != args["automation_id"] or
                str(element.control_type) != args["control_type"] or
                int(control.top_level_parent().handle) != binding.hwnd):
            raise RuntimeError("control_escaped_window_scope")
        if args["action"] == "read_text":
            value = control.window_text()
            return {"pid": binding.pid, "hwnd": binding.hwnd,
                    "automation_id": args["automation_id"],
                    "text_length": len(value),
                    "text_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()}
        if not control.is_enabled() or not control.is_visible():
            raise RuntimeError("control_unavailable")
        effect_checkpoint()
        control.invoke()  # UIA InvokePattern; no uncontrolled mouse coordinates
        return {"pid": binding.pid, "hwnd": binding.hwnd,
                "automation_id": args["automation_id"], "action": "invoke"}


class WindowsUIAExecutor(GuardedExecutor):
    kind = "windows_uia"

    def __init__(self, *, machine_id: str, owner_principal_id: str,
                 bindings: tuple[WindowsUIABinding, ...], policy=None, backend=None):
        if len({b.capability_id for b in bindings}) != len(bindings):
            raise ValueError("duplicate_capability")
        super().__init__(machine_id=machine_id, owner_principal_id=owner_principal_id,
                         bindings={b.capability_id: b for b in bindings}, policy=policy)
        self.backend = backend if backend is not None else PywinautoUIABackend()

    def _validate(self, request, binding: WindowsUIABinding) -> dict:
        args = dict(request.arguments)
        action = args.get("action")
        if action not in binding.allowed_actions:
            raise ValueError("action_not_in_capability")
        expected = {"pid", "hwnd", "action"}
        if action != "read_window_title":
            expected.update(("automation_id", "control_type"))
        if (set(args) != expected or type(args.get("pid")) is not int or
                type(args.get("hwnd")) is not int or
                args["pid"] != binding.pid or args["hwnd"] != binding.hwnd):
            raise ValueError("window_pid_mismatch")
        if action != "read_window_title":
            if (not isinstance(args.get("automation_id"), str) or
                    args["automation_id"] not in binding.allowed_automation_ids or
                    args.get("control_type") not in binding.allowed_control_types):
                raise ValueError("selector_not_permitted")
        return args

    def _execute(self, binding: WindowsUIABinding, arguments: dict) -> dict:
        return self.backend.run(binding, arguments)
