import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import argparse
import contextlib
import io

from core.librarian.catalog import command_catalog, latest_catalog_record, load_catalog_records, query_catalog_records


class LibrarianCatalogTests(unittest.TestCase):
    def record(
        self,
        packet_id: str,
        source_packet_dir: str = "/tmp/packet",
        project: str = "Inbox",
        category: str = "receipt",
        document_type=None,
        classification_corrected=None,
    ):
        record = {
            "packet_id": packet_id,
            "packet_type": "laia.ingest.scan",
            "project": project,
            "created_at": "2026-06-07T17:19:35-07:00",
            "finalized_at": "2026-06-07T17:54:09-07:00",
            "approved_category": category,
            "confidence": 0.9,
            "page_count": 2,
            "word_count": 129,
            "source_packet_dir": source_packet_dir,
            "destination_packet_dir": "/tmp/archive",
        }
        if document_type is not None:
            record["document_type"] = document_type
        if classification_corrected is not None:
            record["classification_corrected"] = classification_corrected
        return record

    def test_catalog_last_reads_final_valid_jsonl_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            first = self.record("first")
            last = self.record("last")
            catalog.write_text(json.dumps(first) + "\n" + json.dumps(last) + "\n", encoding="utf-8")

            self.assertEqual(latest_catalog_record(catalog)["packet_id"], "last")

    def test_catalog_ignores_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text("\n\n" + json.dumps(self.record("only")) + "\n\n", encoding="utf-8")

            records = load_catalog_records(catalog)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["packet_id"], "only")

    def test_catalog_skips_invalid_json_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(
                "{not valid json}\n" + json.dumps(self.record("valid")) + "\n",
                encoding="utf-8",
            )

            records = load_catalog_records(catalog)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["packet_id"], "valid")

    def test_catalog_errors_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "missing.jsonl"

            with self.assertRaises(SystemExit):
                load_catalog_records(catalog)

    def test_catalog_errors_when_no_valid_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text("\n{not valid json}\n[]\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                load_catalog_records(catalog)

    def test_catalog_does_not_modify_packet_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_dir = root / "Inbox" / "Ingest" / "Scans" / "2026-06-07_171935_inbox"
            packet_dir.mkdir(parents=True)
            packet_json = packet_dir / "packet.json"
            packet_json.write_text('{"packet_type": "laia.ingest.scan"}\n', encoding="utf-8")
            before = packet_json.read_text(encoding="utf-8")
            catalog = root / "Catalog" / "ingest_catalog.jsonl"
            catalog.parent.mkdir()
            catalog.write_text(json.dumps(self.record("only", str(packet_dir))) + "\n", encoding="utf-8")

            latest_catalog_record(catalog)
            after = packet_json.read_text(encoding="utf-8")

            self.assertEqual(before, after)

    def test_catalog_project_filters_records(self):
        records = [
            self.record("inbox", project="Inbox"),
            self.record("receipts", project="Receipts"),
        ]

        filtered = query_catalog_records(records, project="Receipts")

        self.assertEqual([record["packet_id"] for record in filtered], ["receipts"])

    def test_catalog_category_filters_records(self):
        records = [
            self.record("receipt", category="receipt"),
            self.record("financial", category="financial"),
        ]

        filtered = query_catalog_records(records, category="receipt")

        self.assertEqual([record["packet_id"] for record in filtered], ["receipt"])

    def test_catalog_project_and_category_filter_records(self):
        records = [
            self.record("a", project="Receipts", category="financial"),
            self.record("b", project="Inbox", category="receipt"),
            self.record("c", project="Receipts", category="receipt"),
        ]

        filtered = query_catalog_records(records, project="Receipts", category="receipt")

        self.assertEqual([record["packet_id"] for record in filtered], ["c"])

    def test_catalog_limit_limits_output(self):
        records = [
            self.record("one"),
            self.record("two"),
            self.record("three"),
        ]

        filtered = query_catalog_records(records, limit=2)

        self.assertEqual([record["packet_id"] for record in filtered], ["three", "two"])

    def test_catalog_json_emits_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(json.dumps(self.record("one", project="Receipts")) + "\n", encoding="utf-8")
            args = argparse.Namespace(last=False, project="Receipts", category="", limit=20, json=True)
            output = io.StringIO()

            with patch("core.librarian.catalog.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_catalog(args)

            data = json.loads(output.getvalue())
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["records"][0]["packet_id"], "one")

    def test_catalog_last_command_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(
                json.dumps(self.record("first")) + "\n" + json.dumps(self.record("last")) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(last=True, project="", category="", limit=20, json=False)
            output = io.StringIO()

            with patch("core.librarian.catalog.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_catalog(args)

            self.assertIn("LAIA Librarian Catalog Entry", output.getvalue())
            self.assertIn("Packet ID: last", output.getvalue())

    def test_catalog_last_displays_document_type_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(
                json.dumps(self.record("last", document_type="survey_invitation")) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()

            with patch("core.librarian.catalog.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_catalog(argparse.Namespace(last=True, project="", category="", limit=20, json=False))

            self.assertIn("Document Type: survey_invitation", output.getvalue())

    def test_catalog_last_displays_classification_corrected_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(
                json.dumps(self.record("last", classification_corrected=True)) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()

            with patch("core.librarian.catalog.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_catalog(argparse.Namespace(last=True, project="", category="", limit=20, json=False))

            self.assertIn("Classification Corrected: true", output.getvalue())

    def test_catalog_query_displays_document_type_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(
                json.dumps(self.record("one", document_type="survey_invitation")) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()

            with patch("core.librarian.catalog.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_catalog(argparse.Namespace(last=False, project="", category="", limit=20, json=False))

            self.assertIn("Document Type: survey_invitation", output.getvalue())

    def test_catalog_query_displays_classification_corrected_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(
                json.dumps(self.record("one", classification_corrected=False)) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()

            with patch("core.librarian.catalog.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_catalog(argparse.Namespace(last=False, project="", category="", limit=20, json=False))

            self.assertIn("Classification Corrected: false", output.getvalue())

    def test_catalog_older_records_without_correction_fields_display_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "ingest_catalog.jsonl"
            catalog.write_text(json.dumps(self.record("old")) + "\n", encoding="utf-8")
            output = io.StringIO()

            with patch("core.librarian.catalog.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_catalog(argparse.Namespace(last=True, project="", category="", limit=20, json=False))

            text = output.getvalue()
            self.assertIn("Packet ID: old", text)
            self.assertNotIn("Document Type:", text)
            self.assertNotIn("Classification Corrected:", text)


if __name__ == "__main__":
    unittest.main()
