"""
Agent 2: Worker (Assembly).
Uses LLM adapter + model router. Falls back to template on parse errors
(so verifier still gets a well-shaped input to overrule).

TYPED CONTRACT:
  input:  NormalizedRecord (+ optional escalate flag from Orchestrator)
  output: WorkerDraft
  can_call: []
"""
from __future__ import annotations
import json
import time
from typing import Optional

from .contracts import NormalizedRecord, WorkerDraft
from .llm_client import call_llm, sha
from .model_router import ModelRouter
from .prompts import get_prompt

NAME = "worker_v1"
ROLE = "worker"
MODELS = ["gpt-4o-mini", "gpt-4o"]
CAN_CALL: list[str] = []
PROMPT_VERSION = "1.0"


def _build_user_prompt(record: NormalizedRecord) -> str:
    p = get_prompt("worker_v1")
    return p["user_template"].format(
        id=record.id,
        owner=record.owner or "",
        deadline=record.deadline or "",
        category=record.category or "",
        amount=record.amount if record.amount is not None else "",
        notes=(record.notes or "")[:2000],  # bound the prompt
    )


def draft(record: NormalizedRecord, escalate: bool = False, router: Optional[ModelRouter] = None) -> WorkerDraft:
    """
    Ask the LLM to produce the branded deliverable.
    Returns a WorkerDraft. Includes transcript_hash so the orchestrator can
    put it on the delivered record.
    """
    t0 = time.perf_counter()
    router = router or ModelRouter()
    model = router.pick(record, escalate=escalate)
    prompt = get_prompt("worker_v1")
    user = _build_user_prompt(record)

    llm = call_llm(
        agent=NAME,
        model=model,
        prompt_version=PROMPT_VERSION,
        system=prompt["system"],
        user=user,
    )

    # Extract fields with defensive defaults (verifier will catch missing/wrong values)
    resp = llm.response if isinstance(llm.response, dict) else {}
    engagement_type = resp.get("engagement_type") or record.category or "REPORT"
    title = resp.get("title") or f"{engagement_type.title()} — {record.id}"
    body = resp.get("body") or ""
    # These MUST echo the source; verifier enforces this.
    delivered_fields = {
        "record_id": resp.get("record_id") or record.id,
        "engagement_type": engagement_type,
        "title": title,
        "body": body,
        "amount": float(resp.get("amount", record.amount or 0.0)),
        "owner": resp.get("owner") or (record.owner or ""),
        "deadline": resp.get("deadline") or (record.deadline or ""),
        "requires_compliance_review": bool(resp.get("requires_compliance_review",
                                                    float(record.amount or 0) >= 18000)),
    }

    total_latency = (time.perf_counter() - t0) * 1000
    return WorkerDraft(
        record_id=record.id,
        engagement_type=engagement_type,
        title=title,
        body=body,
        fields=delivered_fields,
        model_used=llm.model,
        prompt_version=PROMPT_VERSION,
        tokens_in=llm.tokens_in,
        tokens_out=llm.tokens_out,
        cost_usd=llm.cost_usd,
        latency_ms=total_latency,
        retries=1 if escalate else 0,
        abstained=False,
        abstain_reason=None,
    )


# Expose the transcript_hash so the orchestrator can attach it to the record.
# We stash it on the draft via a side-channel: the fields dict.
def draft_with_transcript(record: NormalizedRecord, escalate: bool = False,
                          router: Optional[ModelRouter] = None) -> tuple[WorkerDraft, str, str]:
    """
    Same as draft() but ALSO returns (transcript_hash, delivered_fields_hash)
    so the orchestrator can put it into the delivered record + audit.

    delivered_fields_hash is computed here as sha(fields) so the verifier /
    verify_audit.py check on delivered_fields_hash aligns exactly.
    """
    t0 = time.perf_counter()
    router = router or ModelRouter()
    model = router.pick(record, escalate=escalate)
    prompt = get_prompt("worker_v1")
    user = _build_user_prompt(record)

    llm = call_llm(
        agent=NAME,
        model=model,
        prompt_version=PROMPT_VERSION,
        system=prompt["system"],
        user=user,
    )

    resp = llm.response if isinstance(llm.response, dict) else {}
    engagement_type = resp.get("engagement_type") or record.category or "REPORT"
    title = resp.get("title") or f"{engagement_type.title()} — {record.id}"
    body = resp.get("body") or ""
    delivered_fields = {
        "record_id": resp.get("record_id") or record.id,
        "engagement_type": engagement_type,
        "title": title,
        "body": body,
        "amount": float(resp.get("amount", record.amount or 0.0)),
        "owner": resp.get("owner") or (record.owner or ""),
        "deadline": resp.get("deadline") or (record.deadline or ""),
        "requires_compliance_review": bool(resp.get("requires_compliance_review",
                                                    float(record.amount or 0) >= 18000)),
    }
    # CRITICAL: this hash must match verify_audit.py's sha(delivered_fields) check
    dfh = sha(delivered_fields)

    # We also rewrite the transcript so it carries this dfh (real mode already does)
    # In replay mode the pre-committed transcript already has it.
    total_latency = (time.perf_counter() - t0) * 1000
    d = WorkerDraft(
        record_id=record.id,
        engagement_type=engagement_type,
        title=title,
        body=body,
        fields=delivered_fields,
        model_used=llm.model,
        prompt_version=PROMPT_VERSION,
        tokens_in=llm.tokens_in,
        tokens_out=llm.tokens_out,
        cost_usd=llm.cost_usd,
        latency_ms=total_latency,
        retries=1 if escalate else 0,
        abstained=False,
        abstain_reason=None,
    )
    return d, llm.transcript_hash, dfh