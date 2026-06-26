import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.appraisal_context import build_appraisal_context, write_appraisal_context
from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    init_sale_item,
    prepare_photo_edit,
    review_images,
    scan_exports,
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


class RecordAppraisalContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def setup_sale_project(self, project_id="record-001", category="records", filenames=None):
        filenames = filenames or ["DSCF7416.JPG", "DSCF7417.JPG"]
        ensure_project_record(project_id)
        export = self.root / f"{project_id}-cohort-export"
        files = export / "files"
        files.mkdir(parents=True)
        for name in filenames:
            (files / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            project_id,
            {
                "packet_id": "packet-one",
                "packet_path": str(self.root / "packet"),
                "cohort_id": project_id,
                "cohort_name": project_id,
                "cohort_path": str(self.root / "packet/cohort"),
                "cohort_status": "ready",
                "file_count": len(filenames),
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item(project_id, title="Gino Vanelli - A Pauper In Paradise", category=category)

    def approve_roles(self, project_id, roles):
        prepare_photo_edit(project_id)
        for filename, role in roles.items():
            assign_role(project_id, filename, role)
        exports = self.root / f"projects/{project_id}/photo_edit/exports"
        for filename in roles:
            (exports / f"{Path(filename).stem}.jpg").write_bytes(JPEG)
        scan_exports(project_id)
        review_images(project_id, list(roles.keys()), "approved")

    def test_record_context_with_front_and_back_evidence(self):
        self.setup_sale_project()
        self.approve_roles("record-001", {"DSCF7416.JPG": "cover_front", "DSCF7417.JPG": "cover_back"})

        context = build_appraisal_context("record-001")

        self.assertEqual(context["category"], "records")
        self.assertEqual(context["profile"], "records")
        self.assertEqual(context["identity"]["artist"], None)
        self.assertEqual(context["identity"]["title"], "Gino Vanelli - A Pauper In Paradise")
        coverage = context["evidence"]["photo_coverage"]
        self.assertEqual(coverage["cover_front"]["status"], "approved")
        self.assertEqual(coverage["cover_front"]["files"], ["DSCF7416.JPG"])
        self.assertEqual(coverage["cover_back"]["status"], "approved")
        self.assertEqual(coverage["label_a"]["status"], "missing")
        self.assertEqual(coverage["matrix"]["status"], "missing")
        self.assertTrue(context["evidence"]["minimum_listing_photos_met"])
        self.assertEqual(context["listing_readiness"]["photo_evidence"], "ready_basic")
        self.assertEqual(context["listing_readiness"]["condition"], "missing")
        self.assertEqual(context["listing_readiness"]["price"], "missing")
        self.assertEqual(context["listing_readiness"]["description"], "missing")
        self.assertEqual(context["listing_readiness"]["overall"], "not_ready")
        self.assertIn("Playback not tested.", context["safe_listing_language"])
        self.assertIn("Do not claim playback quality unless play-tested.", context["avoid_claiming"])
        self.assertIn("Specific pressing/version is not confirmed.", context["unverified_claims"])

    def test_record_metadata_identity_does_not_require_label_catalog_or_matrix(self):
        self.setup_sale_project()
        self.approve_roles("record-001", {"DSCF7416.JPG": "cover_front", "DSCF7417.JPG": "cover_back"})
        path = self.root / "projects/record-001/sale_item.json"
        item = json.loads(path.read_text())
        item["record_metadata"] = {"artist": "Gino Vanelli", "title": "A Pauper In Paradise"}
        path.write_text(json.dumps(item))

        context = build_appraisal_context("record-001")

        self.assertEqual(context["identity"]["artist"], "Gino Vanelli")
        self.assertEqual(context["identity"]["title"], "A Pauper In Paradise")
        self.assertEqual(context["identity"]["label"], None)
        self.assertEqual(context["identity"]["catalog_number"], None)
        self.assertEqual(context["identity"]["matrix_runout"], None)

    def test_writes_json_and_markdown_to_appraisal_directory(self):
        self.setup_sale_project()
        self.approve_roles("record-001", {"DSCF7416.JPG": "cover_front", "DSCF7417.JPG": "cover_back"})
        context = build_appraisal_context("record-001")

        paths = write_appraisal_context("record-001", context)

        json_path = self.root / "projects/record-001/appraisal/context.json"
        md_path = self.root / "projects/record-001/appraisal/context.md"
        self.assertEqual(paths["json"], str(json_path))
        self.assertEqual(paths["md"], str(md_path))
        self.assertEqual(json.loads(json_path.read_text())["profile"], "records")
        markdown = md_path.read_text()
        self.assertIn("# Appraisal Context: record-001", markdown)
        self.assertIn("| cover_front | approved | DSCF7416.JPG |", markdown)
        self.assertIn("| cover_back | approved | DSCF7417.JPG |", markdown)
        self.assertIn("Photo evidence: ready_basic", markdown)

    def test_generic_fallback_for_non_record_category(self):
        self.setup_sale_project("chair-001", "furniture", filenames=["A.JPG"])
        self.approve_roles("chair-001", {"A.JPG": "front"})

        context = build_appraisal_context("chair-001")

        self.assertEqual(context["profile"], "generic")
        self.assertEqual(context["category"], "furniture")
        self.assertEqual(context["evidence"]["approved_photo_count"], 1)
        self.assertIn("Category-specific appraisal rules are not configured.", context["unverified_claims"])


if __name__ == "__main__":
    unittest.main()
