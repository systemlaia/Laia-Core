import json
import tempfile
import unittest
from pathlib import Path

from core.photo_ingest.cohorts import _write_json, add_files, cohort_dir, create_cohort, read_cohort
from core.photo_ingest.record_vision import confirm_record, create_record_cohorts, suggest_record_groups


class PhotoRecordGroupTests(unittest.TestCase):
    def make_packet(self, root: Path) -> Path:
        packet = root / "packet"
        (packet / "originals/ROLL").mkdir(parents=True)
        (packet / "review").mkdir()
        files = []
        for number in range(1, 7):
            relative = f"ROLL/IMG{number}.JPG"
            (packet / "originals" / relative).write_bytes(b"image")
            files.append(relative)
        create_cohort(packet, "Records for sale")
        add_files(packet, "records-for-sale", files)
        return packet

    def write_candidates(self, packet: Path):
        rows = []
        types = ["cover_front", "cover_back", "label", "cover_front", "detail", "vinyl"]
        for number, image_type in enumerate(types, 1):
            rows.append(
                {
                    "relative_path": f"ROLL/IMG{number}.JPG", "status": "ok",
                    "candidate": {
                        "image_type": image_type,
                        "artist": "Artist" if image_type == "cover_front" else "",
                        "title": f"Album {number}" if image_type == "cover_front" else "",
                        "confidence": "high" if image_type == "cover_front" else "medium",
                    },
                }
            )
        _write_json(
            cohort_dir(packet, "records-for-sale") / "vision/record_candidates.json",
            {"candidates": rows},
        )

    def test_grouping_starts_at_cover_front_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            self.write_candidates(packet)
            result = suggest_record_groups(packet, "records-for-sale")
            self.assertEqual(len(result["groups"]), 2)
            self.assertEqual(result["groups"][0]["files"], [f"ROLL/IMG{x}.JPG" for x in [1, 2, 3]])
            self.assertEqual(result["groups"][1]["files"], [f"ROLL/IMG{x}.JPG" for x in [4, 5, 6]])

    def test_partial_vision_data_keeps_manual_grouping_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            _write_json(
                cohort_dir(packet, "records-for-sale") / "vision/record_candidates.json",
                {
                    "candidates": [
                        {
                            "relative_path": "ROLL/IMG1.JPG", "status": "ok",
                            "candidate": {"image_type": "label", "confidence": "low"},
                        }
                    ]
                },
            )
            result = suggest_record_groups(packet, "records-for-sale", group_size=3)
            self.assertEqual(len(result["groups"]), 2)
            self.assertTrue(result["groups"][0]["manual_hint"])

    def test_child_cohort_has_stable_id_parent_and_candidate_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            self.write_candidates(packet)
            suggest_record_groups(packet, "records-for-sale")
            created = create_record_cohorts(packet, "records-for-sale", limit=1)
            self.assertEqual(created[0]["cohort_id"], "record-001")
            self.assertEqual(created[0]["name"], "Artist - Album 1")
            self.assertEqual(created[0]["parent_cohort_id"], "records-for-sale")
            self.assertEqual(
                [row["relative_path"] for row in read_cohort(packet, "record-001")["files"]],
                [f"ROLL/IMG{x}.JPG" for x in [1, 2, 3]],
            )

    def test_confirmed_metadata_is_separate_from_candidate_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp))
            self.write_candidates(packet)
            suggest_record_groups(packet, "records-for-sale")
            create_record_cohorts(packet, "records-for-sale", limit=1)
            result = confirm_record(packet, "record-001", "Human Artist", "Human Title", "Label", "CAT-1")
            confirmed = json.loads(Path(result["path"]).read_text())
            candidate = json.loads(
                (cohort_dir(packet, "records-for-sale") / "vision/record_candidates.json").read_text()
            )
            self.assertEqual(confirmed["record_type"], "laia.confirmed_record_metadata")
            self.assertEqual(confirmed["artist"], "Human Artist")
            self.assertEqual(candidate["candidates"][0]["candidate"]["artist"], "Artist")


if __name__ == "__main__":
    unittest.main()
