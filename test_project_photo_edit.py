import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import add_cohort_to_project, command_projects_briefing, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    edit_status_data,
    init_sale_item,
    load_edit_manifest,
    load_sale_item,
    open_photo_edit,
    package_photos,
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


class ProjectPhotoEditTests(unittest.TestCase):
    def setup_project(self, root: Path):
        env = {"LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects")}
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        ensure_project_record("CLD-3080")
        packet = root / "packet"
        originals = packet / "originals"
        originals.mkdir(parents=True)
        (originals / "ORIGINAL.JPG").write_bytes(b"original")
        export = root / "cohort-export"
        files = export / "files/album"
        files.mkdir(parents=True)
        for name in ["A.JPG", "B.JPG", "C.JPG"]:
            (files / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            "cld-3080",
            {
                "packet_id": "packet-one",
                "packet_path": str(packet),
                "cohort_id": "cld-3080",
                "cohort_name": "CLD-3080",
                "cohort_path": str(packet / "review/cohorts/cld-3080"),
                "cohort_status": "ready",
                "file_count": 3,
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item("cld-3080", model="CLD-3080", category="electronics")
        return packet, export

    def render(self, root: Path, name: str):
        path = root / "projects/cld-3080/photo_edit/exports" / name
        path.write_bytes(JPEG)
        return path

    def test_workspace_uses_export_is_idempotent_and_preserves_xmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, export = self.setup_project(root)
            first = prepare_photo_edit("cld-3080")
            work = root / "projects/cld-3080/photo_edit/work"
            xmp = work / "A.JPG.xmp"
            xmp.write_text("edits", encoding="utf-8")
            second = prepare_photo_edit("cld-3080")
            self.assertEqual(first["copied"], 3)
            self.assertEqual(second["existing"], 3)
            self.assertEqual(xmp.read_text(), "edits")
            manifest = load_edit_manifest("cld-3080")
            self.assertTrue(all(str(export) in image["source_path"] for image in manifest["images"]))
            self.assertTrue(all(str(packet / "originals") not in image["source_path"] for image in manifest["images"]))
            self.assertEqual(load_sale_item("cld-3080")["sale"]["status"], "photos_in_progress")

    def test_conflicting_workspace_file_stops_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            prepare_photo_edit("cld-3080")
            (root / "projects/cld-3080/photo_edit/work/A.JPG").write_bytes(b"conflict")
            with self.assertRaises(ValueError):
                prepare_photo_edit("cld-3080")

    def test_darktable_open_validates_app_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            prepare_photo_edit("cld-3080")
            before = load_edit_manifest("cld-3080")["opened_at"]
            with patch.dict(os.environ, {"LAIA_DARKTABLE_APP": str(root / "missing.app")}, clear=False):
                with self.assertRaises(FileNotFoundError):
                    open_photo_edit("cld-3080")
            self.assertEqual(load_edit_manifest("cld-3080")["opened_at"], before)

    def test_roles_exports_approval_verification_and_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            prepare_photo_edit("cld-3080")
            with self.assertRaises(ValueError):
                assign_role("cld-3080", "A.JPG", "invalid")
            assign_role("cld-3080", "A.JPG", "hero")
            assign_role("cld-3080", "B.JPG", "rear")
            assign_role("cld-3080", "C.JPG", "ports")
            for name in ["A.jpg", "B.jpg", "C.jpg"]:
                self.render(root, name)
            result = scan_exports("cld-3080")
            self.assertEqual(result["matched"], 3)
            review_images("cld-3080", ["A.JPG", "B.JPG", "C.JPG"], "approved")
            verified = verify_photo_edit("cld-3080")
            self.assertTrue(verified["success"])
            self.assertEqual(load_sale_item("cld-3080")["sale"]["status"], "photos_ready")
            package = package_photos("cld-3080")
            names = [photo["filename"] for photo in package["photos"]]
            self.assertEqual(names, ["cld-3080_hero.jpg", "cld-3080_rear.jpg", "cld-3080_ports.jpg"])
            manifest = json.loads(Path(package["manifest"]).read_text())
            self.assertEqual(manifest["photos"][0]["source_packet_id"], "packet-one")
            self.assertEqual(manifest["photos"][0]["source_cohort_id"], "cld-3080")

    def test_export_scan_reports_unmatched_duplicates_and_approval_requires_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            prepare_photo_edit("cld-3080")
            with self.assertRaises(ValueError):
                review_images("cld-3080", ["A.JPG"], "approved")
            self.render(root, "A.jpg")
            self.render(root, "A.jpeg")
            self.render(root, "UNKNOWN.jpg")
            result = scan_exports("cld-3080")
            self.assertEqual(len(result["duplicates"]), 1)
            self.assertEqual(len(result["unmatched"]), 1)

    def test_verification_requires_approved_hero_and_briefing_shows_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            prepare_photo_edit("cld-3080")
            assign_role("cld-3080", "A.JPG", "front")
            self.render(root, "A.jpg")
            scan_exports("cld-3080")
            review_images("cld-3080", ["A.JPG"], "approved")
            result = verify_photo_edit("cld-3080")
            self.assertFalse(result["success"])
            self.assertTrue(any("hero" in error for error in result["errors"]))
            output = __import__("io").StringIO()
            with __import__("contextlib").redirect_stdout(output):
                command_projects_briefing(type("Args", (), {"identifier": "cld-3080", "json": False})())
            self.assertIn("Sale Item:", output.getvalue())
            self.assertIn("Photo Editing:", output.getvalue())
            self.assertIn("hero image: missing", output.getvalue())


if __name__ == "__main__":
    unittest.main()
