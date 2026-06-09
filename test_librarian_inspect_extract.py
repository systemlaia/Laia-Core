import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.librarian.inspect_extract import command_inspect_extract, load_inspection


class LibrarianInspectExtractTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        *,
        packet_id: str = "laia-scan-1",
        with_extract: bool = True,
        with_correction: bool = False,
        warnings=None,
        text: str = "VONS\n04/28/26\nTOTAL 4.99\n",
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / packet_id
        packet_dir.mkdir(parents=True)
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(
            json.dumps({"packet_type": "laia.ingest.scan"}) + "\n",
            encoding="utf-8",
        )
        output_dir = packet_dir / "output"
        output_dir.mkdir()
        (output_dir / "scan.txt").write_text(text, encoding="utf-8")
        extract_dir = packet_dir / "extract"
        extract_dir.mkdir()
        extract_json = extract_dir / "extract.json"
        if with_extract:
            extract_json.write_text(
                json.dumps({
                    "fields": {
                        "merchant": "VONS",
                        "transaction_date": None,
                        "transaction_time": "09:44",
                        "subtotal": None,
                        "tax": "0.00",
                        "tip": None,
                        "total": None,
                        "payment_method": "visa",
                        "last_four": "1234",
                        "currency": "USD",
                    },
                    "warnings": warnings or ["transaction_date not found", "total not found"],
                }) + "\n",
                encoding="utf-8",
            )
        if with_correction:
            (extract_dir / "correction.json").write_text(
                json.dumps({
                    "corrections": {
                        "total": {"original": None, "corrected": "4.99"},
                    }
                }) + "\n",
                encoding="utf-8",
            )
        record = {
            "packet_id": packet_id,
            "project": "Receipts",
            "approved_category": "receipt",
            "source_packet_dir": str(packet_dir),
        }
        catalog = root / "Catalog" / "ingest_catalog.jsonl"
        catalog.parent.mkdir()
        catalog.write_text(json.dumps(record) + "\n", encoding="utf-8")
        return {
            "catalog": catalog,
            "packet_json": packet_json,
            "extract_json": extract_json,
            "correction_json": extract_dir / "correction.json",
            "record": record,
        }

    def args(self, **kwargs):
        values = {"packet": "laia-scan-1", "lines": 80, "json": False}
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_inspect_finds_packet_by_packet_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp))

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                inspection = load_inspection("laia-scan-1")

            self.assertEqual(inspection["packet_id"], "laia-scan-1")
            self.assertEqual(inspection["catalog_record"]["project"], "Receipts")

    def test_inspect_prints_extracted_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp))
            output = io.StringIO()

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                with contextlib.redirect_stdout(output):
                    command_inspect_extract(self.args())

            text = output.getvalue()
            self.assertIn("Extracted Fields:", text)
            self.assertIn("merchant: VONS", text)
            self.assertIn("total: None", text)

    def test_inspect_prints_corrections_if_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp), with_correction=True)
            output = io.StringIO()

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                with contextlib.redirect_stdout(output):
                    command_inspect_extract(self.args())

            self.assertIn("total: None -> 4.99", output.getvalue())

    def test_inspect_prints_no_corrections_if_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp))
            output = io.StringIO()

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                with contextlib.redirect_stdout(output):
                    command_inspect_extract(self.args())

            self.assertIn("No corrections found.", output.getvalue())

    def test_inspect_prints_warnings_and_ocr_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp), text="line one\nline two\nline three\n")
            output = io.StringIO()

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                with contextlib.redirect_stdout(output):
                    command_inspect_extract(self.args())

            text = output.getvalue()
            self.assertIn("transaction_date not found", text)
            self.assertIn("line one", text)
            self.assertIn("line three", text)

    def test_inspect_supports_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp), text="line one\nline two\nline three\n")

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                inspection = load_inspection("laia-scan-1", lines=2)

            self.assertEqual(inspection["ocr_preview"], "line one\nline two")

    def test_inspect_supports_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp), with_correction=True)
            output = io.StringIO()

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                with contextlib.redirect_stdout(output):
                    command_inspect_extract(self.args(json=True))

            data = json.loads(output.getvalue())
            self.assertEqual(data["packet_id"], "laia-scan-1")
            self.assertEqual(data["fields"]["merchant"], "VONS")
            self.assertEqual(data["corrections"]["total"]["corrected"], "4.99")

    def test_inspect_fails_when_packet_id_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp))

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                with self.assertRaisesRegex(SystemExit, "Packet ID not found in catalog."):
                    load_inspection("missing")

    def test_inspect_fails_when_extract_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp), with_extract=False)

            with patch("core.librarian.inspect_extract.catalog_path", return_value=fixture["catalog"]):
                with self.assertRaisesRegex(SystemExit, "No extraction sidecar found for packet."):
                    load_inspection("laia-scan-1")

    def test_inspect_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self.make_packet(Path(tmp), with_correction=True)
            catalog = fixture["catalog"]
            packet_json = fixture["packet_json"]
            extract_json = fixture["extract_json"]
            correction_json = fixture["correction_json"]
            before_catalog = catalog.read_text(encoding="utf-8")
            before_packet = packet_json.read_text(encoding="utf-8")
            before_extract = extract_json.read_text(encoding="utf-8")
            before_correction = correction_json.read_text(encoding="utf-8")

            with patch("core.librarian.inspect_extract.catalog_path", return_value=catalog):
                command_inspect_extract(self.args())

            self.assertEqual(catalog.read_text(encoding="utf-8"), before_catalog)
            self.assertEqual(packet_json.read_text(encoding="utf-8"), before_packet)
            self.assertEqual(extract_json.read_text(encoding="utf-8"), before_extract)
            self.assertEqual(correction_json.read_text(encoding="utf-8"), before_correction)


if __name__ == "__main__":
    unittest.main()
