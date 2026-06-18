"""Pydantic request/response schemas (API surface).

These are deliberately separate from the SQLModel persistence model in `db.py`
so the wire contract can evolve independently of storage.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Effort(str, Enum):
    quick = "quick"
    standard = "standard"
    deep = "deep"


class JobState(str, Enum):
    pending = "pending"
    working = "working"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class Jurisdiction(str, Enum):
    california = "CA"
    new_york = "NY"
    general = "general"


class JobCreate(BaseModel):
    query: str = Field(..., min_length=1, description="The legal question to research.")
    effort: Effort = Effort.standard


class JobStatus(BaseModel):
    job_id: str
    status: JobState
    effort: Effort
    progress_pct: float = Field(..., description="Noisy progress 0-100; NOT a reliable ETA signal.")
    phase: Optional[str] = None
    message: Optional[str] = None
    created_at: str
    # Intentionally NO eta field: the (mock of the) real system cannot reliably
    # estimate its own completion time.


class Citation(BaseModel):
    title: str
    url: str
    type: str = "statute"


class ReportSection(BaseModel):
    title: str
    body_markdown: str


class LegalReport(BaseModel):
    job_id: str
    query: str
    effort: Effort
    jurisdiction: Jurisdiction
    summary_markdown: str
    risk_score: int = Field(..., ge=0, le=100, description="Enforceability risk for the employer (0=void, 100=strongly enforceable).")
    citations: list[Citation] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)
    disclaimer: str


class JobResult(BaseModel):
    job_id: str
    status: JobState
    report: Optional[LegalReport] = None
    error: Optional[str] = None


class JobCreated(BaseModel):
    job_id: str
    status: JobState
    effort: Effort
    query: str
    created_at: str


class Health(BaseModel):
    status: str = "ok"
