"""
Versioned prompts. Single source of truth.

Each prompt has:
  - name (matches agent role)
  - version (e.g. "1.0")
  - system + user template

Templates use {placeholders} — orchestrator fills them.
"""
from __future__ import annotations

WORKER_V1 = {
    "name": "worker",
    "version": "1.0",
    "system": (
        "You are a senior accounting-firm engagement assistant. "
        "You draft short, professional deliverables (letters, cover memos, "
        "review packets) using ONLY the facts provided. "
        "NEVER invent numbers, names, or dates. "
        "If a field is missing, leave a bracketed placeholder like [MISSING]. "
        "Respond in strict JSON matching the requested schema."
    ),
    "user_template": (
        "Draft an accounting engagement deliverable for the following record.\n\n"
        "Record:\n"
        "  id: {id}\n"
        "  owner: {owner}\n"
        "  deadline: {deadline}\n"
        "  category: {category}\n"
        "  amount: {amount}\n"
        "  notes: {notes}\n\n"
        "Category-specific deliverable:\n"
        "  ONBOARDING -> new-client engagement letter\n"
        "  RENEWAL    -> annual renewal confirmation\n"
        "  REVIEW     -> quarterly review memo\n"
        "  REPORT     -> monthly report cover memo\n\n"
        "Return JSON with keys:\n"
        "  {{\n"
        "    \"record_id\": string,\n"
        "    \"engagement_type\": one of [ONBOARDING,RENEWAL,REVIEW,REPORT],\n"
        "    \"title\": string,\n"
        "    \"body\": string (>= 20 chars, professional tone),\n"
        "    \"amount\": number (echo the source amount, do NOT change it),\n"
        "    \"owner\": string (echo source),\n"
        "    \"deadline\": string YYYY-MM-DD (echo source),\n"
        "    \"requires_compliance_review\": true if amount >= 18000 else false\n"
        "  }}"
    ),
}

VERIFIER_V1 = {
    "name": "verifier",
    "version": "1.0",
    "system": (
        "You are an independent accounting-quality reviewer. "
        "Compare a draft deliverable against its source record and detect ANY "
        "invented facts, wrong numbers, wrong dates, category mismatches, "
        "or structural problems. "
        "You have OVERRULE authority. Be strict. Return JSON only."
    ),
    "user_template": (
        "Source record:\n{source_json}\n\n"
        "Draft to review:\n{draft_json}\n\n"
        "Check for:\n"
        "  1. amount mismatch (draft.amount must equal source.amount)\n"
        "  2. owner/deadline echoed verbatim\n"
        "  3. engagement_type matches source.category\n"
        "  4. body has no invented client names, sums, or dates\n"
        "  5. body is professional and >= 20 chars\n\n"
        "Return JSON with keys:\n"
        "  {{\n"
        "    \"verdict\": \"pass\" | \"fail\" | \"needs_human\",\n"
        "    \"reason_code\": null | \"AGENT_HALLUCINATION\" | \"AGENT_MALFORMED\",\n"
        "    \"findings\": [array of short strings]\n"
        "  }}"
    ),
}


PROMPT_REGISTRY = {
    "worker_v1": WORKER_V1,
    "verifier_v1": VERIFIER_V1,
}


def get_prompt(agent_name: str) -> dict:
    return PROMPT_REGISTRY[agent_name]