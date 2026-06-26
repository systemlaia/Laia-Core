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
    build_appraisal_context,
    build_listing_draft_context,
    command_record_condition,
    read_research,
    read_record_condition,
    record_condition_update,
    write_record_condition,
)
from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    init_sale_item,
    load_sale_item,
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


class RecordConditionCaptureTests(unittest.TestCase):
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
            grading_note="Record is in a poly record sleeve. Spine reads GINO VANNELLI A PAUPER IN PARADISE A&M SP-4664.",
        )

    def test_empty_record_condition_defaults_and_writes_files(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()

        condition = read_record_condition("record-001")
        paths = write_record_condition("record-001", condition)

        self.assertEqual(condition["grading"]["overall_condition"], "unassessed")
        self.assertEqual(condition["grading"]["grading_standard"], "visual")
        self.assertFalse(condition["grading"]["playback_tested"])
        self.assertTrue(condition["grading"]["visual_grade_only"])
        self.assertEqual(condition["grading"]["confidence"], "low")
        self.assertTrue(condition["included_materials"]["poly_sleeve"])
        self.assertTrue(condition["sleeve_observations"]["spine_readable"])
        self.assertTrue(Path(paths["json"]).is_file())
        self.assertTrue(Path(paths["md"]).is_file())

    def test_update_writes_condition_and_sale_item_fields(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()

        condition, _paths = record_condition_update(
            "record-001",
            media_condition="VG",
            sleeve_condition="G+",
            condition="fair",
            grading_standard="visual",
            playback_tested="false",
            grading_note="Visual grade only; playback not tested. Sleeve has visible shelf/ring wear.",
            poly_sleeve="true",
            spine_readable="true",
            ring_wear="visible",
            shelf_wear="visible",
        )
        item = load_sale_item("record-001")

        self.assertEqual(condition["grading"]["media_condition"], "VG")
        self.assertEqual(condition["grading"]["sleeve_condition"], "G+")
        self.assertEqual(condition["grading"]["overall_condition"], "fair")
        self.assertEqual(condition["grading"]["confidence"], "medium")
        self.assertEqual(item["record_metadata"]["media_condition"], "VG")
        self.assertEqual(item["record_metadata"]["sleeve_condition"], "G+")
        self.assertEqual(item["condition"]["overall"], "fair")
        self.assertEqual(item["condition"]["functional"], "not_applicable")

    def test_downstream_context_research_and_draft_use_condition_capture(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()
        record_condition_update(
            "record-001",
            media_condition="Visual grade pending",
            sleeve_condition="Fair; visible shelf/ring wear from photos",
            condition="fair",
            grading_note="Visual grade only; playback not tested.",
            playback_tested="false",
        )

        context = build_appraisal_context("record-001")
        research = read_research("record-001")
        draft = build_listing_draft_context("record-001")

        self.assertEqual(context["condition"]["media_condition"], "Visual grade pending")
        self.assertEqual(context["condition"]["sleeve_condition"], "Fair; visible shelf/ring wear from photos")
        self.assertNotIn("Media condition missing", research["evidence_limits"])
        self.assertNotIn("Sleeve condition missing", research["evidence_limits"])
        self.assertIn("Playback not tested", research["evidence_limits"])
        self.assertFalse(draft["readiness"]["can_publish"])
        self.assertEqual(draft["readiness"]["state"], "needs_price")
        self.assertEqual(draft["readiness"]["missing"], ["asking_price"])

    def test_draft_ready_basic_after_condition_and_price(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()
        record_condition_update(
            "record-001",
            media_condition="Visual grade pending",
            sleeve_condition="Fair; visible shelf/ring wear from photos",
            condition="fair",
            playback_tested="false",
        )
        update_sale_item("record-001", asking_price="10.00")

        draft = build_listing_draft_context("record-001")

        self.assertTrue(draft["readiness"]["can_publish"])
        self.assertEqual(draft["readiness"]["state"], "ready_basic")

    def test_cli_json_returns_valid_json(self):
        self.setup_project()
        self.approve_front_back()
        self.add_record_metadata()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            command_record_condition(type("Args", (), {"identifier": "record-001", "json": True})())

        data = json.loads(output.getvalue())
        self.assertEqual(data["project"], "record-001")
        self.assertEqual(data["profile"], "records")

    def test_generic_project_fails_gracefully(self):
        self.setup_project("chair-001", "furniture", filenames=["A.JPG"])
        condition = read_record_condition("chair-001")
        self.assertEqual(condition["profile"], "generic")


if __name__ == "__main__":
    unittest.main()
