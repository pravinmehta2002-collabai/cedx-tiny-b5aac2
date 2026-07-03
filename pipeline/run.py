"""
Top-level pipeline runner.
Wires: intake -> normalize -> exceptions -> orchestrator -> delivery -> audit bundle.

One command:
    python -m pipeline.run

Environment:
    CASE_ID              (default CEDX-B5AAC2)
    SEED_DIR             (default seed)
    OUT_DIR              (default out)
    PIPELINE_VERSION     (default 0.4.0-step4)
    REPLAY_LLM           (default true — used in Step 6)
    MAX_COST_USD_PER_RECORD, MAX_STEPS_PER_RECORD, MAX_LATENCY_MS_PER_RECORD
"""
from __future__ import annotations
import json
import os
import statistics
from pathlib import Path

from agents import ROSTER
from agents.orchestrator import Orchestrator, Budget, RecordOutcome
from pipeline.amendment import derive_amendment, print_startup_banner
from pipeline.approval import ApprovalMachine
from pipeline.audit import AuditBundle, AuditLogger
from pipeline.delivery import build_package
from pipeline.exceptions import ExceptionQueue
from pipeline.intake import intake
from pipeline.normalize import Normalizer


def _cost_summary(outcomes: list[RecordOutcome]) -> dict:
    latencies = [o.total_latency_ms for o in outcomes if o.total_latency_ms > 0]
    costs = [o.total_cost_usd for o in outcomes]
    total = sum(costs)
    n = len(outcomes) or 1
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else (max(latencies) if latencies else 0.0)
    return {
        "total_usd": round(total, 6),
        "avg_usd_per_record": round(total / n, 6),
        "p95_latency_ms": round(p95, 2),
        "records": n,
        "projected_usd_per_10k": round((total / n) * 10_000, 4),
    }


def main() -> int:
    seed_dir = Path(os.environ.get("SEED_DIR", "seed"))
    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    case_id = os.environ.get("CASE_ID", "CEDX-B5AAC2")
    pipeline_version = os.environ.get("PIPELINE_VERSION", "0.4.0-step4")
    replay_llm = os.environ.get("REPLAY_LLM", "true").lower() == "true"

    out_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency: fresh audit log on every full run (probe-idempotency uses
    # a separate mechanism — this is the *demo* run).
    (out_dir / "audit_events.jsonl").unlink(missing_ok=True)
    (out_dir / "audit.json").unlink(missing_ok=True)
    (out_dir / "package.json").unlink(missing_ok=True)
    (out_dir / "exceptions.json").unlink(missing_ok=True)

    # --- amendment ---
    am = derive_amendment(case_id)
    print_startup_banner(am)
    print(f"[run] case_id={case_id} pipeline={pipeline_version} seed={seed_dir} out={out_dir}")
    print(f"[run] REPLAY_LLM={replay_llm}  (LLM calls wired in Step 6)")

    # --- audit backbone ---
    log = AuditLogger(out_dir, case_id=case_id, pipeline_version=pipeline_version)
    log.pipeline_start(seed_dir=str(seed_dir), amendment=am.to_audit())

    # --- stage 1: intake ---
    raws = intake(seed_dir)
    print(f"[run] intake: {len(raws)} raw records")

    # --- stage 2a: normalize (declarative) ---
    norm = Normalizer(Path("schemas/field_mapping.yaml"))
    normalized = []
    drift_by_id: dict[str, list[str]] = {}
    for raw in raws:
        res = norm.normalize(raw)
        if res.record is None:
            # unrecoverable (no id) — log and skip; not counted as a record
            log.append(
                actor="intake",
                action="record_exception",
                record_id=None,
                payload={
                    "reason_code": "MISSING_INPUT",
                    "reason_class": "A",
                    "detail": f"cannot normalize: no id (source={raw.source_format})",
                },
            )
            continue
        normalized.append(res.record)
        if res.drift_fields:
            drift_by_id[res.record.id] = res.drift_fields
    print(f"[run] normalized: {len(normalized)} records "
          f"({sum(1 for v in drift_by_id.values() if v)} with schema drift)")

    # --- stage 2b: exception queue ---
    eq = ExceptionQueue(Path("schemas/field_mapping.yaml"))
    triaged = eq.triage(normalized, drift_by_id)
    n_block = sum(1 for t in triaged if t.blocked)
    print(f"[run] triaged: {len(triaged)} records, {n_block} blocked")

    # --- stage 3-4: orchestrator drives worker + verifier + approval ---
    approvals = ApprovalMachine(log, am)
    orch = Orchestrator(log, approvals, Budget())
    outcomes = orch.process(triaged)

    delivered = [o for o in outcomes if o.status == "delivered"]
    exceptions = [o for o in outcomes if o.status == "exception"]
    superseded = [o for o in outcomes if o.status == "superseded"]
    print(f"[run] outcomes: delivered={len(delivered)} exception={len(exceptions)} superseded={len(superseded)}")

    # --- stage 5: delivery package ---
    package = build_package(delivered, case_id=case_id, pipeline_version=pipeline_version)
    (out_dir / "package.json").write_text(
        json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    (out_dir / "exceptions.json").write_text(
        json.dumps(
            [
                {
                    "id": o.record_id,
                    "reason_code": o.reason_code,
                    "reason_class": o.reason_class,
                }
                for o in exceptions
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- final audit bundle ---
    cost = _cost_summary(outcomes)
    log.pipeline_end({
        "delivered": len(delivered),
        "exception": len(exceptions),
        "superseded": len(superseded),
        "cost_total_usd": cost["total_usd"],
    })
    bundle = AuditBundle(log, ROSTER, am.to_audit(), seed_dir=str(seed_dir))
    audit_path = bundle.write(cost_summary=cost, output_package=package)

    # --- summary ---
    print(f"\n[run] ✅ wrote {audit_path}")
    print(f"[run] ✅ wrote {out_dir / 'package.json'} ({len(delivered)} items)")
    print(f"[run] ✅ wrote {out_dir / 'exceptions.json'} ({len(exceptions)} items)")
    print(f"[run] cost: total=${cost['total_usd']:.4f}  "
          f"avg=${cost['avg_usd_per_record']:.6f}  "
          f"p95_ms={cost['p95_latency_ms']:.1f}  "
          f"@10k=${cost['projected_usd_per_10k']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())