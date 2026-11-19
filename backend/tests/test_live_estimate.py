"""Live valuation admits only dated condition-matched evidence and eligible scans."""

from __future__ import annotations

import csv
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.src.assessment_receipt import TTL_SECONDS, issue_receipt, verify_receipt
from backend.src.live_estimate import build_live_estimate
from backend.src.market_evidence import REQUIRED_MARKET_FIELDS, parse_price
from backend.src.phone_catalogue import match_catalogue_candidate

DEVICE = {
    "catalogue_id": match_catalogue_candidate("Samsung", "Galaxy S24 Ultra")["catalogue_match"]["catalogue_id"],
    "brand": "Samsung", "model": "Galaxy S24 Ultra", "storage": "256GB",
}
STAMP = "2026-11-19T12:00:00+00:00"


def observation(i, **changes):
    return {
        "source": "Fixture seller", "source_url": f"https://fixture.invalid/listing/{i}",
        "brand": DEVICE["brand"], "model": DEVICE["model"], "storage_gb": 256, "price": 1000+i*100,
        "country": "MY", "currency": "MYR", "price_type": "asking_price", "condition_group": "clean",
        "observed_at": "2026-11-01", "grounding_verified": True, "usable_for_market_range": True, **changes,
    }


class LiveEstimateTests(unittest.TestCase):
    def test_archived_calibration_cannot_price_live_scans(self):
        with patch.dict("os.environ", {"REVALUE_AUDITED_MARKET_CSV": ""}):
            result = build_live_estimate(DEVICE, "A", {"status": "blocked"})
        self.assertEqual(result["live_retrieval_status"], "blocked")
        self.assertIsNone(result["value_low"])

    def test_current_condition_match_and_tracking_deduplication(self):
        rows = [observation(i) for i in range(3)]
        rows.extend([
            observation(8, condition_group="damaged_working"),
            observation(9, observed_at="2026-01-01"),
            observation(10, observed_at="2026-12-01"),
            observation(11, grounding_verified=False),
            observation(0, source_url="https://fixture.invalid/listing/0/?utm_source=tracker", price=100000),
        ])
        with patch("backend.src.live_estimate.now_iso", return_value=STAMP):
            result = build_live_estimate(DEVICE, "A", {"status": "ok", "market_observations": rows})
        self.assertEqual((result["value_low"], result["value_high"]), (1050, 1150))
        self.assertEqual(result["condition_matched_count"], 3)
        self.assertEqual(result["exclusions"], {"different_or_unknown_condition": 1,
                                               "stale_or_unknown_date": 2, "duplicate_listing": 1})
        self.assertTrue(all(row["evidence_origin"] == "search_grounded" for row in result["eligible_observations"]))

    def test_operator_reviewed_rows_need_review_references_and_are_attributed(self):
        fields = list(REQUIRED_MARKET_FIELDS) + ["review_reference"]
        with TemporaryDirectory() as folder:
            path = Path(folder) / "fixture.csv"
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for i in range(4):
                    writer.writerow({**observation(i), "storage": "256GB", "condition": "clean",
                                     "review_reference": "operator-note" if i < 3 else ""})
            with patch.dict("os.environ", {"REVALUE_AUDITED_MARKET_CSV": str(path)}), patch(
                "backend.src.live_estimate.now_iso", return_value=STAMP
            ):
                result = build_live_estimate(DEVICE, "A", {"status": "blocked"})
        self.assertEqual(result["audited_evidence_status"], "available")
        self.assertEqual(result["comparable_sources"], {"audited_csv": 3})

    def test_bad_price_values_are_not_resale_observations(self):
        for invalid in ("-RM 150", "RM 150–500", True, float("inf"), float("nan"), 10**500):
            self.assertIsNone(parse_price(invalid))
        self.assertEqual(parse_price("RM 1,050.00"), 1050)

    def test_receipt_binds_current_grade_model_and_storage(self):
        with patch("backend.src.assessment_receipt.time.time", return_value=100):
            receipt = issue_receipt(DEVICE, "B", "provisional")
            self.assertEqual(verify_receipt(receipt, DEVICE, "B"), "provisional")
            self.assertIsNone(verify_receipt(receipt, DEVICE, "A"))
            self.assertIsNone(verify_receipt(receipt, {**DEVICE, "storage": "128GB"}, "B"))
            with self.assertRaises(ValueError):
                issue_receipt(DEVICE, "A", "review_required")
        with patch("backend.src.assessment_receipt.time.time", return_value=101 + TTL_SECONDS):
            self.assertIsNone(verify_receipt(receipt, DEVICE, "B"))


if __name__ == "__main__":
    unittest.main()
