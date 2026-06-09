import json
import tempfile
import unittest
from pathlib import Path

from core.librarian.route import route_packet


class LibrarianRouteTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        name: str = "2026-06-07_171935_inbox",
        packet_type: str = "laia.ingest.scan",
        with_index: bool = True,
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / name
        source_dir = packet_dir / "source"
        output_dir = packet_dir / "output"
        logs_dir = packet_dir / "logs"
        source_dir.mkdir(parents=True)
        output_dir.mkdir()
        logs_dir.mkdir()

        (source_dir / "page_0001.tif").write_bytes(b"image")
        (output_dir / "scan.pdf").write_bytes(b"%PDF")
        (logs_dir / "scanimage.log").write_text("log\n", encoding="utf-8")

        packet = {
            "packet_type": packet_type,
            "project": "Inbox",
            "page_count": 1,
            "paths": {
                "packet_dir": str(packet_dir),
                "source_dir": str(source_dir),
                "pdf": str(output_dir / "scan.pdf"),
                "scan_log": str(logs_dir / "scanimage.log"),
            },
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet), encoding="utf-8")

        if with_index:
            index_dir = packet_dir / "index"
            index_dir.mkdir()
            (index_dir / "index.json").write_text(
                json.dumps({"index_type": "laia.librarian.index"}),
                encoding="utf-8",
            )

        return packet_json

    def test_routing_requires_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_index=False)
            archive_root = Path(tmp) / "Archive" / "Ingest"

            with self.assertRaises(SystemExit):
                route_packet(packet_json, archive_root)

    def test_routing_preserves_packet_as_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            archive_root = Path(tmp) / "Archive" / "Ingest"
            metadata, _ = route_packet(packet_json, archive_root)
            destination = Path(metadata["destination_packet_dir"])

            self.assertTrue(destination.is_dir())
            self.assertTrue((destination / "packet.json").exists())
            self.assertTrue((destination / "source" / "page_0001.tif").exists())
            self.assertTrue((destination / "output" / "scan.pdf").exists())
            self.assertTrue((destination / "logs" / "scanimage.log").exists())
            self.assertTrue(packet_json.exists())

    def test_route_json_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            archive_root = Path(tmp) / "Archive" / "Ingest"
            metadata, source_route_path = route_packet(packet_json, archive_root)
            destination = Path(metadata["destination_packet_dir"])

            self.assertTrue(source_route_path.exists())
            self.assertTrue((destination / "route" / "route.json").exists())
            route_data = json.loads(source_route_path.read_text(encoding="utf-8"))
            self.assertEqual(route_data["action"], "copy")
            self.assertEqual(route_data["status"], "complete")

    def test_scan_packets_route_to_project_year_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), name="2026-06-07_171935_inbox")
            archive_root = Path(tmp) / "Archive" / "Ingest"
            metadata, _ = route_packet(packet_json, archive_root)

            expected = (
                archive_root
                / "Scans"
                / "inbox"
                / "2026"
                / "06"
                / "2026-06-07_171935_inbox"
            )
            self.assertEqual(Path(metadata["destination_packet_dir"]), expected)
            self.assertTrue(expected.exists())

    def test_rejects_non_laia_ingest_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), packet_type="external.scan")
            archive_root = Path(tmp) / "Archive" / "Ingest"

            with self.assertRaises(SystemExit):
                route_packet(packet_json, archive_root)


if __name__ == "__main__":
    unittest.main()
