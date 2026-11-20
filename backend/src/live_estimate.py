"""Price a live assessment using current, comparable Malaysian resale evidence."""

from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .market_evidence import (
    REPAIR_PRICE_TYPES, REQUIRED_MARKET_FIELDS, TRADE_IN_PRICE_TYPES,
    classify_freshness, condition_group_from_exterior_grade, normalize_condition_group,
    normalize_source_url, now_iso, parse_storage_gb, validate_market_observations,
)
from .valuation import value_from_market_observations


def _audited_rows(device: dict[str, Any], condition: str, timestamp: str) -> tuple[list[dict], str]:
    configured = os.environ.get("REVALUE_AUDITED_MARKET_CSV")
    if not configured:
        return [], "not_configured"
    try:
        path = Path(configured)
        if path.stat().st_size > 2_000_000:
            raise ValueError("Evidence file too large")
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not {*REQUIRED_MARKET_FIELDS, "review_reference"} <= set(reader.fieldnames or []):
                raise ValueError("Evidence file requires explicit review references")
            source_rows = [
                row for row in reader
                if isinstance(row.get("review_reference"), str) and row["review_reference"].strip()
            ]
        rows, _ = validate_market_observations(
            source_rows, confirmed_device=device, condition_group=condition,
            retrieved_at=timestamp, require_grounding=False,
        )
        return [asdict(row) for row in rows], "available"
    except (OSError, ValueError, TypeError, csv.Error):
        return [], "invalid"


def build_live_estimate(device: dict[str, Any], grade: str, market: dict[str, Any]) -> dict[str, Any]:
    condition = condition_group_from_exterior_grade(grade)
    timestamp = now_iso()
    reviewed, audit_status = _audited_rows(device, condition, timestamp)
    grounded = [{**row, "evidence_origin": "search_grounded"}
                for row in market.get("market_observations", []) if row.get("grounding_verified") is True]
    audited = [{**row, "evidence_origin": "audited_csv"} for row in reviewed if row["usable_for_market_range"]]
    selected, seen = [], set()
    exclusions: Counter[str] = Counter()
    for row in audited + grounded:
        source = normalize_source_url(row.get("source_url"))
        if not source:
            exclusions["invalid_listing_link"] += 1
        elif classify_freshness(row.get("observed_at"), timestamp) != "fresh":
            exclusions["stale_or_unknown_date"] += 1
        elif normalize_condition_group(row.get("condition_group") or row.get("condition")) != condition:
            exclusions["different_or_unknown_condition"] += 1
        elif source in seen:
            exclusions["duplicate_listing"] += 1
        else:
            seen.add(source)
            selected.append(row)

    # Benchmarks are informative references only. They never enter the price distribution or quote calculator.
    def references(key, kinds):
        candidates = [({**r, "evidence_origin": "audited_csv"}) for r in reviewed if r["price_type"] in kinds]
        candidates.extend({**r, "evidence_origin": "search_grounded"} for r in market.get(key, [])
                          if r.get("grounding_verified") is True)
        return [r for r in candidates if r.get("currency") == "MYR" and r.get("country") == "MY"
                and classify_freshness(r.get("observed_at"), timestamp) == "fresh"]

    result = asdict(value_from_market_observations(
        observations=selected, brand=device["brand"], model=device["model"],
        storage_gb=parse_storage_gb(device["storage"]), condition_group=condition,
        trade_in_benchmark=references("trade_in_benchmarks", TRADE_IN_PRICE_TYPES),
        repair_references=references("repair_references", REPAIR_PRICE_TYPES),
    ))
    counts = Counter(row["evidence_origin"] for row in selected)
    result.update(
        condition_group=condition, live_retrieval_status=market.get("status", "unavailable"),
        audited_evidence_status=audit_status, comparable_sources=dict(counts), exclusions=dict(exclusions),
        price_basis="eligible_observations" if result["value_low"] is not None else "insufficient_market_evidence",
    )
    result["eligible_observations"] = [
        {key: row[key] for key in ("source", "source_url", "observed_at", "price", "price_type", "evidence_origin")}
        for row in selected
    ]
    if result["value_low"] is None:
        result["notes"] = [
            f"Found {result['condition_matched_count']} recent, distinct resale observations for this model, storage and condition. At least three are needed."
        ]
    else:
        result["notes"] = ["Range is the middle half of eligible observed prices, rounded to RM50.",
                           "Asking and retail prices do not establish completed sale prices or offers."]
    result["limitations"] = [
        "Search grounding matches a source link; ReValue has not independently confirmed the listing price.",
        "An audited row is a dated operator-reviewed observation, not a guaranteed current sale or quote.",
        "Internal function, repair outcome and final merchant quotes require separate confirmation.",
    ]
    return result
