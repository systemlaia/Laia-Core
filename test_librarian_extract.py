import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.librarian.extract import (
    build_extraction,
    command_extract,
    extract_receipt_fields,
    run_batch,
    select_batch_records,
    write_extraction,
)


class LibrarianExtractTests(unittest.TestCase):
    sample_text = """VONS
4520 SUNSET BLVD
LOS ANGELES CA 90027
(323) 662-8107
04/28/26 09:44
SUBTOTAL 4.99
TAX 0.00
TIP 1.00
TOTAL 5.99
Mastercard ****1234
"""

    def make_packet(
        self,
        root: Path,
        category: str = "receipt",
        text: str = sample_text,
        packet_id: str = "laia-scan-20260608-144553-receipts",
        name: str = "2026-06-08_144553_receipts",
        project: str = "Receipts",
        finalized_at: str = "2026-06-08T14:50:00-07:00",
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / name
        output_dir = packet_dir / "output"
        output_dir.mkdir(parents=True)
        if text is not None:
            (output_dir / "scan.txt").write_text(text, encoding="utf-8")
        packet = {
            "packet_type": "laia.ingest.scan",
            "project": project,
            "created_at": "2026-06-08T14:45:53-07:00",
        }
        (packet_dir / "packet.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
        final_dir = packet_dir / "final"
        final_dir.mkdir()
        (final_dir / "final.json").write_text(
            json.dumps({"approved_category": category}, indent=2),
            encoding="utf-8",
        )
        classify_dir = packet_dir / "classify"
        classify_dir.mkdir()
        (classify_dir / "classification.json").write_text(
            json.dumps({"primary_category": category}, indent=2),
            encoding="utf-8",
        )
        summary_dir = packet_dir / "summary"
        summary_dir.mkdir()
        (summary_dir / "summary.json").write_text(
            json.dumps({"text_preview": text or ""}, indent=2),
            encoding="utf-8",
        )
        record = {
            "packet_id": packet_id,
            "packet_type": "laia.ingest.scan",
            "project": project,
            "approved_category": category,
            "finalized_at": finalized_at,
            "source_packet_dir": str(packet_dir),
        }
        return packet_dir, record

    def test_extract_last_reads_latest_catalog_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_dir, record = self.make_packet(root)
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir()
            catalog.write_text(
                json.dumps({**record, "packet_id": "older", "source_packet_dir": "/tmp/missing"}) + "\n"
                + json.dumps(record) + "\n",
                encoding="utf-8",
            )

            with patch("core.librarian.extract.catalog_path", return_value=catalog):
                command_extract(argparse.Namespace(last=True))

            self.assertTrue((packet_dir / "extract" / "extract.json").exists())

    def test_receipt_category_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_dir, record = self.make_packet(Path(tmp), category="receipt")
            extraction = build_extraction(record)

            self.assertEqual(extraction["category"], "receipt")

    def test_financial_category_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_dir, record = self.make_packet(Path(tmp), category="financial")
            extraction = build_extraction(record)

            self.assertEqual(extraction["category"], "financial")

    def test_unsupported_category_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_dir, record = self.make_packet(Path(tmp), category="medical")

            with self.assertRaisesRegex(SystemExit, "Extraction currently supports receipt and financial"):
                build_extraction(record)

    def test_missing_ocr_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_dir, record = self.make_packet(Path(tmp), text=None)

            with self.assertRaisesRegex(SystemExit, "No OCR text found for extraction"):
                build_extraction(record)

    def test_extracts_receipt_fields(self):
        fields, warnings = extract_receipt_fields(self.sample_text)

        self.assertEqual(fields["merchant"], "VONS")
        self.assertEqual(fields["transaction_date"], "04/28/26")
        self.assertEqual(fields["transaction_time"], "09:44")
        self.assertEqual(fields["total"], "5.99")
        self.assertEqual(fields["tax"], "0.00")
        self.assertEqual(fields["tip"], "1.00")
        self.assertEqual(fields["payment_method"], "mastercard")
        self.assertEqual(fields["last_four"], "1234")
        self.assertEqual(fields["currency"], "USD")
        self.assertEqual(warnings, [])

    def test_writes_json_and_markdown_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_dir, record = self.make_packet(Path(tmp))
            extraction = build_extraction(record)
            extract_json, extract_md = write_extraction(record, extraction)

            self.assertEqual(extract_json, packet_dir / "extract" / "extract.json")
            self.assertEqual(extract_md, packet_dir / "extract" / "extract.md")
            self.assertTrue(extract_json.exists())
            self.assertTrue(extract_md.exists())

    def test_does_not_modify_packet_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_dir, record = self.make_packet(Path(tmp))
            packet_json = packet_dir / "packet.json"
            before = packet_json.read_text(encoding="utf-8")
            extraction = build_extraction(record)
            write_extraction(record, extraction)
            after = packet_json.read_text(encoding="utf-8")

            self.assertEqual(before, after)

    def test_does_not_append_to_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_dir, record = self.make_packet(root)
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir()
            catalog.write_text(json.dumps(record) + "\n", encoding="utf-8")
            before = catalog.read_text(encoding="utf-8")

            with patch("core.librarian.extract.catalog_path", return_value=catalog):
                command_extract(argparse.Namespace(last=True))

            after = catalog.read_text(encoding="utf-8")
            self.assertEqual(before, after)

    def test_batch_project_selects_matching_records(self):
        records = [
            {"packet_id": "a", "project": "Inbox", "approved_category": "receipt"},
            {"packet_id": "b", "project": "Receipts", "approved_category": "receipt"},
        ]

        selected = select_batch_records(records, project="Receipts")

        self.assertEqual([record["packet_id"] for record in selected], ["b"])

    def test_batch_category_selects_matching_records(self):
        records = [
            {"packet_id": "a", "project": "Receipts", "approved_category": "financial"},
            {"packet_id": "b", "project": "Receipts", "approved_category": "receipt"},
        ]

        selected = select_batch_records(records, category="receipt")

        self.assertEqual([record["packet_id"] for record in selected], ["b"])

    def test_batch_limit_limits_records(self):
        records = [
            {"packet_id": "a", "project": "Receipts", "approved_category": "receipt", "finalized_at": "1"},
            {"packet_id": "b", "project": "Receipts", "approved_category": "receipt", "finalized_at": "2"},
        ]

        selected = select_batch_records(records, limit=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["packet_id"], "b")

    def test_batch_skips_existing_extract_unless_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_dir, record = self.make_packet(Path(tmp))
            extraction = build_extraction(record)
            write_extraction(record, extraction)

            summary = run_batch([record], force=False)

            self.assertEqual(summary["skipped_existing"], 1)
            self.assertEqual(summary["extracted"], 0)
            self.assertTrue((packet_dir / "extract" / "extract.json").exists())

    def test_batch_reruns_with_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_dir, record = self.make_packet(Path(tmp))
            extraction = build_extraction(record)
            write_extraction(record, extraction)

            summary = run_batch([record], force=True)

            self.assertEqual(summary["extracted"], 1)
            self.assertEqual(summary["skipped_existing"], 0)

    def test_batch_missing_ocr_is_reported_without_abort(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _missing_dir, missing = self.make_packet(root, text=None, packet_id="missing", name="missing")
            _valid_dir, valid = self.make_packet(root, packet_id="valid", name="valid")

            summary = run_batch([missing, valid])

            self.assertEqual(summary["skipped_missing_ocr"], 1)
            self.assertEqual(summary["extracted"], 1)

    def test_batch_unsupported_category_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_dir, record = self.make_packet(Path(tmp), category="medical")

            summary = run_batch([record])

            self.assertEqual(summary["skipped_unsupported"], 1)
            self.assertEqual(summary["extracted"], 0)

    def test_json_batch_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_dir, record = self.make_packet(root)
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir()
            catalog.write_text(json.dumps(record) + "\n", encoding="utf-8")
            output = io.StringIO()
            args = argparse.Namespace(
                last=False,
                project="Receipts",
                category="",
                limit=30,
                force=True,
                json=True,
            )

            with patch("core.librarian.extract.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_extract(args)

            data = json.loads(output.getvalue())
            self.assertEqual(data["selected"], 1)
            self.assertEqual(data["extracted"], 1)


if __name__ == "__main__":
    unittest.main()
