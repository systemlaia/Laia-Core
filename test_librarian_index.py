import json
import tempfile
import time
import unittest
from pathlib import Path

from core.librarian.index import build_index, find_latest_packet


class LibrarianIndexTests(unittest.TestCase):
    def make_packet(self, root: Path, name: str, packet_type: str = "laia.ingest.scan", with_text: bool = True):
        packet_dir = root / "Scans" / name
        source_dir = packet_dir / "source"
        output_dir = packet_dir / "output"
        logs_dir = packet_dir / "logs"
        source_dir.mkdir(parents=True)
        output_dir.mkdir()
        logs_dir.mkdir()

        (source_dir / "page_0001.tif").write_bytes(b"fake image 1")
        (source_dir / "page_0002.tif").write_bytes(b"fake image 2")
        pdf = output_dir / "scan.pdf"
        ocr_pdf = output_dir / "scan_ocr.pdf"
        scan_log = logs_dir / "scanimage.log"
        pdf.write_bytes(b"%PDF")
        ocr_pdf.write_bytes(b"%PDF OCR")
        scan_log.write_text("scan log\n", encoding="utf-8")

        text = output_dir / "scan.txt"
        if with_text:
            text.write_text("hello world\nsecond line\n", encoding="utf-8")

        packet = {
            "packet_type": packet_type,
            "project": "Inbox",
            "page_count": 2,
            "paths": {
                "packet_dir": str(packet_dir),
                "source_dir": str(source_dir),
                "pdf": str(pdf),
                "ocr_pdf": str(ocr_pdf),
                "text": str(text),
                "scan_log": str(scan_log),
            },
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet), encoding="utf-8")
        return packet_json

    def test_finds_latest_ingest_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_packet = self.make_packet(root, "2026-06-07_100000_old")
            time.sleep(0.01)
            new_packet = self.make_packet(root, "2026-06-07_110000_new")

            self.assertEqual(find_latest_packet(root), new_packet)
            self.assertNotEqual(find_latest_packet(root), old_packet)

    def test_indexes_scan_packet_with_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), "with_text", with_text=True)
            index = build_index(packet_json)

            self.assertEqual(index["packet_type"], "laia.ingest.scan")
            self.assertTrue(index["ocr_text_available"])
            self.assertEqual(index["text_stats"]["word_count"], 4)
            self.assertEqual(index["text_stats"]["line_count"], 2)
            self.assertEqual(index["file_inventory"]["source_image_count"], 2)
            self.assertTrue(index["file_inventory"]["pdf_exists"])
            self.assertTrue(index["file_inventory"]["ocr_pdf_exists"])
            self.assertTrue(index["file_inventory"]["text_exists"])
            self.assertTrue(index["file_inventory"]["scan_log_exists"])

    def test_indexes_scan_packet_without_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), "without_text", with_text=False)
            index = build_index(packet_json)

            self.assertFalse(index["ocr_text_available"])
            self.assertEqual(index["text_stats"]["character_count"], 0)
            self.assertEqual(index["text_stats"]["word_count"], 0)
            self.assertEqual(index["text_stats"]["line_count"], 0)
            self.assertFalse(index["file_inventory"]["text_exists"])

    def test_rejects_non_laia_ingest_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), "bad_type", packet_type="external.scan")

            with self.assertRaises(SystemExit):
                build_index(packet_json)


if __name__ == "__main__":
    unittest.main()
