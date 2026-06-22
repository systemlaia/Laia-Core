import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import command_projects_briefing, ensure_project_record
from core.projects.sale_items import (
    channel_recommendations,
    init_sale_item,
    load_sale_item,
    record_listing,
    update_listing,
)


class SaleItemChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_project_record("CLD-3080")

    def test_existing_record_without_listings_loads_and_legacy_channel_migrates(self):
        init_sale_item("cld-3080", category="electronics")
        path = self.root / "projects/cld-3080/sale_item.json"
        data = json.loads(path.read_text())
        data.pop("listings")
        data["sale"]["channels"] = [{"channel": "Facebook Marketplace", "url": "https://example.test/fb", "listed_at": "2026-06-20T12:00:00Z"}]
        path.write_text(json.dumps(data))
        item = load_sale_item("cld-3080")
        self.assertEqual(item["listings"][0]["listing_id"], "facebook-marketplace-20260620")
        self.assertEqual(item["listings"][0]["url"], "https://example.test/fb")

    def test_listing_create_repeat_update_and_status_summary(self):
        init_sale_item("cld-3080", category="electronics")
        first = record_listing("cld-3080", "facebook_marketplace", "https://example.test/one", 325)
        listing_id = first["listings"][0]["listing_id"]
        second = record_listing("cld-3080", "Facebook Marketplace", "https://example.test/two", 300)
        self.assertEqual(len(second["listings"]), 1)
        self.assertEqual(second["listings"][0]["listing_id"], listing_id)
        self.assertEqual(second["listings"][0]["asking_price"], "300.00")
        update_listing("cld-3080", listing_id, status="pending_pickup")
        self.assertEqual(load_sale_item("cld-3080")["sale"]["status"], "pending_pickup")
        update_listing("cld-3080", listing_id, status="removed")
        self.assertEqual(load_sale_item("cld-3080")["sale"]["status"], "listing_ready")

    def test_crosspost_plan_and_briefing_show_channels(self):
        init_sale_item("cld-3080", category="electronics")
        record_listing("cld-3080", "facebook_marketplace", "https://example.test/fb", 325)
        plan = channel_recommendations(load_sale_item("cld-3080"))
        recommended = {row["channel_id"] for row in plan["recommended"]}
        optional = {row["channel_id"] for row in plan["optional"]}
        self.assertTrue({"facebook_marketplace", "craigslist", "offerup"} <= recommended)
        self.assertTrue({"ebay", "reverb"} <= optional)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            command_projects_briefing(type("Args", (), {"identifier": "cld-3080", "json": False})())
        self.assertIn("Sales Channels:", output.getvalue())
        self.assertIn("Facebook Marketplace: listed at $325.00", output.getvalue())

    def test_records_recommend_discogs_and_ebay(self):
        init_sale_item("cld-3080", category="vinyl records")
        plan = channel_recommendations(load_sale_item("cld-3080"))
        recommended = {row["channel_id"] for row in plan["recommended"]}
        self.assertTrue({"discogs", "ebay"} <= recommended)


if __name__ == "__main__":
    unittest.main()
