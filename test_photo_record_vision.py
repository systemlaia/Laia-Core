import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.photo_ingest.cohorts import add_files, create_cohort
from core.photo_ingest.record_vision import identify_records, vision_sidecar_path


class PhotoRecordVisionTests(unittest.TestCase):
    def make_packet(self, root: Path) -> Path:
        packet = root / "packet"
        (packet / "originals/ROLL").mkdir(parents=True)
        (packet / "previews/ROLL").mkdir(parents=True)
        (packet / "review").mkdir()
        for number in [1, 2]:
            (packet / f"originals/ROLL/IMG{number}.JPG").write_bytes(b"original")
            (packet / f"previews/ROLL/IMG{number}.jpg").write_bytes(b"preview")
        create_cohort(packet, "Records")
        add_files(packet, "records", ["ROLL/IMG1.JPG", "ROLL/IMG2.JPG"])
        return packet

    def test_unavailable_ollama_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            with patch("core.photo_ingest.record_vision.shutil.which", return_value=None):
                with self.assertRaisesRegex(SystemExit, "ollama pull llava"):
                    identify_records(packet, "records")

    def test_mocked_response_writes_sidecars_and_aggregate_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            response = json.dumps(
                {
                    "image_type": "cover_front", "artist": "Thelonious Monk",
                    "title": "Brilliant Corners", "record_label": "", "catalog_number": "",
                    "visible_text": ["Thelonious Monk", "Brilliant Corners"],
                    "format_hint": "vinyl record cover", "confidence": "medium",
                    "uncertainty_note": "Pressing unknown.",
                }
            )
            with patch("core.photo_ingest.record_vision.ollama_preflight", return_value="/usr/bin/ollama"):
                with patch("core.photo_ingest.record_vision.run_ollama_image", return_value=response):
                    result = identify_records(packet, "records", limit=1)
            sidecar = vision_sidecar_path(packet, "records", "ROLL/IMG1.JPG")
            self.assertTrue(sidecar.is_file())
            self.assertEqual(json.loads(sidecar.read_text())["candidate"]["artist"], "Thelonious Monk")
            self.assertIn("Thelonious Monk", Path(result["markdown_path"]).read_text())

    def test_invalid_json_is_recorded_as_failed_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            with patch("core.photo_ingest.record_vision.ollama_preflight", return_value="/usr/bin/ollama"):
                with patch("core.photo_ingest.record_vision.run_ollama_image", return_value="not json"):
                    result = identify_records(packet, "records", limit=1)
            sidecar = json.loads(vision_sidecar_path(packet, "records", "ROLL/IMG1.JPG").read_text())
            self.assertEqual(sidecar["status"], "failed")
            self.assertEqual(result["failed"], 1)


if __name__ == "__main__":
    unittest.main()
