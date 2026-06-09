import json
import tempfile
import unittest
from pathlib import Path

from core.librarian.review import build_review, write_review


class LibrarianReviewTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        packet_type: str = "laia.ingest.scan",
        with_index: bool = True,
        with_summary: bool = True,
        with_classification: bool = True,
        with_route: bool = True,
        primary_category: str = "receipt",
        confidence: float = 0.9,
        ocr_text_available: bool = True,
        ocr_status: str = "complete",
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / "2026-06-07_171935_inbox"
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
        packet_json.write_text(json.dumps(packet), encoding="utf-8")

        if with_index:
            index_dir = packet_dir / "index"
            index_dir.mkdir()
            index = {
                "index_type": "laia.librarian.index",
                "ocr_text_available": ocr_text_available,
                "text_stats": {
                    "character_count": 120,
                    "word_count": 20,
                    "line_count": 4,
                },
            }
            (index_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

        if with_summary:
            summary_dir = packet_dir / "summary"
            summary_dir.mkdir()
            summary = {
                "summary_type": "laia.librarian.summary",
                "packet_type": packet_type,
                "project": "Inbox",
                "created_at": packet["created_at"],
                "page_count": 2,
                "word_count": 20,
                "ocr_status": ocr_status,
                "pdf_status": "created",
                "text_preview": "Receipt subtotal total tax paid by mastercard.",
            }
            (summary_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

        if with_classification:
            classify_dir = packet_dir / "classify"
            classify_dir.mkdir()
            matched = {"receipt": ["receipt", "subtotal"]} if primary_category != "unknown" else {}
            categories = [primary_category] if primary_category != "unknown" else []
            classification = {
                "packet_type": packet_type,
                "project": "Inbox",
                "primary_category": primary_category,
                "categories": categories,
                "confidence": confidence,
                "matched_keywords": matched,
                "rules_version": "scan-keywords-v0",
                "source_packet_dir": str(packet_dir),
            }
            (classify_dir / "classification.json").write_text(json.dumps(classification), encoding="utf-8")

        if with_route:
            route_dir = packet_dir / "route"
            route_dir.mkdir()
            route = {
                "destination_packet_dir": str(root / "Archive" / "Ingest" / "Scans" / "inbox"),
                "status": "complete",
            }
            (route_dir / "route.json").write_text(json.dumps(route), encoding="utf-8")

        return packet_json

    def test_review_requires_index_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_index=False)

            with self.assertRaises(SystemExit):
                build_review(packet_json)

    def test_review_requires_summary_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_summary=False)

            with self.assertRaises(SystemExit):
                build_review(packet_json)

    def test_review_requires_classification_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_classification=False)

            with self.assertRaises(SystemExit):
                build_review(packet_json)

    def test_review_works_with_route_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_route=True)
            review = build_review(packet_json)

            self.assertTrue(review["routed"])
            self.assertIn("Archive/Ingest/Scans/inbox", review["destination_packet_dir"])

    def test_review_works_without_route_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_route=False)
            review = build_review(packet_json)

            self.assertFalse(review["routed"])
            self.assertEqual(review["destination_packet_dir"], "")

    def test_high_confidence_recommends_approve_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), primary_category="receipt", confidence=0.9)
            review = build_review(packet_json)

            self.assertEqual(review["recommended_action"], "approve_classification")

    def test_unknown_recommends_manual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), primary_category="unknown", confidence=0.0)
            review = build_review(packet_json)

            self.assertEqual(review["recommended_action"], "manual_review")

    def test_missing_ocr_recommends_rescan_or_manual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(
                Path(tmp),
                ocr_text_available=False,
                ocr_status="missing",
                primary_category="receipt",
                confidence=0.9,
            )
            review = build_review(packet_json)

            self.assertEqual(review["recommended_action"], "rescan_or_manual_review")

    def test_review_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            review = build_review(packet_json)
            review_md, review_json = write_review(packet_json, review)

            self.assertTrue(review_md.exists())
            self.assertTrue(review_json.exists())
            self.assertIn("# LAIA Ingest Review", review_md.read_text(encoding="utf-8"))

    def test_rejects_non_laia_ingest_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), packet_type="external.scan")

            with self.assertRaises(SystemExit):
                build_review(packet_json)


if __name__ == "__main__":
    unittest.main()
