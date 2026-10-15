"""Skill text is disclosed as data. Reading it does not execute it."""
from __future__ import annotations

from pathlib import Path

from .content_fence import MAX_CONTENT_BYTES
from .gate import Subject


def read_skill_text(path: Path | str) -> str:
    """Read one SKILL.md. Symlinks and other filenames are refused."""
    candidate = Path(path)
    if candidate.name != "SKILL.md" or candidate.is_symlink() or not candidate.is_file():
        raise ValueError("SKILL_ABSENT")
    raw = candidate.read_bytes()
    if len(raw) > MAX_CONTENT_BYTES:
        raise ValueError("CONTENT_UNBOUNDED")
    return raw.decode("utf-8")


def disclose_skill(gate, authorization, binding, policy, *, skill_id: str, content: str):
    """Bind disclosure to the host operation. The body stays data."""
    subject = Subject(
        kind="skill",
        subject_id=skill_id,
        capability=f"skill:{skill_id}:read",
        manifest={},
        content=content,
    )
    return gate.invoke(
        authorization=authorization, binding=binding, policy=policy,
        subject=subject, package=None, effect=None,
    )
