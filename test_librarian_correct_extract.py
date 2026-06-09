import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.librarian.correct_extract import (
    build_correction,
    command_correct_extract,
    correction_values,
    find_catalog_record,
    write_correction,
)


class LibrarianCorrectExtractTests(unittest.TestCase):
    def make_packet(self, root: Path, packet_id: str = "laia-scan-1", with_extract: bool = True):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / packet_id
        packet_dir.mkdir(parents=True)
        packet_json = packet_dir / "packet.json"
        packet_json.write_text('{"packet_type": "laia.ingest.scan"}\n', encoding="utf-8")
        if with_extract:
            extract_dir = packet_dir / "extract"
            extract_dir.mkdir()
            extraction = {
                "fields": {
                    "merchant": "VONS",
                    "total": None,
                    "tax": "0.00",
                    "last_four": None,
                }
            }
            (extract_dir / "extract.json").write_text(json.dumps(extraction), encoding="utf-8")
        record = {
            "packet_id": packet_id,
            "source_packet_dir": str(packet_dir),
        }
        return packet_json, record

    def write_catalog(self, root: Path, records):
        catalog = root / "Catalog" / "ingest_catalog.jsonl"
        catalog.parent.mkdir()
        catalog.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
        return catalog

    def args(self, **kwargs):
        values = {
            "packet": "laia-scan-1",
            "merchant": None,
            "transaction_date": None,
            "transaction_time": None,
            "subtotal": None,
            "tax": None,
            "tip": None,
            "total": None,
            "payment_method": None,
            "last_four": None,
            "currency": None,
            "note": None,
        }
        values.update(kwargs)
        return argparse.Namespace(**values)

    def test_correct_extract_finds_packet_by_packet_id(self):
        record = {"packet_id": "wanted"}

        found = find_catalog_record("wanted", [{"packet_id": "other"}, record])

        self.assertEqual(found, record)

    def test_writes_correction_json_and_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_json, record = self.make_packet(Path(tmp))
            correction = build_correction(record, {"total": "4.99"}, [])
            correction_json, correction_md = write_correction(record, correction)

            self.assertTrue(correction_json.exists())
            self.assertTrue(correction_md.exists())

    def test_fails_if_packet_id_not_found(self):
        with self.assertRaisesRegex(SystemExit, "Packet ID not found in catalog"):
            find_catalog_record("missing", [{"packet_id": "other"}])

    def test_fails_if_extract_sidecar_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_json, record = self.make_packet(Path(tmp), with_extract=False)

            with self.assertRaisesRegex(SystemExit, "No extraction sidecar found for packet"):
                build_correction(record, {"total": "4.99"}, [])

    def test_requires_at_least_one_correction_or_note(self):
        with self.assertRaisesRegex(SystemExit, "At least one correction field or note is required"):
            correction_values(self.args())

    def test_supports_total(self):
        corrections, notes = correction_values(self.args(total="4.99"))

        self.assertEqual(corrections, {"total": "4.99"})
        self.assertEqual(notes, [])

    def test_supports_multiple_fields(self):
        corrections, notes = correction_values(
            self.args(merchant="VONS", total="4.99", note="manual correction")
        )

        self.assertEqual(corrections["merchant"], "VONS")
        self.assertEqual(corrections["total"], "4.99")
        self.assertEqual(notes, ["manual correction"])

    def test_rejects_bad_last_four(self):
        with self.assertRaisesRegex(SystemExit, "last_four must be exactly 4 digits"):
            correction_values(self.args(last_four="12345"))

    def test_preserves_previous_corrections(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_json, record = self.make_packet(Path(tmp))
            first = build_correction(record, {"merchant": "VONS"}, ["first"])
            write_correction(record, first)
            second = build_correction(record, {"total": "4.99"}, ["second"])

            self.assertEqual(second["corrections"]["merchant"]["corrected"], "VONS")
            self.assertEqual(second["corrections"]["total"]["corrected"], "4.99")
            self.assertEqual(second["notes"], ["first", "second"])

    def test_overwrites_explicit_corrected_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            _packet_json, record = self.make_packet(Path(tmp))
            first = build_correction(record, {"total": "4.99"}, [])
            write_correction(record, first)
            second = build_correction(record, {"total": "5.99"}, [])

            self.assertEqual(second["corrections"]["total"]["corrected"], "5.99")
            self.assertEqual(second["changed_fields"], ["total"])

    def test_does_not_modify_catalog_packet_or_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json, record = self.make_packet(root)
            catalog = self.write_catalog(root, [record])
            extract_json = Path(record["source_packet_dir"]) / "extract" / "extract.json"
            before_catalog = catalog.read_text(encoding="utf-8")
            before_packet = packet_json.read_text(encoding="utf-8")
            before_extract = extract_json.read_text(encoding="utf-8")

            with patch("core.librarian.correct_extract.catalog_path", return_value=catalog):
                command_correct_extract(self.args(total="4.99"))

            self.assertEqual(catalog.read_text(encoding="utf-8"), before_catalog)
            self.assertEqual(packet_json.read_text(encoding="utf-8"), before_packet)
            self.assertEqual(extract_json.read_text(encoding="utf-8"), before_extract)


if __name__ == "__main__":
    unittest.main()
