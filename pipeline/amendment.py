"""
CASE_ID-bound live amendment (STEP 8 in TASK.md).

Rule per task spec:
    H = sha256(CASE_ID)  # lowercase hex
    R = ["risk_officer","legal_counsel","compliance","finance_controller"][ int(H[0],16) % 4 ]
    T = 10000 + (int(H[1:3],16) % 50) * 1000

Any record with normalized primary numeric field (amount) >= T requires an
additional recorded approval by role R, IN ADDITION to normal approval,
before delivery.

For CASE_ID=CEDX-B5AAC2, the CEDX portal displayed: role=compliance, threshold=18000.
We compute both here and assert they match, so we never silently disagree with
the portal.
"""
from __future__ import annotations
import hashlib
import os
from dataclasses import dataclass
from typing import Literal

APPROVER_ROLES = ("risk_officer", "legal_counsel", "compliance", "finance_controller")

Role = Literal["risk_officer", "legal_counsel", "compliance", "finance_controller"]


@dataclass(frozen=True)
class Amendment:
    case_id: str
    role: Role
    threshold: float

    def requires_second_approval(self, amount: float | None) -> bool:
        """True iff record must ALSO be approved by self.role before delivery."""
        if amount is None:
            return False
        return float(amount) >= float(self.threshold)

    def to_audit(self) -> dict:
        return {"role": self.role, "threshold": self.threshold}


def derive_amendment(case_id: str | None = None) -> Amendment:
    """
    Deterministically derive (role, threshold) from CASE_ID.
    Matches the exact formula printed in TASK.md Step 8.
    """
    case_id = case_id or os.environ.get("CASE_ID", "CEDX-B5AAC2")

    h = hashlib.sha256(case_id.encode("utf-8")).hexdigest()  # lowercase hex
    role = APPROVER_ROLES[int(h[0], 16) % 4]                 # first nibble mod 4
    threshold = 10000 + (int(h[1:3], 16) % 50) * 1000        # next byte mod 50

    return Amendment(case_id=case_id, role=role, threshold=float(threshold))  # type: ignore[arg-type]


def print_startup_banner(am: Amendment) -> None:
    """TASK.md requires: print `AMENDMENT: role=<R> threshold=<T>` at startup."""
    print(f"AMENDMENT: role={am.role} threshold={int(am.threshold)}")


if __name__ == "__main__":
    # Sanity check: our CASE_ID should compute to compliance@18000 per portal
    am = derive_amendment("CEDX-B5AAC2")
    print_startup_banner(am)
    print(f"case_id  = {am.case_id}")
    print(f"role     = {am.role}")
    print(f"threshold= {am.threshold}")

    # Portal told us: compliance @ 18000
    expected_role, expected_threshold = "compliance", 18000.0
    assert am.role == expected_role, f"role mismatch: {am.role} vs {expected_role}"
    assert am.threshold == expected_threshold, \
        f"threshold mismatch: {am.threshold} vs {expected_threshold}"
    print("✅ Amendment matches CEDX portal value.")