import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    bootstrap_record_sale_item,
    init_sale_item,
    load_sale_item,
    prepare_photo_edit,
    review_images,
    sale_item_markdown,
    scan_exports,
    update_sale_item,
    verify_photo_edit,
)


JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/"
    "9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABAf/8QA"
    "FBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPxB//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxB//8QA"
    "FBABAQAAAAAAAAAAAAAAAAAAABH/2gAIAQEAAT8QH//Z"
)


class RecordSaleItemVerificationTests(unittest.TestCase):
    def setup_record_project(self, root: Path, filenames=None):
        filenames = filenames or ["DSCF7416.JPG", "DSCF7417.JPG"]
        patcher = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects")}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        ensure_project_record("record-001")
        export = root / "cohort-export"
        files = export / "files"
        files.mkdir(parents=True)
        for name in filenames:
            (files / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            "record-001",
            {
                "packet_id": "20260610-184234_DSD_sd_ingest",
                "packet_path": str(root / "packet"),
                "cohort_id": "record-001",
                "cohort_name": "record-001",
                "cohort_path": str(root / "packet/cohort"),
                "cohort_status": "ready",
                "file_count": len(filenames),
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item("record-001", title="Gino Vanelli - A Pauper In Paradise", category="records")

    def approve_roles(self, root: Path, roles: dict):
        prepare_photo_edit("record-001")
        for filename, role in roles.items():
            assign_role("record-001", filename, role)
        exports = root / "projects/record-001/photo_edit/exports"
        for filename in roles:
            (exports / f"{Path(filename).stem}.jpg").write_bytes(JPEG)
        scan_exports("record-001")
        review_images("record-001", list(roles.keys()), "approved")

    def test_record_passes_with_cover_front_and_cover_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_record_project(root)
            self.approve_roles(root, {"DSCF7416.JPG": "cover_front", "DSCF7417.JPG": "cover_back"})
            result = verify_photo_edit("record-001")
            self.assertTrue(result["success"])
            self.assertEqual(result["profile"], "records")
            self.assertEqual(result["coverage"], {"cover_front": "approved", "cover_back": "approved"})
            self.assertEqual(result["warnings"], [])

    def test_record_cover_front_only_warns_but_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_record_project(root, filenames=["DSCF7416.JPG"])
            self.approve_roles(root, {"DSCF7416.JPG": "cover_front"})
            result = verify_photo_edit("record-001")
            self.assertTrue(result["success"])
            self.assertIn("No approved cover_back image.", result["warnings"])

    def test_record_without_cover_front_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_record_project(root)
            self.approve_roles(root, {"DSCF7417.JPG": "cover_back"})
            result = verify_photo_edit("record-001")
            self.assertFalse(result["success"])
            self.assertIn("Exactly one approved cover_front image is required.", result["errors"])
            self.assertNotIn("Exactly one approved hero image is required.", result["errors"])

    def test_duplicate_cover_front_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_record_project(root, filenames=["A.JPG", "B.JPG"])
            self.approve_roles(root, {"A.JPG": "cover_front", "B.JPG": "cover_front"})
            result = verify_photo_edit("record-001")
            self.assertFalse(result["success"])
            self.assertIn("Exactly one approved cover_front image is required.", result["errors"])
            self.assertIn("Duplicate unique role: cover_front", result["errors"])

    def test_record_bootstrap_sets_category_metadata_and_functional_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            patcher = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects")}, clear=False)
            patcher.start()
            self.addCleanup(patcher.stop)
            ensure_project_record("record-001")
            bootstrap_record_sale_item(
                "record-001",
                "packet-one",
                "record-001",
                "Gino Vanelli",
                "A Pauper In Paradise",
                "A&M",
                "SP-4666",
            )
            item = load_sale_item("record-001")
            self.assertEqual(item["category"], "records")
            self.assertEqual(item["condition"]["functional"], "not_applicable")
            self.assertEqual(item["record_metadata"]["artist"], "Gino Vanelli")
            self.assertEqual(item["record_metadata"]["title"], "A Pauper In Paradise")
            self.assertIn("Functional: not applicable", sale_item_markdown(item))

    def test_record_condition_fields_are_free_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_record_project(root)
            item = update_sale_item(
                "record-001",
                media_condition="VG",
                sleeve_condition="VG",
                grading_note="visual grade only; playback not tested",
            )
            self.assertEqual(item["record_metadata"]["media_condition"], "VG")
            self.assertEqual(item["record_metadata"]["sleeve_condition"], "VG")
            self.assertEqual(
                item["record_metadata"]["grading_note"],
                "visual grade only; playback not tested",
            )


if __name__ == "__main__":
    unittest.main()
