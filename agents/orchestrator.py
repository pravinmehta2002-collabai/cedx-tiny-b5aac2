"""
Agent 1: Orchestrator / Planner (rule-based, no LLM).
- Owns the run
- Delegates records to worker or exception queue
- Enforces step + cost budgets
- Handles routing (worker | exception | superseded)

TYPED CONTRACT:
  input:  NormalizedRecord
  output: OrchestratorDecision
  can_call: ["worker_v1", "verifier_v1"]
"""
from __future__ import annotations
from .contracts import NormalizedRecord, OrchestratorDecision

NAME = "orchestrator_v1"
ROLE = "orchestrator"
MODELS: list[str] = []
CAN_CALL = ["worker_v1", "verifier_v1"]
PROMPT_VERSION = "1.0"


def route(record: NormalizedRecord) -> OrchestratorDecision:
    """
    Rule-based routing. Full implementation lands in Step 3.
    For tracer commit we just declare the signature.
    """
    return OrchestratorDecision(record_id=record.id, route="worker")