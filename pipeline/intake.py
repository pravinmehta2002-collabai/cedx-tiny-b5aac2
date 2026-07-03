"""
Stage 1: Intake.
Reads BOTH data formats:
  - seed/feed.json         (JSON array of records)
  - seed/inbox/*.pdf       (PDF work requests)
  - seed/inbox/*.eml       (Email work requests)

Produces raw dicts + provenance (source_format, source_version_hash).
NO business logic here — this is just parse + tag.
"""
from __future__ import annotations
import email
import hashlib
import json
import re
from dataclasses import dataclass, field
from email import policy
from pathlib import Path
from typing import Any


@dataclass
class RawRecord:
    """Untyped/undandidated dict + provenance. Normalizer turns this into NormalizedRecord."""
    payload: dict[str, Any]
    source_format: str                 # "feed" | "pdf" | "eml"
    source_path: str                   # for debugging
    source_version_hash: str           # sha256 of the raw payload bytes


# --------------------------------------------------------------------------- #
# JSON feed
# --------------------------------------------------------------------------- #
def read_feed(feed_path: Path) -> list[RawRecord]:
    """Parse seed/feed.json (JSON array of dict records)."""
    raw_bytes = feed_path.read_bytes()
    records = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{feed_path} must be a JSON array")

    out = []
    for rec in records:
        h = hashlib.sha256(json.dumps(rec, sort_keys=True).encode("utf-8")).hexdigest()
        out.append(RawRecord(
            payload=rec,
            source_format="feed",
            source_path=str(feed_path),
            source_version_hash=f"sha256:{h}",
        ))
    return out


# --------------------------------------------------------------------------- #
# PDF parser (schema-agnostic key: value extractor)
# --------------------------------------------------------------------------- #
_PDF_LINE_RX = re.compile(r"^\s*([A-Za-z][A-Za-z _\-]*?)\s*:\s*(.+?)\s*$")


def _pdf_text_to_dict(text: str) -> dict[str, Any]:
    """
    Extract 'Key: value' lines from PDF text. Keys are lowercased and
    whitespace-normalized so 'Owner' and 'OWNER ' both become 'owner'.
    """
    out: dict[str, Any] = {}
    for line in text.splitlines():
        m = _PDF_LINE_RX.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        val = m.group(2).strip()
        # try numeric
        if re.fullmatch(r"-?\d+", val):
            out[key] = int(val)
        elif re.fullmatch(r"-?\d+\.\d+", val):
            out[key] = float(val)
        else:
            out[key] = val
    return out


def read_pdf(pdf_path: Path) -> RawRecord:
    """Parse one PDF into a raw dict + provenance."""
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    payload = _pdf_text_to_dict(text)

    raw_bytes = pdf_path.read_bytes()
    h = hashlib.sha256(raw_bytes).hexdigest()
    return RawRecord(
        payload=payload,
        source_format="pdf",
        source_path=str(pdf_path),
        source_version_hash=f"sha256:{h}",
    )


# --------------------------------------------------------------------------- #
# EML parser (same key:value convention, in the body)
# --------------------------------------------------------------------------- #
def read_eml(eml_path: Path) -> RawRecord:
    """
    Parse one .eml file. We accept either:
      - Subject line + body of 'Key: value' pairs, or
      - JSON blob in the body.
    """
    raw_bytes = eml_path.read_bytes()
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)

    # Get body (plain text)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content()
                break
    else:
        body = msg.get_content() if msg.get_content_type() == "text/plain" else str(msg.get_payload())

    subject = msg.get("Subject", "") or ""

    # Try JSON body first
    payload: dict[str, Any] = {}
    stripped = body.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = _pdf_text_to_dict(body)
    else:
        payload = _pdf_text_to_dict(body)

    # If subject contains "REC-###" and payload has no id, extract from subject
    if "id" not in payload:
        m = re.search(r"(REC-\d+)", subject + " " + body)
        if m:
            payload["id"] = m.group(1)

    h = hashlib.sha256(raw_bytes).hexdigest()
    return RawRecord(
        payload=payload,
        source_format="eml",
        source_path=str(eml_path),
        source_version_hash=f"sha256:{h}",
    )


# --------------------------------------------------------------------------- #
# Top-level intake
# --------------------------------------------------------------------------- #
def intake(seed_dir: Path) -> list[RawRecord]:
    """
    Read the entire seed:
      - seed/feed.json               (JSON array)
      - seed/inbox/*.pdf / *.eml     (individual work requests)

    Returns a flat list of RawRecord (no dedup, no normalization).
    """
    seed_dir = Path(seed_dir)
    all_raw: list[RawRecord] = []

    feed_path = seed_dir / "feed.json"
    if feed_path.exists():
        all_raw.extend(read_feed(feed_path))

    inbox_dir = seed_dir / "inbox"
    if inbox_dir.exists():
        for p in sorted(inbox_dir.iterdir()):
            suffix = p.suffix.lower()
            if suffix == ".pdf":
                try:
                    all_raw.append(read_pdf(p))
                except Exception as e:
                    print(f"[intake] WARN: failed to parse PDF {p}: {e}")
            elif suffix == ".eml":
                try:
                    all_raw.append(read_eml(p))
                except Exception as e:
                    print(f"[intake] WARN: failed to parse EML {p}: {e}")

    return all_raw


if __name__ == "__main__":
    # Quick smoke test
    import os
    seed = Path(os.environ.get("SEED_DIR", "seed"))
    records = intake(seed)
    print(f"[intake] Parsed {len(records)} raw records from {seed}")
    for r in records[:3]:
        print(f"  - {r.source_format:5} {r.source_path}")
        print(f"    payload keys: {list(r.payload.keys())}")