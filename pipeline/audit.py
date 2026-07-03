"""
Append-only audit backbone.

We keep two artifacts:

  1. `out/audit_events.jsonl` — the LIVE append-only event log.
     One JSON object per line, monotonic `seq`, and each event has
     `prev_hash` + `hash` forming a tamper-evident chain.
     `probe-append-only` verifies mutation is rejected.

  2. `out/audit.json` — the FINAL assembled bundle written at end-of-run.
     Conforms to `audit.schema.json`. This is what `verify_audit.py`
     reads at grading time.

Design rules:
  * Never mutate a written line.
  * `seq` is 0, 1, 2, ... strictly.
  * The final bundle re-derives its `records[]` view by folding events,
    so events are the single source of truth.
"""
from __future__ import annotations
import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bytes(obj: Any) -> bytes:
    """Deterministic bytes for hashing — matches verify_audit.canon()."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_of(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


# --------------------------------------------------------------------------- #
# Append-only event log
# --------------------------------------------------------------------------- #
class AuditLogger:
    """
    Thread-safe append-only writer for out/audit_events.jsonl.
    Idempotency: if the file already exists we resume seq counter from its length,
    so `docker compose up` twice does NOT create duplicate seqs.
    """

    def __init__(self, out_dir: Path, case_id: str, pipeline_version: str):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.out_dir / "audit_events.jsonl"
        self.case_id = case_id
        self.pipeline_version = pipeline_version
        self._lock = threading.Lock()
        self._seq, self._prev_hash = self._resume_state()

    # ---- resume / init --------------------------------------------------- #
    def _resume_state(self) -> tuple[int, str]:
        """Read existing file (if any) to continue seq + hash-chain."""
        if not self.events_path.exists():
            return 0, "sha256:" + "0" * 64
        seq = 0
        prev_hash = "sha256:" + "0" * 64
        with self.events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    seq = int(obj.get("seq", seq)) + 1
                    prev_hash = obj.get("hash", prev_hash)
                except json.JSONDecodeError:
                    continue
        return seq, prev_hash

    # ---- append ---------------------------------------------------------- #
    def append(
        self,
        actor: str,
        action: str,
        record_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> dict:
        """Append one event; returns the event as written (with seq+hash)."""
        payload = payload or {}
        with self._lock:
            ev = {
                "seq": self._seq,
                "ts": utcnow_iso(),
                "actor": actor,
                "action": action,
                "record_id": record_id,
                "payload": payload,
                "prev_hash": self._prev_hash,
            }
            ev["hash"] = sha256_of({k: ev[k] for k in ev if k != "hash"})
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            self._seq += 1
            self._prev_hash = ev["hash"]
            return ev

    # ---- helpers for common events -------------------------------------- #
    def pipeline_start(self, seed_dir: str, amendment: dict):
        return self.append(
            actor="pipeline",
            action="pipeline_start",
            payload={
                "case_id": self.case_id,
                "pipeline_version": self.pipeline_version,
                "seed_dir": seed_dir,
                "amendment": amendment,
            },
        )

    def pipeline_end(self, summary: dict):
        return self.append(actor="pipeline", action="pipeline_end", payload=summary)

    def read_all(self) -> list[dict]:
        """Return all events (in order). Used for assembly + trace."""
        if not self.events_path.exists():
            return []
        out = []
        with self.events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return out

    # ---- integrity check (used by probe-append-only) -------------------- #
    def verify_chain(self) -> bool:
        """Recompute the hash chain; True iff every prev_hash / hash lines up."""
        prev = "sha256:" + "0" * 64
        for i, ev in enumerate(self.read_all()):
            if ev.get("seq") != i:
                return False
            if ev.get("prev_hash") != prev:
                return False
            body = {k: ev[k] for k in ev if k != "hash"}
            if sha256_of(body) != ev.get("hash"):
                return False
            prev = ev["hash"]
        return True


# --------------------------------------------------------------------------- #
# Final bundle assembler (writes out/audit.json)
# --------------------------------------------------------------------------- #
@dataclass
class RecordView:
    """Per-record fold of events, matching audit.schema.json shape."""
    id: str
    version: int = 1
    source_format: str = "feed"
    source_version_hash: Optional[str] = None
    status: str = "exception"                       # delivered | exception | superseded
    reason_code: Optional[str] = None
    reason_class: Optional[str] = None
    transcript_hash: Optional[str] = None
    delivered_fields: Optional[dict] = None
    delivered_fields_hash: Optional[str] = None
    agent_trace: list[dict] = field(default_factory=list)
    approval_trail: list[dict] = field(default_factory=list)


class AuditBundle:
    """
    Assembles out/audit.json from the event log + agent roster + cost summary.
    Conforms to audit.schema.json.
    """

    def __init__(self, logger: AuditLogger, agents_roster: list[dict], amendment: dict, seed_dir: str):
        self.logger = logger
        self.agents_roster = agents_roster
        self.amendment = amendment
        self.seed_dir = seed_dir

    def _fold_records(self, events: list[dict]) -> dict[str, RecordView]:
        """
        Rebuild record-level state by replaying events.
        This is where 'events are the single source of truth' becomes concrete.
        """
        rv: dict[str, RecordView] = {}

        def get(rid: str) -> RecordView:
            if rid not in rv:
                rv[rid] = RecordView(id=rid)
            return rv[rid]

        for ev in events:
            rid = ev.get("record_id")
            action = ev.get("action", "")
            payload = ev.get("payload", {}) or {}
            actor = ev.get("actor", "")
            ts = ev.get("ts", "")

            if not rid:
                continue
            r = get(rid)

            if action == "record_ingested":
                r.version = payload.get("version", r.version)
                r.source_format = payload.get("source_format", r.source_format)
                r.source_version_hash = payload.get("source_version_hash", r.source_version_hash)

            elif action == "record_exception":
                r.status = "exception"
                r.reason_code = payload.get("reason_code")
                r.reason_class = payload.get("reason_class")
                r.approval_trail.append({
                    "state": "blocked", "actor": actor, "ts": ts,
                    "reason": payload.get("detail"),
                })

            elif action == "record_superseded":
                r.status = "superseded"
                r.reason_code = "SUPERSEDED_VERSION"
                r.reason_class = "B"

            elif action == "agent_span":
                # attach a span to the trace
                span = {k: v for k, v in payload.items() if k != "trace_only"}
                r.agent_trace.append(span)

            elif action == "state_transition":
                r.approval_trail.append({
                    "state": payload.get("to_state"),
                    "actor": actor,
                    "ts": ts,
                    "reason": payload.get("reason"),
                })

            elif action == "record_delivered":
                r.status = "delivered"
                r.delivered_fields = payload.get("delivered_fields")
                r.delivered_fields_hash = payload.get("delivered_fields_hash")
                r.transcript_hash = payload.get("transcript_hash")

        return rv

    def write(
        self,
        cost_summary: dict,
        output_package: dict,
    ) -> Path:
        """
        Write out/audit.json.
        `cost_summary` = {total_usd, avg_usd_per_record, p95_latency_ms, records, projected_usd_per_10k}
        `output_package` = the final delivered package (used to compute output_package_hash)
        """
        events = self.logger.read_all()
        record_views = self._fold_records(events)

        # Build records[] in schema shape
        records_out = []
        for rv in record_views.values():
            records_out.append({
                "id": rv.id,
                "version": rv.version,
                "source_format": rv.source_format,
                "source_version_hash": rv.source_version_hash,
                "status": rv.status,
                "reason_code": rv.reason_code,
                "reason_class": rv.reason_class,
                "transcript_hash": rv.transcript_hash,
                "delivered_fields": rv.delivered_fields,
                "delivered_fields_hash": rv.delivered_fields_hash,
                "agent_trace": rv.agent_trace,
                "approval_trail": rv.approval_trail,
            })

        # Build events[] in schema shape (only what the schema requires)
        events_out = [
            {
                "seq": ev["seq"],
                "ts": ev["ts"],
                "actor": ev["actor"],
                "action": ev["action"],
                "record_id": ev.get("record_id"),
            }
            for ev in events
        ]

        bundle = {
            "case_id": self.logger.case_id,
            "pipeline_version": self.logger.pipeline_version,
            "generated_at": utcnow_iso(),
            "seed_dir": self.seed_dir,
            "amendment": self.amendment,
            "agents": self.agents_roster,
            "cost": cost_summary,
            "output_package_hash": sha256_of(output_package),
            "records": records_out,
            "events": events_out,
        }

        audit_path = self.logger.out_dir / "audit.json"
        audit_path.write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return audit_path


# --------------------------------------------------------------------------- #
# smoke test
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    from pipeline.amendment import derive_amendment, print_startup_banner
    from agents import ROSTER

    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    # Reset for demo
    (out_dir / "audit_events.jsonl").unlink(missing_ok=True)
    (out_dir / "audit.json").unlink(missing_ok=True)

    case_id = os.environ.get("CASE_ID", "CEDX-B5AAC2")
    am = derive_amendment(case_id)
    print_startup_banner(am)

    log = AuditLogger(out_dir, case_id=case_id, pipeline_version="0.2.0-step3")
    log.pipeline_start(seed_dir="seed", amendment=am.to_audit())
    log.append("orchestrator_v1", "record_ingested", "REC-001",
               {"version": 1, "source_format": "feed", "source_version_hash": "sha256:abc"})
    log.append("orchestrator_v1", "record_exception", "REC-014",
               {"reason_code": "MISSING_INPUT", "reason_class": "A", "detail": "owner is null"})
    log.pipeline_end({"processed": 2})

    print(f"\n[audit] events written: {len(log.read_all())}")
    print(f"[audit] chain valid   : {log.verify_chain()}")

    bundle = AuditBundle(log, ROSTER, am.to_audit(), seed_dir="seed")
    path = bundle.write(
        cost_summary={
            "total_usd": 0.0, "avg_usd_per_record": 0.0, "p95_latency_ms": 0,
            "records": 0, "projected_usd_per_10k": 0.0
        },
        output_package={"records": []},
    )
    print(f"[audit] bundle written: {path}")