"""
Agent 3: Verifier / Critic (INDEPENDENT check on Worker output).
- Runs a different prompt + can use a different model
- Catches AGENT_HALLUCINATION, AGENT_MALFORMED, coherence failures
- Can OVERRULE the Worker (produces 'fail' verdict → Orchestrator retries or routes)
- This is the "agent-checks-agent" gate — mandatory per HARD RULES

TYPED CONTRACT:
  input:  (NormalizedRecord, WorkerDraft)
  output: VerifierVerdict
  can_call: []
"""
from __future__ import annotations
from .contracts import NormalizedRecord, WorkerDraft, VerifierVerdict

NAME = "verifier_v1"
ROLE = "verifier"
MODELS = ["gpt-4o-mini"]
CAN_CALL: list[str] = []
PROMPT_VERSION = "1.0"


def verify(record: NormalizedRecord, draft: WorkerDraft) -> VerifierVerdict:
    """
    Independent verification. Full implementation lands in Step 6.
    Tracer stub.
    """
    raise NotImplementedError("Verifier.verify implemented in Step 6")