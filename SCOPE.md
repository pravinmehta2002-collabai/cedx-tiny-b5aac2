# SCOPE.md — Tiny CEDX Agent Fleet

## Identity
- **CASE_ID:** `CEDX-B5AAC2`
- **Candidate:** pravin singh mehta
- **Kickoff:** 2026-07-01
- **Deadline:** 72h from kickoff

## Industry & Tier
- **Industry:** Accounting Firms
- **Tier:** Tier 2 — High-Value Professional Services
- **Reference workflow:** https://cedxsystems.com/workflows (Accounting Firms)

## Live Amendment (CASE_ID-bound)
Derived from CASE_ID `CEDX-B5AAC2`:
- **Approver role (second gate):** `compliance`
- **Threshold:** `18000`
- **Rule:** Any record where normalized `amount >= 18000` requires an
  additional `compliance` officer approval, in addition to the normal
  Partner approval, before delivery.

Startup will print:

AMENDMENT: role=compliance threshold=18000

## Agent Topology (planned)
Minimum roster (≥3 agents, typed contracts, real handoffs):

| Agent | Role | Model(s) | Can call |
|---|---|---|---|
| `orchestrator_v1` | orchestrator | none (rule-based) | `worker_v1`, `verifier_v1` |
| `worker_v1` | worker | cheap default (gpt-4o-mini class) + escalation (gpt-4o class) | — |
| `verifier_v1` | verifier | cheap (gpt-4o-mini class) | — |

Optional 4th agent (for live-extension readiness): `redactor_v1` (PII stripping).

## 5 Governed Stages
1. **Intake** — parse `seed/feed.json` + `seed/inbox/*.pdf` + `seed/inbox/*.eml`
2. **Orchestration** — declarative normalize + exception queue (12 reason codes)
3. **Assembly** — Worker drafts accounting engagement deliverable via model router
4. **Review** — Verifier overrules Worker; state machine + amendment approval chain
5. **Delivery** — branded package + append-only `out/audit.json` with agent traces

## Deliverable Framing
For each valid engagement record, produce a **branded accounting engagement package**:
- ONBOARDING → new-client engagement letter draft
- RENEWAL → annual renewal confirmation
- REVIEW → quarterly review memo cover
- REPORT → monthly report cover memo

## Planted-Problem Handling (data + agent layer)
Detected via rules + LLM-abstain (no hardcoded IDs):
- Data: STALE, MISSING_INPUT, OUTLIER, INJECTION_BLOCKED, LOW_CONFIDENCE, UNVERIFIED_ANOMALY
- Agent: AGENT_HALLUCINATION, AGENT_LOOP, AGENT_MALFORMED, BUDGET_EXCEEDED
- Auto-resolved (Class B): SCHEMA_DRIFT, SUPERSEDED_VERSION

## Run Contract
- Single command: `docker compose up` (or `make demo`)
- Default: `REPLAY_LLM=true` — 100% offline, uses committed `/transcripts/*.json`
- Real path: `REPLAY_LLM=false` with `LLM_API_KEY` env var
- Writes: `out/package.json`, `out/audit.json`, `out/exceptions.json`

## Repo Layout (see ARCHITECTURE.md for details)

agents/ one file per agent (typed contracts in contracts.py)
pipeline/ intake, normalize, exceptions, approval, delivery, audit, replay
schemas/ versioned output schema + field mapping (declarative)
operator/ CLI (approve/reject/edit/request-changes)
eval/ ≥10 golden cases + LLM-judge per agent
probes/ one script per Makefile probe
transcripts/ committed LLM replays (offline mode)
seed/ DO NOT EDIT — canonical input
out/ runtime artifacts (package + audit + exceptions)

## Signed-off scope (locks the tracer bullet)
-  Multi-agent fleet with real Verifier overrule path
-  Amendment: compliance @ 18000
-  Full 12-reason-code exception queue
-  Append-only audit + agent_trace + cost accounting
-  Model router (cheap default + escalation)
-  REPLAY_LLM=true default (offline grading)
-  All 10 Makefile probes
-  3–5 min narrated Loom

CASE_ID: CEDX-B5AAC2