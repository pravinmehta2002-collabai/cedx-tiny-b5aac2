# CEDX Tiny Agent Fleet — `CEDX-B5AAC2`

## Overview

This project implements a deterministic multi-agent workflow for accounting engagement processing.

The pipeline ingests accounting engagement records from JSON feeds and PDF/EML documents, normalizes and validates the data, generates branded client deliverables through an AI worker, verifies every output using an independent verifier agent, and records every decision in an append-only audit trail.

The default execution mode is fully offline using replayed LLM transcripts, enabling deterministic grading without requiring API access.

---

# 1. Industry & Scope

**Industry:** Accounting Firms (Tier 2 – High-Value Professional Services)

**CASE_ID:** `CEDX-B5AAC2`

This project processes accounting engagement records from multiple input sources and produces complete engagement packages.

### Supported Inputs

- JSON engagement feed
- PDF documents
- EML email inbox

### Supported Deliverables

- Engagement Letter (**ONBOARDING**)
- Renewal Confirmation (**RENEWAL**)
- Review Memo (**REVIEW**)
- Monthly Report Memo (**REPORT**)

Each engagement package passes through normalization, validation, AI drafting, verification, approval, delivery, and audit logging.

---

# 2. Repository Structure

```
agents/
    orchestrator.py
    worker.py
    verifier.py
    contracts.py

pipeline/
schemas/
scripts/
seed/
transcripts/
probes/
eval/
out/

ARCHITECTURE.md
DECISIONS.md
audit.schema.json
verify_audit.py
docker-compose.yml
```

---

# 3. Agent Topology

See **ARCHITECTURE.md** for the complete architecture.

| Agent | Role | Models | Can Call |
|-------|------|--------|----------|
| `orchestrator_v1` | Rule-based orchestration | Rule Engine | worker_v1, verifier_v1 |
| `worker_v1` | Draft generation | GPT-4o Mini / GPT-4o (API Mode) | — |
| `verifier_v1` | Independent verification | GPT-4o Mini | — |

### Agent Responsibilities

### Orchestrator

- Routes records
- Manages retries
- Enforces approval gates
- Applies budget limits
- Writes audit events

### Worker

- Creates engagement deliverables
- Generates structured outputs
- Uses replay transcripts (default)
- Supports live LLM mode

### Verifier

- Cross-checks worker output
- Detects hallucinations
- Detects malformed responses
- Blocks unverified deliveries

Contracts are defined in:

```
agents/contracts.py
```

---

# 4. How to Run

## Docker (Recommended)

```bash
docker compose up --build
```

## Local

```bash
pip install -r requirements.txt

python -m scripts.generate_transcripts

python -m pipeline.run

python verify_audit.py \
    --audit out/audit.json \
    --transcripts transcripts \
    --schema audit.schema.json
```

### Default Configuration

```
REPLAY_LLM=true
SEED_DIR=seed
OUT_DIR=out
CASE_ID=CEDX-B5AAC2
```

The default configuration runs completely offline using replay transcripts.

No API key is required unless:

```
REPLAY_LLM=false
```

---

# 5. Controls (Probe Suite)

Run individual probes:

```bash
python -m probes.probe_approval
python -m probes.probe_agent_failure
python -m probes.probe_agent_malformed
python -m probes.probe_agent_loop
python -m probes.probe_budget
python -m probes.probe_append_only
python -m probes.probe_idempotency
python -m probes.probe_injection
python -m probes.probe_unverified_anomaly
```

### Expected Result

All nine probes complete successfully (exit code 0).

The probes validate:

- Approval gating
- Agent hallucination detection
- Malformed output detection
- Retry limits
- Budget enforcement
- Append-only audit integrity
- Idempotent execution
- Prompt injection blocking
- Delivery refusal for unknown anomalies

---

# 6. Exception Detection & Handling

Detection is data-driven.

No record IDs are hardcoded.

Field aliases are maintained declaratively in:

```
schemas/field_mapping.yaml
```

| Class | Reason Code | Detection Method |
|--------|-------------|------------------|
| A | STALE | Deadline earlier than today |
| A | MISSING_INPUT | Required field missing or empty |
| A | OUTLIER | Robust MAD (per batch) or hard bounds |
| A | INJECTION_BLOCKED | Prompt-injection pattern matching |
| A | LOW_CONFIDENCE | TODO markers, vague notes, unknown categories |
| A | UNVERIFIED_ANOMALY | Catch-all routing failure |
| A | AGENT_HALLUCINATION | Verifier detects field mismatch |
| A | AGENT_MALFORMED | Verifier detects invalid structure |
| A | AGENT_LOOP | Retry limit exceeded |
| A | BUDGET_EXCEEDED | Cost or step ceiling exceeded |
| B | SCHEMA_DRIFT | Alias mapped to canonical field |
| B | SUPERSEDED_VERSION | Duplicate engagement version detected |

---

# 7. Generalization

Detection logic is data-driven rather than record-specific.

Features include:

- Declarative field alias mapping
- Per-batch outlier recomputation
- Automatic schema normalization
- Held-out field renaming support
- No record-specific rules

Example:

```
amt
```

is automatically normalized to

```
amount
```

and logged as:

```
SCHEMA_DRIFT
```

---

# 8. LLM Contract & Evaluation

## Replay Mode (Default)

```
REPLAY_LLM=true
```

Runs entirely offline using stored transcripts.

Provides:

- Deterministic execution
- Repeatable grading
- No API cost

---

## Live LLM Mode

```
REPLAY_LLM=false
```

Supports live inference using:

- OpenAI
- Groq

Requires:

```
LLM_API_KEY
```

Each request records a transcript containing:

- Agent
- Model
- Prompt version
- Request
- Response
- Response hash
- Delivered fields hash
- Tokens in
- Tokens out
- Cost (USD)
- Latency (ms)

Every load-bearing delivery references a worker transcript.

The audit verifier checks transcript integrity.

---

## Evaluation Harness

Run:

```bash
python -m eval.run_eval
```

Includes:

- 10 golden evaluation cases
- Per-agent scoring
- Deterministic replay

---

# 9. Cost & Scale

See **DECISIONS.md** for the complete analysis.

Measured/Estimated summary:

| Metric | Value |
|---------|-------|
| Average cost per record | ~$0.000116 |
| p95 latency | ~174 ms |
| Replay mode | No API cost |
| Estimated API cost (10,000 records/day) | ~$5–15/day |

Replay mode remains the default execution path for deterministic grading.

---

# 10. CASE_ID Amendment

Derived from:

```
CEDX-B5AAC2
```

Amendment:

```
role = compliance
threshold = 18000
```

Any engagement with:

```
amount >= 18000
```

requires:

- Standard partner approval
- Additional compliance approval

before delivery.

The approval probe verifies both successful approval and refusal paths.

---

# 11. AI Usage

This project was developed with AI-assisted coding tools (Cursor and Claude) for implementation support.

The system architecture, orchestration flow, control logic, evaluation strategy, probe design, and project integration were designed and assembled by me.

I can explain, modify, and extend every major component during the live review.

---

# 12. Design Tradeoffs & Future Work

## Current Implementation

- Offline replay mode
- Multi-agent orchestration
- Independent verifier agent
- Rule-based anomaly detection
- Append-only audit trail
- Nine probe tests
- Evaluation harness
- Deterministic execution

## Planned Improvements

- Parallel worker pool
- Branded PDF generation
- Database-backed transcript index
- Dedicated PII redaction agent
- Audit dashboards
- Queue-based execution
- Metrics and monitoring
- Horizontal worker scaling

---

# Project Summary

This project demonstrates a production-oriented, deterministic multi-agent workflow for accounting engagement processing.

Key capabilities include:

- Multi-agent orchestration
- AI-assisted document generation
- Independent verification
- Approval workflows
- Schema normalization
- Exception handling
- Prompt injection protection
- Budget enforcement
- Replayable LLM execution
- Append-only audit logging
- Deterministic evaluation
- Comprehensive probe suite
