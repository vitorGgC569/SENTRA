"""Stable canonical resource identity, independent of Maestri display names."""
from __future__ import annotations
import re
from dataclasses import dataclass

IDENTIFIER=re.compile(r"^[0-9a-f]{32}$")

def check(identifier: str) -> str:
    if not isinstance(identifier,str) or not IDENTIFIER.fullmatch(identifier):
        raise ValueError("invalid persistent resource ID")
    return identifier

@dataclass(frozen=True)
class Namespace:
    workspace: str
    team: str | None = None
    agent: str | None = None
    session: str | None = None
    task: str | None = None

    def __post_init__(self):
        check(self.workspace)
        if self.team: check(self.team)
        if self.agent: check(self.agent)
        if self.session: check(self.session)
        if self.task: check(self.task)
        if self.task and not self.team:
            raise ValueError("tasks require a team namespace")

    @property
    def path(self) -> str:
        parts=["workspace",self.workspace]
        if self.team:parts.extend(("team",self.team))
        if self.agent:parts.extend(("agent",self.agent))
        if self.session:parts.extend(("session",self.session))
        if self.task:parts.extend(("task",self.task))
        return "/".join(parts)
