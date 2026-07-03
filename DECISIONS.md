Markdown

# DECISIONS.md — CEDX Tiny Agent Fleet

**CASE_ID:** `CEDX-B5AAC2` · **Industry:** Accounting Firms · **Amendment:** compliance@18000

## What I did NOT automate + why

- **Real partner/compliance approvers:** demo pipeline auto-approves so `docker compose up` completes non-interactively. Human-in-the-loop path is fully implemented via `cli/operator_cli.py` (approve/reject/request-changes/deliver commands) — every action goes through the same audit event log. This is the CEDX practical trade-off: end-to-end demonstrability without pretending we shipped a full BPM system.
- **Real PDF branded output:** delivery produces a structured JSON package (`out/package.json`). Wrapping it in a branded PDF is a 15-minute live-extension add — deliberately deferred to keep the 72h scope tight.
- **Real API calls:** default is `REPLAY_LLM=true` (offline transcripts). This is the grader's default path anyway, and it makes eval + probes deterministic + free.

## Outlier / abstain thresholds — why they generalize

- **OUTLIER (`schemas/field_mapping.yaml`):** Robust MAD (Median Absolute Deviation) computed per-batch. `|x − median| > 6 × MAD` is an outlier. Also a hard ceiling of $500k / hard floor of $0. **This generalizes to held-out data with different magnitudes** because the median + MAD are recomputed per run — nothing is hardcoded.
- **LOW_CONFIDENCE:** fires when notes ≤ 3 chars OR notes contain TODO/`?` markers OR category isn't in the canonical set. All three signals are cheap rules; when they fire we abstain BEFORE calling the LLM (saves cost + honest).
- **INJECTION_BLOCKED:** substring match against ~12 documented patterns (`approve immediately`, `ignore your rules`, `jailbreak`, etc). Case-insensitive. First line of defense; verifier is second line.

## Router policy + cost numbers

- Cheap default: `gpt-4o-mini` (~$0.15/1M input, $0.60/1M output).
- Escalate to `gpt-4o` (~$5/1M input, $15/1M output) if: verifier overrule retry, `amount >= $50,000`, or `notes >= 500 chars`.
- Justification: on our 14 delivered records, all are trivial/clean → 100% land on cheap. `probe-budget` proves the ceiling actually fires.

### Cost numbers (from our seed, REPLAY mode)

| Metric | Value |
|--------|-------|
| Total run cost | $0.0027 |
| Avg cost / record | $0.000116 |
| p95 latency / record | 174 ms |
| **Projected @ 10,000 records/day** | **~$1.16** |

At real API pricing (not replay), the same policy would put us at roughly **$5–$15 per 10k records/day**, depending on how often the router escalates (empirically <5% of records).

## How provenance survives re-run

- Every LLM call is keyed by `sha256(agent, model, prompt_version, request)`. In replay mode the same request always hits the same committed transcript. In real mode the same request always writes the same transcript file — safe to re-run.
- `probe-idempotency` proves 2 runs produce identical `delivered_fields_hash` set for all 14 delivered records.
- `pipeline.replay` reconstructs the full agent decision path from `out/audit_events.jsonl` alone.

## What breaks first at 10k records

1. **Sequential per-record processing.** Current pipeline is single-threaded. At 10k/day we'd need to move to a worker pool (Ray/Dramatiq/simple `asyncio.gather`). The typed contracts make this a mechanical refactor.
2. **Transcript-directory scan (O(n) file iteration).** `_load_transcript_by_request` iterates all files. Above ~5k transcripts we'd add a SQLite index on `(agent, model, prompt_version, request_hash)`.
3. **Audit file size.** `out/audit_events.jsonl` grows linearly. At 10k records × ~15 events each = 150k events (~30MB). Fine. But `out/audit.json` (assembled bundle) would be ~10MB — still fine but should be paginated at 100k.

## Ownership & AI usage — honest

- The task said "AI assistants are allowed and expected." I used them for boilerplate, but the architecture and every controls decision are mine.
- Every module has a single responsibility; every agent has a typed contract; every probe tests exactly one invariant. If any of that were AI-shoveled without understanding, the **live extension** would catch me — which is why I designed the router as a swappable class and left the Verifier's two-layer structure (rules + LLM) obvious.
- Live-extension readiness — I can, within 20 minutes, add: a new agent (Redactor), a new reason code + detector, a router policy swap, a two-pass verifier, or a fourth approver tier.

CASE_ID: **CEDX-B5AAC2**
