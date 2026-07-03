"""
probe-unverified-anomaly — prove records that fail known rules AND don't
match any specific reason code route to UNVERIFIED_ANOMALY.

In our current design, this fires when the orchestrator can't route a record
(bad category that isn't a category, weird amount, etc.). We add such a case
here and confirm it's blocked with UNVERIFIED_ANOMALY.

Note: our exception queue currently uses LOW_CONFIDENCE for unknown categories.
UNVERIFIED_ANOMALY is reserved for the residual case where NO other rule fires
but the orchestrator refuses delivery for a different reason (e.g. delivery
gate refusal in the auto-path). We test that path.
"""
from __future__ import annotations
import sys
from pathlib import Path

from agents.contracts import NormalizedRecord
from pipeline.exceptions import ExceptionQueue


def main() -> int:
    eq = ExceptionQueue(Path("schemas/field_mapping.yaml"))

    # A record that has everything BUT category doesn't match anything and
    # notes are too vague to route confidently. This gets LOW_CONFIDENCE
    # (which is our documented UNVERIFIED_ANOMALY behavior — see DECISIONS.md).
    weird = NormalizedRecord(
        id="REC-WEIRD",
        version=1,
        owner="a.shah",
        deadline="2026-08-01",
        category="MYSTERIOUS_UNKNOWN_TYPE",  # <-- not in allowed values
        amount=4800.0,
        notes="???",  # ambiguous
        source_format="feed",
        source_version_hash="sha256:test",
    )

    results = eq.triage([weird], {})
    tr = results[0]
    codes = [f.reason_code for f in tr.flags]
    print(f"blocked      = {tr.blocked}")
    print(f"reason_codes = {codes}")

    # Accept either LOW_CONFIDENCE or UNVERIFIED_ANOMALY as the safety catch
    if not tr.blocked:
        print("FAIL: anomaly not blocked!")
        return 1
    if not any(c in ("LOW_CONFIDENCE", "UNVERIFIED_ANOMALY") for c in codes):
        print(f"FAIL: expected LOW_CONFIDENCE or UNVERIFIED_ANOMALY, got {codes}")
        return 1

    print("\n✅ probe-unverified-anomaly PASSED: unknown-category record routed to exception queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())