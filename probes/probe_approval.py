"""
probe-approval — prove the delivery gate refuses non-approved items.

Two scenarios:
  A) Draft record → try to deliver WITHOUT approval → must be refused.
  B) High-value record ($21,500) → partner-only approval → still refused
     because amendment requires compliance sign-off.

Exit 0 = both refusals happened AND were logged.
Exit 1 = anything got delivered that shouldn't have.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

from pipeline.amendment import derive_amendment, print_startup_banner
from pipeline.approval import ApprovalMachine
from pipeline.audit import AuditLogger


def main() -> int:
    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    (out_dir / "audit_events.jsonl").unlink(missing_ok=True)

    case_id = os.environ.get("CASE_ID", "CEDX-B5AAC2")
    am = derive_amendment(case_id)
    print_startup_banner(am)

    log = AuditLogger(out_dir, case_id=case_id, pipeline_version="probe-approval")
    log.pipeline_start(seed_dir="probe", amendment=am.to_audit())
    mac = ApprovalMachine(log, am)

    # --- Scenario A: no approval at all ---
    print("\n[A] draft record, no approval → attempt deliver")
    mac.open("REC-A", amount=4800)
    ok_a, why_a = mac.attempt_deliver("REC-A")
    print(f"    delivered={ok_a}  reason={why_a}")
    if ok_a:
        print("FAIL: delivered without approval!")
        return 1

    # --- Scenario B: high-value with only partner approval ---
    print("\n[B] amount=21500, only partner-role approval → attempt deliver")
    mac.open("REC-B", amount=21500)
    mac.submit_for_review("REC-B", actor="worker_v1")
    mac.approve("REC-B", actor="partner:test", role="partner", reason="partner ok")
    ok_b, why_b = mac.attempt_deliver("REC-B")
    print(f"    delivered={ok_b}  reason={why_b}")
    if ok_b:
        print(f"FAIL: high-value record delivered without {am.role} approval!")
        return 1

    # --- Scenario C: add compliance approval, retry deliver → must succeed ---
    print(f"\n[C] add {am.role} approval → attempt deliver")
    mac.approve("REC-B", actor=f"{am.role}:test", role=am.role,
                reason=f"amendment {case_id}")
    ok_c, why_c = mac.attempt_deliver("REC-B")
    print(f"    delivered={ok_c}  reason={why_c}")
    if not ok_c:
        print("FAIL: compliance-approved high-value record was refused!")
        return 1

    # --- Verify refusal events were logged ---
    events = log.read_all()
    refusals = [e for e in events if e.get("action") == "delivery_refused"]
    print(f"\n[audit] delivery_refused events logged: {len(refusals)}")
    if len(refusals) < 2:
        print("FAIL: refusals not properly logged")
        return 1

    print("\n✅ probe-approval PASSED: gate correctly refused non-approved deliveries")
    return 0


if __name__ == "__main__":
    sys.exit(main())