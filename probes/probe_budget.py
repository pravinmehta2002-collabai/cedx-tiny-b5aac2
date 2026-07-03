"""
probe-budget — prove per-record cost/step budget triggers BUDGET_EXCEEDED.

Strategy:
  Set MAX_COST_USD_PER_RECORD to something absurdly small (e.g. $0.00001)
  Run the orchestrator on one clean record → worker draft exceeds budget →
  orchestrator raises BUDGET_EXCEEDED and blocks the record.

Exit 0 = record shows BUDGET_EXCEEDED and is NOT delivered.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

from agents.orchestrator import Orchestrator, Budget
from pipeline.amendment import derive_amendment
from pipeline.approval import ApprovalMachine
from pipeline.audit import AuditLogger
from pipeline.exceptions import ExceptionQueue
from pipeline.intake import intake
from pipeline.normalize import Normalizer


def main() -> int:
    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    (out_dir / "audit_events.jsonl").unlink(missing_ok=True)

    case_id = os.environ.get("CASE_ID", "CEDX-B5AAC2")
    am = derive_amendment(case_id)

    # Load first clean record from seed
    raws = intake(Path("seed"))
    norm = Normalizer(Path("schemas/field_mapping.yaml"))
    normalized, drift = [], {}
    for raw in raws:
        r = norm.normalize(raw)
        if r.record:
            normalized.append(r.record)
            if r.drift_fields:
                drift[r.record.id] = r.drift_fields

    eq = ExceptionQueue(Path("schemas/field_mapping.yaml"))
    triaged = eq.triage(normalized, drift)
    clean = [t for t in triaged if not t.blocked and not t.superseded_by]
    if not clean:
        print("FAIL: no clean records in seed to test budget on")
        return 1

    # Take only ONE clean record and starve the budget
    target = clean[0]
    print(f"[probe-budget] targeting {target.record.id} with cost ceiling $0.00001")

    log = AuditLogger(out_dir, case_id=case_id, pipeline_version="probe-budget")
    log.pipeline_start(seed_dir="probe", amendment=am.to_audit())
    approvals = ApprovalMachine(log, am)
    starved = Budget(max_cost_usd=0.00001, max_steps=1, max_latency_ms=100.0)
    orch = Orchestrator(log, approvals, budget=starved)

    outcomes = orch.process([target])
    oc = outcomes[0]
    print(f"    status      = {oc.status}")
    print(f"    reason_code = {oc.reason_code}")

    if oc.status == "delivered":
        print("FAIL: record delivered despite budget ceiling")
        return 1
    if oc.reason_code != "BUDGET_EXCEEDED":
        print(f"FAIL: expected BUDGET_EXCEEDED, got {oc.reason_code}")
        return 1

    # Verify audit event was emitted
    events = log.read_all()
    exc_events = [e for e in events if e.get("action") == "record_exception"
                  and (e.get("payload") or {}).get("reason_code") == "BUDGET_EXCEEDED"]
    if not exc_events:
        print("FAIL: no BUDGET_EXCEEDED event in audit log")
        return 1

    print("\n✅ probe-budget PASSED: BUDGET_EXCEEDED raised + logged, record NOT delivered")
    return 0


if __name__ == "__main__":
    sys.exit(main())