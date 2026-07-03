"""
Agent 2: Worker (Assembly).
Drafts the branded accounting engagement deliverable.

STEP 4: template-based deterministic draft (no LLM yet).
STEP 6: real LLM call + model router + abstain path.

TYPED CONTRACT:
  input:  NormalizedRecord
  output: WorkerDraft
  can_call: []   # workers are leaves
"""
from __future__ import annotations
import time
from .contracts import NormalizedRecord, WorkerDraft

NAME = "worker_v1"
ROLE = "worker"
MODELS = ["gpt-4o-mini", "gpt-4o"]  # cheap default + escalation (used in Step 6)
CAN_CALL: list[str] = []
PROMPT_VERSION = "1.0"


# ---- template bodies keyed by engagement category -------------------------- #
_TEMPLATES = {
    "ONBOARDING": (
        "Engagement Letter — New Client Onboarding\n\n"
        "This letter confirms our firm's engagement to provide accounting "
        "services for the client onboarding matter referenced above. "
        "Owner {owner} will lead the setup, and deliverables will be "
        "provided by {deadline}. Estimated engagement fee: ${amount:,.2f}."
    ),
    "RENEWAL": (
        "Annual Renewal Confirmation\n\n"
        "This confirms the renewal of the annual engagement described above. "
        "Owner {owner} will oversee continuity; the renewal cycle closes on "
        "{deadline}. Renewal fee: ${amount:,.2f}."
    ),
    "REVIEW": (
        "Quarterly Review Memo\n\n"
        "This memo covers the quarterly review deliverable identified above. "
        "Owner {owner} will produce the review packet by {deadline}. "
        "Engagement fee for this cycle: ${amount:,.2f}."
    ),
    "REPORT": (
        "Monthly Report Cover Memo\n\n"
        "This cover memo transmits the monthly report identified above. "
        "Owner {owner} will circulate final materials by {deadline}. "
        "Reporting fee: ${amount:,.2f}."
    ),
}


def draft(record: NormalizedRecord, escalate: bool = False) -> WorkerDraft:
    """
    Produce the deliverable draft.
    STEP 4 stub: deterministic template fill. Records the model tier that
    WOULD have been used so cost/router logs still look sane end-to-end.
    """
    t0 = time.perf_counter()

    model = MODELS[1] if escalate else MODELS[0]  # gpt-4o if escalated, else mini
    category = record.category or "REPORT"        # normalizer guarantees valid category if we reach here
    body = _TEMPLATES.get(category, _TEMPLATES["REPORT"]).format(
        owner=record.owner or "(unassigned)",
        deadline=record.deadline or "(no deadline)",
        amount=float(record.amount or 0.0),
    )
    title = f"{category.title()} — {record.id}"

    delivered_fields = {
        "record_id": record.id,
        "engagement_type": category,
        "title": title,
        "body": body,
        "amount": float(record.amount or 0.0),
        "owner": record.owner or "",
        "deadline": record.deadline or "",
        "requires_compliance_review": float(record.amount or 0.0) >= 18000.0,
    }

    latency_ms = (time.perf_counter() - t0) * 1000
    # deterministic pseudo-costs so aggregate math works before Step 6
    tokens_in = 200 + len(record.notes or "") // 4
    tokens_out = 120
    cost_usd = (0.0022 if escalate else 0.00019)   # matches gpt-4o vs mini rough cost

    return WorkerDraft(
        record_id=record.id,
        engagement_type=category,
        title=title,
        body=body,
        fields=delivered_fields,
        model_used=model,
        prompt_version=PROMPT_VERSION,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        retries=0,
        abstained=False,
        abstain_reason=None,
    )