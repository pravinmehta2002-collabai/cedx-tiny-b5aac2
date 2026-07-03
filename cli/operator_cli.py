"""
Operator surface (CLI).

TASK.md requires a human-in-the-loop review path. Every action logged
with actor + timestamp + before/after (where applicable).

Usage:
    python -m operator.cli approve         --id REC-018 --actor partner:j.doe --role partner
    python -m operator.cli approve         --id REC-018 --actor compliance:e.reyes --role compliance --reason "amend CEDX-B5AAC2"
    python -m operator.cli reject          --id REC-014 --actor partner:j.doe --reason "missing owner"
    python -m operator.cli request-changes --id REC-007 --actor senior:m.khan --reason "wrong deadline in draft"
    python -m operator.cli deliver         --id REC-001 --actor delivery_svc
    python -m operator.cli show            --id REC-018

Amendment is loaded from CASE_ID env var. All events go to the same
append-only log the pipeline uses, so operator actions are indistinguishable
from pipeline actions at the audit layer.

NOTE: this CLI operates on the LIVE audit log; it does NOT rebuild the
approval-machine state across process boundaries. In Step 4 we wire the
orchestrator to bootstrap the machine from the event log at startup.
For now, it's usable inside a single-process run (e.g. probe scripts).
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from pipeline.amendment import derive_amendment, print_startup_banner
from pipeline.approval import ApprovalMachine
from pipeline.audit import AuditLogger


def _build_machine() -> tuple[ApprovalMachine, AuditLogger]:
    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    case_id = os.environ.get("CASE_ID", "CEDX-B5AAC2")
    log = AuditLogger(out_dir, case_id=case_id, pipeline_version=os.environ.get("PIPELINE_VERSION", "0.2.0-step3"))
    am = derive_amendment(case_id)
    return ApprovalMachine(log, am), log


def _replay_state_for(rid: str, mac: ApprovalMachine, log: AuditLogger):
    """
    Rebuild in-memory approval state for a single record from the event log.
    This is what enables cross-process CLI usage.
    """
    from pipeline.approval import State
    events = [e for e in log.read_all() if e.get("record_id") == rid]
    if not events:
        return None

    # Try to find amount from an earlier state_transition or ingest
    amount = None
    for ev in events:
        payload = ev.get("payload") or {}
        if "amount" in payload and payload["amount"] is not None:
            amount = payload["amount"]
            break

    # Fresh record
    rec = mac.open(rid, amount=amount, actor="operator_cli")   # emits DRAFT event
    # Now replay approvals + transitions from history
    for ev in events:
        action = ev.get("action")
        payload = ev.get("payload") or {}
        actor = ev.get("actor", "unknown")
        if action == "state_transition":
            to = payload.get("to_state")
            if to == "in_review":
                try: mac.submit_for_review(rid, actor=actor)
                except Exception: pass
            elif to == "approved":
                mac.approve(rid, actor=actor, role=payload.get("role", "partner"),
                            reason=payload.get("reason"))
    return rec


def cmd_show(args, mac, log):
    events = [e for e in log.read_all() if e.get("record_id") == args.id]
    print(f"=== events for {args.id} ({len(events)}) ===")
    for e in events:
        print(json.dumps(e, indent=2))


def cmd_approve(args, mac, log):
    _replay_state_for(args.id, mac, log)
    mac.approve(args.id, actor=args.actor, role=args.role, reason=args.reason)
    print(f"approved: {args.id} by {args.actor} ({args.role})")


def cmd_reject(args, mac, log):
    _replay_state_for(args.id, mac, log)
    mac.block(args.id, actor=args.actor, reason=args.reason)
    print(f"rejected/blocked: {args.id} by {args.actor} — {args.reason}")


def cmd_request_changes(args, mac, log):
    _replay_state_for(args.id, mac, log)
    mac.request_changes(args.id, actor=args.actor, reason=args.reason)
    print(f"changes requested: {args.id} by {args.actor} — {args.reason}")


def cmd_deliver(args, mac, log):
    _replay_state_for(args.id, mac, log)
    ok, why = mac.attempt_deliver(args.id, actor=args.actor)
    print(f"deliver: ok={ok} reason={why}")


def main():
    ap = argparse.ArgumentParser(prog="operator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("approve", "reject", "request-changes", "deliver", "show"):
        sp = sub.add_parser(name)
        sp.add_argument("--id", required=True)
        if name != "show":
            sp.add_argument("--actor", required=True)
        if name in ("approve",):
            sp.add_argument("--role", required=True,
                            choices=["partner", "senior", "manager",
                                     "risk_officer", "legal_counsel",
                                     "compliance", "finance_controller"])
            sp.add_argument("--reason", default=None)
        if name in ("reject", "request-changes"):
            sp.add_argument("--reason", required=True)

    args = ap.parse_args()
    mac, log = _build_machine()
    print_startup_banner(mac.amendment)

    dispatch = {
        "approve": cmd_approve,
        "reject": cmd_reject,
        "request-changes": cmd_request_changes,
        "deliver": cmd_deliver,
        "show": cmd_show,
    }
    dispatch[args.cmd](args, mac, log)


if __name__ == "__main__":
    main()