import json
import tempfile
import unittest
from pathlib import Path

from core.librarian.summarize import build_summary, write_summary


class LibrarianSummarizeTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        packet_type: str = "laia.ingest.scan",
        with_index: bool = True,
        with_route: bool = True,
        text: str = "alpha beta gamma\n",
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / "2026-06-07_171935_inbox"
        output_dir = packet_dir / "output"
        source_dir = packet_dir / "source"
        logs_dir = packet_dir / "logs"
        output_dir.mkdir(parents=True)
        source_dir.mkdir()
        logs_dir.mkdir()

        text_path = output_dir / "scan.txt"
        text_path.write_text(text, encoding="utf-8")
        pdf = output_dir / "scan.pdf"
        pdf.write_bytes(b"%PDF")

        packet = {
            "packet_type": packet_type,
            "created_at": "2026-06-07T17:19:35-07:00",
            "project": "Inbox",
            "page_count": 2,
            "ocr_status": "complete",
            "pdf_status": "created",
            "paths": {
                "packet_dir": str(packet_dir),
                "source_dir": str(source_dir),
                "pdf": str(pdf),
                "text": str(text_path),
                "scan_log": str(logs_dir / "scanimage.log"),
            },
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet), encoding="utf-8")

        if with_index:
            index_dir = packet_dir / "index"
            index_dir.mkdir()
            index = {
                "index_type": "laia.librarian.index",
                "text_stats": {
                    "character_count": len(text),
                    "word_count": len(text.split()),
                    "line_count": len(text.splitlines()),
                },
            }
            (index_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

        if with_route:
            route_dir = packet_dir / "route"
            route_dir.mkdir()
            route = {
                "destination_packet_dir": str(root / "Archive" / "Ingest" / "Scans" / "inbox"),
                "status": "complete",
            }
            (route_dir / "route.json").write_text(json.dumps(route), encoding="utf-8")

        return packet_json

    def test_summarize_requires_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_index=False)

            with self.assertRaises(SystemExit):
                build_summary(packet_json)

    def test_summarize_with_route_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_route=True)
            summary = build_summary(packet_json)

            self.assertTrue(summary["routed"])
            self.assertIn("Archive/Ingest/Scans/inbox", summary["destination_packet_dir"])

    def test_summarize_without_route_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_route=False)
            summary = build_summary(packet_json)

            self.assertFalse(summary["routed"])
            self.assertEqual(summary["destination_packet_dir"], "")

    def test_summary_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            summary = build_summary(packet_json)
            summary_md, summary_json = write_summary(packet_json, summary)

            self.assertTrue(summary_md.exists())
            self.assertTrue(summary_json.exists())
            self.assertIn("# LAIA Ingest Summary", summary_md.read_text(encoding="utf-8"))

    def test_text_preview_is_limited(self):
        with tempfile.TemporaryDirectory() as tmp:
            full_text = "word " * 400
            packet_json = self.make_packet(Path(tmp), text=full_text)
            summary = build_summary(packet_json, preview_limit=1000)

            self.assertLessEqual(len(summary["text_preview"]), 1000)
            self.assertNotEqual(summary["text_preview"], full_text.strip())

    def test_rejects_non_laia_ingest_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), packet_type="external.scan")

            with self.assertRaises(SystemExit):
                build_summary(packet_json)


if __name__ == "__main__":
    unittest.main()
