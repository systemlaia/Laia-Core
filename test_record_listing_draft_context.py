import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.appraisal_context import (
    build_listing_draft_context,
    command_listing_draft_context,
    write_listing_draft_context,
)
from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    init_sale_item,
    prepare_photo_edit,
    review_images,
    scan_exports,
    update_sale_item,
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


class RecordListingDraftContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def setup_project(self, project_id="record-001", category="records", filenames=None):
        filenames = filenames or ["DSCF7416.JPG", "DSCF7417.JPG"]
        ensure_project_record(project_id)
        export = self.root / f"{project_id}-export"
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
        init_sale_item(project_id, title="Gino Vannelli - A Pauper In Paradise", category=category)

    def approve_front_back(self, project_id="record-001"):
        prepare_photo_edit(project_id)
        assign_role(project_id, "DSCF7416.JPG", "cover_front")
        assign_role(project_id, "DSCF7417.JPG", "cover_back")
        exports = self.root / f"projects/{project_id}/photo_edit/exports"
        for filename in ["DSCF7416", "DSCF7417"]:
            (exports / f"{filename}.jpg").write_bytes(JPEG)
        scan_exports(project_id)
        review_images(project_id, ["DSCF7416.JPG", "DSCF7417.JPG"], "approved")

    def add_record_metadata(self):
        update_sale_item(
            "record-001",
            title="Gino Vannelli - A Pauper In Paradise",
            record_artist="Gino Vannelli",
            record_title="A Pauper In Paradise",
            record_label="A&M Records",
            catalog_number="SP-4664",
            grading_note=(
                "Spine reads GINO VANNELLI A PAUPER IN PARADISE A&M SP-4664 1977. "
                "A&M RECORDS, INC. PRINTED IN U.S.A."
            ),
        )

    def test_record_listing_draft_is_conservative_when_condition_and_price_missing(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()

        draft = build_listing_draft_context("record-001")

        self.assertEqual(draft["drafts"]["title"], "Gino Vannelli - A Pauper In Paradise LP - A&M SP-4664")
        self.assertFalse(draft["readiness"]["can_publish"])
        self.assertEqual(draft["readiness"]["state"], "needs_condition")
        self.assertIn("condition", draft["readiness"]["missing"])
        self.assertIn("asking_price", draft["readiness"]["missing"])
        self.assertEqual(draft["photo_evidence"]["roles"]["cover_front"], ["DSCF7416.JPG"])
        self.assertEqual(draft["photo_evidence"]["roles"]["cover_back"], ["DSCF7417.JPG"])
        self.assertIn("Playback not tested.", draft["safe_claims"])
        self.assertIn("Do not claim first pressing.", draft["avoid_claiming"])
        self.assertIn("Do not claim playback quality.", draft["avoid_claiming"])
        self.assertIn("Do not claim Near Mint/Excellent condition.", draft["avoid_claiming"])
        description = draft["drafts"]["full_description"].lower()
        for forbidden in ["rare", "first pressing", "near mint", "excellent", "collector copy"]:
            self.assertNotIn(forbidden, description)
        self.assertIn("Playback has not been tested.", draft["drafts"]["full_description"])
        self.assertIn("Media and sleeve condition are not yet graded.", draft["drafts"]["full_description"])
        self.assertIsNone(draft["pricing"]["suggested_asking_price"])
        self.assertEqual(draft["pricing"]["research_confidence"], "low")

    def test_writes_markdown_and_json(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()
        draft = build_listing_draft_context("record-001")

        paths = write_listing_draft_context("record-001", draft)

        self.assertEqual(paths["json"], str(self.root / "projects/record-001/listing/draft_context.json"))
        self.assertEqual(paths["md"], str(self.root / "projects/record-001/listing/draft.md"))
        markdown = Path(paths["md"]).read_text()
        self.assertIn("# Listing Draft: record-001", markdown)
        self.assertIn("Publish ready: no", markdown)
        self.assertIn("Gino Vannelli - A Pauper In Paradise LP - A&M SP-4664", markdown)
        self.assertIn("Media condition: not yet graded", markdown)
        self.assertIn("Pricing confidence: low", markdown)
        self.assertIn("- cover_front: DSCF7416.JPG", markdown)

    def test_condition_and_price_make_record_ready_basic(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()
        update_sale_item(
            "record-001",
            condition="fair",
            media_condition="Visual grade pending",
            sleeve_condition="Fair; visible shelf/ring wear from photos",
            asking_price="10.00",
            pricing_note="Placeholder local asking price pending better sold comps.",
        )

        draft = build_listing_draft_context("record-001")

        self.assertTrue(draft["readiness"]["can_publish"])
        self.assertEqual(draft["readiness"]["state"], "ready_basic")
        self.assertEqual(draft["readiness"]["missing"], [])
        self.assertIn("Pricing confidence low.", draft["readiness"]["warnings"])

    def test_cli_json_returns_valid_json(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            command_listing_draft_context(type("Args", (), {"identifier": "record-001", "json": True})())

        data = json.loads(output.getvalue())
        self.assertEqual(data["project"], "record-001")
        self.assertEqual(data["profile"], "records")

    def test_generic_fallback_works(self):
        self.setup_project("chair-001", "furniture", filenames=["A.JPG"])
        prepare_photo_edit("chair-001")
        assign_role("chair-001", "A.JPG", "front")
        exports = self.root / "projects/chair-001/photo_edit/exports"
        (exports / "A.jpg").write_bytes(JPEG)
        scan_exports("chair-001")
        review_images("chair-001", ["A.JPG"], "approved")

        draft = build_listing_draft_context("chair-001")

        self.assertEqual(draft["profile"], "generic")
        self.assertEqual(draft["category"], "furniture")
        self.assertFalse(draft["readiness"]["can_publish"])


if __name__ == "__main__":
    unittest.main()
