import json
import os
import tempfile
import unittest
from pathlib import Path

from core.photo_ingest.cohorts import add_files, cohort_dir, create_cohort, read_cohort
from core.photo_ingest.record_vision import create_record_pair_cohorts, suggest_record_pairs
from core.projects.appraisal_context import listing_draft_context_path
from core.projects.registry import ensure_project_record
from core.projects.sale_items import bootstrap_record_sale_items_from_cohorts, edit_manifest_path, load_sale_item


class RecordBatchSplitTests(unittest.TestCase):
    def make_packet(self, root: Path, count: int = 7) -> Path:
        packet = root / "20260610-184234_DSD_sd_ingest"
        (packet / "originals/246_FUJI").mkdir(parents=True)
        (packet / "review").mkdir()
        files = []
        for number in range(7416, 7416 + count):
            relative = f"246_FUJI/DSCF{number}.JPG"
            (packet / "originals" / relative).write_bytes(b"image")
            files.append(relative)
        create_cohort(packet, "Records for sale")
        add_files(packet, "records-for-sale", files)
        create_cohort(
            packet,
            "Record 001",
            parent="records-for-sale",
            status="ready",
            cohort_id="record-001",
            description="Existing record.",
        )
        add_files(packet, "record-001", files[:2])
        return packet

    def test_suggests_pairs_with_boundaries_existing_detection_and_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            result = suggest_record_pairs(
                packet,
                "records-for-sale",
                start="246_FUJI/DSCF7416.JPG",
                end="246_FUJI/DSCF7422.JPG",
                mode="pairs",
            )
            self.assertEqual([item["id"] for item in result["suggestions"]], ["record-001", "record-002", "record-003"])
            self.assertEqual(result["suggestions"][0]["status"], "exists")
            self.assertEqual(result["suggestions"][1]["roles"]["246_FUJI/DSCF7418.JPG"], "cover_front")
            self.assertTrue(any("Odd trailing file" in warning for warning in result["warnings"]))
            self.assertTrue((cohort_dir(packet, "records-for-sale") / "records/pair_suggestions.json").is_file())
            self.assertTrue((cohort_dir(packet, "records-for-sale") / "records/pair_suggestions.md").is_file())

    def test_creates_child_pair_cohorts_and_skips_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp), count=6)
            suggest_record_pairs(packet, "records-for-sale")
            result = create_record_pair_cohorts(
                packet,
                "records-for-sale",
                limit=2,
                mark_ready=True,
                export=True,
                contact_sheets=True,
            )
            self.assertEqual([item["cohort_id"] for item in result["created"]], ["record-002"])
            self.assertEqual(result["skipped"][0]["id"], "record-001")
            self.assertEqual(result["skipped"][0]["reason"], "already exists")
            record_001 = read_cohort(packet, "record-001")
            record_002 = read_cohort(packet, "record-002")
            self.assertEqual([row["relative_path"] for row in record_001["files"]], ["246_FUJI/DSCF7416.JPG", "246_FUJI/DSCF7417.JPG"])
            self.assertEqual([row["relative_path"] for row in record_002["files"]], ["246_FUJI/DSCF7418.JPG", "246_FUJI/DSCF7419.JPG"])
            self.assertEqual(record_002["status"], "ready")
            self.assertTrue(Path(result["exports"][0]["destination"]).is_dir())
            self.assertTrue(Path(result["contact_sheets"][0]["path"]).is_file())

    def test_bootstraps_unidentified_sale_item_project_scaffolds_and_photo_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root, count=6)
            project_root = root / "projects"
            export_root = root / "exports"
            old_project_root = os.environ.get("LAIA_PROJECT_REGISTRY_ROOT")
            old_export_root = os.environ.get("LAIA_PHOTO_COHORT_EXPORT_ROOT")
            os.environ["LAIA_PROJECT_REGISTRY_ROOT"] = str(project_root)
            os.environ["LAIA_PHOTO_COHORT_EXPORT_ROOT"] = str(export_root)
            try:
                ensure_project_record("record-001", project_type="sale_item")
                suggest_record_pairs(packet, "records-for-sale")
                create_record_pair_cohorts(packet, "records-for-sale", limit=2, mark_ready=True, export=True)
                result = bootstrap_record_sale_items_from_cohorts(
                    str(packet),
                    parent="records-for-sale",
                    prefix="record",
                    limit=2,
                    skip_existing=True,
                    prepare_photo_edit_workspace=True,
                    appraisal_context=True,
                    condition=True,
                    listing_draft=True,
                )
                self.assertEqual([item["project_id"] for item in result["created"]], ["record-002"])
                self.assertEqual(result["skipped"][0]["cohort_id"], "record-001")
                item = load_sale_item("record-002")
                self.assertEqual(item["category"], "records")
                self.assertEqual(item["condition"]["functional"], "not_applicable")
                self.assertIn(item["sale"]["status"], {"photos_ready", "photos_in_progress"})
                self.assertEqual(item["title"], "Unidentified Record 002")
                self.assertEqual(item["record_metadata"]["artist"], "")
                self.assertEqual(item["record_metadata"]["title"], "")
                manifest = json.loads(edit_manifest_path("record-002").read_text())
                roles = {image["role"] for image in manifest["images"]}
                self.assertEqual(roles, {"cover_front", "cover_back"})
                self.assertEqual(manifest["approved_count"], 0)
                self.assertTrue((project_root / "record-002/appraisal/context.json").is_file())
                self.assertTrue((project_root / "record-002/appraisal/condition.json").is_file())
                self.assertTrue(listing_draft_context_path("record-002").is_file())
            finally:
                if old_project_root is None:
                    os.environ.pop("LAIA_PROJECT_REGISTRY_ROOT", None)
                else:
                    os.environ["LAIA_PROJECT_REGISTRY_ROOT"] = old_project_root
                if old_export_root is None:
                    os.environ.pop("LAIA_PHOTO_COHORT_EXPORT_ROOT", None)
                else:
                    os.environ["LAIA_PHOTO_COHORT_EXPORT_ROOT"] = old_export_root


if __name__ == "__main__":
    unittest.main()
