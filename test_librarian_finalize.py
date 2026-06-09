import json
import os
import tempfile
import unittest
from pathlib import Path

from core.librarian.finalize import (
    append_catalog_record,
    build_final,
    find_approved_unfinalized_packet,
    packet_id_for,
    write_final,
)


class LibrarianFinalizeTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        packet_type: str = "laia.ingest.scan",
        with_approval: bool = True,
        approval_status: str = "approved",
        name: str = "2026-06-07_171935_inbox",
        with_final: bool = False,
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / name
        packet_dir.mkdir(parents=True)

        packet = {
            "packet_type": packet_type,
            "created_at": "2026-06-07T17:19:35-07:00",
            "project": "Inbox",
            "page_count": 2,
            "paths": {
                "packet_dir": str(packet_dir),
            },
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet, indent=2), encoding="utf-8")

        index_dir = packet_dir / "index"
        index_dir.mkdir()
        index = {
            "index_type": "laia.librarian.index",
            "ocr_text_available": True,
            "text_stats": {
                "character_count": 120,
                "word_count": 20,
                "line_count": 4,
            },
        }
        (index_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

        summary_dir = packet_dir / "summary"
        summary_dir.mkdir()
        summary = {
            "summary_type": "laia.librarian.summary",
            "packet_type": packet_type,
            "project": "Inbox",
            "created_at": packet["created_at"],
            "page_count": 2,
            "word_count": 20,
            "ocr_status": "complete",
            "pdf_status": "created",
            "text_preview": "Receipt subtotal total tax paid by mastercard.",
        }
        (summary_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

        classify_dir = packet_dir / "classify"
        classify_dir.mkdir()
        classification = {
            "packet_type": packet_type,
            "project": "Inbox",
            "primary_category": "receipt",
            "categories": ["receipt"],
            "confidence": 0.9,
            "matched_keywords": {"receipt": ["receipt", "subtotal"]},
        }
        (classify_dir / "classification.json").write_text(json.dumps(classification), encoding="utf-8")

        review_dir = packet_dir / "review"
        review_dir.mkdir()
        review = {
            "review_type": "laia.librarian.review",
            "packet_type": packet_type,
            "project": "Inbox",
            "primary_category": "receipt",
            "confidence": 0.9,
            "review_status": "pending",
            "recommended_action": "approve_classification",
            "source_packet_dir": str(packet_dir),
        }
        (review_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")

        route_dir = packet_dir / "route"
        route_dir.mkdir()
        route = {
            "destination_packet_dir": str(root / "Archive" / "Ingest" / "Scans" / "inbox"),
            "status": "complete",
        }
        (route_dir / "route.json").write_text(json.dumps(route), encoding="utf-8")

        if with_approval:
            approval_dir = packet_dir / "approval"
            approval_dir.mkdir()
            approval = {
                "approval_type": "laia.librarian.approval",
                "packet_type": packet_type,
                "project": "Inbox",
                "approved_at": "2026-06-07T17:49:21-07:00",
                "review_status": approval_status,
                "approved_category": "receipt",
                "confidence": 0.9,
                "source_review_status": "pending",
                "recommended_action": "approve_classification",
                "source_packet_dir": str(packet_dir),
                "approved_by": "local_user",
            }
            (approval_dir / "approval.json").write_text(json.dumps(approval), encoding="utf-8")

        if with_final:
            final_dir = packet_dir / "final"
            final_dir.mkdir()
            (final_dir / "final.json").write_text('{"catalog_status": "finalized"}\n', encoding="utf-8")

        return packet_json

    def test_finalize_requires_approval_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_approval=False)

            with self.assertRaises(SystemExit):
                build_final(packet_json)

    def test_finalize_rejects_non_approved_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), approval_status="pending")

            with self.assertRaises(SystemExit):
                build_final(packet_json)

    def test_final_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            final = build_final(packet_json)
            final_json, final_md = write_final(packet_json, final)

            self.assertTrue(final_json.exists())
            self.assertTrue(final_md.exists())
            self.assertIn("# LAIA Ingest Final Record", final_md.read_text(encoding="utf-8"))

    def test_finalize_appends_to_catalog_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json = self.make_packet(root)
            final = build_final(packet_json)
            catalog_path = append_catalog_record(final, catalog_root=root / "Catalog")

            lines = catalog_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["packet_id"], "laia-scan-20260607-171935-inbox")
            self.assertNotIn("text_preview", record)

    def test_finalize_does_not_append_duplicate_catalog_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json = self.make_packet(root)
            final = build_final(packet_json)
            catalog_path = append_catalog_record(final, catalog_root=root / "Catalog")
            append_catalog_record(final, catalog_root=root / "Catalog")

            lines = catalog_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)

    def test_finalize_produces_deterministic_packet_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            packet = json.loads(packet_json.read_text(encoding="utf-8"))

            self.assertEqual(
                packet_id_for(packet_json, packet),
                "laia-scan-20260607-171935-inbox",
            )
            self.assertEqual(packet_id_for(packet_json, packet), packet_id_for(packet_json, packet))

    def test_finalize_preserves_packet_json_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            before = packet_json.read_text(encoding="utf-8")
            final = build_final(packet_json)
            write_final(packet_json, final)
            after = packet_json.read_text(encoding="utf-8")

            self.assertEqual(before, after)

    def test_rejects_non_laia_ingest_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), packet_type="external.scan")

            with self.assertRaises(SystemExit):
                build_final(packet_json)

    def test_finalize_ignores_already_finalized_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, name="2026-06-08_100000_receipts", with_final=True)
            pending = self.make_packet(root, name="2026-06-08_100100_receipts")

            selected = find_approved_unfinalized_packet(root / "Inbox" / "Ingest")

            self.assertEqual(selected, pending)

    def test_finalize_picks_newest_approved_unfinalized_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = self.make_packet(root, name="2026-06-08_100000_receipts")
            newer = self.make_packet(root, name="2026-06-08_100100_receipts")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))

            selected = find_approved_unfinalized_packet(root / "Inbox" / "Ingest")

            self.assertEqual(selected, newer)

    def test_finalize_fails_when_no_approved_unfinalized_packet_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, name="2026-06-08_100000_receipts", with_final=True)

            with self.assertRaisesRegex(SystemExit, "No approved unfinalized packet found to finalize"):
                find_approved_unfinalized_packet(root / "Inbox" / "Ingest")


if __name__ == "__main__":
    unittest.main()
