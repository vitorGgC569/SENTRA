"""Hierarquia Project / Run / AgentSession desacoplada do provider remoto.

OMA_PROJECT != RUN != REMOTE_CONVERSATION: amanhã o projeto remoto pode ser
trocado sem alterar Task/Agent/Candidate/Evidence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RemoteConversation:
    conversation_key: str  # ex: EXEC-039 (nome padronizado OMA)
    role: str
    remote_url: Optional[str] = None
    remote_id: Optional[str] = None
    run_id: str = ""
    status: str = "IDLE"  # IDLE | BUSY | COMPLETED | FAILED


@dataclass
class AgentSession:
    session_key: str
    role: str
    specialization: str = ""
    conversation: Optional[RemoteConversation] = None


@dataclass
class ResearchRun:
    run_id: str
    project_id: str
    objective: str
    sessions: Dict[str, AgentSession] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def add_session(self, session_key: str, role: str, specialization: str = "") -> AgentSession:
        s = AgentSession(session_key=session_key, role=role, specialization=specialization)
        self.sessions[session_key] = s
        return s

    def attach_conversation(self, session_key: str, conversation_key: str,
                            remote_url: Optional[str] = None,
                            remote_id: Optional[str] = None) -> RemoteConversation:
        conv = RemoteConversation(conversation_key=conversation_key,
                                  role=self.sessions[session_key].role,
                                  remote_url=remote_url, remote_id=remote_id,
                                  run_id=self.run_id, status="BUSY")
        self.sessions[session_key].conversation = conv
        return conv


@dataclass
class OmaProject:
    project_id: str  # PRJ-0041
    remote_name: str  # "Navier-Stokes Research 0041" (nome no site)
    domain: str = ""
    runs: Dict[str, ResearchRun] = field(default_factory=dict)
    shared_instructions: str = ""

    def new_run(self, run_id: str, objective: str) -> ResearchRun:
        run = ResearchRun(run_id=run_id, project_id=self.project_id, objective=objective)
        self.runs[run_id] = run
        return run


def standard_conversation_name(role: str, index: int) -> str:
    """[EXEC-001], [CRIT-002], [VAL-LOGIC-01], [MASTER], [PLAN]..."""
    return f"[{role.upper()}-{index:03d}]" if index > 0 else f"[{role.upper()}]"
