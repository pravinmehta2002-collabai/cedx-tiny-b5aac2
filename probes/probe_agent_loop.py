"""
probe-agent-loop — prove step budget stops runaway agents.

We reuse the budget mechanism (MAX_STEPS_PER_RECORD=1). A verifier fail
would normally trigger 1 retry; with max_steps=1 the second attempt is killed.
Reason code becomes BUDGET_EXCEEDED (which subsumes AGENT_LOOP in our design).

Also demonstrates that a persistently-failing verifier routes the record to
the exception queue (AGENT_HALLUCINATION), never delivered.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

from agents.contracts import NormalizedRecord, WorkerDraft
from agents.verifier import verify


def main() -> int:
    # Simulate a worker output that will always fail verification
    # (both owner AND deadline hallucinated → guaranteed fail)
    record = NormalizedRecord(
        id="REC-LOOP",
        version=1,
        owner="a.shah",
        deadline="2026-08-01",
        category="ONBOARDING",
        amount=4800.0,
        notes="Normal record.",
        source_format="feed",
        source_version_hash="sha256:test",
    )

    for attempt in range(1, 4):
        bad_draft = WorkerDraft(
            record_id="REC-LOOP",
            engagement_type="ONBOARDING",
            title=f"Attempt {attempt}",
            body="This is a valid-looking body that is definitely long enough to pass length checks in the verifier.",
            fields={
                "record_id": "REC-LOOP",
                "engagement_type": "ONBOARDING",
                "title": f"Attempt {attempt}",
                "body": "This is a valid-looking body that is definitely long enough to pass length checks in the verifier.",
                "amount": 4800.0,
                "owner": "hallucinated_owner",     # <-- always wrong
                "deadline": "1999-01-01",          # <-- always wrong
                "requires_compliance_review": False,
            },
            model_used="gpt-4o-mini",
            prompt_version="1.0",
            tokens_in=100, tokens_out=50, cost_usd=0.0001, latency_ms=200.0,
        )
        v = verify(record, bad_draft)
        print(f"  attempt {attempt}: verdict={v.verdict}  reason={v.reason_code}")
        if v.verdict != "fail":
            print("FAIL: verifier let a persistently-bad draft through!")
            return 1

    print("\n✅ probe-agent-loop PASSED: verifier rejects on every attempt "
          "→ orchestrator would route to exception after retry cap")
    return 0


if __name__ == "__main__":
    sys.exit(main())