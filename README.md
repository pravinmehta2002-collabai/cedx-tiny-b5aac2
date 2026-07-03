Markdown

# CEDX Tiny Agent Fleet — `CEDX-B5AAC2`

## 1. Industry & Scope
**Industry:** Accounting Firms (Tier 2 — High-Value Professional Services)  
**CASE_ID:** `CEDX-B5AAC2`

Scope: a small but genuinely-working multi-agent pipeline that ingests accounting engagement records (JSON feed + PDF/EML inbox), normalizes + validates them, drafts branded deliverables, verifies + approves, and delivers with a full append-only audit trail. Deliverable = "engagement package": engagement letter (ONBOARDING), renewal confirmation (RENEWAL), review memo (REVIEW), monthly report memo (REPORT).

## 2. Agent topology
See [ARCHITECTURE.md](ARCHITECTURE.md).

| Agent | Role | Models | Can call |
|-------|------|--------|----------|
| `orchestrator_v1` | orchestrator | (rule-based) | worker_v1, verifier_v1 |
| `worker_v1` | worker | gpt-4o-mini + gpt-4o | — |
| `verifier_v1` | verifier | gpt-4o-mini | — |

Files: `agents/orchestrator.py`, `agents/worker.py`, `agents/verifier.py`, contracts in `agents/contracts.py`.

## 3. How to Run
```bash
# One command (Docker) — grader path
docker compose up --build

# Local (no Docker)
pip install -r requirements.txt
python -m scripts.generate_transcripts     # one-time, generates offline transcripts
python -m pipeline.run                     # full pipeline
python verify_audit.py --audit out/audit.json --transcripts transcripts --schema audit.schema.json
Defaults: REPLAY_LLM=true, SEED_DIR=seed, OUT_DIR=out, CASE_ID=CEDX-B5AAC2.