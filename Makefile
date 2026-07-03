# ---------------------------------------------------------------------------
# CEDX Tiny Agent Fleet — Makefile
# CASE_ID: CEDX-B5AAC2
# ---------------------------------------------------------------------------
.PHONY: help demo verify trace replay eval seed-transcripts clean clean-transcripts \
        tracer-check \
        probe-approval probe-agent-failure probe-agent-malformed probe-agent-loop \
        probe-budget probe-append-only probe-idempotency probe-injection \
        probe-unverified-anomaly probe-crash probes-all all

# --- default target ------------------------------------------------------- #
help:
	@echo "CEDX Tiny Agent Fleet — CASE_ID CEDX-B5AAC2"
	@echo ""
	@echo "  make demo                     Full fleet run on \$$SEED_DIR"
	@echo "  make verify                   Run verify_audit.py on out/audit.json"
	@echo "  make trace ID=REC-001         Print agent decision path for one record"
	@echo "  make replay ID=REC-001        Same as trace (lineage from log alone)"
	@echo "  make eval                     Run agent eval harness (10 golden cases)"
	@echo "  make seed-transcripts         Generate offline transcripts (one-time)"
	@echo "  make clean                    Wipe out/*"
	@echo "  make clean-transcripts        Wipe transcripts/*.json"
	@echo ""
	@echo "  make probe-approval           Try to deliver a non-approved item"
	@echo "  make probe-agent-failure      Feed hallucinated worker output"
	@echo "  make probe-agent-malformed    Feed malformed worker output"
	@echo "  make probe-agent-loop         Persistent verifier fail -> retry cap"
	@echo "  make probe-budget             Feed a record that busts cost ceiling"
	@echo "  make probe-append-only        Try to mutate a past audit entry"
	@echo "  make probe-idempotency        Run demo twice, check no duplicates"
	@echo "  make probe-injection          Feed a prompt-injection record"
	@echo "  make probe-unverified-anomaly Feed an unknown-category record"
	@echo "  make probes-all               Run every probe"
	@echo ""
	@echo "  make all                      demo + verify + probes-all + eval"
	@echo "  make tracer-check             Sanity-check the scaffold"

# --- core pipeline -------------------------------------------------------- #
demo:
	@python -m pipeline.run

verify:
	@python verify_audit.py --audit out/audit.json --transcripts transcripts --schema audit.schema.json

trace:
	@python -m pipeline.replay $(ID)

replay:
	@python -m pipeline.replay $(ID)

eval:
	@python -m eval.run_eval

seed-transcripts:
	@python -m scripts.generate_transcripts

# --- cleanup -------------------------------------------------------------- #
clean:
	@python -c "from pathlib import Path; [p.unlink() for p in Path('out').glob('*') if p.name != '.gitkeep']"
	@echo "cleaned out/"

clean-transcripts:
	@python -c "from pathlib import Path; [p.unlink() for p in Path('transcripts').glob('*.json')]"
	@echo "cleaned transcripts/"

# --- probes --------------------------------------------------------------- #
probe-approval:
	@python -m probes.probe_approval

probe-agent-failure:
	@python -m probes.probe_agent_failure

probe-agent-malformed:
	@python -m probes.probe_agent_malformed

probe-agent-loop:
	@python -m probes.probe_agent_loop

probe-budget:
	@python -m probes.probe_budget

probe-append-only:
	@python -m probes.probe_append_only

probe-idempotency:
	@python -m probes.probe_idempotency

probe-injection:
	@python -m probes.probe_injection

probe-unverified-anomaly:
	@python -m probes.probe_unverified_anomaly

probe-crash:
	@echo "probe-crash: bonus — not implemented (see DECISIONS.md)"

probes-all: probe-approval probe-agent-failure probe-agent-malformed \
            probe-agent-loop probe-budget probe-append-only \
            probe-idempotency probe-injection probe-unverified-anomaly
	@echo ""
	@echo "ALL PROBES PASSED"

# --- aggregate ------------------------------------------------------------ #
all: demo verify probes-all eval
	@echo ""
	@echo "EVERYTHING PASSED"

# --- tracer bullet sanity check (kept for CEDX kickoff evidence) ---------- #
tracer-check:
	@echo "[tracer-check] Verifying scaffold..."
	@test -f SCOPE.md && echo "  OK SCOPE.md"
	@test -f Dockerfile && echo "  OK Dockerfile"
	@test -f docker-compose.yml && echo "  OK docker-compose.yml"
	@test -f agents/orchestrator.py && echo "  OK agents/orchestrator.py"
	@test -f agents/worker.py && echo "  OK agents/worker.py"
	@test -f agents/verifier.py && echo "  OK agents/verifier.py"
	@test -f audit.schema.json && echo "  OK audit.schema.json"
	@test -f verify_audit.py && echo "  OK verify_audit.py"
	@python -c "from agents import ROSTER; assert len(ROSTER) >= 3; print(f'  OK agent roster has {len(ROSTER)} agents')"
	@echo "[tracer-check] OK — CASE_ID CEDX-B5AAC2"