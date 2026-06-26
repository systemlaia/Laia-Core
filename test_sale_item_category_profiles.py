import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    build_listing_package,
    init_sale_item,
    prepare_photo_edit,
    review_images,
    scan_exports,
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


class SaleItemCategoryProfileTests(unittest.TestCase):
    def setup_project(self, root: Path, project_id: str, category: str, filenames=None):
        filenames = filenames or ["A.JPG", "B.JPG", "C.JPG"]
        patcher = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects")}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        ensure_project_record(project_id)
        export = root / "cohort-export"
        files = export / "files"
        files.mkdir(parents=True)
        for name in filenames:
            (files / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            project_id,
            {
                "packet_id": "packet-one",
                "packet_path": str(root / "packet"),
                "cohort_id": project_id,
                "cohort_name": project_id,
                "cohort_path": str(root / "packet/cohort"),
                "cohort_status": "ready",
                "file_count": len(filenames),
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item(project_id, title=project_id, category=category)

    def render_all(self, root: Path, project_id: str, filenames):
        exports = root / f"projects/{project_id}/photo_edit/exports"
        for name in filenames:
            (exports / f"{Path(name).stem}.jpg").write_bytes(JPEG)

    def approve_roles(self, root: Path, project_id: str, roles: dict):
        prepare_photo_edit(project_id)
        for filename, role in roles.items():
            assign_role(project_id, filename, role)
        self.render_all(root, project_id, roles.keys())
        scan_exports(project_id)
        review_images(project_id, list(roles.keys()), "approved")

    def test_electronics_still_requires_cld_style_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root, "cld-3080", "electronics")
            self.approve_roles(root, "cld-3080", {"A.JPG": "front"})
            result = verify_photo_edit("cld-3080")
            self.assertFalse(result["success"])
            self.assertEqual(result["profile"], "electronics")
            self.assertIn("Exactly one approved hero image is required.", result["errors"])
            self.assertIn("No approved rear image.", result["warnings"])
            self.assertIn("No approved ports image.", result["warnings"])

    def test_generic_fallback_requires_only_an_approved_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root, "chair-001", "furniture", filenames=["A.JPG"])
            self.approve_roles(root, "chair-001", {"A.JPG": "front"})
            result = verify_photo_edit("chair-001")
            self.assertTrue(result["success"])
            self.assertEqual(result["profile"], "generic")
            self.assertEqual(result["warnings"], [])

    def test_record_listing_package_does_not_require_functional_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root, "record-001", "records", filenames=["A.JPG", "B.JPG"])
            package = build_listing_package("record-001")
            self.assertEqual(package["profile"], "records")
            self.assertIn("condition", package["missing_fields"])
            self.assertIn("asking price", package["missing_fields"])
            self.assertIn("description", package["missing_fields"])
            self.assertNotIn("functional status", package["missing_fields"])


if __name__ == "__main__":
    unittest.main()
