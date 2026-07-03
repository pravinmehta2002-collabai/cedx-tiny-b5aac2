"""
probe-append-only — prove the audit log is tamper-evident.

Strategy:
  1) Run pipeline (or use existing log).
  2) Mutate the first event line in-place.
  3) verify_chain() must return False.

Exit 0 = tampering detected. Exit 1 = tampering NOT detected.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

from pipeline.audit import AuditLogger


def main() -> int:
    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    events_path = out_dir / "audit_events.jsonl"

    # Ensure we have some events — if empty, run the pipeline first
    if not events_path.exists() or events_path.stat().st_size == 0:
        print("[probe-append-only] no audit log; running pipeline first")
        subprocess.check_call([sys.executable, "-m", "pipeline.run"])

    case_id = os.environ.get("CASE_ID", "CEDX-B5AAC2")
    log = AuditLogger(out_dir, case_id=case_id, pipeline_version="probe-append-only")

    ok_before = log.verify_chain()
    print(f"chain valid BEFORE mutation: {ok_before}")
    if not ok_before:
        print("FAIL: chain was already broken before probe ran")
        return 1

    # Mutate first line
    data = events_path.read_text(encoding="utf-8").splitlines()
    if not data:
        print("FAIL: no events to mutate")
        return 1
    tampered = data[0].replace("pipeline", "TAMPERED", 1)
    events_path.write_text("\n".join([tampered] + data[1:]) + "\n", encoding="utf-8")

    ok_after = log.verify_chain()
    print(f"chain valid AFTER mutation : {ok_after}")

    if ok_after:
        print("FAIL: tamper was NOT detected — audit is not append-only!")
        return 1

    print("\n✅ probe-append-only PASSED: tamper detected by hash chain")
    return 0


if __name__ == "__main__":
    sys.exit(main())