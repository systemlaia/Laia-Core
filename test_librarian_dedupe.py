import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.librarian.catalog import load_catalog_records
from core.librarian.dedupe import command_dedupe, dedupe_record


class LibrarianDedupeTests(unittest.TestCase):
    def packet_record(self, packet_id: str, source_packet_dir: str, packet_type: str = "laia.ingest.scan", project: str = "Receipts", approved_category: str = "receipt", page_count: int = 2, word_count: int = 20):
        return {
            "packet_id": packet_id,
            "packet_type": packet_type,
            "project": project,
            "created_at": "2026-06-08T13:58:53-07:00",
            "finalized_at": "2026-06-08T14:00:00-07:00",
            "approved_category": approved_category,
            "confidence": 0.92,
            "page_count": page_count,
            "word_count": word_count,
            "source_packet_dir": source_packet_dir,
            "destination_packet_dir": "/tmp/archive",
        }

    def make_packet(self, root: Path, name: str, text: str, packet_type: str = "laia.ingest.scan", project: str = "Receipts") -> Path:
        packet_dir = root / name
        packet_dir.mkdir(parents=True, exist_ok=True)
        packet_json = packet_dir / "packet.json"
        packet_data = {
            "packet_type": packet_type,
            "project": project,
            "created_at": "2026-06-08T13:58:53-07:00",
            "page_count": 2,
            "paths": {
                "text": str(packet_dir / "output" / "scan.txt"),
            },
        }
        packet_json.write_text(json.dumps(packet_data, indent=2), encoding="utf-8")
        output_dir = packet_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "scan.txt").write_text(text, encoding="utf-8")
        return packet_dir

    def test_dedupe_requires_catalog(self):
        args = argparse.Namespace(last=True)
        with tempfile.TemporaryDirectory() as tmp:
            catalog_file = Path(tmp) / "ingest_catalog.jsonl"
            with patch("core.librarian.dedupe.catalog_path", return_value=catalog_file):
                with self.assertRaises(SystemExit):
                    command_dedupe(args)

    def test_dedupe_ignores_latest_packet_self(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet1 = self.make_packet(root, "2026-06-08_135532_receipts", "VONS 4.99 MOOS")
            packet2 = self.make_packet(root, "2026-06-08_135853_receipts", "VONS 4.99 MOOS")
            record1 = self.packet_record("laia-scan-20260608-135532-receipts", str(packet1))
            record2 = self.packet_record("laia-scan-20260608-135532-receipts", str(packet2))
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps(record1) + "\n" + json.dumps(record2) + "\n", encoding="utf-8")

            records = load_catalog_records(catalog)
            target = records[-1]
            prior = records[:-1]
            report = dedupe_record(target, prior)

            self.assertEqual(report["candidate_count"], 0)
            self.assertEqual(report["candidates"], [])

    def test_dedupe_detects_similar_receipt_as_likely_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet1 = self.make_packet(root, "2026-06-08_135532_receipts", "VONS 4.99 SIG IC CRM MOOS TK BALANCE 4.99 MASTERCARD")
            packet2 = self.make_packet(root, "2026-06-08_135853_receipts", "VONS 4.99 SIG IC CRM MOOS TK BALANCE 4.99 MASTERCARD")
            record1 = self.packet_record("laia-scan-20260608-135532-receipts", str(packet1))
            record2 = self.packet_record("laia-scan-20260608-135853-receipts", str(packet2))
            report = dedupe_record(record2, [record1])

            self.assertEqual(report["candidate_count"], 1)
            candidate = report["candidates"][0]
            self.assertEqual(candidate["packet_id"], record1["packet_id"])
            self.assertEqual(candidate["category"], "likely_duplicate")
            self.assertIn("shared amount", " ".join(candidate["reasons"]))
            self.assertIn("shared merchant token", " ".join(candidate["reasons"]))
            self.assertIn("OCR similarity", " ".join(candidate["reasons"]))

    def test_dedupe_does_not_flag_different_amount_receipt_as_likely_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet1 = self.make_packet(root, "2026-06-08_135722_receipts", "VONS 8.99 TORTILLA CHIPS BALANCE 8.99 MASTERCARD")
            packet2 = self.make_packet(root, "2026-06-08_135853_receipts", "VONS 4.99 SIG IC CRM MOOS TK BALANCE 4.99 MASTERCARD")
            record1 = self.packet_record("laia-scan-20260608-135722-receipts", str(packet1))
            record2 = self.packet_record("laia-scan-20260608-135853-receipts", str(packet2))
            report = dedupe_record(record2, [record1])

            self.assertTrue(report["candidate_count"] == 0 or report["candidates"][0]["category"] != "likely_duplicate")

    def test_dedupe_writes_sidecars_and_preserves_catalog_and_packet(self):
        args = argparse.Namespace(last=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet1 = self.make_packet(root, "2026-06-08_135532_receipts", "VONS 4.99 SIG IC CRM MOOS TK BALANCE 4.99 MASTERCARD")
            packet2 = self.make_packet(root, "2026-06-08_135853_receipts", "VONS 4.99 SIG IC CRM MOOS TK BALANCE 4.99 MASTERCARD")
            record1 = self.packet_record("laia-scan-20260608-135532-receipts", str(packet1))
            record2 = self.packet_record("laia-scan-20260608-135853-receipts", str(packet2))
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps(record1) + "\n" + json.dumps(record2) + "\n", encoding="utf-8")

            packet_json = packet2 / "packet.json"
            before_packet = packet_json.read_text(encoding="utf-8")
            before_catalog = catalog.read_text(encoding="utf-8")

            with patch("core.librarian.dedupe.catalog_path", return_value=catalog):
                command_dedupe(args)

            after_packet = packet_json.read_text(encoding="utf-8")
            after_catalog = catalog.read_text(encoding="utf-8")
            self.assertEqual(before_packet, after_packet)
            self.assertEqual(before_catalog, after_catalog)

            dedupe_dir = packet2 / "dedupe"
            self.assertTrue((dedupe_dir / "dedupe.json").exists())
            self.assertTrue((dedupe_dir / "dedupe.md").exists())

    def test_dedupe_rejects_non_laia_ingest_packets(self):
        args = argparse.Namespace(last=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root, "2026-06-08_135853_other", "OTHER TEXT", packet_type="other.scan", project="Receipts")
            record = self.packet_record("laia-scan-20260608-135853-other", str(packet), packet_type="other.scan")
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir(parents=True, exist_ok=True)
            catalog.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with patch("core.librarian.dedupe.catalog_path", return_value=catalog):
                with self.assertRaises(SystemExit):
                    command_dedupe(args)


if __name__ == "__main__":
    unittest.main()
