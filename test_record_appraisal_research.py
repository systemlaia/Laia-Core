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
    add_appraisal_research_entry,
    build_appraisal_research,
    command_appraisal_research,
    read_research,
    write_appraisal_research,
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


class RecordAppraisalResearchTests(unittest.TestCase):
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
        init_sale_item(project_id, title="Gino Vanelli - A Pauper In Paradise", category=category)

    def approve_front_back(self, project_id="record-001"):
        prepare_photo_edit(project_id)
        assign_role(project_id, "DSCF7416.JPG", "cover_front")
        assign_role(project_id, "DSCF7417.JPG", "cover_back")
        exports = self.root / f"projects/{project_id}/photo_edit/exports"
        for filename in ["DSCF7416", "DSCF7417"]:
            (exports / f"{filename}.jpg").write_bytes(JPEG)
        scan_exports(project_id)
        review_images(project_id, ["DSCF7416.JPG", "DSCF7417.JPG"], "approved")

    def test_empty_record_research_is_low_confidence_and_writes_files(self):
        self.setup_project()
        self.approve_front_back()

        research = build_appraisal_research("record-001")
        paths = write_appraisal_research("record-001", research)

        self.assertEqual(research["profile"], "records")
        self.assertEqual(research["research_status"]["entry_count"], 0)
        self.assertEqual(research["pricing_summary"]["confidence"], "low")
        self.assertIsNone(research["pricing_summary"]["suggested_asking_price"])
        self.assertIn("Pressing/version not confirmed", research["evidence_limits"])
        self.assertIn("Media condition missing", research["evidence_limits"])
        self.assertIn("Sleeve condition missing", research["evidence_limits"])
        self.assertTrue(Path(paths["json"]).is_file())
        self.assertTrue(Path(paths["md"]).is_file())

    def test_add_comparable_and_manual_note_increment_ids(self):
        self.setup_project()
        self.approve_front_back()

        comp, _paths = add_appraisal_research_entry(
            "record-001",
            source="Manual comparable",
            source_type="manual_note",
            price="10.00",
            currency="USD",
            match_confidence="low",
            price_confidence="low",
            note="Same artist/title observed, but pressing and condition not confirmed.",
        )
        note, _paths = add_appraisal_research_entry(
            "record-001",
            source="Human review",
            source_type="manual_note",
            note="Back cover confirms artist/title.",
            confidence="high",
        )
        second, _paths = add_appraisal_research_entry(
            "record-001",
            source="Discogs",
            source_type="discogs",
            price="12.00",
            sold="false",
            note="Another low confidence entry.",
        )

        research = read_research("record-001")
        self.assertEqual(comp["id"], "comp-001")
        self.assertEqual(note["id"], "note-001")
        self.assertEqual(second["id"], "comp-002")
        self.assertEqual(len(research["comparables"]), 2)
        self.assertEqual(len(research["manual_notes"]), 1)
        self.assertEqual(research["pricing_summary"]["confidence"], "low")
        self.assertIsNone(research["pricing_summary"]["suggested_asking_price"])

    def test_medium_high_sold_comps_produce_range_but_missing_condition_caps_confidence(self):
        self.setup_project()
        self.approve_front_back()
        for price in ["8.00", "14.00"]:
            add_appraisal_research_entry(
                "record-001",
                source="Sold comp",
                source_type="discogs",
                price=price,
                sold="true",
                match_confidence="medium",
                price_confidence="high",
                note="Sold comp with medium match.",
            )

        research = read_research("record-001")

        self.assertEqual(research["pricing_summary"]["confidence"], "medium")
        self.assertEqual(research["pricing_summary"]["low"], 8.0)
        self.assertEqual(research["pricing_summary"]["high"], 14.0)
        self.assertIsNone(research["pricing_summary"]["suggested_asking_price"])
        self.assertIn("condition missing", research["pricing_summary"]["warnings"])

    def test_markdown_includes_identity_guardrails_and_comparables_table(self):
        self.setup_project()
        self.approve_front_back()
        add_appraisal_research_entry(
            "record-001",
            source="Discogs",
            source_type="discogs",
            price="12.00",
            note="Same artist/title; pressing unknown.",
        )

        markdown = (self.root / "projects/record-001/appraisal/research.md").read_text()

        self.assertIn("# Appraisal Research: record-001", markdown)
        self.assertIn("Gino Vanelli - A Pauper In Paradise", markdown)
        self.assertIn("| comp-001 | Discogs | no | $12.00 USD | low | low | Same artist/title; pressing unknown. |", markdown)
        self.assertIn("Do not price as a collector pressing", markdown)

    def test_cli_json_returns_valid_json(self):
        self.setup_project()
        self.approve_front_back()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            command_appraisal_research(type("Args", (), {"identifier": "record-001", "json": True})())

        data = json.loads(output.getvalue())
        self.assertEqual(data["project"], "record-001")
        self.assertEqual(data["profile"], "records")

    def test_existing_research_refreshes_identity_and_preserves_entries(self):
        self.setup_project()
        self.approve_front_back()
        add_appraisal_research_entry(
            "record-001",
            source="Manual comparable",
            source_type="manual_note",
            price="10.00",
            note="Original comparable note keeps original text.",
        )
        add_appraisal_research_entry(
            "record-001",
            source="Human review",
            source_type="manual_note",
            note="Original manual note keeps original text.",
            confidence="high",
        )
        path = self.root / "projects/record-001/appraisal/research.json"
        stale = json.loads(path.read_text())
        stale["identity"] = {
            "artist": "Gino Vanelli",
            "title": "A Pauper In Paradise",
            "label": None,
            "catalog_number": None,
            "pressing": None,
            "matrix_runout": None,
        }
        stale["pricing_history"] = [{"confidence": "low"}]
        path.write_text(json.dumps(stale))
        update_sale_item(
            "record-001",
            title="Gino Vannelli - A Pauper In Paradise",
            record_artist="Gino Vannelli",
            record_label="A&M Records",
            catalog_number="SP-4664",
        )

        research = read_research("record-001")
        write_appraisal_research("record-001", research)
        saved = json.loads(path.read_text())

        self.assertEqual(saved["identity"]["artist"], "Gino Vannelli")
        self.assertEqual(saved["identity"]["label"], "A&M Records")
        self.assertEqual(saved["identity"]["catalog_number"], "SP-4664")
        self.assertEqual([entry["id"] for entry in saved["comparables"]], ["comp-001"])
        self.assertEqual([entry["id"] for entry in saved["manual_notes"]], ["note-001"])
        self.assertEqual(saved["pricing_history"], [{"confidence": "low"}])
        self.assertEqual(saved["comparables"][0]["notes"], "Original comparable note keeps original text.")

    def test_generic_fallback_works_for_non_record_category(self):
        self.setup_project("chair-001", "furniture", filenames=["A.JPG"])
        prepare_photo_edit("chair-001")
        assign_role("chair-001", "A.JPG", "front")
        exports = self.root / "projects/chair-001/photo_edit/exports"
        (exports / "A.jpg").write_bytes(JPEG)
        scan_exports("chair-001")
        review_images("chair-001", ["A.JPG"], "approved")

        research = build_appraisal_research("chair-001")

        self.assertEqual(research["profile"], "generic")
        self.assertEqual(research["category"], "furniture")
        self.assertEqual(research["pricing_summary"]["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
