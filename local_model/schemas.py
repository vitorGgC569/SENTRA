from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SubTask(BaseModel):
    id: str
    description: str
    role: str = "implementer"
    target_files: List[str] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    summary: str
    tasks: List[SubTask] = Field(default_factory=list)


class PlanResponse(BaseModel):
    round_objective: str
    tasks: List[SubTask] = Field(default_factory=list)


class CritiqueDecision(BaseModel):
    status: str  # "accept", "request_revision", "reject"
    reason: str = ""
    accepted_results: List[Dict[str, Any]] = Field(default_factory=list)
    revision_tasks: List[Dict[str, Any]] = Field(default_factory=list)


class FinalAcceptance(BaseModel):
    accepted: bool
    reason: str
