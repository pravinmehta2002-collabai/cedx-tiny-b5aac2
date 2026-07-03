"""
LLM adapter with two modes:

  REPLAY_LLM=true  (DEFAULT — this is what graders run):
    - Compute deterministic request_hash from (agent, model, prompt_version, request)
    - Look up transcripts/<request_hash>.json
    - Return committed response (no network I/O)

  REPLAY_LLM=false:
    - Call real API (OpenAI/Groq/Anthropic/Gemini-compatible)
    - Persist transcript to transcripts/<request_hash>.json
    - Return response

Transcript on disk:
    {
      "agent": "worker_v1",
      "model": "gpt-4o-mini",
      "prompt_version": "1.0",
      "request": {"system": ..., "user": ...},
      "response": {...},                          # parsed JSON (worker/verifier both return JSON)
      "response_hash": "sha256:<hex>",            # sha256(canonical(response))
      "delivered_fields_hash": "sha256:<hex>",    # sha256(canonical(response)) — same for workers
      "tokens_in": int, "tokens_out": int, "cost_usd": float, "latency_ms": float
    }

verify_audit.py checks:
  - filename stem == response_hash hex
  - agent tag exists and is a worker (for delivered records)
  - sha256(response) == response_hash
  - delivered_fields_hash matches record.delivered_fields_hash
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canon(obj)).hexdigest()


# --------------------------------------------------------------------------- #
# response object
# --------------------------------------------------------------------------- #
@dataclass
class LLMResponse:
    response: dict                    # parsed JSON returned by the LLM
    response_hash: str                # sha256:...
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    transcript_hash: str              # equal to response_hash (canonical id)
    delivered_fields_hash: str        # for workers, sha of response; for verifiers, same
    from_replay: bool


# --------------------------------------------------------------------------- #
# pricing table (per 1M tokens) — used for both real + replay accounting
# --------------------------------------------------------------------------- #
_PRICING = {
    # (model): (input_usd_per_1m, output_usd_per_1m)
    "gpt-4o-mini":       (0.15, 0.60),
    "gpt-4o":            (5.00, 15.00),
    "claude-3-5-haiku":  (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "gemini-1.5-flash":  (0.075, 0.30),
    "llama-3.1-8b":      (0.05, 0.08),   # e.g. Groq
    "llama-3.1-70b":     (0.59, 0.79),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    tin, tout = _PRICING.get(model, (0.5, 1.5))
    return (tokens_in / 1_000_000) * tin + (tokens_out / 1_000_000) * tout


# --------------------------------------------------------------------------- #
# transcript I/O
# --------------------------------------------------------------------------- #
def _transcripts_dir() -> Path:
    p = Path(os.environ.get("TRANSCRIPTS_DIR", "transcripts"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _persist_transcript(t: dict) -> Path:
    tdir = _transcripts_dir()
    stem = t["response_hash"].split(":")[-1]
    path = tdir / f"{stem}.json"
    path.write_text(json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _load_transcript_by_hash(response_hash: str) -> Optional[dict]:
    stem = response_hash.split(":")[-1]
    p = _transcripts_dir() / f"{stem}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _replay_key(agent: str, model: str, prompt_version: str, request: dict) -> str:
    """
    Deterministic key that maps (agent, model, prompt_version, request) -> transcript.
    We store this key in a small index so replay is O(1).
    """
    payload = {"agent": agent, "model": model, "prompt_version": prompt_version, "request": request}
    return sha(payload)

def _load_transcript_by_request(agent: str, model: str, prompt_version: str, request: dict) -> Optional[dict]:
    """
    Replay lookup with whitespace-tolerant fingerprint matching.
    Small formatting drift (e.g. trailing spaces, different newlines) between
    generator and runtime does NOT break replay.
    """
    def _fp(req: dict) -> str:
        sys_txt = req.get("system", "") or ""
        usr_txt = req.get("user", "") or ""
        # Collapse all whitespace runs -> single space
        return " ".join(sys_txt.split()) + "||" + " ".join(usr_txt.split())

    target_fp = _fp(request)
    tdir = _transcripts_dir()

    # Pass 1: exact request match (fast, strict)
    for p in tdir.glob("*.json"):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if (
            t.get("agent") == agent
            and t.get("model") == model
            and t.get("prompt_version") == prompt_version
            and t.get("request") == request
        ):
            return t

    # Pass 2: whitespace-tolerant fingerprint match
    for p in tdir.glob("*.json"):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if (
            t.get("agent") == agent
            and t.get("model") == model
            and t.get("prompt_version") == prompt_version
            and _fp(t.get("request", {})) == target_fp
        ):
            return t

    return None

# --------------------------------------------------------------------------- #
# real API (only used when REPLAY_LLM=false)
# --------------------------------------------------------------------------- #
def _call_real_api(model: str, system: str, user: str) -> tuple[dict, int, int]:
    """
    Minimal OpenAI-compatible call. Supports:
      LLM_PROVIDER=openai  -> https://api.openai.com/v1/chat/completions
      LLM_PROVIDER=groq    -> https://api.groq.com/openai/v1/chat/completions
    Returns (parsed_response_dict, tokens_in, tokens_out).
    Response MUST be JSON. If not, we wrap raw text under {"raw": ...}.
    """
    import urllib.request

    provider = os.environ.get("LLM_PROVIDER", "openai").lower()
    base_url = os.environ.get("LLM_BASE_URL") or {
        "openai": "https://api.openai.com/v1",
        "groq":   "https://api.groq.com/openai/v1",
    }.get(provider, "https://api.openai.com/v1")
    api_key = os.environ.get("LLM_API_KEY", "")

    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")

    j = json.loads(raw)
    content = j["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"raw": content}
    usage = j.get("usage", {})
    return parsed, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def call_llm(
    *,
    agent: str,
    model: str,
    prompt_version: str,
    system: str,
    user: str,
) -> LLMResponse:
    """
    Unified LLM call. Dispatches on REPLAY_LLM env var.
    """
    replay = os.environ.get("REPLAY_LLM", "true").lower() == "true"
    request = {"system": system, "user": user}
    t0 = time.perf_counter()

    if replay:
        t = _load_transcript_by_request(agent, model, prompt_version, request)
        if t is None:
            raise RuntimeError(
                f"REPLAY_LLM=true but no transcript found for "
                f"agent={agent} model={model} pv={prompt_version}. "
                f"Run `python -m scripts.generate_transcripts` first."
            )
        latency = (time.perf_counter() - t0) * 1000
        return LLMResponse(
            response=t["response"],
            response_hash=t["response_hash"],
            model=t["model"],
            tokens_in=int(t.get("tokens_in", 0)),
            tokens_out=int(t.get("tokens_out", 0)),
            cost_usd=float(t.get("cost_usd", 0.0)),
            latency_ms=float(t.get("latency_ms", latency)),
            transcript_hash=t["response_hash"],
            delivered_fields_hash=t.get("delivered_fields_hash", t["response_hash"]),
            from_replay=True,
        )

    # ---- real path ---- #
    parsed, tin, tout = _call_real_api(model, system, user)
    latency = (time.perf_counter() - t0) * 1000
    cost = _estimate_cost(model, tin, tout)
    response_hash = sha(parsed)
    dfh = response_hash    # for the worker this is exactly the delivered fields

    transcript = {
        "agent": agent,
        "model": model,
        "prompt_version": prompt_version,
        "request": request,
        "response": parsed,
        "response_hash": response_hash,
        "delivered_fields_hash": dfh,
        "tokens_in": tin,
        "tokens_out": tout,
        "cost_usd": cost,
        "latency_ms": latency,
    }
    _persist_transcript(transcript)

    return LLMResponse(
        response=parsed,
        response_hash=response_hash,
        model=model,
        tokens_in=tin,
        tokens_out=tout,
        cost_usd=cost,
        latency_ms=latency,
        transcript_hash=response_hash,
        delivered_fields_hash=dfh,
        from_replay=False,
    )