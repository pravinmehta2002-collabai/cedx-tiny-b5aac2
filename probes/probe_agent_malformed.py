"""
probe-agent-malformed — prove the Verifier catches structurally invalid Worker output.
"""
from __future__ import annotations
import sys

from agents.contracts import NormalizedRecord, WorkerDraft
from agents.verifier import verify


def main() -> int:
    record = NormalizedRecord(
        id="REC-MAL",
        version=1,
        owner="c.nguyen",
        deadline="2026-09-01",
        category="REVIEW",
        amount=4200.0,
        notes="Normal review.",
        source_format="feed",
        source_version_hash="sha256:test",
    )

    malformed = WorkerDraft(
        record_id="REC-MAL",
        engagement_type="REVIEW",
        title="",              # <-- MISSING title
        body="short",          # <-- BODY too short (< 20 chars)
        fields={
            "record_id": "REC-MAL",
            "engagement_type": "REVIEW",
            "title": "",
            "body": "short",
            "amount": 4200.0,
            "owner": "c.nguyen",
            "deadline": "2026-09-01",
            "requires_compliance_review": False,
        },
        model_used="gpt-4o-mini",
        prompt_version="1.0",
        tokens_in=50, tokens_out=10, cost_usd=0.00005, latency_ms=100.0,
    )

    verdict = verify(record, malformed)
    print(f"verdict     = {verdict.verdict}")
    print(f"reason_code = {verdict.reason_code}")
    print(f"findings    = {verdict.findings}")

    if verdict.verdict != "fail":
        print("FAIL: verifier did NOT catch malformed output!")
        return 1
    if verdict.reason_code != "AGENT_MALFORMED":
        print(f"FAIL: expected AGENT_MALFORMED, got {verdict.reason_code}")
        return 1

    print("\n✅ probe-agent-malformed PASSED: Verifier caught malformed Worker output")
    return 0


if __name__ == "__main__":
    sys.exit(main())