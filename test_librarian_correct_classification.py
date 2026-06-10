import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.librarian.approve import build_approval, write_approval
from core.librarian.correct_classification import (
    build_correction,
    command_correct_classification,
    find_packet_by_id,
    write_correction,
)
from core.librarian.finalize import append_catalog_record, build_final


class LibrarianCorrectClassificationTests(unittest.TestCase):
    def make_packet(self, root: Path, *, with_classification: bool = True):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / "2026-06-09_182954_mailinbox"
        packet_dir.mkdir(parents=True)
        packet = {
            "packet_type": "laia.ingest.scan",
            "created_at": "2026-06-09T18:29:54-07:00",
            "project": "MailInbox",
            "page_count": 1,
            "paths": {"packet_dir": str(packet_dir)},
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet, indent=2), encoding="utf-8")

        index_dir = packet_dir / "index"
        index_dir.mkdir()
        (index_dir / "index.json").write_text(
            json.dumps({"text_stats": {"word_count": 42}}),
            encoding="utf-8",
        )
        summary_dir = packet_dir / "summary"
        summary_dir.mkdir()
        (summary_dir / "summary.json").write_text(
            json.dumps({"page_count": 1, "word_count": 42, "ocr_status": "complete", "pdf_status": "created"}),
            encoding="utf-8",
        )
        classify_dir = packet_dir / "classify"
        classify_dir.mkdir()
        classification = {
            "packet_type": "laia.ingest.scan",
            "project": "MailInbox",
            "primary_category": "receipt",
            "categories": ["receipt"],
            "confidence": 0.4,
            "matched_keywords": {"receipt": ["cash"]},
        }
        classification_json = classify_dir / "classification.json"
        if with_classification:
            classification_json.write_text(json.dumps(classification, indent=2), encoding="utf-8")
        review_dir = packet_dir / "review"
        review_dir.mkdir()
        review = {
            "review_type": "laia.librarian.review",
            "packet_type": "laia.ingest.scan",
            "project": "MailInbox",
            "primary_category": "receipt",
            "confidence": 0.4,
            "review_status": "pending",
            "recommended_action": "manual_review",
            "source_packet_dir": str(packet_dir),
        }
        review_json = review_dir / "review.json"
        review_json.write_text(json.dumps(review, indent=2), encoding="utf-8")
        return packet_json, classification_json, review_json

    def args(self, **kwargs):
        values = {
            "packet": "laia-scan-20260609-182954-mailinbox",
            "category": "mail",
            "document_type": "",
            "note": [],
        }
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_correct_classification_finds_pending_packet_by_packet_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json, _classification_json, _review_json = self.make_packet(Path(tmp))

            found = find_packet_by_id("laia-scan-20260609-182954-mailinbox", Path(tmp) / "Inbox" / "Ingest")

            self.assertEqual(found, packet_json)

    def test_correct_classification_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json, _classification_json, _review_json = self.make_packet(Path(tmp))
            correction = build_correction(
                packet_json,
                category="mail",
                document_type="survey_invitation",
                notes=["Nielsen survey invitation."],
            )
            correction_json, correction_md = write_correction(packet_json, correction)

            self.assertTrue(correction_json.exists())
            self.assertTrue(correction_md.exists())
            data = json.loads(correction_json.read_text(encoding="utf-8"))
            self.assertEqual(data["corrected"]["primary_category"], "mail")
            self.assertEqual(data["corrected"]["document_type"], "survey_invitation")
            self.assertIn("# LAIA Classification Correction", correction_md.read_text(encoding="utf-8"))

    def test_correct_classification_fails_if_packet_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "Packet ID not found."):
                find_packet_by_id("missing", Path(tmp) / "Inbox" / "Ingest")

    def test_correct_classification_fails_if_classification_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json, _classification_json, _review_json = self.make_packet(Path(tmp), with_classification=False)

            with self.assertRaisesRegex(SystemExit, "No classification sidecar found for packet."):
                build_correction(packet_json, category="mail")

    def test_command_preserves_original_classification_review_and_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json, classification_json, review_json = self.make_packet(root)
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir()
            catalog.write_text("", encoding="utf-8")
            before_classification = classification_json.read_text(encoding="utf-8")
            before_review = review_json.read_text(encoding="utf-8")
            before_catalog = catalog.read_text(encoding="utf-8")

            with patch(
                "core.librarian.correct_classification.find_packet_by_id",
                return_value=packet_json,
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_correct_classification(
                        self.args(
                            document_type="survey_invitation",
                            note=["receipt classifier was triggered by cash transfer."],
                        )
                    )

            self.assertEqual(classification_json.read_text(encoding="utf-8"), before_classification)
            self.assertEqual(review_json.read_text(encoding="utf-8"), before_review)
            self.assertEqual(catalog.read_text(encoding="utf-8"), before_catalog)

    def test_approve_uses_corrected_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json, _classification_json, _review_json = self.make_packet(Path(tmp))
            correction = build_correction(
                packet_json,
                category="mail",
                document_type="survey_invitation",
                notes=[],
            )
            write_correction(packet_json, correction)

            approval, _warning = build_approval(packet_json)

            self.assertEqual(approval["approved_category"], "mail")
            self.assertEqual(approval["document_type"], "survey_invitation")
            self.assertTrue(approval["classification_corrected"])

    def test_finalize_uses_corrected_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json, _classification_json, _review_json = self.make_packet(Path(tmp))
            write_correction(
                packet_json,
                build_correction(packet_json, category="mail", document_type="survey_invitation"),
            )
            approval, _warning = build_approval(packet_json)
            write_approval(packet_json, approval)

            final = build_final(packet_json)

            self.assertEqual(final["approved_category"], "mail")
            self.assertEqual(final["document_type"], "survey_invitation")
            self.assertTrue(final["classification_corrected"])

    def test_catalog_includes_corrected_category_and_document_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json, _classification_json, _review_json = self.make_packet(root)
            write_correction(
                packet_json,
                build_correction(packet_json, category="mail", document_type="survey_invitation"),
            )
            approval, _warning = build_approval(packet_json)
            write_approval(packet_json, approval)
            final = build_final(packet_json)
            catalog_path = append_catalog_record(final, catalog_root=root / "Catalog")

            record = json.loads(catalog_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["approved_category"], "mail")
            self.assertEqual(record["document_type"], "survey_invitation")
            self.assertTrue(record["classification_corrected"])


if __name__ == "__main__":
    unittest.main()
