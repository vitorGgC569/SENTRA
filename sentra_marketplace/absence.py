"""Absence probes are not a connector call, a network fetch, visual weights, or QuickJS."""
from __future__ import annotations

ABSENCE_REASONS = frozenset({
    "VISUAL_MODEL_NOT_OPTED_IN",
    "MODEL_PACKAGE_ABSENT",
    "PACKAGE_ABSENT",
    "CATALOG_ABSENT",
    "CATALOG_EMPTY",
    "CONNECTOR_PACKAGE_ABSENT",
    "CONNECTOR_UNKNOWN",
    "SKILL_ABSENT",
})


def absence_stamp(reason: str) -> dict:
    """Marks a missing local artifact. Empty when the reason is not an absence."""
    if reason not in ABSENCE_REASONS:
        return {}
    return {
        "absence_probe": True,
        "connector_real": False,
        "network": False,
        "visual_weights": False,
        "quickjs": False,
        "homologated": False,
        "inference_homologated": False,
        "grants_created": False,
    }
