import argparse
import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.photo_ingest.cohorts import create_cohort
from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.registry import validate_action
from core.projects.sale_items import (
    add_photo_edit_source,
    command_photo_edit_package,
    command_photo_edit_status,
    edit_source_detail,
    edit_sources,
    init_sale_item,
    load_edit_manifest,
    open_photo_edit,
    package_photos,
    prepare_photo_edit,
    source_id,
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


class PhotoEditSourceTests(unittest.TestCase):
    def setup_project(self, root: Path):
        env = {
            "LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects"),
            "LAIA_PHOTO_PACKET_ROOT": str(root / "packets"),
            "LAIA_PHOTO_COHORT_EXPORT_ROOT": str(root / "exports"),
            "LAIA_PACKET_REGISTRY_DB": str(root / "registry.db"),
        }
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        ensure_project_record("CLD-3080")
        initial = root / "initial-export/files"
        initial.mkdir(parents=True)
        (initial / "A.JPG").write_bytes(b"initial-a")
        (initial / "B.JPG").write_bytes(b"initial-b")
        add_cohort_to_project(
            "cld-3080",
            {
                "packet_id": "packet-one",
                "packet_path": str(root / "packets/2026/packet-one"),
                "cohort_id": "cld-3080",
                "cohort_name": "CLD-3080",
                "cohort_path": str(root / "cohort"),
                "cohort_status": "ready",
                "file_count": 2,
                "artifact_path": str(root / "initial-export"),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item("cld-3080")
        prepare_photo_edit("cld-3080")
        manifest_path = root / "projects/cld-3080/photo_edit/edit_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        first = manifest["images"][0]
        xmp = Path(first["xmp_path"])
        xmp.write_text("existing edits", encoding="utf-8")
        render = root / "projects/cld-3080/photo_edit/exports/A.jpg"
        render.write_bytes(JPEG)
        first.update(
            {
                "role": "hero",
                "review_status": "approved",
                "edit_status": "approved",
                "export_path": str(render),
                "export_sha256": __import__("hashlib").sha256(JPEG).hexdigest(),
                "dimensions": {"width": 1, "height": 1},
            }
        )
        manifest["status"] = "complete"
        manifest["reviewed_at"] = "2026-06-17T01:00:00Z"
        manifest["completed_at"] = "2026-06-17T01:00:00Z"
        manifest["history"].append(
            {"event": "verification", "timestamp": "2026-06-17T01:00:00Z", "success": True, "warnings": ["No approved rear image."]}
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest_path, xmp

    def make_supplemental(self, root: Path):
        packet = root / "packets/2026/packet-two"
        (packet / "originals/DCIM").mkdir(parents=True)
        (packet / "packet_manifest.json").write_text(
            json.dumps({"packet_type": "laia.photo_ingest", "job_id": "packet-two"}) + "\n"
        )
        create_cohort(packet, "CLD-3080 supplemental", status="ready")
        export = root / "exports/packet-two/cld-3080-supplemental/files"
        export.mkdir(parents=True)
        (export / "A.JPG").write_bytes(b"supplemental-a")
        (export / "C.JPG").write_bytes(b"initial-b")
        (export / "D.JPG").write_bytes(b"supplemental-d")
        return packet, export.parent

    def test_legacy_manifest_migrates_in_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _xmp = self.setup_project(root)
            raw = json.loads(manifest_path.read_text())
            raw.pop("sources", None)
            for image in raw["images"]:
                for key in ["source_id", "source_packet_id", "source_cohort_id", "source_export_path", "source_filename", "work_filename", "import_batch_id", "added_at"]:
                    image.pop(key, None)
            manifest_path.write_text(json.dumps(raw) + "\n")
            migrated = load_edit_manifest("cld-3080")
            self.assertEqual(len(migrated["sources"]), 1)
            self.assertEqual(migrated["images"][0]["work_filename"], "A.JPG")
            self.assertNotIn("sources", json.loads(manifest_path.read_text()))

    def test_dry_run_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, xmp = self.setup_project(root)
            self.make_supplemental(root)
            before = manifest_path.read_bytes()
            work_before = sorted(path.name for path in manifest_path.parent.joinpath("work").iterdir())
            result = add_photo_edit_source("cld-3080", packet="packet-two", cohort="cld-3080-supplemental", dry_run=True)
            self.assertTrue(result["dry_run"])
            self.assertEqual(manifest_path.read_bytes(), before)
            self.assertEqual(sorted(path.name for path in manifest_path.parent.joinpath("work").iterdir()), work_before)
            self.assertEqual(xmp.read_text(), "existing edits")

    def test_add_preserves_state_dedupes_content_and_renames_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest_path, xmp = self.setup_project(root)
            self.make_supplemental(root)
            before = load_edit_manifest("cld-3080")
            approved = before["images"][0].copy()
            result = add_photo_edit_source("cld-3080", packet="packet-two", cohort="cld-3080-supplemental", note="rear and ports")
            self.assertEqual(result["added"], 2)
            self.assertEqual(result["identical_count"], 1)
            manifest = load_edit_manifest("cld-3080")
            self.assertEqual(len(manifest["sources"]), 2)
            self.assertEqual(manifest["status"], "needs_reverify")
            self.assertEqual(manifest["images"][0]["role"], approved["role"])
            self.assertEqual(manifest["images"][0]["review_status"], "approved")
            self.assertEqual(manifest["images"][0]["export_path"], approved["export_path"])
            self.assertEqual(xmp.read_text(), "existing edits")
            new = [image for image in manifest["images"] if image["source_packet_id"] == "packet-two"]
            self.assertEqual(len(new), 2)
            collision = next(image for image in new if image["source_filename"] == "A.JPG")
            self.assertEqual(collision["work_filename"], "cld-3080-supplemental__A.JPG")
            self.assertTrue(Path(collision["work_path"]).is_file())
            self.assertEqual(collision["role"], "")
            self.assertEqual(collision["edit_status"], "unedited")
            self.assertEqual(collision["review_status"], "unreviewed")
            event = manifest["history"][-1]
            self.assertEqual(event["event"], "supplemental_source_added")
            self.assertEqual(event["previous_verification"]["status"], "complete")

    def test_duplicate_source_is_idempotent_and_source_detail_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            self.make_supplemental(root)
            add_photo_edit_source("cld-3080", packet="packet-two", cohort="cld-3080-supplemental")
            second = add_photo_edit_source("cld-3080", packet="packet-two", cohort="cld-3080-supplemental")
            self.assertTrue(second["existing_source"])
            self.assertEqual(second["added"], 0)
            sources = edit_sources("cld-3080")
            self.assertEqual(len(sources), 2)
            detail = edit_source_detail("cld-3080", source_id("packet-two", "cld-3080-supplemental"))
            self.assertTrue(all(image["checksum_ok"] for image in detail["images"]))

    def test_status_is_aligned_and_reports_multiple_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            self.make_supplemental(root)
            add_photo_edit_source("cld-3080", packet="packet-two", cohort="cld-3080-supplemental")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                command_photo_edit_status(argparse.Namespace(identifier="cld-3080", json=False))
            text = output.getvalue()
            self.assertIn("Sources: 2", text)
            self.assertIn("New unreviewed: 2", text)
            self.assertIn("filename", text)
            self.assertIn("supplemental", text)
            self.assertIn("-", text)

    def test_package_includes_multiple_sources_and_removes_stale_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            self.make_supplemental(root)
            add_photo_edit_source("cld-3080", packet="packet-two", cohort="cld-3080-supplemental")
            manifest_path = root / "projects/cld-3080/photo_edit/edit_manifest.json"
            manifest = load_edit_manifest("cld-3080")
            supplemental = next(image for image in manifest["images"] if image.get("source_filename") == "D.JPG")
            render = root / "projects/cld-3080/photo_edit/exports" / (Path(supplemental["work_filename"]).stem + ".jpg")
            render.write_bytes(JPEG)
            supplemental.update(
                {
                    "role": "rear",
                    "review_status": "approved",
                    "edit_status": "approved",
                    "export_path": str(render),
                    "export_sha256": __import__("hashlib").sha256(JPEG).hexdigest(),
                    "dimensions": {"width": 1, "height": 1},
                }
            )
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            stale = root / "projects/cld-3080/listing/photos/cld-3080_stale.jpg"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(b"stale")
            package = package_photos("cld-3080")
            self.assertFalse(stale.exists())
            self.assertEqual(package["count"], 2)
            by_role = {photo["role"]: photo for photo in package["photos"]}
            self.assertEqual(by_role["hero"]["source_packet_id"], "packet-one")
            self.assertEqual(by_role["rear"]["source_packet_id"], "packet-two")
            self.assertEqual(by_role["rear"]["source_cohort_id"], "cld-3080-supplemental")

    def test_expected_package_failure_exits_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            manifest = load_edit_manifest("cld-3080")
            for image in manifest["images"]:
                image["review_status"] = "unreviewed"
            (root / "projects/cld-3080/photo_edit/edit_manifest.json").write_text(json.dumps(manifest) + "\n")
            with self.assertRaises(SystemExit) as raised:
                command_photo_edit_package(argparse.Namespace(identifier="cld-3080", json=False))
            self.assertIn("No approved", str(raised.exception))

    def test_pending_open_uses_argument_list_and_action_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_project(root)
            self.make_supplemental(root)
            add_photo_edit_source("cld-3080", packet="packet-two", cohort="cld-3080-supplemental")
            app = root / "darktable"
            app.write_text("", encoding="utf-8")
            action = validate_action(
                "photo_edit_add_source",
                {"project": "cld-3080", "packet": "packet-two", "cohort": "cld-3080-supplemental"},
            )
            self.assertEqual(action["action_type"], "photo_edit_add_source")
            with patch.dict(os.environ, {"LAIA_DARKTABLE_APP": str(app)}, clear=False):
                with patch("core.projects.sale_items.subprocess.run") as run:
                    result = open_photo_edit("cld-3080", pending=True)
            command = run.call_args.args[0]
            self.assertEqual(command[0], str(app))
            self.assertEqual(len(command), 3)
            self.assertTrue(result["passed_pending_directly"])


if __name__ == "__main__":
    unittest.main()
