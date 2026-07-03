"""
Agent 3: Verifier (Independent check).
Runs AFTER the Worker. Can OVERRULE the Worker with a fail verdict.

STEP 4: rule-based checks (deterministic cross-checks against source record).
STEP 6: adds LLM-based hallucination detection.

TYPED CONTRACT:
  input:  (NormalizedRecord, WorkerDraft)
  output: VerifierVerdict
  can_call: []
"""
from __future__ import annotations
import time
from .contracts import NormalizedRecord, WorkerDraft, VerifierVerdict

NAME = "verifier_v1"
ROLE = "verifier"
MODELS = ["gpt-4o-mini"]
CAN_CALL: list[str] = []
PROMPT_VERSION = "1.0"


def verify(record: NormalizedRecord, worker_draft: WorkerDraft) -> VerifierVerdict:
    """
    Independent check. Different logic path than the Worker so agreement is
    not just echo. In Step 6 we ALSO add an LLM cross-check.
    """
    t0 = time.perf_counter()
    findings: list[str] = []

    # Check 1: engagement_type in draft must match record.category
    if record.category and worker_draft.engagement_type != record.category:
        findings.append(
            f"AGENT_HALLUCINATION: draft engagement_type={worker_draft.engagement_type} "
            f"but source category={record.category}"
        )

    # Check 2: amount in draft fields must equal source amount (no invented numbers)
    src_amount = float(record.amount or 0.0)
    draft_amount = float(worker_draft.fields.get("amount", 0.0))
    if abs(src_amount - draft_amount) > 0.01:
        findings.append(
            f"AGENT_HALLUCINATION: draft amount={draft_amount} vs source={src_amount}"
        )

    # Check 3: owner and deadline must be preserved verbatim (no fabrication)
    if record.owner and worker_draft.fields.get("owner") != record.owner:
        findings.append(
            f"AGENT_HALLUCINATION: owner mismatch draft={worker_draft.fields.get('owner')!r} "
            f"source={record.owner!r}"
        )
    if record.deadline and worker_draft.fields.get("deadline") != record.deadline:
        findings.append(
            f"AGENT_HALLUCINATION: deadline mismatch draft={worker_draft.fields.get('deadline')!r} "
            f"source={record.deadline!r}"
        )

    # Check 4: structural — body must be non-trivial, title present
    if not worker_draft.body or len(worker_draft.body.strip()) < 20:
        findings.append("AGENT_MALFORMED: body too short or empty")
    if not worker_draft.title:
        findings.append("AGENT_MALFORMED: missing title")

    # Determine verdict + reason_code
    if findings:
        # First finding drives the reason code
        first = findings[0]
        if first.startswith("AGENT_HALLUCINATION"):
            reason_code = "AGENT_HALLUCINATION"
        elif first.startswith("AGENT_MALFORMED"):
            reason_code = "AGENT_MALFORMED"
        else:
            reason_code = "AGENT_MALFORMED"
        verdict = "fail"
    else:
        reason_code = None
        verdict = "pass"

    latency_ms = (time.perf_counter() - t0) * 1000
    # small deterministic cost for the verifier check (cheap model)
    tokens_in = 150
    tokens_out = 30
    cost_usd = 0.00015

    return VerifierVerdict(
        record_id=record.id,
        verdict=verdict,
        reason_code=reason_code,
        findings=findings,
        model_used=MODELS[0],
        prompt_version=PROMPT_VERSION,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )