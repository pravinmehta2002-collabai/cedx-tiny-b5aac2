"""
Stage 5: Delivery.
Assemble the final branded 'engagement package' that the accounting firm
would ship to its clients. This is what output_package_hash covers.

STEP 4: a compact JSON package (records + summary). Real branded PDF
generation is an easy live-extension add (out of scope for the 72h build).
"""
from __future__ import annotations
from typing import Any


def build_package(delivered_outcomes: list, case_id: str, pipeline_version: str) -> dict[str, Any]:
    """
    delivered_outcomes: list of RecordOutcome with status == 'delivered'.
    Returns a dict suitable for hashing + writing to out/package.json.
    """
    items = []
    for oc in delivered_outcomes:
        if oc.status != "delivered":
            continue
        items.append({
            "record_id": oc.record_id,
            "engagement_type": oc.delivered_fields.get("engagement_type"),
            "title": oc.delivered_fields.get("title"),
            "amount": oc.delivered_fields.get("amount"),
            "owner": oc.delivered_fields.get("owner"),
            "deadline": oc.delivered_fields.get("deadline"),
            "requires_compliance_review": oc.delivered_fields.get("requires_compliance_review"),
            "body": oc.delivered_fields.get("body"),
            "delivered_fields_hash": oc.delivered_fields_hash,
        })

    total_amount = sum((i.get("amount") or 0.0) for i in items)
    return {
        "case_id": case_id,
        "pipeline_version": pipeline_version,
        "brand": "CEDX Accounting Firm — Engagement Delivery",
        "item_count": len(items),
        "total_amount_usd": total_amount,
        "items": items,
    }