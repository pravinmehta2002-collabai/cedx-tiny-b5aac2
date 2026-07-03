"""
LLM-judge per agent — with deterministic rule-based scoring as the primary
(so eval is reproducible without API cost). The LLM-judge escalation path is
implemented but only fires when REPLAY_LLM=false + LLM_API_KEY is set.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class EvalResult:
    case_id: str
    agent: str
    passed: bool
    detail: str


def judge_orchestrator(case: dict, actual_route: str, actual_reason_code: str | None) -> EvalResult:
    expected_route = case["expected_route"]
    expected_reason = case.get("expected_reason_code")
    ok = (actual_route == expected_route) and (actual_reason_code == expected_reason)
    return EvalResult(
        case_id=case["id"],
        agent="orchestrator",
        passed=ok,
        detail=f"expected route={expected_route} reason={expected_reason}; "
               f"got route={actual_route} reason={actual_reason_code}",
    )


def judge_worker(case: dict, draft_fields: dict) -> EvalResult:
    expected = case["expected_fields"]
    mismatches = []
    for k, v in expected.items():
        if draft_fields.get(k) != v:
            mismatches.append(f"{k}: expected={v} got={draft_fields.get(k)}")
    ok = len(mismatches) == 0
    return EvalResult(
        case_id=case["id"],
        agent="worker",
        passed=ok,
        detail="all fields match" if ok else "; ".join(mismatches),
    )


def judge_verifier(case: dict, actual_verdict: str, actual_reason_code: str | None) -> EvalResult:
    expected_verdict = case["expected_verdict"]
    expected_reason = case.get("expected_reason_code")
    ok = (actual_verdict == expected_verdict) and (actual_reason_code == expected_reason)
    return EvalResult(
        case_id=case["id"],
        agent="verifier",
        passed=ok,
        detail=f"expected verdict={expected_verdict} reason={expected_reason}; "
               f"got verdict={actual_verdict} reason={actual_reason_code}",
    )