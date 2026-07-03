import tempfile
import unittest
from pathlib import Path

from core.photo_ingest.cohorts import add_files, build_contact_sheet_html, create_cohort


class PhotoContactSheetHtmlTests(unittest.TestCase):
    def make_packet(self, root: Path, count=49) -> Path:
        packet = root / "packet"
        (packet / "originals/ROLL").mkdir(parents=True)
        (packet / "previews/ROLL").mkdir(parents=True)
        (packet / "review").mkdir()
        files = []
        for index in range(1, count + 1):
            name = f"IMG{index:04d}.JPG"
            relative = f"ROLL/{name}"
            (packet / "originals" / relative).write_bytes(b"original")
            (packet / "previews/ROLL" / f"IMG{index:04d}.jpg").write_bytes(b"preview")
            files.append(relative)
        create_cohort(packet, "Records")
        add_files(packet, "records", files)
        return packet

    def test_html_contains_all_49_filenames_sections_and_required_file_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            result = build_contact_sheet_html(packet, "records", page_size=25, columns=5)
            html = Path(result["path"]).read_text()
            self.assertEqual(result["file_count"], 49)
            self.assertEqual(result["preview_count"], 49)
            self.assertIn("ROLL/IMG0001.JPG", html)
            self.assertIn("ROLL/IMG0049.JPG", html)
            self.assertIn('id="page-1"', html)
            self.assertIn('id="page-2"', html)
            self.assertEqual(len(Path(result["files_path"]).read_text().splitlines()), 49)
            self.assertNotIn("http://", html)
            self.assertNotIn("https://", html)

    def test_preview_is_preferred_and_missing_preview_falls_back_to_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp), count=2)
            (packet / "previews/ROLL/IMG0002.jpg").unlink()
            result = build_contact_sheet_html(packet, "records")
            html = Path(result["path"]).read_text()
            self.assertEqual(result["preview_count"], 1)
            self.assertEqual(result["original_count"], 1)
            self.assertIn("../../../previews/ROLL/IMG0001.", html)
            self.assertIn("../../../originals/ROLL/IMG0002.JPG", html)


if __name__ == "__main__":
    unittest.main()
