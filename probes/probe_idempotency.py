"""
probe-idempotency — prove that running the pipeline twice does NOT produce duplicates.

Strategy:
  1) Run pipeline. Snapshot delivered record IDs + hashes.
  2) Run pipeline again on the same seed.
  3) Assert the delivered set is IDENTICAL (same IDs, same hashes).
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _snapshot(audit_path: Path) -> tuple[set[str], set[str]]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    delivered_ids = {r["id"] for r in audit["records"] if r["status"] == "delivered"}
    hashes = {r["delivered_fields_hash"] for r in audit["records"]
              if r["status"] == "delivered" and r.get("delivered_fields_hash")}
    return delivered_ids, hashes


def main() -> int:
    out_dir = Path(os.environ.get("OUT_DIR", "out"))
    audit_path = out_dir / "audit.json"

    # --- Run 1 ---
    print("[probe-idempotency] run 1...")
    subprocess.check_call([sys.executable, "-m", "pipeline.run"])
    ids_1, hashes_1 = _snapshot(audit_path)
    print(f"    run 1: delivered={len(ids_1)}  unique_hashes={len(hashes_1)}")

    # --- Run 2 ---
    print("[probe-idempotency] run 2...")
    subprocess.check_call([sys.executable, "-m", "pipeline.run"])
    ids_2, hashes_2 = _snapshot(audit_path)
    print(f"    run 2: delivered={len(ids_2)}  unique_hashes={len(hashes_2)}")

    if ids_1 != ids_2:
        print(f"FAIL: delivered id set differs\n  run1-run2: {ids_1 - ids_2}\n  run2-run1: {ids_2 - ids_1}")
        return 1

    if hashes_1 != hashes_2:
        print("FAIL: delivered_fields_hash set differs — non-deterministic output!")
        return 1

    print("\n✅ probe-idempotency PASSED: two runs produced identical delivered set + hashes")
    return 0


if __name__ == "__main__":
    sys.exit(main())