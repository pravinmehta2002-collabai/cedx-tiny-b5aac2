"""
Typed handoff contracts between agents.
Every agent has a declared input/output schema (Pydantic).
This is what makes it a "real fleet" vs a god-function.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


# --- Canonical normalized record (what enters the fleet) ---
class NormalizedRecord(BaseModel):
    id: str
    version: int = 1
    owner: Optional[str] = None
    deadline: Optional[str] = None            # ISO date
    category: Optional[str] = None            # ONBOARDING|RENEWAL|REVIEW|REPORT
    amount: Optional[float] = None
    notes: Optional[str] = None
    source_format: Literal["feed", "eml", "pdf"]
    source_version_hash: str


# --- Orchestrator decision ---
class OrchestratorDecision(BaseModel):
    record_id: str
    route: Literal["worker", "exception", "superseded"]
    reason_code: Optional[str] = None
    reason_class: Optional[Literal["A", "B"]] = None
    note: Optional[str] = None


# --- Worker draft output ---
class WorkerDraft(BaseModel):
    record_id: str
    engagement_type: str                       # ONBOARDING|RENEWAL|REVIEW|REPORT
    title: str
    body: str                                  # the branded deliverable text
    fields: dict                               # structured fields for delivery
    model_used: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    retries: int = 0
    abstained: bool = False
    abstain_reason: Optional[str] = None


# --- Verifier verdict ---
class VerifierVerdict(BaseModel):
    record_id: str
    verdict: Literal["pass", "fail", "needs_human"]
    reason_code: Optional[str] = None          # e.g. AGENT_HALLUCINATION
    findings: list[str] = Field(default_factory=list)
    model_used: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float