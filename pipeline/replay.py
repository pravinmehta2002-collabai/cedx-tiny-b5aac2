"""
Replay / trace utility.

Usage:
    python -m pipeline.replay REC-001

Rebuilds the full decision path for a record from out/audit_events.jsonl
alone — no live state needed. Proves 'reconstruct output lineage from log alone'.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("usage: python -m pipeline.replay <RECORD_ID>")
        sys.exit(2)
    rid = sys.argv[1]
    out = Path(os.environ.get("OUT_DIR", "out"))
    events_path = out / "audit_events.jsonl"
    if not events_path.exists():
        print(f"no event log at {events_path}. Run `python -m pipeline.run` first.")
        sys.exit(1)

    print(f"=== lineage for {rid} ===")
    n = 0
    total_cost = 0.0
    with events_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("record_id") != rid:
                continue
            n += 1
            action = ev.get("action")
            actor = ev.get("actor")
            payload = ev.get("payload", {}) or {}
            marker = "▶"
            if action == "agent_span":
                cost = payload.get("cost_usd", 0.0) or 0.0
                total_cost += cost
                v = f" verdict={payload.get('verdict')}" if payload.get("verdict") else ""
                print(f"{marker} [{ev['seq']:03}] {actor:20} span "
                      f"status={payload.get('status')} model={payload.get('model')} "
                      f"cost=${cost:.6f} lat={payload.get('latency_ms'):.1f}ms{v}")
            elif action == "state_transition":
                print(f"{marker} [{ev['seq']:03}] {actor:20} state -> {payload.get('to_state')} "
                      f"({payload.get('reason','')})")
            elif action == "record_ingested":
                print(f"{marker} [{ev['seq']:03}] {actor:20} ingested "
                      f"src={payload.get('source_format')} amt={payload.get('amount')}")
            elif action == "record_exception":
                print(f"{marker} [{ev['seq']:03}] {actor:20} EXCEPTION "
                      f"{payload.get('reason_code')} ({payload.get('reason_class')}) "
                      f"— {payload.get('detail')}")
            elif action == "record_delivered":
                print(f"{marker} [{ev['seq']:03}] {actor:20} DELIVERED "
                      f"transcript={payload.get('transcript_hash')[:22]}...")
            elif action == "delivery_refused":
                print(f"{marker} [{ev['seq']:03}] {actor:20} DELIVERY REFUSED "
                      f"— {payload.get('reason')}")
            else:
                print(f"{marker} [{ev['seq']:03}] {actor:20} {action}")

    if n == 0:
        print(f"(no events found for {rid})")
        sys.exit(1)
    print(f"\n{n} events, total agent cost=${total_cost:.6f}")


if __name__ == "__main__":
    main()