import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.librarian.extract_report import build_extract_report, command_extract_report
from core.librarian.export import select_export_records


class LibrarianExtractReportTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        packet_id: str = "laia-scan-1",
        project: str = "Receipts",
        category: str = "receipt",
        with_extract: bool = True,
        invalid_extract: bool = False,
        fields=None,
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
            if invalid_extract:
                (extract_dir / "extract.json").write_text("{not valid json}\n", encoding="utf-8")
            else:
                data = {
                    "fields": fields or {
                        "merchant": "VONS",
                        "transaction_date": "04/28/26",
                        "transaction_time": "09:44",
                        "subtotal": None,
                        "tax": "0.00",
                        "tip": None,
                        "total": "5.99",
                        "payment_method": "mastercard",
                        "last_four": "1234",
                        "currency": "USD",
                        "confidence": 0.9,
                    },
                    "warnings": warnings or [],
                }
                (extract_dir / "extract.json").write_text(json.dumps(data), encoding="utf-8")
            if correction is not None:
                (extract_dir / "correction.json").write_text(json.dumps(correction), encoding="utf-8")
        record = {
            "packet_id": packet_id,
            "project": project,
            "approved_category": category,
            "finalized_at": "2026-06-08T18:00:00-07:00",
            "source_packet_dir": str(packet_dir),
        }
        return packet_json, record

    def write_catalog(self, root: Path, records):
        catalog = root / "Catalog" / "ingest_catalog.jsonl"
        catalog.parent.mkdir()
        catalog.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return catalog

    def args(self, **kwargs):
        values = {"project": "", "category": "", "limit": None, "json": False, "raw": False}
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_report_filters_by_project(self):
        records = [
            {"packet_id": "a", "project": "Inbox", "approved_category": "receipt"},
            {"packet_id": "b", "project": "Receipts", "approved_category": "receipt"},
        ]

        selected = select_export_records(records, project="Receipts")

        self.assertEqual([record["packet_id"] for record in selected], ["b"])

    def test_report_filters_by_category(self):
        records = [
            {"packet_id": "a", "project": "Receipts", "approved_category": "financial"},
            {"packet_id": "b", "project": "Receipts", "approved_category": "receipt"},
        ]

        selected = select_export_records(records, category="receipt")

        self.assertEqual([record["packet_id"] for record in selected], ["b"])

    def test_report_supports_limit(self):
        records = [
            {"packet_id": "a", "project": "Receipts", "approved_category": "receipt", "finalized_at": "1"},
            {"packet_id": "b", "project": "Receipts", "approved_category": "receipt", "finalized_at": "2"},
        ]

        selected = select_export_records(records, project="Receipts", limit=1)

        self.assertEqual([record["packet_id"] for record in selected], ["b"])

    def test_report_counts_missing_and_invalid_extracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _a, missing = self.make_packet(root, packet_id="missing", with_extract=False)
            _b, invalid = self.make_packet(root, packet_id="invalid", invalid_extract=True)

            report = build_extract_report([missing, invalid], {"project": "Receipts"})

            self.assertEqual(report["missing_extracts"], 1)
            self.assertEqual(report["invalid_extracts"], 1)
            self.assertEqual(report["extracts_found"], 0)

    def test_report_computes_field_completeness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = {
                "merchant": "VONS",
                "transaction_date": None,
                "transaction_time": "09:44",
                "subtotal": None,
                "tax": "0.00",
                "tip": None,
                "total": "5.99",
                "payment_method": "mastercard",
                "last_four": "",
                "currency": "USD",
                "confidence": 0.9,
            }
            _packet, record = self.make_packet(root, fields=fields)

            report = build_extract_report([record], {"project": "Receipts"})

            self.assertEqual(report["field_completeness"]["merchant"], {"filled": 1, "total": 1})
            self.assertEqual(report["field_completeness"]["transaction_date"], {"filled": 0, "total": 1})
            self.assertEqual(report["raw_field_completeness"]["transaction_date"], {"filled": 0, "total": 1})
            self.assertEqual(report["corrected_field_completeness"]["transaction_date"], {"filled": 0, "total": 1})

    def test_report_groups_warnings_and_lists_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = {
                "merchant": "VONS",
                "transaction_date": None,
                "total": "5.99",
                "confidence": 0.8,
            }
            _packet, record = self.make_packet(
                root,
                fields=fields,
                warnings=["transaction_date not found"],
            )

            report = build_extract_report([record], {"project": "Receipts"})

            self.assertEqual(report["warnings"], [{"warning": "transaction_date not found", "count": 1}])
            self.assertEqual(len(report["needs_review"]), 1)
            self.assertEqual(report["needs_review"][0]["missing"], ["transaction_date"])

    def test_report_still_works_without_corrections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet, record = self.make_packet(root)

            report = build_extract_report([record], {"project": "Receipts"})

            self.assertEqual(report["corrections_found"], 0)
            self.assertEqual(report["corrections"], [])
            self.assertEqual(report["raw_field_completeness"], report["corrected_field_completeness"])

    def test_report_detects_corrections_and_counts_corrected_completeness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = {
                "merchant": "VONS",
                "transaction_date": "04/28/26",
                "total": None,
                "confidence": 0.9,
            }
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"},
                }
            }
            _packet, record = self.make_packet(
                root,
                fields=fields,
                warnings=["total not found"],
                correction=correction,
            )

            report = build_extract_report([record], {"project": "Receipts"})

            self.assertEqual(report["corrections_found"], 1)
            self.assertEqual(report["corrections"][0]["fields"], ["total"])
            self.assertEqual(report["raw_field_completeness"]["total"], {"filled": 0, "total": 1})
            self.assertEqual(report["corrected_field_completeness"]["total"], {"filled": 1, "total": 1})

    def test_corrected_total_reduces_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = {
                "merchant": "VONS",
                "transaction_date": "04/28/26",
                "total": None,
                "confidence": 0.9,
            }
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"},
                }
            }
            _packet, record = self.make_packet(
                root,
                fields=fields,
                warnings=["total not found"],
                correction=correction,
            )

            report = build_extract_report([record], {"project": "Receipts"})

            self.assertEqual(report["needs_review"], [])

    def test_transaction_date_correction_resolves_missing_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = {
                "merchant": "VONS",
                "transaction_date": None,
                "total": "4.99",
                "confidence": 0.9,
            }
            correction = {
                "corrections": {
                    "transaction_date": {"original": None, "corrected": "04/28/26"},
                }
            }
            _packet, record = self.make_packet(
                root,
                fields=fields,
                warnings=["transaction_date not found"],
                correction=correction,
            )

            report = build_extract_report([record], {"project": "Receipts"})

            self.assertEqual(report["corrected_field_completeness"]["transaction_date"], {"filled": 1, "total": 1})
            self.assertEqual(report["needs_review"], [])

    def test_unrelated_warnings_still_require_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = {
                "merchant": "VONS",
                "transaction_date": "04/28/26",
                "total": "4.99",
                "confidence": 0.9,
            }
            _packet, record = self.make_packet(
                root,
                fields=fields,
                warnings=["merchant unclear"],
                correction={"corrections": {"total": {"original": "4.99", "corrected": "4.99"}}},
            )

            report = build_extract_report([record], {"project": "Receipts"})

            self.assertEqual(len(report["needs_review"]), 1)
            self.assertEqual(report["needs_review"][0]["warnings"], ["merchant unclear"])

    def test_raw_mode_ignores_corrections_for_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = {
                "merchant": "VONS",
                "transaction_date": "04/28/26",
                "total": None,
                "confidence": 0.9,
            }
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"},
                }
            }
            _packet, record = self.make_packet(
                root,
                fields=fields,
                warnings=["total not found"],
                correction=correction,
            )

            report = build_extract_report([record], {"project": "Receipts", "raw": True}, use_corrections=False)

            self.assertEqual(len(report["needs_review"]), 1)
            self.assertEqual(report["needs_review"][0]["missing"], ["total"])

    def test_report_json_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _packet, record = self.make_packet(root)
            catalog = self.write_catalog(root, [record])
            output = io.StringIO()

            with patch("core.librarian.extract_report.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_extract_report(self.args(project="Receipts", json=True))

            data = json.loads(output.getvalue())
            self.assertEqual(data["selected"], 1)
            self.assertEqual(data["extracts_found"], 1)

    def test_report_json_includes_correction_information(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            correction = {
                "corrections": {
                    "total": {"original": None, "corrected": "4.99"},
                }
            }
            _packet, record = self.make_packet(
                root,
                fields={"merchant": "VONS", "transaction_date": "04/28/26", "total": None, "confidence": 0.9},
                correction=correction,
            )
            catalog = self.write_catalog(root, [record])
            output = io.StringIO()

            with patch("core.librarian.extract_report.catalog_path", return_value=catalog):
                with contextlib.redirect_stdout(output):
                    command_extract_report(self.args(project="Receipts", json=True))

            data = json.loads(output.getvalue())
            self.assertEqual(data["corrections_found"], 1)
            self.assertEqual(data["corrections"][0]["fields"], ["total"])

    def test_report_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json, record = self.make_packet(root)
            catalog = self.write_catalog(root, [record])
            extract_json = Path(record["source_packet_dir"]) / "extract" / "extract.json"
            before_catalog = catalog.read_text(encoding="utf-8")
            before_packet = packet_json.read_text(encoding="utf-8")
            before_extract = extract_json.read_text(encoding="utf-8")
            correction_json = Path(record["source_packet_dir"]) / "extract" / "correction.json"
            correction_json.write_text(
                json.dumps({"corrections": {"total": {"original": None, "corrected": "4.99"}}}),
                encoding="utf-8",
            )
            before_correction = correction_json.read_text(encoding="utf-8")

            with patch("core.librarian.extract_report.catalog_path", return_value=catalog):
                command_extract_report(self.args(project="Receipts"))

            self.assertEqual(catalog.read_text(encoding="utf-8"), before_catalog)
            self.assertEqual(packet_json.read_text(encoding="utf-8"), before_packet)
            self.assertEqual(extract_json.read_text(encoding="utf-8"), before_extract)
            self.assertEqual(correction_json.read_text(encoding="utf-8"), before_correction)


if __name__ == "__main__":
    unittest.main()
