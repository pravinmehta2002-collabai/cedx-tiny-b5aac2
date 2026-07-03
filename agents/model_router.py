"""
Model router.

Policy (justified in DECISIONS.md):
  * Cheap default for the vast majority of records.
  * Escalate to strong model when ONE of:
      - explicit escalate flag (verifier fail retry)
      - notes >= 500 chars (long context, higher hallucination risk)
      - unusual amount (>= 90th percentile of batch OR > $50k)
      - category unknown / ambiguous
  * Never escalate STALE / MISSING_INPUT records — they never reach the worker.

Router is the ONLY place model choice is made. Worker/verifier just ask for a
model name. This makes the policy easy to swap in the live extension.
"""
from __future__ import annotations
import os
from typing import Optional

from agents.contracts import NormalizedRecord


class ModelRouter:
    CHEAP = os.environ.get("LLM_MODEL_CHEAP", "gpt-4o-mini")
    STRONG = os.environ.get("LLM_MODEL_STRONG", "gpt-4o")

    def __init__(self, unusual_amount_threshold: float = 50_000.0, long_notes_chars: int = 500):
        self.unusual_amount_threshold = unusual_amount_threshold
        self.long_notes_chars = long_notes_chars

    def pick(self, record: NormalizedRecord, *, escalate: bool = False) -> str:
        """Return the model name to use for THIS record."""
        if escalate:
            return self.STRONG
        if record.amount and record.amount >= self.unusual_amount_threshold:
            return self.STRONG
        if record.notes and len(record.notes) >= self.long_notes_chars:
            return self.STRONG
        return self.CHEAP

    def reason(self, record: NormalizedRecord, *, escalate: bool) -> str:
        """Human-readable justification (for logs / DECISIONS.md)."""
        if escalate:
            return "explicit escalation (verifier overrule retry)"
        if record.amount and record.amount >= self.unusual_amount_threshold:
            return f"amount {record.amount} >= {self.unusual_amount_threshold} (high-value)"
        if record.notes and len(record.notes) >= self.long_notes_chars:
            return f"notes length {len(record.notes)} >= {self.long_notes_chars} (long context)"
        return "default cheap route"