import json
import tempfile
import unittest
from pathlib import Path

from core.librarian.classify import build_classification, write_classification


class LibrarianClassifyTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        packet_type: str = "laia.ingest.scan",
        with_summary: bool = True,
        text: str = "",
        preview: str = "",
        tags=None,
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / "2026-06-07_171935_inbox"
        output_dir = packet_dir / "output"
        output_dir.mkdir(parents=True)

        text_path = output_dir / "scan.txt"
        text_path.write_text(text, encoding="utf-8")

        packet = {
            "packet_type": packet_type,
            "created_at": "2026-06-07T17:19:35-07:00",
            "project": "Inbox",
            "page_count": 2,
            "tags": tags or [],
            "paths": {
                "packet_dir": str(packet_dir),
                "text": str(text_path),
            },
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet), encoding="utf-8")

        if with_summary:
            summary_dir = packet_dir / "summary"
            summary_dir.mkdir()
            summary = {
                "summary_type": "laia.librarian.summary",
                "packet_type": packet_type,
                "project": "Inbox",
                "text_preview": preview,
            }
            (summary_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

        return packet_json

    def test_classify_requires_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_summary=False)

            with self.assertRaises(SystemExit):
                build_classification(packet_json)

    def test_classification_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), text="root canal tooth")
            classification = build_classification(packet_json)
            classification_json, classification_md = write_classification(packet_json, classification)

            self.assertTrue(classification_json.exists())
            self.assertTrue(classification_md.exists())
            self.assertIn("# LAIA Ingest Classification", classification_md.read_text(encoding="utf-8"))

    def test_dental_text_classifies_as_dental(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), text="The dentist noted a root canal and tooth pain.")
            classification = build_classification(packet_json)

            self.assertEqual(classification["primary_category"], "dental")
            self.assertIn("dental", classification["categories"])
            self.assertIn("root canal", classification["matched_keywords"]["dental"])
            self.assertGreaterEqual(classification["confidence"], 0.7)

    def test_receipt_text_classifies_as_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), text="Receipt subtotal total tax paid by mastercard.")
            classification = build_classification(packet_json)

            self.assertEqual(classification["primary_category"], "receipt")
            self.assertIn("receipt", classification["categories"])
            self.assertIn("subtotal", classification["matched_keywords"]["receipt"])

    def test_unknown_text_classifies_as_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), text="blue folded paper with quiet margins")
            classification = build_classification(packet_json)

            self.assertEqual(classification["primary_category"], "unknown")
            self.assertEqual(classification["categories"], [])
            self.assertEqual(classification["confidence"], 0.0)

    def test_multiple_categories_can_be_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), text="Root canal tooth with healthnet.")
            classification = build_classification(packet_json)

            self.assertEqual(classification["primary_category"], "dental")
            self.assertIn("dental", classification["categories"])
            self.assertIn("insurance", classification["categories"])
            self.assertEqual(classification["confidence"], 0.9)

    def test_rejects_non_laia_ingest_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), packet_type="external.scan")

            with self.assertRaises(SystemExit):
                build_classification(packet_json)


if __name__ == "__main__":
    unittest.main()
