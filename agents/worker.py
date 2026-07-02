"""
Agent 2: Worker (LLM-heavy Assembly step).
- Drafts the branded accounting engagement deliverable
- Uses model router: cheap by default, escalates on retry/ambiguity
- Enforces structured output + abstain path

TYPED CONTRACT:
  input:  NormalizedRecord
  output: WorkerDraft
  can_call: []   # workers are leaves; only orchestrator calls them
"""
from __future__ import annotations
from .contracts import NormalizedRecord, WorkerDraft

NAME = "worker_v1"
ROLE = "worker"
MODELS = ["gpt-4o-mini", "gpt-4o"]   # cheap default + escalation
CAN_CALL: list[str] = []
PROMPT_VERSION = "1.0"


def draft(record: NormalizedRecord, escalate: bool = False) -> WorkerDraft:
    """
    Draft the deliverable. Full implementation lands in Step 6.
    Tracer stub.
    """
    raise NotImplementedError("Worker.draft implemented in Step 6")