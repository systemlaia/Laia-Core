import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import (
    add_cohort_to_project,
    ensure_project_record,
    project_tasks,
)
from core.projects.sale_items import (
    bootstrap_sale_item,
    build_listing_package,
    init_sale_item,
    load_sale_item,
    record_listing,
    record_sale,
    update_sale_item,
)


class SaleItemTests(unittest.TestCase):
    def setup_project(self, root: Path):
        env = {"LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects")}
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        ensure_project_record("CLD-3080")
        export = root / "export"
        export.mkdir()
        add_cohort_to_project(
            "cld-3080",
            {
                "packet_id": "packet-one",
                "packet_path": str(root / "packet"),
                "cohort_id": "cld-3080",
                "cohort_name": "CLD-3080",
                "cohort_path": str(root / "packet/cohort"),
                "cohort_status": "ready",
                "file_count": 8,
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        return export

    def test_initialization_derives_linked_cohort_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            export = self.setup_project(root)
            item = init_sale_item("cld-3080", title="LaserDisc Player", model="CLD-3080", category="electronics")
            self.assertEqual(item["source"]["packet_id"], "packet-one")
            self.assertEqual(item["source"]["cohort_id"], "cld-3080")
            self.assertEqual(item["source"]["cohort_export_path"], str(export))
            init_sale_item("cld-3080", title="Should not overwrite")
            self.assertEqual(load_sale_item("cld-3080")["title"], "LaserDisc Player")
            self.assertTrue((root / "projects/cld-3080/sale_item.md").is_file())

    def test_updates_condition_and_list_fields_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            init_sale_item("cld-3080")
            update_sale_item(
                "cld-3080",
                condition="good",
                functional_status="working",
                known_defect="scratched lid",
                included_item="remote",
                missing_item="manual",
                serial_number="ABC123",
                asking_price="249.99",
            )
            update_sale_item(
                "cld-3080",
                known_defect="scratched lid",
                included_item="remote",
                missing_item="manual",
            )
            item = load_sale_item("cld-3080")
            self.assertEqual(item["condition"]["known_defects"], ["scratched lid"])
            self.assertEqual(item["included_items"], ["remote"])
            self.assertEqual(item["missing_items"], ["manual"])
            self.assertEqual(item["pricing"]["asking_price"], "249.99")

    def test_listing_and_decimal_sale_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            init_sale_item("cld-3080")
            record_listing("cld-3080", "eBay", "https://example.test/item", "300.00", "listed")
            sold = record_sale("cld-3080", "eBay", "275.00", "27.50", "18.25", "Buyer")
            self.assertEqual(sold["sale"]["status"], "sold")
            self.assertEqual(sold["sale"]["net_proceeds"], "229.25")

    def test_bootstrap_creates_tasks_once_and_darktable_step_is_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            first = bootstrap_sale_item("cld-3080")
            second = bootstrap_sale_item("cld-3080")
            self.assertEqual(len(first["created_tasks"]), 4)
            self.assertEqual(second["created_tasks"], [])
            tasks = project_tasks("cld-3080")
            self.assertEqual(len(tasks), 4)
            edit_task = next(task for task in tasks if task["title"].startswith("Edit "))
            manual = next(item for item in edit_task["checklist"] if item["text"].startswith("edit images"))
            self.assertEqual(manual["action"]["action_type"], "manual")
            self.assertIn("Darktable", manual["action"]["parameters"]["instruction"])

    def test_listing_package_reports_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            init_sale_item("cld-3080", category="electronics")
            package = build_listing_package("cld-3080")
            self.assertEqual(package["status"], "incomplete")
            self.assertIn("condition", package["missing_fields"])
            self.assertIn("verified listing photos", package["missing_fields"])
            saved = json.loads((root / "projects/cld-3080/listing/listing_package.json").read_text())
            self.assertEqual(saved["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
