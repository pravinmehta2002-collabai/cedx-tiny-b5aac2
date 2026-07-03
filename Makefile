# ---------------------------------------------------------------------------
# CEDX Tiny Agent Fleet — probe surface (thin over the fleet)
# CASE_ID: CEDX-B5AAC2
# ---------------------------------------------------------------------------
.PHONY: help demo verify trace eval replay \
        probe-approval probe-agent-failure probe-budget \
        probe-append-only probe-idempotency probe-crash \
        clean tracer-check

help:
	@echo "CEDX Tiny Agent Fleet — CASE_ID CEDX-B5AAC2"
	@echo ""
	@echo "  make demo                   Full fleet run (REPLAY_LLM=true) on \$$SEED_DIR"
	@echo "  make verify                 Run verify_audit.py on out/audit.json"
	@echo "  make trace ID=REC-001       Print agent decision path for one record"
	@echo "  make replay ID=REC-001      Reconstruct output lineage from log alone"
	@echo "  make eval                   Run agent eval harness (>=10 golden cases)"
	@echo ""
	@echo "  make probe-approval         Try to deliver a non-approved item"
	@echo "  make probe-agent-failure    Feed hallucinated worker output"
	@echo "  make probe-budget           Feed a record that busts cost/step ceiling"
	@echo "  make probe-append-only      Try to mutate a past audit entry"
	@echo "  make probe-idempotency      Run demo twice, check no duplicates"
	@echo "  make probe-crash            SIGKILL between stages, verify resume"
	@echo ""
	@echo "  make tracer-check           Sanity-check the tracer bullet scaffold"

demo:
	@python -m pipeline.run

verify:
	@python verify_audit.py --audit out/audit.json --transcripts transcripts --schema audit.schema.json

trace:
	@python -m pipeline.replay $(ID)

seed-transcripts:
	@python -m scripts.generate_transcripts

clean:
	@python -c "from pathlib import Path; [p.unlink() for p in Path('out').glob('*') if p.name != '.gitkeep']"
	@echo "cleaned out/"

clean-transcripts:
	@python -c "from pathlib import Path; [p.unlink() for p in Path('transcripts').glob('*.json')]"
	@echo "cleaned transcripts/"

probe-append-only:
	@echo "[probe-append-only] verifying hash chain rejects mutation..."
	@python -c "from pipeline.audit import AuditLogger; \
from pathlib import Path; \
import os; \
log = AuditLogger(Path(os.environ.get('OUT_DIR','out')), 'CEDX-B5AAC2', '0.2.0-step3'); \
print('chain valid before mutation:', log.verify_chain()); \
p = log.events_path; \
data = p.read_text(encoding='utf-8').splitlines(); \
tampered = data[0].replace('pipeline','TAMPERED') if data else ''; \
p.write_text('\\n'.join([tampered] + data[1:]) + '\\n', encoding='utf-8') if data else None; \
ok = log.verify_chain(); \
print('chain valid after mutation :', ok); \
import sys; sys.exit(0 if not ok else 1)"

verify:
	python verify_audit.py --audit out/audit.json --transcripts transcripts --schema audit.schema.json

trace:
	@echo "trace ID=$(ID) — implemented in Step 4"

replay:
	@echo "replay ID=$(ID) — implemented in Step 5"

eval:
	@echo "eval harness — implemented in Step 9"

probe-approval:
	@echo "probe-approval — implemented in Step 8"

probe-agent-failure:
	@echo "probe-agent-failure — implemented in Step 8"

probe-budget:
	@echo "probe-budget — implemented in Step 8"

probe-append-only:
	@echo "probe-append-only — implemented in Step 8"

probe-idempotency:
	@echo "probe-idempotency — implemented in Step 8"

probe-crash:
	@echo "probe-crash — implemented in Step 8"

tracer-check:
	@echo "[tracer-check] Verifying scaffold..."
	@test -f SCOPE.md && echo "  ✓ SCOPE.md"
	@test -f Dockerfile && echo "  ✓ Dockerfile"
	@test -f docker-compose.yml && echo "  ✓ docker-compose.yml"
	@test -f agents/orchestrator.py && echo "  ✓ agents/orchestrator.py"
	@test -f agents/worker.py && echo "  ✓ agents/worker.py"
	@test -f agents/verifier.py && echo "  ✓ agents/verifier.py"
	@test -f audit.schema.json && echo "  ✓ audit.schema.json"
	@test -f verify_audit.py && echo "  ✓ verify_audit.py"
	@python -c "from agents import ROSTER; assert len(ROSTER) >= 3; print(f'  ✓ agent roster has {len(ROSTER)} agents')"
	@echo "[tracer-check] OK — CASE_ID CEDX-B5AAC2 tracer bullet ready"

clean:
	rm -rf out/*.json out/*.pdf __pycache__ */__pycache__ */*/__pycache__
	touch out/.gitkeep