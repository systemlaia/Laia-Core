import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import add_video_evidence, ensure_project_record
from core.projects.sale_items import build_channel_package, channel_packages, init_sale_item, update_sale_item


class SaleItemChannelPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)
        ensure_project_record("CLD-3080")
        init_sale_item("cld-3080", title="Pioneer CLD-3080", category="electronics")
        update_sale_item("cld-3080", description="Fully tested LaserDisc player.", asking_price=325)
        photos = self.root / "projects/cld-3080/listing/photos"
        photos.mkdir(parents=True)
        (photos / "hero.jpg").write_bytes(b"hero")
        (photos / "rear.jpg").write_bytes(b"rear")
        self.video = self.root / "demo.mp4"
        self.video.write_bytes(b"video")
        add_video_evidence(
            "cld-3080",
            {
                "packet_id": "video-one", "role": "functional_demo",
                "original_path": str(self.video), "proxy_path": str(self.video),
                "duration_seconds": 10, "verification_status": "ok",
            },
        )

    def test_craigslist_package_has_text_price_and_all_photos_without_video(self):
        package = build_channel_package("cld-3080", "craigslist")
        root = Path(package["package_path"])
        self.assertEqual(package["photos"], ["hero.jpg", "rear.jpg"])
        self.assertEqual(package["videos"], [])
        self.assertEqual((root / "price.txt").read_text().strip(), "325.00")
        self.assertIn("Functional demonstration video available", (root / "description.txt").read_text())
        self.assertTrue((root / "package.json").is_file())

    def test_facebook_package_includes_available_video(self):
        package = build_channel_package("cld-3080", "facebook_marketplace")
        self.assertEqual(len(package["videos"]), 1)
        self.assertTrue((Path(package["package_path"]) / "videos" / package["videos"][0]).is_file())
        self.assertEqual(len(channel_packages("cld-3080")), 1)

    def test_ebay_package_contains_policy_placeholders(self):
        package = build_channel_package("cld-3080", "ebay")
        description = Path(package["description_path"]).read_text()
        self.assertIn("Shipping policy:", description)
        self.assertIn("Package weight/dimensions:", description)


if __name__ == "__main__":
    unittest.main()
