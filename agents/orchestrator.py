"""
Agent 1: Orchestrator / Planner (rule-based, no LLM).
Owns the run:
  - decides what to do with each triaged record
  - enforces per-record step + cost budgets
  - drives the approval state machine
  - emits agent_span events into the audit log
  - handles verifier overrule -> retry (escalate) -> abstain -> route

TYPED CONTRACT:
  input:  list[TriageResult]
  output: list[RecordOutcome]     (drives delivery/exception dumps)
  can_call: ["worker_v1", "verifier_v1"]
"""
from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from .contracts import NormalizedRecord
from . import worker, verifier
from pipeline.approval import ApprovalMachine, State
from pipeline.audit import AuditLogger, sha256_of
from pipeline.exceptions import TriageResult

NAME = "orchestrator_v1"
ROLE = "orchestrator"
MODELS: list[str] = []
CAN_CALL = ["worker_v1", "verifier_v1"]
PROMPT_VERSION = "1.0"


# --------------------------------------------------------------------------- #
# per-record outcome (what delivery + audit assembly need)
# --------------------------------------------------------------------------- #
@dataclass
class RecordOutcome:
    record_id: str
    status: str                              # delivered | exception | superseded
    reason_code: Optional[str] = None
    reason_class: Optional[str] = None
    delivered_fields: Optional[dict] = None
    delivered_fields_hash: Optional[str] = None
    transcript_hash: Optional[str] = None
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    steps_used: int = 0


# --------------------------------------------------------------------------- #
# budgets (per-record ceilings)
# --------------------------------------------------------------------------- #
@dataclass
class Budget:
    max_cost_usd: float = float(os.environ.get("MAX_COST_USD_PER_RECORD", 0.05))
    max_steps: int = int(os.environ.get("MAX_STEPS_PER_RECORD", 6))
    max_latency_ms: float = float(os.environ.get("MAX_LATENCY_MS_PER_RECORD", 15000))


class Orchestrator:
    """
    Coordinates worker + verifier for each triaged record.
    Emits full agent_trace spans into the audit log.
    """

    def __init__(self, logger: AuditLogger, approvals: ApprovalMachine, budget: Optional[Budget] = None):
        self.log = logger
        self.approvals = approvals
        self.budget = budget or Budget()

    # ---- span emission -------------------------------------------------- #
    def _span(
        self,
        record_id: str,
        agent: str,
        status: str,
        *,
        model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        retries: int = 0,
        transcript_hash: Optional[str] = None,
        verdict: Optional[str] = None,
    ):
        payload = {
            "agent": agent,
            "model": model,
            "prompt_version": prompt_version,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "retries": retries,
            "transcript_hash": transcript_hash,
            "status": status,
            "verdict": verdict,
        }
        self.log.append(
            actor=agent,
            action="agent_span",
            record_id=record_id,
            payload=payload,
        )

    # ---- per-record processing ------------------------------------------ #
    def process(self, triaged: list[TriageResult]) -> list[RecordOutcome]:
        outcomes: list[RecordOutcome] = []
        for tr in triaged:
            r = tr.record
            # Emit ingest event for the audit fold
            self.log.append(
                actor=NAME,
                action="record_ingested",
                record_id=r.id,
                payload={
                    "version": r.version,
                    "source_format": r.source_format,
                    "source_version_hash": r.source_version_hash,
                    "amount": r.amount,
                },
            )

            outcomes.append(self._process_one(tr))
        return outcomes

    def _process_one(self, tr: TriageResult) -> RecordOutcome:
        r = tr.record
        oc = RecordOutcome(record_id=r.id, status="exception")

        # ---- SUPERSEDED ---- #
        if tr.superseded_by:
            oc.status = "superseded"
            oc.reason_code = "SUPERSEDED_VERSION"
            oc.reason_class = "B"
            self.log.append(
                actor=NAME, action="record_superseded", record_id=r.id,
                payload={"superseded_by": tr.superseded_by},
            )
            self._span(r.id, NAME, status="routed")
            return oc

        # ---- BLOCKED by exception queue ---- #
        if tr.blocked:
            worst = tr.worst_flag
            oc.reason_code = worst.reason_code
            oc.reason_class = worst.reason_class
            self._span(r.id, NAME, status="routed")
            self.log.append(
                actor=NAME, action="record_exception", record_id=r.id,
                payload={"reason_code": worst.reason_code,
                         "reason_class": worst.reason_class,
                         "detail": worst.detail},
            )
            self.approvals.open(r.id, amount=r.amount, actor=NAME)
            self.approvals.block(r.id, actor=NAME, reason=worst.detail)
            return oc

        # ---- Class-B info ---- #
        for f in tr.flags:
            if f.reason_class == "B":
                self.log.append(
                    actor=NAME, action="record_exception", record_id=r.id,
                    payload={"reason_code": f.reason_code, "reason_class": "B",
                             "detail": f.detail},
                )

        # ---- CLEAN PATH: Orchestrator -> Worker -> Verifier ---- #
        self._span(r.id, NAME, status="routed")
        self.approvals.open(r.id, amount=r.amount, actor=NAME)

        # Import here to avoid circular deps in earlier steps
        from agents.worker import draft_with_transcript
        from agents.model_router import ModelRouter
        router = ModelRouter()

        MAX_ATTEMPTS = 2
        escalate = False
        draft = None
        verdict = None
        transcript_hash = None
        delivered_fields_hash = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            draft, transcript_hash, delivered_fields_hash = draft_with_transcript(
                r, escalate=escalate, router=router
            )
            oc.total_cost_usd += draft.cost_usd
            oc.total_latency_ms += draft.latency_ms
            oc.steps_used += 1

            # Budget guard
            if (oc.total_cost_usd > self.budget.max_cost_usd
                    or oc.steps_used > self.budget.max_steps
                    or oc.total_latency_ms > self.budget.max_latency_ms):
                self._span(r.id, worker.NAME, status="killed",
                           model=draft.model_used, prompt_version=draft.prompt_version,
                           tokens_in=draft.tokens_in, tokens_out=draft.tokens_out,
                           cost_usd=draft.cost_usd, latency_ms=draft.latency_ms,
                           retries=attempt - 1, transcript_hash=transcript_hash)
                oc.status = "exception"
                oc.reason_code = "BUDGET_EXCEEDED"
                oc.reason_class = "A"
                self.log.append(
                    actor=NAME, action="record_exception", record_id=r.id,
                    payload={"reason_code": "BUDGET_EXCEEDED", "reason_class": "A",
                             "detail": f"budget exceeded (cost={oc.total_cost_usd:.4f})"},
                )
                self.approvals.block(r.id, actor=NAME, reason="budget exceeded")
                return oc

            # Emit worker span with REAL transcript_hash
            self._span(
                r.id, worker.NAME,
                status="ok" if attempt == 1 else "retried",
                model=draft.model_used, prompt_version=draft.prompt_version,
                tokens_in=draft.tokens_in, tokens_out=draft.tokens_out,
                cost_usd=draft.cost_usd, latency_ms=draft.latency_ms,
                retries=attempt - 1,
                transcript_hash=transcript_hash,
            )

            if attempt == 1:
                self.approvals.submit_for_review(r.id, actor=worker.NAME)

            # Verifier
            verdict = verifier.verify(r, draft)
            oc.total_cost_usd += verdict.cost_usd
            oc.total_latency_ms += verdict.latency_ms
            oc.steps_used += 1

            if verdict.verdict == "pass":
                self._span(r.id, verifier.NAME, status="ok",
                           model=verdict.model_used, prompt_version=verdict.prompt_version,
                           tokens_in=verdict.tokens_in, tokens_out=verdict.tokens_out,
                           cost_usd=verdict.cost_usd, latency_ms=verdict.latency_ms,
                           verdict="pass")
                break
            else:
                self._span(r.id, verifier.NAME, status="overruled",
                           model=verdict.model_used, prompt_version=verdict.prompt_version,
                           tokens_in=verdict.tokens_in, tokens_out=verdict.tokens_out,
                           cost_usd=verdict.cost_usd, latency_ms=verdict.latency_ms,
                           verdict="fail")
                if attempt < MAX_ATTEMPTS:
                    escalate = True
                else:
                    oc.status = "exception"
                    oc.reason_code = verdict.reason_code or "AGENT_HALLUCINATION"
                    oc.reason_class = "A"
                    self.log.append(
                        actor=NAME, action="record_exception", record_id=r.id,
                        payload={"reason_code": oc.reason_code, "reason_class": "A",
                                 "detail": f"verifier overruled after {MAX_ATTEMPTS} attempts; "
                                           f"findings={verdict.findings}"},
                    )
                    self.approvals.block(r.id, actor=NAME, reason="verifier overrule; needs human")
                    return oc

        assert draft is not None and verdict is not None

        # Approvals (auto in demo mode; operator CLI handles manual mode)
        self.approvals.approve(r.id, actor="partner:auto", role="partner",
                               reason="verifier pass; auto-approved by demo pipeline")
        if self.approvals.amendment.requires_second_approval(r.amount):
            self.approvals.approve(
                r.id,
                actor=f"{self.approvals.amendment.role}:auto",
                role=self.approvals.amendment.role,
                reason=f"amount {r.amount} >= {self.approvals.amendment.threshold} — "
                       f"amendment {self.log.case_id}",
            )

        ok, why = self.approvals.attempt_deliver(r.id, actor="delivery_svc")
        if not ok:
            oc.status = "exception"
            oc.reason_code = "UNVERIFIED_ANOMALY"
            oc.reason_class = "A"
            self.log.append(
                actor="delivery_svc", action="record_exception", record_id=r.id,
                payload={"reason_code": "UNVERIFIED_ANOMALY", "reason_class": "A",
                         "detail": f"delivery refused: {why}"},
            )
            return oc

        oc.status = "delivered"
        oc.delivered_fields = draft.fields
        oc.delivered_fields_hash = delivered_fields_hash
        oc.transcript_hash = transcript_hash
        self.log.append(
            actor="delivery_svc", action="record_delivered", record_id=r.id,
            payload={"delivered_fields": draft.fields,
                     "delivered_fields_hash": delivered_fields_hash,
                     "transcript_hash": transcript_hash},
        )
        return oc


# Keep the old function name available for the tracer-check import
def route(record: NormalizedRecord):
    """Legacy shim from Step 1. Not used at runtime."""
    from .contracts import OrchestratorDecision
    return OrchestratorDecision(record_id=record.id, route="worker")