import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.appraisal_context import build_appraisal_context, build_appraisal_research
from core.projects.record_identity_evidence import (
    add_record_identity_evidence,
    command_record_identity_evidence,
    identity_evidence_markdown_path,
    identity_evidence_path,
    read_record_identity_evidence,
    write_record_identity_evidence,
)
from core.projects.record_visual_identification import (
    record_identification_evaluation_with_paths,
    record_identify_visual,
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


class RecordIdentityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def setup_project(self, project_id="record-003"):
        ensure_project_record(project_id)
        export = self.root / f"{project_id}-export"
        files = export / "files"
        files.mkdir(parents=True)
        for name in ["DSCF7420.JPG", "DSCF7421.JPG"]:
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
        init_sale_item(project_id, title="Earth, Wind & Fire - Spirit", category="records")
        update_sale_item(
            project_id,
            title="Earth, Wind & Fire - Spirit",
            category="records",
            functional_status="not_applicable",
            record_artist="Earth, Wind & Fire",
            record_title="Spirit",
            record_label="Columbia",
            catalog_number="PC 34241",
        )

    def approve_front_back(self, project_id="record-003"):
        prepare_photo_edit(project_id)
        assign_role(project_id, "DSCF7420.JPG", "cover_front")
        assign_role(project_id, "DSCF7421.JPG", "cover_back")
        exports = self.root / f"projects/{project_id}/photo_edit/exports"
        for filename in ["DSCF7420", "DSCF7421"]:
            (exports / f"{filename}.jpg").write_bytes(JPEG)
        scan_exports(project_id)
        review_images(project_id, ["DSCF7420.JPG", "DSCF7421.JPG"], "approved")
        package_photos(project_id)

    def write_llava_candidate(self, **values):
        self.approve_front_back()
        payload = {
            "artist": values.get("artist"),
            "title": values.get("title"),
            "label": values.get("label"),
            "catalog_number": values.get("catalog_number"),
            "format": "LP",
            "visible_text": values.get("visible_text", []),
            "front_cover_observations": values.get("front_cover_observations", []),
            "back_cover_observations": values.get("back_cover_observations", []),
            "spine_observations": [],
            "uncertain_text": [],
            "confidence": values.get("confidence", "low"),
        }
        record_identify_visual("record-003", runner=lambda model, prompt, images: json.dumps(payload))

    def add_spirit_evidence(self):
        add_record_identity_evidence(
            "record-003",
            field="artist",
            value="Earth, Wind & Fire",
            source_type="approved_photo",
            visibility="clearly_visible",
            confidence="confirmed",
            note="Front cover text clearly shows Earth, Wind & Fire.",
        )
        add_record_identity_evidence(
            "record-003",
            field="title",
            value="Spirit",
            source_type="approved_photo",
            visibility="clearly_visible",
            confidence="confirmed",
            note="Front cover text clearly shows Spirit.",
        )
        add_record_identity_evidence(
            "record-003",
            field="label",
            value="Columbia",
            source_type="approved_photo",
            visibility="partially_visible",
            confidence="high",
            note="Columbia logo appears on back cover.",
        )
        add_record_identity_evidence(
            "record-003",
            field="catalog_number",
            value="PC 34241",
            source_type="physical_inspection",
            visibility="not_readable_in_current_photos",
            confidence="confirmed",
            note="Confirmed by physically holding the record.",
        )

    def test_creates_empty_identity_evidence_for_record_project(self):
        self.setup_project()

        evidence = read_record_identity_evidence("record-003")
        paths = write_record_identity_evidence("record-003", evidence)

        self.assertEqual(evidence["project"], "record-003")
        self.assertEqual(evidence["category"], "records")
        self.assertEqual(evidence["field_evidence"], {})
        self.assertTrue(Path(paths["json"]).is_file())
        self.assertTrue(Path(paths["md"]).is_file())

    def test_adds_field_evidence_and_writes_files(self):
        self.setup_project()

        entry, paths = add_record_identity_evidence(
            "record-003",
            field="catalog_number",
            value="PC 34241",
            source_type="physical_inspection",
            visibility="not_readable_in_current_photos",
            confidence="confirmed",
            note="Confirmed by physically holding the record.",
        )

        evidence = read_record_identity_evidence("record-003")
        self.assertEqual(entry["source_type"], "physical_inspection")
        self.assertEqual(evidence["identity"]["catalog_number"], "PC 34241")
        self.assertTrue(identity_evidence_path("record-003").is_file())
        self.assertTrue(identity_evidence_markdown_path("record-003").is_file())
        self.assertTrue(Path(paths["json"]).is_file())

    def test_supports_required_source_types_and_visibility_values(self):
        self.setup_project()

        for source_type in ["approved_photo", "physical_inspection", "external_catalog", "llava_candidate"]:
            add_record_identity_evidence(
                "record-003",
                field="front_cover_text",
                value=source_type,
                source_type=source_type,
                visibility="externally_supported" if source_type == "external_catalog" else "clearly_visible",
                confidence="high",
                note=f"Evidence from {source_type}.",
            )

        evidence = read_record_identity_evidence("record-003")
        self.assertEqual(len(evidence["field_evidence"]["front_cover_text"]), 4)

    def test_source_quality_summary_groups_fields(self):
        self.setup_project()
        self.add_spirit_evidence()

        evidence = read_record_identity_evidence("record-003")
        summary = evidence["source_quality_summary"]

        self.assertEqual(summary["photo_supported_fields"], ["artist", "label", "title"])
        self.assertEqual(summary["physical_inspection_supported_fields"], ["catalog_number"])
        self.assertIn("pressing", summary["unconfirmed_fields"])
        self.assertIn("matrix_runout", summary["fields_needing_better_photos"])
        self.assertIn("catalog_number", summary["fields_needing_better_photos"])

    def test_markdown_includes_evidence_table_and_summary(self):
        self.setup_project()
        self.add_spirit_evidence()

        markdown = identity_evidence_markdown_path("record-003").read_text()

        self.assertIn("# Record Identity Evidence: record-003", markdown)
        self.assertIn("| catalog_number | PC 34241 | physical_inspection | not_readable_in_current_photos | confirmed |", markdown)
        self.assertIn("Physical-inspection-supported fields:", markdown)

    def test_cli_json_returns_valid_json(self):
        self.setup_project()
        self.add_spirit_evidence()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            command_record_identity_evidence(type("Args", (), {"identifier": "record-003", "json": True})())

        data = json.loads(output.getvalue())
        self.assertEqual(data["identity"]["catalog_number"], "PC 34241")

    def test_appraisal_context_includes_identity_evidence_summary(self):
        self.setup_project()
        self.add_spirit_evidence()

        context = build_appraisal_context("record-003")

        summary = context["evidence"]["identity_evidence_summary"]
        self.assertTrue(any("Catalog number: PC 34241" in line for line in summary))

    def test_appraisal_research_notes_physical_catalog_limit(self):
        self.setup_project()
        self.add_spirit_evidence()

        research = build_appraisal_research("record-003")

        self.assertIn("Catalog number confirmed by physical inspection, not by current photos", research["evidence_limits"])

    def test_evaluation_uses_source_visibility_for_not_readable_catalog(self):
        self.setup_project()
        self.add_spirit_evidence()
        self.write_llava_candidate(artist="Earth Wind & Fire", title=None, catalog_number=None, visible_text=["Earth Wind & Fire", "21"])

        evaluation, _paths = record_identification_evaluation_with_paths("record-003")

        catalog = evaluation["field_results"]["catalog_number"]
        self.assertEqual(catalog["result"], "missing")
        self.assertEqual(catalog["source_visibility"], "not_readable_in_current_photos")
        self.assertFalse(catalog["model_expected_to_read"])
        self.assertIn("catalog_number_missing_not_readable", evaluation["failure_modes"])

    def test_clearly_visible_title_miss_remains_normal_failure(self):
        self.setup_project()
        self.add_spirit_evidence()
        self.write_llava_candidate(artist="Earth Wind & Fire", title=None, catalog_number=None)

        evaluation, _paths = record_identification_evaluation_with_paths("record-003")

        title = evaluation["field_results"]["title"]
        self.assertEqual(title["result"], "missing")
        self.assertTrue(title["model_expected_to_read"])
        self.assertIn("title_missing", evaluation["failure_modes"])

    def test_sale_item_metadata_is_not_overwritten_by_evidence_add(self):
        self.setup_project()
        before = json.dumps(load_sale_item("record-003"), sort_keys=True)

        add_record_identity_evidence(
            "record-003",
            field="catalog_number",
            value="DIFFERENT",
            source_type="external_catalog",
            visibility="externally_supported",
            confidence="medium",
            note="External catalog candidate only.",
        )

        after = json.dumps(load_sale_item("record-003"), sort_keys=True)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
