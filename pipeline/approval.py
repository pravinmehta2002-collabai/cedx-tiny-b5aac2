"""
Approval state machine (6 states per audit.schema.json enum).

States:
  draft → in_review → approved → delivered
                    ↘ changes_requested (loops back to draft)
                    ↘ blocked (terminal for exceptions)

Amendment enforcement:
  If amount >= amendment.threshold, delivery is refused UNTIL a second
  approval by amendment.role has been recorded.

Server-side rule (delivery refuses non-approved items):
  attempt_deliver(record) will REJECT unless:
    * last state is 'approved'
    * AND (if amount >= threshold) there is an approval by amendment.role.
  Rejection is itself logged as an event — the audit shows the refusal.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from pipeline.amendment import Amendment
from pipeline.audit import AuditLogger


class State(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    DELIVERED = "delivered"
    BLOCKED = "blocked"


# legal transitions (from -> allowed to)
_ALLOWED = {
    State.DRAFT:              {State.IN_REVIEW, State.BLOCKED},
    State.IN_REVIEW:          {State.APPROVED, State.CHANGES_REQUESTED, State.BLOCKED},
    State.CHANGES_REQUESTED:  {State.DRAFT, State.BLOCKED},
    State.APPROVED:           {State.APPROVED, State.DELIVERED, State.BLOCKED},   # APPROVED->APPROVED for 2nd sign-off
    State.DELIVERED:          set(),
    State.BLOCKED:            set(),
}


@dataclass
class ApprovalRecord:
    """Per-record approval state."""
    record_id: str
    amount: Optional[float]
    state: State = State.DRAFT
    approvals: list[dict] = field(default_factory=list)   # {actor, role, ts, reason}
    trail: list[dict] = field(default_factory=list)       # each transition


class ApprovalMachine:
    """
    Wraps the FSM + amendment enforcement + audit event emission.
    Keep this small: it only knows about states and the amendment rule.
    """

    def __init__(self, logger: AuditLogger, amendment: Amendment):
        self.log = logger
        self.amendment = amendment
        self._by_id: dict[str, ApprovalRecord] = {}

    # ---- create ---------------------------------------------------------- #
    def open(self, record_id: str, amount: Optional[float], actor: str = "worker_v1") -> ApprovalRecord:
        rec = ApprovalRecord(record_id=record_id, amount=amount, state=State.DRAFT)
        self._by_id[record_id] = rec
        self._emit(rec, actor, prev=None, to=State.DRAFT, reason="opened")
        return rec

    # ---- transitions ----------------------------------------------------- #
    def _transition(self, rec: ApprovalRecord, to: State, actor: str, reason: Optional[str] = None):
        if to not in _ALLOWED[rec.state]:
            raise ValueError(
                f"illegal transition for {rec.record_id}: {rec.state.value} -> {to.value}"
            )
        prev = rec.state
        rec.state = to
        self._emit(rec, actor, prev=prev, to=to, reason=reason)

    def submit_for_review(self, rid: str, actor: str = "worker_v1") -> None:
        self._transition(self._by_id[rid], State.IN_REVIEW, actor, "verifier check requested")

    def request_changes(self, rid: str, actor: str, reason: str) -> None:
        self._transition(self._by_id[rid], State.CHANGES_REQUESTED, actor, reason)
        # re-open for another draft round
        self._transition(self._by_id[rid], State.DRAFT, actor, "reopen after changes_requested")

    def approve(self, rid: str, actor: str, role: str, reason: Optional[str] = None) -> None:
        """
        Register an approval by (actor, role). If it's the FIRST approval,
        transition IN_REVIEW -> APPROVED. If we're already APPROVED and this
        is the amendment role for a high-value record, stay APPROVED but
        record the second sign-off in the trail.
        """
        rec = self._by_id[rid]
        rec.approvals.append({"actor": actor, "role": role, "reason": reason})

        if rec.state == State.IN_REVIEW:
            self._transition(rec, State.APPROVED, actor,
                             reason or f"first approval by {role}")
        elif rec.state == State.APPROVED:
            # second approval (typically the amendment role)
            self._transition(rec, State.APPROVED, actor,
                             reason or f"second approval by {role}")
        else:
            raise ValueError(
                f"cannot approve {rid} in state {rec.state.value}"
            )

    def block(self, rid: str, actor: str, reason: str) -> None:
        rec = self._by_id.get(rid) or self.open(rid, amount=None, actor=actor)
        self._transition(rec, State.BLOCKED, actor, reason)

    # ---- amendment gate -------------------------------------------------- #
    def amendment_satisfied(self, rec: ApprovalRecord) -> tuple[bool, str]:
        """Returns (satisfied, explanation)."""
        if not self.amendment.requires_second_approval(rec.amount):
            return True, "amount below threshold; single approval sufficient"

        needed = self.amendment.role
        roles_present = {a["role"] for a in rec.approvals}
        if needed in roles_present:
            return True, f"second approval by {needed} recorded"
        return False, (
            f"amount {rec.amount} >= threshold {self.amendment.threshold}; "
            f"amendment requires additional approval by role={needed}"
        )

    # ---- delivery gate --------------------------------------------------- #
    def attempt_deliver(self, rid: str, actor: str = "delivery_svc") -> tuple[bool, str]:
        """
        Server-side check. Returns (delivered, reason).
        NEVER delivers a non-approved item. Refusal is logged as an event.
        """
        rec = self._by_id.get(rid)
        if rec is None:
            self._emit_refusal(rid, actor, "no approval record exists")
            return False, "no approval record"

        if rec.state != State.APPROVED:
            self._emit_refusal(rid, actor, f"state={rec.state.value}, not approved")
            return False, f"state is {rec.state.value}"

        ok, why = self.amendment_satisfied(rec)
        if not ok:
            self._emit_refusal(rid, actor, why)
            return False, why

        self._transition(rec, State.DELIVERED, actor, "delivery ok")
        return True, "delivered"

    # ---- helpers --------------------------------------------------------- #
    def _emit(self, rec: ApprovalRecord, actor: str, prev: Optional[State], to: State, reason: Optional[str]):
        entry = {
            "from_state": prev.value if prev else None,
            "to_state": to.value,
            "reason": reason,
        }
        rec.trail.append(entry)
        self.log.append(
            actor=actor,
            action="state_transition",
            record_id=rec.record_id,
            payload=entry,
        )

    def _emit_refusal(self, rid: str, actor: str, why: str):
        self.log.append(
            actor=actor,
            action="delivery_refused",
            record_id=rid,
            payload={"reason": why},
        )

    def get(self, rid: str) -> Optional[ApprovalRecord]:
        return self._by_id.get(rid)


# --------------------------------------------------------------------------- #
# smoke test — proves the amendment gate refuses on high-value records
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import os
    from pathlib import Path
    from pipeline.amendment import derive_amendment, print_startup_banner

    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    (out_dir / "audit_events.jsonl").unlink(missing_ok=True)
    (out_dir / "audit.json").unlink(missing_ok=True)

    case_id = os.environ.get("CASE_ID", "CEDX-B5AAC2")
    am = derive_amendment(case_id)
    print_startup_banner(am)

    log = AuditLogger(out_dir, case_id=case_id, pipeline_version="0.2.0-step3")
    log.pipeline_start(seed_dir="seed", amendment=am.to_audit())
    mac = ApprovalMachine(log, am)

    # --- Scenario A: normal record (amount 4800) ---
    print("\n=== Scenario A: amount=4800 (below threshold) ===")
    mac.open("REC-001", amount=4800)
    mac.submit_for_review("REC-001", actor="worker_v1")
    mac.approve("REC-001", actor="partner:j.doe", role="partner", reason="ok")
    ok, why = mac.attempt_deliver("REC-001")
    print(f"delivered? {ok} — {why}")

    # --- Scenario B: high-value record (21500) — single approval only ---
    print("\n=== Scenario B: amount=21500, only partner approval ===")
    mac.open("REC-018", amount=21500)
    mac.submit_for_review("REC-018", actor="worker_v1")
    mac.approve("REC-018", actor="partner:j.doe", role="partner")
    ok, why = mac.attempt_deliver("REC-018")
    print(f"delivered? {ok} — {why}   (expect False, amendment blocks)")

    # --- Scenario C: same record + compliance sign-off ---
    print("\n=== Scenario C: add compliance approval, retry delivery ===")
    mac.approve("REC-018", actor="compliance:sys", role="compliance",
                reason=f"amount>=18000 amendment {case_id}")
    ok, why = mac.attempt_deliver("REC-018")
    print(f"delivered? {ok} — {why}   (expect True)")

    print(f"\nchain valid: {log.verify_chain()}")