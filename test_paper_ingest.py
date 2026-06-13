import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from core.paper_ingest.standardize import (
    PAPER_PACKET_TYPE,
    build_workflow_state,
    state_sidecar_path,
    standardize_packet,
    verify_packet,
    write_workflow_state,
)
from core.packets.standard import count_checksum_entries, read_packet_manifest, validate_required_items
from core.packets.registry import PAPER_REQUIRED_ITEMS


class PaperPacketStandardTests(unittest.TestCase):
    def make_packet(self, root):
        packet = Path(root) / "2026" / "paper-job"
        originals = packet / "originals"
        source = packet / "source"
        logs = packet / "logs"
        originals.mkdir(parents=True)
        source.mkdir()
        logs.mkdir()
        (originals / "page_0001.tif").write_bytes(b"page one")
        (originals / "page_0002.tif").write_bytes(b"page two")
        (source / "page_0001.tif").write_bytes(b"legacy page")
        (logs / "scanimage.log").write_text("ok\n", encoding="utf-8")
        (packet / "packet.json").write_text(
            json.dumps(
                {
                    "packet_type": "laia.ingest.scan",
                    "created_at": "2026-06-10T18:42:34-07:00",
                    "device_label": "CANON DR-3010C",
                    "source": "ADF Duplex",
                    "page_count": 2,
                    "paths": {"packet_dir": str(packet), "source_dir": str(source)},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return packet

    def write_sidecar(self, packet, rel, data=None):
        path = packet / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data or {"status": "ok"}) + "\n", encoding="utf-8")
        return path

    def test_paper_packet_manifest_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            result = standardize_packet(packet)
            manifest = read_packet_manifest(packet)

            self.assertTrue(result["manifest_written"])
            self.assertEqual(manifest["packet_type"], PAPER_PACKET_TYPE)
            self.assertEqual(manifest["packet_version"], "0.1")
            self.assertEqual(manifest["job_id"], packet.name)
            self.assertEqual(manifest["page_count"], 2)
            self.assertEqual(manifest["asset_count"], 2)
            self.assertEqual(manifest["ingest_node"], "CANON DR-3010C")

    def test_paper_checksum_generation_and_counting(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            standardize_packet(packet)

            checksum_file = packet / "checksums.sha256"
            self.assertTrue(checksum_file.exists())
            self.assertEqual(count_checksum_entries(checksum_file), 2)
            self.assertIn("./page_0001.tif", checksum_file.read_text(encoding="utf-8"))

    def test_paper_required_item_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            standardize_packet(packet)
            validation = validate_required_items(packet, PAPER_REQUIRED_ITEMS)

            self.assertTrue(validation.ok)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_packet(packet), 0)

    def test_standardize_does_not_overwrite_existing_manifest_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            manifest_path = packet / "packet_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "packet_type": "laia.paper_ingest",
                        "packet_version": "0.1",
                        "job_id": "custom-id",
                        "source": "custom-source",
                        "packet_path": str(packet),
                        "page_count": 99,
                        "created_at": "2026-01-01T00:00:00Z",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            standardize_packet(packet)
            self.assertEqual(read_packet_manifest(packet)["job_id"], "custom-id")

            standardize_packet(packet, force=True)
            self.assertEqual(read_packet_manifest(packet)["job_id"], packet.name)

    def test_classification_sidecar_maps_to_classified_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "classify/classification.json", {"category": "receipt"})

            state = build_workflow_state(packet)

            self.assertEqual(state["workflow_status"], "classified")
            self.assertEqual(state["review_status"], "new")
            self.assertEqual(state["classification_category"], "receipt")

    def test_extract_sidecar_maps_to_extracted_in_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "classify/classification.json")
            self.write_sidecar(packet, "extract/extract.json")

            state = build_workflow_state(packet)

            self.assertEqual(state["workflow_status"], "extracted")
            self.assertEqual(state["review_status"], "in_review")

    def test_summary_sidecar_maps_to_summarized_in_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "summary/summary.json")

            state = build_workflow_state(packet)

            self.assertEqual(state["workflow_status"], "summarized")
            self.assertEqual(state["review_status"], "in_review")

    def test_review_sidecar_maps_to_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "review/review.json")

            state = build_workflow_state(packet)

            self.assertEqual(state["workflow_status"], "reviewed")
            self.assertEqual(state["review_status"], "reviewed")

    def test_approval_sidecar_maps_to_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "approval/approval.json", {"approved_category": "receipt"})

            state = build_workflow_state(packet)

            self.assertEqual(state["workflow_status"], "approved")
            self.assertEqual(state["review_status"], "approved")
            self.assertEqual(state["approved_category"], "receipt")

    def test_final_sidecar_maps_to_finalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "final/final.json", {"document_type": "receipt"})

            state = build_workflow_state(packet)

            self.assertEqual(state["workflow_status"], "finalized")
            self.assertEqual(state["review_status"], "finalized")
            self.assertEqual(state["document_type"], "receipt")

    def test_failure_sidecar_overrides_final_and_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "approval/approval.json")
            self.write_sidecar(packet, "final/final.json")
            self.write_sidecar(packet, "failure/failure.json")

            state = build_workflow_state(packet)

            self.assertEqual(state["workflow_status"], "failed")
            self.assertEqual(state["review_status"], "failed")

    def test_correction_sidecar_sets_classification_corrected_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "classify/classification.json")
            self.write_sidecar(packet, "classify/correction.json")

            state = build_workflow_state(packet)

            self.assertTrue(state["classification_corrected"])

    def test_standardize_writes_paper_workflow_state_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)
            self.write_sidecar(packet, "approval/approval.json")

            result = standardize_packet(packet)

            self.assertTrue(state_sidecar_path(packet).exists())
            self.assertEqual(result["workflow_state"]["workflow_status"], "approved")
            self.assertEqual(write_workflow_state(packet)["review_status"], "approved")


if __name__ == "__main__":
    unittest.main()
