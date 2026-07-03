"""
Stage 2a: Normalize.
Uses schemas/field_mapping.yaml (declarative) to translate any inbound field
name into the canonical shape. Emits (NormalizedRecord, list[str] drift_notes).

If a source uses 'amt' instead of 'amount', we map it AND caller logs SCHEMA_DRIFT.
This is what lets the pipeline survive held-out data with renamed fields.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from agents.contracts import NormalizedRecord
from pipeline.intake import RawRecord


@dataclass
class NormalizationResult:
    record: Optional[NormalizedRecord]      # None if id is missing (unrecoverable)
    drift_fields: list[str]                 # names that were aliased -> canonical
    dropped_fields: list[str]               # names not in any alias set (ignored)
    original_payload: dict[str, Any]        # for debugging / audit


class Normalizer:
    def __init__(self, mapping_path: Path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.canonical_fields: dict[str, dict] = cfg["canonical_fields"]
        # Build alias -> canonical index
        self._alias_index: dict[str, str] = {}
        for canonical, spec in self.canonical_fields.items():
            for alias in spec.get("aliases", []):
                self._alias_index[alias.lower()] = canonical

    def normalize(self, raw: RawRecord) -> NormalizationResult:
        canonical_dict: dict[str, Any] = {}
        drift: list[str] = []
        dropped: list[str] = []

        for key, val in raw.payload.items():
            k = str(key).strip().lower()
            canonical = self._alias_index.get(k)
            if canonical is None:
                dropped.append(key)
                continue
            # Flag drift: alias present that isn't the canonical name itself
            if k != canonical:
                drift.append(f"{key}->{canonical}")
            canonical_dict[canonical] = val

        # Apply defaults for optional fields
        for name, spec in self.canonical_fields.items():
            if name not in canonical_dict and "default" in spec:
                canonical_dict[name] = spec["default"]

        # Uppercase category if present
        if isinstance(canonical_dict.get("category"), str):
            canonical_dict["category"] = canonical_dict["category"].strip().upper()

        # Coerce version to int
        if "version" in canonical_dict:
            try:
                canonical_dict["version"] = int(canonical_dict["version"])
            except (ValueError, TypeError):
                canonical_dict["version"] = 1

        # Coerce amount to float
        if "amount" in canonical_dict and canonical_dict["amount"] is not None:
            try:
                canonical_dict["amount"] = float(canonical_dict["amount"])
            except (ValueError, TypeError):
                canonical_dict["amount"] = None

        # Must have an id at minimum to be routable
        if not canonical_dict.get("id"):
            return NormalizationResult(
                record=None,
                drift_fields=drift,
                dropped_fields=dropped,
                original_payload=raw.payload,
            )

        record = NormalizedRecord(
            id=str(canonical_dict["id"]),
            version=canonical_dict.get("version", 1),
            owner=canonical_dict.get("owner"),
            deadline=str(canonical_dict["deadline"]) if canonical_dict.get("deadline") is not None else None,
            category=canonical_dict.get("category"),
            amount=canonical_dict.get("amount"),
            notes=canonical_dict.get("notes", ""),
            source_format=raw.source_format,   # type: ignore[arg-type]
            source_version_hash=raw.source_version_hash,
        )
        return NormalizationResult(
            record=record,
            drift_fields=drift,
            dropped_fields=dropped,
            original_payload=raw.payload,
        )


if __name__ == "__main__":
    import os
    from pipeline.intake import intake
    seed = Path(os.environ.get("SEED_DIR", "seed"))
    n = Normalizer(Path("schemas/field_mapping.yaml"))
    raws = intake(seed)
    print(f"[normalize] {len(raws)} raw records")
    for r in raws:
        res = n.normalize(r)
        drift = f" DRIFT={res.drift_fields}" if res.drift_fields else ""
        if res.record:
            print(f"  {res.record.id:8} {r.source_format:4} amount={res.record.amount} cat={res.record.category}{drift}")
        else:
            print(f"  <no-id> {r.source_format:4} payload={r.original_payload}{drift}")