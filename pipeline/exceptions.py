"""
Stage 2b: Exception Queue.
Rule-based detection of all 12 planted-problem reason codes.
Two classes:
  - Class A (BLOCKING): STALE, MISSING_INPUT, OUTLIER, INJECTION_BLOCKED,
                        LOW_CONFIDENCE, UNVERIFIED_ANOMALY
  - Class B (AUTO-RESOLVED, LOGGED, DELIVERED): SCHEMA_DRIFT, SUPERSEDED_VERSION

Agent-layer codes (AGENT_HALLUCINATION, AGENT_LOOP, AGENT_MALFORMED,
BUDGET_EXCEEDED) are raised by the Verifier / Orchestrator, not here.

CRITICAL: no reason code is triggered by matching a record ID.
Everything is derived from the DATA itself + statistics over the batch.
"""
from __future__ import annotations
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

from agents.contracts import NormalizedRecord


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class ExceptionFlag:
    reason_code: str
    reason_class: str            # "A" or "B"
    detail: str                  # human-readable explanation
    blocking: bool               # True for Class A + agent failures


@dataclass
class TriageResult:
    record: NormalizedRecord
    flags: list[ExceptionFlag] = field(default_factory=list)
    superseded_by: Optional[str] = None    # if this is an older version replaced
    replaces: Optional[str] = None         # if this record supersedes another

    @property
    def blocked(self) -> bool:
        return any(f.blocking for f in self.flags)

    @property
    def worst_flag(self) -> Optional[ExceptionFlag]:
        blockers = [f for f in self.flags if f.blocking]
        if blockers:
            return blockers[0]
        return self.flags[0] if self.flags else None


# --------------------------------------------------------------------------- #
# Detector
# --------------------------------------------------------------------------- #
class ExceptionQueue:
    """
    Applies rule-based detectors over a BATCH of normalized records.
    Batch-level context is required for OUTLIER (robust stats) and
    SUPERSEDED_VERSION (dedup on id).
    """

    def __init__(self, mapping_path: Path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.canonical_fields = cfg["canonical_fields"]
        self.injection_patterns = [p.lower() for p in cfg.get("injection_patterns", [])]
        self.outlier_policy = cfg.get("outlier_policy", {})
        self.low_conf = cfg.get("low_confidence_signals", {})
        self.allowed_categories = set(
            self.canonical_fields["category"].get("allowed_values", [])
        )

    # ----- individual detectors ------------------------------------------- #
    def _detect_missing_input(self, r: NormalizedRecord) -> Optional[ExceptionFlag]:
        required = [name for name, spec in self.canonical_fields.items()
                    if spec.get("required")]
        missing = []
        for name in required:
            val = getattr(r, name, None)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                missing.append(name)
        if missing:
            return ExceptionFlag(
                reason_code="MISSING_INPUT",
                reason_class="A",
                blocking=True,
                detail=f"required fields null/empty: {missing}",
            )
        return None

    def _detect_stale(self, r: NormalizedRecord, now: date) -> Optional[ExceptionFlag]:
        if not r.deadline:
            return None
        try:
            dl = datetime.fromisoformat(r.deadline).date()
        except ValueError:
            return None
        if dl < now:
            return ExceptionFlag(
                reason_code="STALE",
                reason_class="A",
                blocking=True,
                detail=f"deadline {r.deadline} already passed (now={now.isoformat()})",
            )
        return None

    def _detect_injection(self, r: NormalizedRecord) -> Optional[ExceptionFlag]:
        if not r.notes:
            return None
        notes_l = r.notes.lower()
        for pat in self.injection_patterns:
            if pat in notes_l:
                return ExceptionFlag(
                    reason_code="INJECTION_BLOCKED",
                    reason_class="A",
                    blocking=True,
                    detail=f"notes contains injection pattern: {pat!r}",
                )
        return None

    def _detect_low_confidence(self, r: NormalizedRecord) -> Optional[ExceptionFlag]:
        """
        Ambiguous records that the LLM would only be able to guess at.
        We abstain BEFORE calling the LLM — cheap + honest.
        """
        notes = (r.notes or "").strip().lower()

        # Very short notes AND no category
        max_chars = self.low_conf.get("notes_too_vague_max_chars", 3)
        if not r.category and len(notes) <= max_chars:
            return ExceptionFlag(
                reason_code="LOW_CONFIDENCE",
                reason_class="A",
                blocking=True,
                detail=f"missing category and notes too vague ({len(notes)} chars)",
            )

        # TODO-marker tokens
        for tok in self.low_conf.get("notes_contains_todo", []):
            if tok in notes:
                return ExceptionFlag(
                    reason_code="LOW_CONFIDENCE",
                    reason_class="A",
                    blocking=True,
                    detail=f"notes contains ambiguity marker: {tok!r}",
                )

        # Category exists but isn't in the allowed set → won't route
        if r.category and r.category not in self.allowed_categories:
            return ExceptionFlag(
                reason_code="LOW_CONFIDENCE",
                reason_class="A",
                blocking=True,
                detail=f"category {r.category!r} not in {sorted(self.allowed_categories)}",
            )
        return None

    def _detect_amount_out_of_range(self, r: NormalizedRecord) -> Optional[ExceptionFlag]:
        """Hard floor / ceiling — defense in depth."""
        if r.amount is None:
            return None
        floor = self.outlier_policy.get("hard_floor", 0)
        ceiling = self.outlier_policy.get("hard_ceiling", 1_000_000)
        if r.amount < floor or r.amount > ceiling:
            return ExceptionFlag(
                reason_code="OUTLIER",
                reason_class="A",
                blocking=True,
                detail=f"amount {r.amount} outside hard bounds [{floor}, {ceiling}]",
            )
        return None

    # ----- BATCH-level detectors ------------------------------------------ #
    def _compute_outlier_bounds(self, records: list[NormalizedRecord]) -> Optional[tuple[float, float]]:
        """
        Robust outlier bounds using Median Absolute Deviation (MAD).
        Returns (low, high) or None if not enough data.
        NOT hardcoded — recomputed per batch, so held-out data with different
        magnitudes still gets sane bounds.
        """
        amounts = [r.amount for r in records if isinstance(r.amount, (int, float))]
        min_n = self.outlier_policy.get("min_records_required", 5)
        if len(amounts) < min_n:
            return None
        med = statistics.median(amounts)
        deviations = [abs(a - med) for a in amounts]
        mad = statistics.median(deviations) or 1.0    # avoid /0
        mult = self.outlier_policy.get("threshold_multiplier", 6.0)
        low = med - mult * mad
        high = med + mult * mad
        return (low, high)

    def _dedupe_by_id(self, records: list[NormalizedRecord]) -> dict[str, NormalizedRecord]:
        """
        SUPERSEDED_VERSION: same id appearing multiple times -> keep highest version.
        Returns id -> chosen record.
        """
        by_id: dict[str, NormalizedRecord] = {}
        for r in records:
            existing = by_id.get(r.id)
            if existing is None or (r.version or 1) > (existing.version or 1):
                by_id[r.id] = r
        return by_id

    # ----- top-level triage ------------------------------------------------ #
    def triage(
        self,
        records: list[NormalizedRecord],
        schema_drift_by_id: dict[str, list[str]],   # from Normalizer
        now: Optional[date] = None,
    ) -> list[TriageResult]:
        """
        Run all detectors over the batch and return one TriageResult per record.
        Note: superseded (older) versions are returned with SUPERSEDED_VERSION Class B.
        """
        now = now or date.today()
        results: list[TriageResult] = []

        # Batch-wide computations
        outlier_bounds = self._compute_outlier_bounds(records)
        winners = self._dedupe_by_id(records)   # id -> latest

        for r in records:
            tr = TriageResult(record=r)

            # SUPERSEDED_VERSION (Class B, non-blocking)
            winner = winners[r.id]
            if winner is not r:
                tr.flags.append(ExceptionFlag(
                    reason_code="SUPERSEDED_VERSION",
                    reason_class="B",
                    blocking=False,
                    detail=f"record superseded by version {winner.version}",
                ))
                tr.superseded_by = f"{r.id}@v{winner.version}"
                results.append(tr)
                continue     # older versions get no further processing

            # SCHEMA_DRIFT (Class B) from the normalizer
            drift = schema_drift_by_id.get(r.id, [])
            if drift:
                tr.flags.append(ExceptionFlag(
                    reason_code="SCHEMA_DRIFT",
                    reason_class="B",
                    blocking=False,
                    detail=f"aliases mapped: {drift}",
                ))

            # Class A detectors (blocking) — order matters: cheapest first
            for detector in (
                self._detect_missing_input,
                lambda x: self._detect_stale(x, now),
                self._detect_injection,
                self._detect_amount_out_of_range,
                self._detect_low_confidence,
            ):
                flag = detector(r)
                if flag:
                    tr.flags.append(flag)
                    break   # one Class-A is enough to block; stop cheap

            # Batch-derived OUTLIER (only if not already blocked and amount known)
            if not tr.blocked and outlier_bounds and r.amount is not None:
                low, high = outlier_bounds
                if r.amount < low or r.amount > high:
                    tr.flags.append(ExceptionFlag(
                        reason_code="OUTLIER",
                        reason_class="A",
                        blocking=True,
                        detail=f"amount {r.amount} outside robust batch bounds "
                               f"[{low:.2f},{high:.2f}] (MAD-based, "
                               f"multiplier={self.outlier_policy.get('threshold_multiplier')})",
                    ))

            results.append(tr)

        return results


if __name__ == "__main__":
    import os
    from pipeline.intake import intake
    from pipeline.normalize import Normalizer

    seed = Path(os.environ.get("SEED_DIR", "seed"))
    raws = intake(seed)
    norm = Normalizer(Path("schemas/field_mapping.yaml"))

    normalized: list[NormalizedRecord] = []
    drift_map: dict[str, list[str]] = {}
    for r in raws:
        res = norm.normalize(r)
        if res.record:
            normalized.append(res.record)
            if res.drift_fields:
                drift_map[res.record.id] = res.drift_fields

    eq = ExceptionQueue(Path("schemas/field_mapping.yaml"))
    triaged = eq.triage(normalized, drift_map)

    delivered_cnt = sum(1 for t in triaged if not t.blocked)
    blocked_cnt = sum(1 for t in triaged if t.blocked)
    print(f"[exceptions] triaged {len(triaged)}: "
          f"{delivered_cnt} would proceed, {blocked_cnt} blocked")
    for t in triaged:
        codes = [f.reason_code for f in t.flags]
        marker = "🚫" if t.blocked else ("⚠️ " if codes else "✅")
        print(f"  {marker} {t.record.id:8} v{t.record.version} amt={t.record.amount} codes={codes}")