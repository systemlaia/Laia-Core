import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import add_cohort_to_project, command_projects_briefing, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    command_photo_edit_status,
    init_sale_item,
    load_edit_manifest,
    normalize_tag,
    package_photos,
    photo_tag_summary,
    prepare_photo_edit,
    update_image_tags,
    verify_photo_edit,
)
from test_project_photo_edit import JPEG


class PhotoEditTagTests(unittest.TestCase):
    def setup_project(self, root: Path):
        patcher = patch.dict(
            os.environ,
            {
                "LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects"),
                "LAIA_PACKET_REGISTRY_DB": str(root / "registry.db"),
                "LAIA_PHOTO_PACKET_ROOT": str(root / "packets"),
            },
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        ensure_project_record("CLD-3080")
        export = root / "export/files"
        export.mkdir(parents=True)
        for name in ["A.JPG", "B.JPG", "C.JPG"]:
            (export / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            "cld-3080",
            {
                "packet_id": "packet-one",
                "packet_path": str(root / "packet"),
                "cohort_id": "cld-3080",
                "cohort_name": "CLD-3080",
                "cohort_path": str(root / "cohort"),
                "cohort_status": "ready",
                "file_count": 3,
                "artifact_path": str(root / "export"),
                "linked_at": "2026-06-20T00:00:00Z",
            },
        )
        init_sale_item("cld-3080")
        prepare_photo_edit("cld-3080")
        return root / "projects/cld-3080/photo_edit/edit_manifest.json"

    def approve(self, root: Path, roles):
        manifest_path = root / "projects/cld-3080/photo_edit/edit_manifest.json"
        manifest = load_edit_manifest("cld-3080")
        for image, role in zip(manifest["images"], roles):
            render = root / "projects/cld-3080/photo_edit/exports" / f"{Path(image['filename']).stem}.jpg"
            render.write_bytes(JPEG)
            image.update(
                {
                    "role": role,
                    "review_status": "approved",
                    "edit_status": "approved",
                    "export_path": str(render),
                    "export_sha256": __import__("hashlib").sha256(JPEG).hexdigest(),
                    "dimensions": {"width": 1, "height": 1},
                }
            )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    def test_manifest_without_tags_loads_with_empty_lists_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = self.setup_project(root)
            raw = json.loads(manifest_path.read_text())
            for image in raw["images"]:
                image.pop("tags", None)
            manifest_path.write_text(json.dumps(raw) + "\n")
            before = manifest_path.read_bytes()
            loaded = load_edit_manifest("cld-3080")
            self.assertTrue(all(image["tags"] == [] for image in loaded["images"]))
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_tag_normalization_add_multiple_and_duplicate_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_project(Path(tmp))
            image = update_image_tags("cld-3080", "A.JPG", ["Rear Panel", "right_side", "ports", "PORTS"], "add")
            self.assertEqual(image["tags"], ["ports", "rear-panel", "right-side"])
            image = update_image_tags("cld-3080", "A.JPG", [" ports "], "add")
            self.assertEqual(image["tags"], ["ports", "rear-panel", "right-side"])
            self.assertEqual(normalize_tag("Side A Label"), "side-a-label")

    def test_untag_set_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_project(Path(tmp))
            update_image_tags("cld-3080", "A.JPG", ["ports", "rear-panel", "right-side"], "set")
            image = update_image_tags("cld-3080", "A.JPG", ["ports"], "remove")
            self.assertEqual(image["tags"], ["rear-panel", "right-side"])
            image = update_image_tags("cld-3080", "A.JPG", ["front", "hero"], "set")
            self.assertEqual(image["tags"], ["front", "hero"])
            image = update_image_tags("cld-3080", "A.JPG", [], "clear")
            self.assertEqual(image["tags"], [])

    def test_missing_file_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_project(Path(tmp))
            with self.assertRaises(FileNotFoundError):
                update_image_tags("cld-3080", "missing.JPG", ["ports"], "add")

    def test_tag_summary_groups_duplicate_tags_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_project(Path(tmp))
            update_image_tags("cld-3080", "A.JPG", ["ports", "left-side"], "set")
            update_image_tags("cld-3080", "B.JPG", ["ports", "right-side"], "set")
            rows = {row["tag"]: row for row in photo_tag_summary("cld-3080")}
            self.assertEqual(rows["ports"]["files"], ["A.JPG", "B.JPG"])
            filtered = photo_tag_summary("cld-3080", "Ports")
            self.assertEqual(len(filtered), 1)
            self.assertEqual(filtered[0]["tag"], "ports")

    def test_duplicate_unique_role_fails_but_duplicate_tag_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            self.approve(root, ["hero", "ports", "ports"])
            update_image_tags("cld-3080", "B.JPG", ["ports"], "set")
            update_image_tags("cld-3080", "C.JPG", ["ports"], "set")
            failed = verify_photo_edit("cld-3080")
            self.assertFalse(failed["success"])
            self.assertIn("Duplicate unique role: ports", failed["errors"])
            assign_role("cld-3080", "C.JPG", "detail")
            passed = verify_photo_edit("cld-3080")
            self.assertTrue(passed["success"])

    def test_status_table_has_tags_and_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_project(Path(tmp))
            update_image_tags("cld-3080", "A.JPG", ["ports", "rear-panel"], "set")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                command_photo_edit_status(argparse.Namespace(identifier="cld-3080", json=False))
            text = output.getvalue()
            self.assertIn("tags", text)
            self.assertIn("ports,rear-panel", text)
            self.assertIn(" - ", text)

    def test_package_manifest_and_markdown_include_tags_and_old_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            self.approve(root, ["hero", "rear", "detail"])
            update_image_tags("cld-3080", "C.JPG", ["ports", "right-side"], "set")
            package = package_photos("cld-3080")
            detail = next(photo for photo in package["photos"] if photo["role"] == "detail")
            self.assertEqual(detail["tags"], ["ports", "right-side"])
            self.assertIn("filename", detail)
            self.assertIn("source_packet_id", detail)
            listing_manifest = json.loads((root / "projects/cld-3080/listing/photos_manifest.json").read_text())
            self.assertEqual(len(listing_manifest["photos"]), 3)
            markdown = (root / "projects/cld-3080/listing/photos_manifest.md").read_text()
            self.assertIn("tags: ports, right-side", markdown)

    def test_briefing_summarizes_approved_roles_and_tags_for_two_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = self.setup_project(root)
            self.approve(root, ["hero", "ports", "detail"])
            update_image_tags("cld-3080", "B.JPG", ["ports", "left-side"], "set")
            update_image_tags("cld-3080", "C.JPG", ["ports", "right-side"], "set")
            manifest = json.loads(manifest_path.read_text())
            manifest["sources"].append(
                {
                    "source_id": "packet-two__supplemental",
                    "packet_id": "packet-two",
                    "cohort_id": "supplemental",
                    "file_count": 0,
                    "status": "active",
                }
            )
            manifest_path.write_text(json.dumps(manifest) + "\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                command_projects_briefing(type("Args", (), {"identifier": "cld-3080", "json": False})())
            text = output.getvalue()
            self.assertIn("Photo Evidence:", text)
            self.assertIn("Approved photos: 3", text)
            self.assertIn("ports: 2", text)
            self.assertIn("right-side: 1", text)


if __name__ == "__main__":
    unittest.main()
