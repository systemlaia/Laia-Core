import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.librarian.export import export_catalog, select_export_records


class LibrarianExportTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        packet_id: str = "laia-scan-20260608-144553-receipts",
        project: str = "Receipts",
        category: str = "receipt",
        with_extract: bool = True,
        invalid_extract: bool = False,
        total=None,
        warnings=None,
        correction=None,
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / packet_id
        packet_dir.mkdir(parents=True)
        packet_json = packet_dir / "packet.json"
        packet_json.write_text('{"packet_type": "laia.ingest.scan"}\n', encoding="utf-8")

        if with_extract:
            extract_dir = packet_dir / "extract"
            extract_dir.mkdir()
            extract_path = extract_dir / "extract.json"
            if invalid_extract:
                extract_path.write_text("{not valid json}\n", encoding="utf-8")
            else:
                extraction = {
                    "fields": {
                        "merchant": "VONS",
                        "transaction_date": "04/28/26",
                        "transaction_time": "09:44",
                        "subtotal": None,
                        "tax": "0.00",
                        "tip": None,
                        "total": total,
                        "payment_method": "mastercard",
                        "last_four": "1234",
                        "currency": "USD",
                        "confidence": 0.77,
                    },
                    "warnings": warnings or [],
                }
                extract_path.write_text(json.dumps(extraction), encoding="utf-8")
            if correction:
                correction_path = extract_dir / "correction.json"
                correction_path.write_text(json.dumps(correction), encoding="utf-8")

        record = {
            "packet_id": packet_id,
            "packet_type": "laia.ingest.scan",
            "project": project,
            "created_at": "2026-06-08T14:45:53-07:00",
            "finalized_at": "2026-06-08T17:54:20-07:00",
            "approved_category": category,
            "confidence": 0.9,
            "page_count": 2,
            "word_count": 120,
            "source_packet_dir": str(packet_dir),
            "destination_packet_dir": str(root / "Archive" / packet_id),
        }
        return packet_json, record

    def write_catalog(self, root: Path, records):
        catalog = root / "Catalog" / "ingest_catalog.jsonl"
        catalog.parent.mkdir()
        catalog.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return catalog

    def args(self, **kwargs):
        values = {
            "project": "Receipts",
            "category": "",
            "format": "csv",
            "limit": None,
            "output": "",
            "apply_corrections": False,
            "raw": False,
        }
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_export_project_receipts_csv_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root, total="5.99")
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                output_path, summary = export_catalog(self.args(output=str(output)))

            self.assertEqual(output_path, output)
            self.assertEqual(summary["exported_records"], 1)
            with output.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["packet_id"], record["packet_id"])
            self.assertEqual(rows[0]["total"], "5.99")

    def test_export_project_receipts_json_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.json"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(format="json", output=str(output)))

            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["records"][0]["packet_id"], record["packet_id"])

    def test_export_category_receipt_filters_records(self):
        records = [
            {"packet_id": "a", "project": "Receipts", "approved_category": "financial"},
            {"packet_id": "b", "project": "Inbox", "approved_category": "receipt"},
        ]

        selected = select_export_records(records, category="receipt")

        self.assertEqual([record["packet_id"] for record in selected], ["b"])

    def test_export_limit_limits_records(self):
        records = [
            {"packet_id": "a", "project": "Receipts", "approved_category": "receipt", "finalized_at": "1"},
            {"packet_id": "b", "project": "Receipts", "approved_category": "receipt", "finalized_at": "2"},
        ]

        selected = select_export_records(records, project="Receipts", limit=1)

        self.assertEqual([record["packet_id"] for record in selected], ["b"])

    def test_export_skips_missing_extract_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root, with_extract=False)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                _output_path, summary = export_catalog(self.args(output=str(output)))

            self.assertEqual(summary["skipped_missing_extract"], 1)
            self.assertEqual(summary["exported_records"], 0)

    def test_export_skips_invalid_extract_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root, invalid_extract=True)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                _output_path, summary = export_catalog(self.args(output=str(output)))

            self.assertEqual(summary["skipped_invalid_extract"], 1)
            self.assertEqual(summary["exported_records"], 0)

    def test_export_does_not_modify_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root)
            catalog = self.write_catalog(root, [record])
            before = catalog.read_text(encoding="utf-8")

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(root / "receipts.csv")))

            self.assertEqual(catalog.read_text(encoding="utf-8"), before)

    def test_export_does_not_modify_packet_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json, record = self.make_packet(root)
            catalog = self.write_catalog(root, [record])
            before = packet_json.read_text(encoding="utf-8")

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(root / "receipts.csv")))

            self.assertEqual(packet_json.read_text(encoding="utf-8"), before)

    def test_export_writes_empty_cells_for_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root, total=None)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(output)))

            with output.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["total"], "")
            self.assertEqual(rows[0]["subtotal"], "")

    def test_export_joins_warnings_for_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root, warnings=["total not found", "date not found"])
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(output)))

            with output.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["extraction_warnings"], "total not found; date not found")

    def test_export_supports_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet_json, record = self.make_packet(root)
            catalog = self.write_catalog(root, [record])
            output = root / "custom" / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                output_path, _summary = export_catalog(self.args(output=str(output)))

            self.assertEqual(output_path, output)
            self.assertTrue(output.exists())

    def test_export_applies_correction_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"}
                }
            }
            _packet_json, record = self.make_packet(root, total=None, correction=correction)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(output)))

            with output.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["total"], "4.99")
            self.assertEqual(rows[0]["corrections_applied"], "true")
            self.assertEqual(rows[0]["corrected_fields"], "total")

    def test_export_apply_corrections_explicit_applies_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"}
                }
            }
            _packet_json, record = self.make_packet(root, total=None, correction=correction)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(output), apply_corrections=True))

            with output.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["total"], "4.99")

    def test_export_raw_ignores_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"}
                }
            }
            _packet_json, record = self.make_packet(root, total=None, correction=correction)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.csv"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(output), raw=True))

            with output.open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]["total"], "")
            self.assertEqual(rows[0]["corrections_applied"], "false")
            self.assertEqual(rows[0]["corrected_fields"], "")

    def test_json_export_includes_correction_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"}
                }
            }
            _packet_json, record = self.make_packet(root, total=None, correction=correction)
            catalog = self.write_catalog(root, [record])
            output = root / "receipts.json"

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(format="json", output=str(output)))

            data = json.loads(output.read_text(encoding="utf-8"))
            row = data["records"][0]
            self.assertEqual(row["total"], "4.99")
            self.assertEqual(row["corrections_applied"], "true")
            self.assertEqual(row["corrected_fields"], "total")
            self.assertEqual(row["corrections"]["total"]["corrected"], "4.99")

    def test_export_does_not_modify_correction_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"}
                }
            }
            _packet_json, record = self.make_packet(root, total=None, correction=correction)
            correction_json = Path(record["source_packet_dir"]) / "extract" / "correction.json"
            before = correction_json.read_text(encoding="utf-8")
            catalog = self.write_catalog(root, [record])

            with patch("core.librarian.export.catalog_path", return_value=catalog):
                export_catalog(self.args(output=str(root / "receipts.csv")))

            self.assertEqual(correction_json.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
