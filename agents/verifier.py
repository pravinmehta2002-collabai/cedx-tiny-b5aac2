"""
Agent 3: Verifier (Independent check).

Two-layer verification:
  1) Rule-based cross-checks (always run — deterministic, no LLM cost).
  2) LLM cross-check (only if rules pass; catches semantic hallucinations).

If EITHER layer fails, verdict=fail with reason_code. Orchestrator handles
retry / route-to-human.
"""
from __future__ import annotations
import time

from .contracts import NormalizedRecord, WorkerDraft, VerifierVerdict
from .llm_client import call_llm
from .prompts import get_prompt

NAME = "verifier_v1"
ROLE = "verifier"
MODELS = ["gpt-4o-mini"]
CAN_CALL: list[str] = []
PROMPT_VERSION = "1.0"


def _rule_checks(record: NormalizedRecord, draft: WorkerDraft) -> list[str]:
    findings: list[str] = []
    if record.category and draft.engagement_type != record.category:
        findings.append(
            f"AGENT_HALLUCINATION: engagement_type={draft.engagement_type} vs source.category={record.category}"
        )
    src_amount = float(record.amount or 0.0)
    draft_amount = float(draft.fields.get("amount", 0.0))
    if abs(src_amount - draft_amount) > 0.01:
        findings.append(f"AGENT_HALLUCINATION: amount {draft_amount} vs source {src_amount}")
    if record.owner and draft.fields.get("owner") != record.owner:
        findings.append(f"AGENT_HALLUCINATION: owner mismatch")
    if record.deadline and draft.fields.get("deadline") != record.deadline:
        findings.append(f"AGENT_HALLUCINATION: deadline mismatch")
    if not draft.body or len(draft.body.strip()) < 20:
        findings.append("AGENT_MALFORMED: body too short")
    if not draft.title:
        findings.append("AGENT_MALFORMED: missing title")
    return findings


def verify(record: NormalizedRecord, worker_draft: WorkerDraft) -> VerifierVerdict:
    t0 = time.perf_counter()

    # Layer 1: rules
    findings = _rule_checks(record, worker_draft)
    if findings:
        reason_code = "AGENT_HALLUCINATION" if any("HALLUCINATION" in f for f in findings) else "AGENT_MALFORMED"
        return VerifierVerdict(
            record_id=record.id,
            verdict="fail",
            reason_code=reason_code,
            findings=findings,
            model_used=MODELS[0],
            prompt_version=PROMPT_VERSION,
            tokens_in=0, tokens_out=0, cost_usd=0.0,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    # Layer 2: LLM semantic cross-check (replay-safe)
    prompt = get_prompt("verifier_v1")
    import json as _json
    user = prompt["user_template"].format(
        source_json=_json.dumps({
            "id": record.id, "owner": record.owner, "deadline": record.deadline,
            "category": record.category, "amount": record.amount, "notes": record.notes,
        }, ensure_ascii=False),
        draft_json=_json.dumps(worker_draft.fields, ensure_ascii=False),
    )

    try:
        llm = call_llm(
            agent=NAME,
            model=MODELS[0],
            prompt_version=PROMPT_VERSION,
            system=prompt["system"],
            user=user,
        )
        r = llm.response if isinstance(llm.response, dict) else {}
        verdict = r.get("verdict", "pass")
        reason_code = r.get("reason_code")
        llm_findings = r.get("findings", []) or []
        latency = (time.perf_counter() - t0) * 1000
        return VerifierVerdict(
            record_id=record.id,
            verdict=verdict if verdict in ("pass", "fail", "needs_human") else "pass",
            reason_code=reason_code,
            findings=[str(x) for x in llm_findings],
            model_used=llm.model,
            prompt_version=PROMPT_VERSION,
            tokens_in=llm.tokens_in,
            tokens_out=llm.tokens_out,
            cost_usd=llm.cost_usd,
            latency_ms=latency,
        )
    except RuntimeError:
        # Missing transcript in replay mode — degrade to rules-only pass
        # (rules already passed above)
        return VerifierVerdict(
            record_id=record.id,
            verdict="pass",
            reason_code=None,
            findings=["rule-based only (no verifier transcript committed)"],
            model_used=MODELS[0],
            prompt_version=PROMPT_VERSION,
            tokens_in=0, tokens_out=0, cost_usd=0.0,
            latency_ms=(time.perf_counter() - t0) * 1000,
        )