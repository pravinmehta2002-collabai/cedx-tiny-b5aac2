"""
probe-agent-failure — prove the Verifier catches a hallucinated Worker output.

We construct a NormalizedRecord and a WorkerDraft that intentionally has:
  - amount mismatch (source=5000 vs draft=99999) → AGENT_HALLUCINATION
Verifier.verify() must return verdict='fail' with reason_code='AGENT_HALLUCINATION'.

Exit 0 = verifier caught it AND agent-failure record is NOT delivered.
Exit 1 = verifier let it pass (broken agent-checks-agent gate).
"""
from __future__ import annotations
import sys

from agents.contracts import NormalizedRecord, WorkerDraft
from agents.verifier import verify


def main() -> int:
    record = NormalizedRecord(
        id="REC-EVIL",
        version=1,
        owner="a.shah",
        deadline="2026-08-01",
        category="ONBOARDING",
        amount=5000.0,
        notes="Normal onboarding.",
        source_format="feed",
        source_version_hash="sha256:test",
    )

    # Hallucinated draft: worker "invented" a much larger amount
    hallucinated = WorkerDraft(
        record_id="REC-EVIL",
        engagement_type="ONBOARDING",
        title="Onboarding — REC-EVIL",
        body="This is a well-formed body that is definitely long enough to pass length check.",
        fields={
            "record_id": "REC-EVIL",
            "engagement_type": "ONBOARDING",
            "title": "Onboarding — REC-EVIL",
            "body": "This is a well-formed body that is definitely long enough to pass length check.",
            "amount": 99999.0,          # <-- HALLUCINATION: source was 5000
            "owner": "a.shah",
            "deadline": "2026-08-01",
            "requires_compliance_review": True,
        },
        model_used="gpt-4o-mini",
        prompt_version="1.0",
        tokens_in=100, tokens_out=50, cost_usd=0.0001, latency_ms=200.0,
    )

    verdict = verify(record, hallucinated)
    print(f"verdict     = {verdict.verdict}")
    print(f"reason_code = {verdict.reason_code}")
    print(f"findings    = {verdict.findings}")

    if verdict.verdict != "fail":
        print("FAIL: verifier did NOT catch the hallucination!")
        return 1
    if verdict.reason_code != "AGENT_HALLUCINATION":
        print(f"FAIL: expected AGENT_HALLUCINATION, got {verdict.reason_code}")
        return 1
    if not any("amount" in f.lower() or "hallucination" in f.lower() for f in verdict.findings):
        print("FAIL: verifier verdict lacks a hallucination finding")
        return 1

    print("\n✅ probe-agent-failure PASSED: Verifier caught hallucinated Worker output")
    return 0


if __name__ == "__main__":
    sys.exit(main())