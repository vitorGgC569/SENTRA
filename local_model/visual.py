"""Opt-in local visual models. A missing pack or runtime is explicit.

This module does not download weights, does not call the text Qwen client,
and does not treat a package hash as a completed inference.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentra_marketplace.absence import absence_stamp
from sentra_marketplace.gate import PackagePin, Subject
from sentra_marketplace.packages import verify_visual_pack


@dataclass(frozen=True)
class VisualModelPin:
    model_id: str
    path: str
    sha256: str

    @property
    def capability(self) -> str:
        return f"visual-model:{self.model_id}:infer"


def _runtime_reason(runtime) -> str:
    """Why this runtime cannot infer. A callable is not a loaded weight file.

    This module has no weight loader, so the reason is never empty and the
    model is never announced as loaded.
    """
    if runtime is not None:
        module = getattr(type(runtime), "__module__", "") or ""
        if type(runtime).__name__ == "QwenLocalClient" or module.endswith("qwen_client"):
            return "TEXT_MODEL_IS_NOT_VISUAL"
    if runtime is None:
        return "VISUAL_RUNTIME_ABSENT"
    return "VISUAL_WEIGHTS_NOT_LOADED"


class LocalVisualModel:
    """Specialized visual pack. Opt-in, local, and unavailable when absent."""

    def readiness(self, pin: VisualModelPin | None = None, *, runtime=None) -> dict[str, Any]:
        runtime_reason = _runtime_reason(runtime)
        base = {
            "available": False, "opt_in_required": True, "network": False,
            "grants_created": False, "inference_homologated": False,
            "text_model_substituted": False, "runtime_reason": runtime_reason,
            "model_loaded": False, "visual_weights": False,
        }
        if pin is None:
            reason = "VISUAL_MODEL_NOT_OPTED_IN"
            return {**base, "reason": reason, "package_present": False,
                    "visual_weights": False, **absence_stamp(reason)}
        checked = verify_visual_pack(Path(pin.path), pin.sha256)
        present = bool(checked.get("ok"))
        reason = runtime_reason if present else checked.get("reason") or "MODEL_PACKAGE_ABSENT"
        body = {
            **base,
            "model_id": pin.model_id,
            "capability": pin.capability,
            "package_present": present,
            "bytes": checked.get("bytes", 0),
            "sha256": checked.get("sha256"),
            "reason": reason,
            "available": False,
            "model_loaded": False,
            "visual_weights": False,
        }
        return {**body, **absence_stamp(reason)}

    def infer(self, gate, authorization, binding, policy, pin: VisualModelPin | None, *,
              runtime=None, prompt: str = ""):
        """Infer only with a host Grant. Absence stays UNAVAILABLE."""
        if pin is None:
            subject = Subject(
                kind="visual_model", subject_id="visual-model",
                capability="visual-model:unselected:infer", manifest={}, content=prompt,
            )
            package = None
            capability_pin = None
        else:
            subject = Subject(
                kind="visual_model", subject_id=pin.model_id, capability=pin.capability,
                manifest={}, content=prompt,
            )
            package = PackagePin(pin.model_id, "visual_model", pin.path, pin.sha256)
            capability_pin = pin
        runtime_reason = _runtime_reason(runtime)
        receipt = gate.invoke(
            authorization=authorization, binding=binding, policy=policy,
            subject=subject, package=package,
            effect=None,
            unavailable_reason=runtime_reason,
        )
        receipt = dict(receipt)
        receipt["inference_homologated"] = False
        receipt["homologated"] = False
        receipt["network"] = False
        receipt["grants_created"] = False
        receipt["model_loaded"] = False
        receipt["visual_weights"] = False
        if capability_pin is not None:
            receipt["model_id"] = capability_pin.model_id
        return receipt
