Markdown

# ARCHITECTURE.md — CEDX Tiny Agent Fleet

**CASE_ID:** `CEDX-B5AAC2`  
**Industry:** Accounting Firms (Tier 2)  
**Amendment:** `role=compliance threshold=18000`

## Agent topology
text

    ┌──────────────────────────────────────────┐
    │  Orchestrator (agents/orchestrator.py)   │
    │  role=orchestrator                       │
    │  models=[] (rule-based, no LLM)          │
    │  can_call=["worker_v1","verifier_v1"]    │
    │  - triage routing                        │
    │  - per-record cost/step/latency budget   │
    │  - verifier overrule → escalate retry    │
    │  - approval FSM driver                   │
    └────────────┬──────────────┬──────────────┘
                 │              │
         ┌───────▼───────┐  ┌──▼────────────────┐
         │  Worker       │  │  Verifier          │
         │  (worker.py)  │  │  (verifier.py)     │
         │  role=worker  │  │  role=verifier     │
         │  models=      │  │  models=           │
         │   [mini,4o]   │  │   [mini]           │
         │  can_call=[]  │  │  can_call=[]       │
         │  - drafts     │  │  - rule checks     │
         │    deliverable│  │  - LLM cross-check │
         │  - via router │  │  - can OVERRULE    │
         └───────┬───────┘  └──────────┬─────────┘
                 │                     │
                 └─────────┬───────────┘
                           │
                ┌──────────▼───────────┐
                │ ApprovalMachine      │
                │ (pipeline/approval)  │
                │ 6-state FSM +        │
                │ amendment gate       │
                │ (compliance@18000)   │
                └──────────┬───────────┘
                           │
                ┌──────────▼───────────┐
                │ AuditLogger          │
                │ (append-only JSONL   │
                │ + hash chain)        │
                └──────────────────────┘
text


## Typed contracts (`agents/contracts.py`)

| Handoff | Input | Output |
|---------|-------|--------|
| Intake → Orchestrator | `RawRecord` | — |
| Normalize → Orchestrator | `NormalizedRecord` | — |
| Orchestrator → Worker | `NormalizedRecord + escalate:bool` | `WorkerDraft` |
| Worker → Verifier | `(NormalizedRecord, WorkerDraft)` | `VerifierVerdict` |
| Verifier → Orchestrator | `VerifierVerdict` | (routes to retry / approve / block) |
| Orchestrator → ApprovalMachine | `record_id + amount` | `State transition` |
| ApprovalMachine → Delivery | approved state + amendment satisfied | branded package |
| Delivery → AuditBundle | `RecordOutcome` | `out/audit.json` |

All schemas are Pydantic models — see [`agents/contracts.py`](agents/contracts.py).

## Verifier OVERRULE flow
Worker.draft(record) → WorkerDraft
│
▼
Verifier.verify(record, draft)
│
verdict == "fail"?
│
├── attempt < MAX_ATTEMPTS ──► escalate=True → Worker retries with STRONG model
│
└── attempt == MAX_ATTEMPTS ──► route to exception queue (AGENT_HALLUCINATION/MALFORMED)
record NOT delivered
approval trail: draft → in_review → blocked

text


## Budget / router decision points

- **Model router** (`agents/model_router.py`): cheap default (gpt-4o-mini), escalate to strong (gpt-4o) if:
  - `escalate=True` (verifier fail retry)
  - `amount >= $50,000` (high-value)
  - `notes >= 500 chars` (long-context risk)
- **Per-record budget** (`agents/orchestrator.py`, `Budget` dataclass): `max_cost_usd=0.05`, `max_steps=6`, `max_latency_ms=15000`. Exceeded → `BUDGET_EXCEEDED` reason code.

## Amendment enforcement

- **Derived from CASE_ID `CEDX-B5AAC2`** per TASK.md Step 8 formula: `role=compliance, threshold=18000`.
- **Startup banner:** `AMENDMENT: role=compliance threshold=18000`.
- **Server-side gate:** `ApprovalMachine.attempt_deliver()` REFUSES delivery if `amount >= 18000` and no `compliance` approval has been recorded. Refusal logged as `delivery_refused` event.
- **Auto-run:** demo pipeline auto-approves both partner AND compliance for delivery flow; operator CLI is available for manual mode.

## Audit backbone

- **Append-only JSONL:** `out/audit_events.jsonl` — one event per line, monotonic `seq`, `prev_hash` + `hash` chain.
- **Chain verification:** `AuditLogger.verify_chain()` recomputes every hash — tamper detected instantly.
- **Final bundle:** `out/audit.json` assembled by folding events. Passes `audit.schema.json` + `verify_audit.py` all 15 checks.
- **Per-record `agent_trace`:** ordered spans of every agent action with model, tokens, cost, latency, status, verdict.

## Where each file lives

| Layer | Files |
|-------|-------|
| Agents | `agents/{orchestrator,worker,verifier}.py`, `agents/contracts.py`, `agents/model_router.py`, `agents/llm_client.py`, `agents/prompts.py` |
| Pipeline | `pipeline/{intake,normalize,exceptions,approval,amendment,audit,delivery,replay,run}.py` |
| Data schemas | `schemas/{field_mapping.yaml,output_v1.json}` |
| Operator | `cli/operator_cli.py` |
| Probes | `probes/probe_*.py` (9 probes) |
| Eval | `eval/{golden_cases.json,judge.py,run_eval.py}` |
| Transcripts | `transcripts/*.json` (offline replay) |
| Docker | `Dockerfile`, `docker-compose.yml`, `Makefile` |

CASE_ID: **CEDX-B5AAC2**