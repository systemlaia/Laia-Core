import json
import tempfile
import unittest
from pathlib import Path

from core.packets import (
    checksum_path,
    count_checksum_entries,
    latest_packet,
    packet_manifest_path,
    packet_path,
    parse_checksum_file,
    read_packet_manifest,
    read_review_sidecar,
    review_sidecar_path,
    selects_path,
    validate_required_items,
    write_packet_manifest,
    write_review_sidecar,
)


class PacketStandardHelperTests(unittest.TestCase):
    def make_packet(self, root):
        packet = Path(root) / "2026" / "20260610-184234_test"
        for item in ["originals", "metadata", "logs"]:
            (packet / item).mkdir(parents=True, exist_ok=True)
        (packet / "checksums.sha256").write_text(
            "a" * 64 + "  ./DCIM/one.jpg\n" + "b" * 64 + " *./DCIM/two.jpg\n\n",
            encoding="utf-8",
        )
        (packet / "ingest_report.md").write_text("# report\n", encoding="utf-8")
        write_packet_manifest(
            packet,
            {
                "packet_type": "laia.test",
                "packet_version": "0.1",
                "job_id": packet.name,
                "source": "/tmp/source",
                "packet_path": str(packet),
                "created_at": "2026-06-10T18:42:34Z",
            },
        )
        return packet

    def test_packet_path_helpers_return_standard_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = packet_path(Path(tmp), "2026", "job")

            self.assertEqual(packet, Path(tmp) / "2026" / "job")
            self.assertEqual(packet_manifest_path(packet), packet / "packet_manifest.json")
            self.assertEqual(checksum_path(packet), packet / "checksums.sha256")
            self.assertEqual(review_sidecar_path(packet), packet / "review" / "packet_review.json")
            self.assertEqual(selects_path(packet), packet / "review" / "selects.txt")

    def test_manifest_read_write_round_trips_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "2026" / "job"
            manifest = {"packet_type": "laia.test", "job_id": "job"}

            path = write_packet_manifest(packet, manifest)

            self.assertEqual(path, packet / "packet_manifest.json")
            self.assertEqual(read_packet_manifest(packet), manifest)
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_checksum_parser_accepts_shasum_text_and_binary_forms(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            entries = parse_checksum_file(packet / "checksums.sha256")

            self.assertEqual(count_checksum_entries(packet / "checksums.sha256"), 2)
            self.assertEqual(entries[0].relative_path, "./DCIM/one.jpg")
            self.assertEqual(entries[1].relative_path, "./DCIM/two.jpg")
            self.assertEqual(entries[1].line_number, 2)

    def test_checksum_parser_rejects_malformed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checksums.sha256"
            path.write_text("not-enough-fields\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                parse_checksum_file(path)

    def test_required_item_validation_reports_present_and_missing_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            result = validate_required_items(packet)

            self.assertTrue(result.ok)
            self.assertEqual(result.missing, ())
            self.assertIn("packet_manifest.json", result.present)

            (packet / "ingest_report.md").unlink()
            result = validate_required_items(packet)
            self.assertFalse(result.ok)
            self.assertEqual(result.missing, ("ingest_report.md",))

    def test_review_sidecar_read_write_merges_defaults_and_creates_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            data = write_review_sidecar(packet, {"review_status": "reviewed", "notes": "Looks good"})

            self.assertEqual(data["review_status"], "reviewed")
            self.assertEqual(read_review_sidecar(packet)["notes"], "Looks good")
            self.assertIsNone(read_review_sidecar(packet)["rating_pass"])
            self.assertTrue(selects_path(packet).exists())

    def test_missing_review_sidecar_returns_defaults_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            data = read_review_sidecar(packet)

            self.assertEqual(data["review_status"], "new")
            self.assertFalse(review_sidecar_path(packet).exists())

    def test_read_review_sidecar_create_writes_default_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(tmp)

            data = read_review_sidecar(packet, create=True)

            self.assertEqual(data["review_status"], "new")
            self.assertTrue(review_sidecar_path(packet).exists())
            self.assertTrue(selects_path(packet).exists())

    def test_latest_packet_discovers_sorted_year_job_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = root / "2025" / "older"
            newer = root / "2026" / "newer"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)

            self.assertEqual(latest_packet(root), newer)

    def test_manifest_reader_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = Path(tmp) / "packet"
            packet.mkdir()
            (packet / "packet_manifest.json").write_text(json.dumps(["bad"]) + "\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                read_packet_manifest(packet)


if __name__ == "__main__":
    unittest.main()
