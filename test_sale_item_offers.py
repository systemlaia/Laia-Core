import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import ensure_project_record
from core.projects.sale_items import init_sale_item, load_sale_item, record_listing, record_offer, update_offer


class SaleItemOfferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_project_record("CLD-3080")
        init_sale_item("cld-3080", category="electronics")
        self.listing = record_listing("cld-3080", "facebook_marketplace", "https://example.test/fb", 325)["listings"][0]

    def test_prior_offer_creation_and_status_updates(self):
        offer = record_offer(
            "cld-3080", "facebook-marketplace", 250, note="Prior local offer before refreshed listing."
        )
        self.assertEqual(offer["amount"], "250.00")
        self.assertEqual(offer["status"], "received")
        item = load_sale_item("cld-3080")
        self.assertEqual(item["listings"][0]["status"], "listed")
        updated = update_offer("cld-3080", offer["offer_id"], "accepted", "Pickup arranged.")
        self.assertEqual(updated["status"], "accepted")
        self.assertEqual(load_sale_item("cld-3080")["sale"]["status"], "pending_pickup")
        update_offer("cld-3080", offer["offer_id"], "completed")
        self.assertEqual(load_sale_item("cld-3080")["sale"]["status"], "sold")

    def test_offer_ids_are_deterministic_and_sequential(self):
        first = record_offer("cld-3080", self.listing["listing_id"], 250)
        second = record_offer("cld-3080", self.listing["listing_id"], 275, status="countered")
        self.assertEqual(first["offer_id"][:-3], second["offer_id"][:-3])
        self.assertTrue(first["offer_id"].endswith("001"))
        self.assertTrue(second["offer_id"].endswith("002"))


if __name__ == "__main__":
    unittest.main()
