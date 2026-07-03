import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.record_visual_identification import (
    command_record_identify_evaluate,
    compare_identity_field,
    evaluation_markdown_path,
    evaluation_path,
    record_identification_evaluation_with_paths,
    record_identify_visual,
    visual_candidate_path,
)
from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    init_sale_item,
    load_sale_item,
    package_photos,
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


class RecordVisualIdentificationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def setup_project(self, project_id="record-002"):
        ensure_project_record(project_id)
        export = self.root / f"{project_id}-export"
        files = export / "files"
        files.mkdir(parents=True)
        for name in ["DSCF7418.JPG", "DSCF7419.JPG"]:
            (files / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            project_id,
            {
                "packet_id": "packet-one",
                "cohort_id": project_id,
                "cohort_status": "ready",
                "file_count": 2,
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item(project_id, title="Unidentified Record 002", category="records")

    def approve_front_back(self, project_id="record-002"):
        prepare_photo_edit(project_id)
        assign_role(project_id, "DSCF7418.JPG", "cover_front")
        assign_role(project_id, "DSCF7419.JPG", "cover_back")
        exports = self.root / f"projects/{project_id}/photo_edit/exports"
        for filename in ["DSCF7418", "DSCF7419"]:
            (exports / f"{filename}.jpg").write_bytes(JPEG)
        scan_exports(project_id)
        review_images(project_id, ["DSCF7418.JPG", "DSCF7419.JPG"], "approved")
        package_photos(project_id)

    def write_candidate(self, **values):
        self.approve_front_back()
        payload = {
            "artist": values.get("artist"),
            "title": values.get("title"),
            "label": values.get("label"),
            "catalog_number": values.get("catalog_number"),
            "year": values.get("year"),
            "format": "LP",
            "visible_text": values.get("visible_text", []),
            "front_cover_observations": values.get("front_cover_observations", []),
            "back_cover_observations": values.get("back_cover_observations", []),
            "spine_observations": [],
            "uncertain_text": [],
            "confidence": values.get("confidence", "low"),
        }
        return record_identify_visual("record-002", runner=lambda model, prompt, images: json.dumps(payload))

    def confirm_identity(self, artist="Gino Vannelli", title="A Pauper In Paradise", label="A&M Records", catalog="SP-4664", year=None):
        item = update_sale_item(
            "record-002",
            title=f"{artist} - {title}",
            category="records",
            functional_status="not_applicable",
            record_artist=artist,
            record_title=title,
            record_label=label,
            catalog_number=catalog,
        )
        if year is not None:
            item.setdefault("record_metadata", {})["year"] = year
            from core.projects.sale_items import write_sale_item
            write_sale_item("record-002", item)

    def test_fails_cleanly_when_no_candidate_exists(self):
        self.setup_project()
        self.confirm_identity()

        with self.assertRaises(FileNotFoundError) as raised:
            record_identification_evaluation_with_paths("record-002")

        self.assertIn("No visual identification candidate found", str(raised.exception))

    def test_fails_cleanly_when_no_confirmed_artist_title_exists(self):
        self.setup_project()
        self.write_candidate(artist="Gino Vannelli", title="A Pauper In Paradise")

        with self.assertRaises(ValueError) as raised:
            record_identification_evaluation_with_paths("record-002")

        self.assertIn("No confirmed record identity available", str(raised.exception))

    def test_evaluates_exact_matches(self):
        self.setup_project()
        self.write_candidate(artist="Gino Vannelli", title="A Pauper In Paradise", label="A&M Records", catalog_number="SP-4664", confidence="medium")
        self.confirm_identity()

        evaluation, _paths = record_identification_evaluation_with_paths("record-002")

        self.assertEqual(evaluation["field_results"]["artist"]["result"], "match")
        self.assertEqual(evaluation["field_results"]["title"]["result"], "match")
        self.assertEqual(evaluation["summary"]["overall_result"], "strong")
        self.assertEqual(evaluation["summary"]["model_utility"], "high")

    def test_evaluates_partial_matches(self):
        result = compare_identity_field("Pauper Paradise", "A Pauper In Paradise")

        self.assertEqual(result["result"], "partial")

    def test_evaluates_missing_candidate_fields(self):
        self.setup_project()
        self.write_candidate(artist=None, title=None)
        self.confirm_identity()

        evaluation, _paths = record_identification_evaluation_with_paths("record-002")

        self.assertEqual(evaluation["field_results"]["artist"]["result"], "missing")
        self.assertEqual(evaluation["field_results"]["title"]["result"], "missing")
        self.assertIn("artist_missing", evaluation["failure_modes"])

    def test_evaluates_incorrect_candidate_fields(self):
        self.setup_project()
        self.write_candidate(artist="George Benson", title="In Flight", label="RCA RECORDS", catalog_number="AFL1-5096")
        self.confirm_identity()

        evaluation, _paths = record_identification_evaluation_with_paths("record-002")

        self.assertEqual(evaluation["field_results"]["artist"]["result"], "incorrect")
        self.assertEqual(evaluation["field_results"]["title"]["result"], "incorrect")
        self.assertEqual(evaluation["summary"]["overall_result"], "poor")
        self.assertIn("artist_incorrect", evaluation["failure_modes"])
        self.assertIn("low_confidence", evaluation["failure_modes"])

    def test_does_not_punish_unconfirmed_fields(self):
        self.setup_project()
        self.write_candidate(artist="Gino Vannelli", title="A Pauper In Paradise", label="A&M Records", catalog_number="SP-4664")
        self.confirm_identity(label="", catalog="")

        evaluation, _paths = record_identification_evaluation_with_paths("record-002")

        self.assertEqual(evaluation["field_results"]["label"]["result"], "unconfirmed")
        self.assertEqual(evaluation["field_results"]["catalog_number"]["result"], "unconfirmed")
        self.assertIn("candidate_unverified_claims", evaluation["failure_modes"])

    def test_writes_evaluation_json_and_markdown(self):
        self.setup_project()
        self.write_candidate(artist="Gino Vannelli", title=None, visible_text=["A&M Records"])
        self.confirm_identity()

        evaluation, paths = record_identification_evaluation_with_paths("record-002")
        markdown = evaluation_markdown_path("record-002").read_text()

        self.assertTrue(Path(paths["json"]).is_file())
        self.assertTrue(Path(paths["md"]).is_file())
        self.assertTrue(evaluation_path("record-002").is_file())
        self.assertIn("| Field | Candidate | Confirmed | Result |", markdown)
        self.assertIn("Keep visual candidates non-authoritative.", markdown)
        self.assertEqual(evaluation["summary"]["human_review_required"], True)

    def test_cli_json_returns_valid_json(self):
        self.setup_project()
        self.write_candidate(artist="Gino Vannelli", title="A Pauper In Paradise")
        self.confirm_identity()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            command_record_identify_evaluate(type("Args", (), {"identifier": "record-002", "json": True})())

        data = json.loads(output.getvalue())
        self.assertEqual(data["project"], "record-002")
        self.assertIn("summary", data)

    def test_low_confidence_candidate_produces_low_utility_unless_strong(self):
        self.setup_project()
        self.write_candidate(artist="Gino Vannelli", title=None, confidence="low")
        self.confirm_identity()

        evaluation, _paths = record_identification_evaluation_with_paths("record-002")

        self.assertEqual(evaluation["candidate_source"]["candidate_confidence"], "low")
        self.assertEqual(evaluation["summary"]["model_utility"], "low")

    def test_candidate_and_sale_item_metadata_remain_unchanged(self):
        self.setup_project()
        self.write_candidate(artist="George Benson", title="In Flight")
        self.confirm_identity()
        before_candidate = visual_candidate_path("record-002").read_text()
        before_item = json.dumps(load_sale_item("record-002"), sort_keys=True)

        record_identification_evaluation_with_paths("record-002")

        after_candidate = visual_candidate_path("record-002").read_text()
        after_item = json.dumps(load_sale_item("record-002"), sort_keys=True)
        self.assertEqual(before_candidate, after_candidate)
        self.assertEqual(before_item, after_item)


if __name__ == "__main__":
    unittest.main()
