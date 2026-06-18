import contextlib
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.packets.registry import (
    connect_registry,
    print_packet_record,
    registry_lifecycle,
    registry_record,
    upsert_registry_record,
)
from core.photo_ingest.cohorts import (
    add_files,
    add_subject,
    build_contact_sheet,
    create_cohort,
    export_cohort,
    range_files,
    read_cohort,
    read_cohort_index,
    read_subjects,
    remove_files,
    resolve_photo_packet,
    update_subject,
)


class PhotoCohortTests(unittest.TestCase):
    def make_packet(self, root: Path, job_id="20260610-184234_DSD_sd_ingest") -> Path:
        packet = root / "2026" / job_id
        for folder in ["originals/246_FUJI", "previews/246_FUJI", "metadata", "contact_sheet", "logs", "review"]:
            (packet / folder).mkdir(parents=True, exist_ok=True)
        checksum_lines = []
        for name in ["DSCF1.JPG", "DSCF2.JPG", "DSCF10.JPG", "DSCF11.JPG"]:
            content = name.encode()
            original = packet / "originals" / "246_FUJI" / name
            original.write_bytes(content)
            (packet / "previews" / "246_FUJI" / name).write_bytes(b"preview-" + content)
            checksum_lines.append(f"{hashlib.sha256(content).hexdigest()}  ./246_FUJI/{name}")
        (packet / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
        (packet / "contact_sheet" / "contact_sheet.jpg").write_bytes(b"sheet")
        (packet / "metadata" / "exiftool.json").write_text("[]\n", encoding="utf-8")
        (packet / "ingest_report.md").write_text("# report\n", encoding="utf-8")
        (packet / "review" / "selects.txt").write_text("246_FUJI/DSCF1.JPG\n", encoding="utf-8")
        manifest = {
            "packet_type": "laia.photo_ingest",
            "packet_version": "0.1",
            "job_id": job_id,
            "packet_path": str(packet),
            "source": "/tmp/card",
            "photo_count": 4,
            "packet_size": "1M",
            "created_at": "2026-06-10T18:42:34Z",
        }
        (packet / "packet_manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        return packet

    def test_direct_and_registry_packet_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root / "packets")
            db = root / "registry.db"
            conn = connect_registry(db)
            record = registry_record("photo", packet)
            upsert_registry_record(conn, record)
            conn.commit()
            conn.close()
            env = {
                "LAIA_PACKET_REGISTRY_DB": str(db),
                "LAIA_PHOTO_PACKET_ROOT": str(root / "packets"),
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(resolve_photo_packet(str(packet)), packet.resolve())
                self.assertEqual(resolve_photo_packet(packet.name), packet.resolve())

    def test_subject_add_is_idempotent_and_update_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            first = add_subject(packet, "CLD-3080")
            second = add_subject(packet, "CLD-3080", note="player", status="deferred")
            self.assertEqual(first["subject_id"], "cld-3080")
            self.assertEqual(len(read_subjects(packet)["subjects"]), 1)
            self.assertEqual(second["note"], "player")
            update_subject(packet, "cld-3080", name="Pioneer CLD-3080", status="archived")
            subject = read_subjects(packet)["subjects"][0]
            self.assertEqual(subject["name"], "Pioneer CLD-3080")
            self.assertEqual(subject["status"], "archived")

    def test_cohort_create_subject_parent_and_invalid_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            add_subject(packet, "Records for sale")
            parent = create_cohort(packet, "Records for sale", subject="Records for sale")
            child = create_cohort(packet, "Album one", subject="records-for-sale", parent=parent["cohort_id"])
            self.assertEqual(child["parent_cohort_id"], "records-for-sale")
            self.assertTrue((packet / "review/cohorts/album-one/cohort.json").is_file())
            self.assertTrue((packet / "review/cohorts/album-one/files.txt").is_file())
            self.assertEqual(len(read_cohort_index(packet)["cohorts"]), 2)
            with self.assertRaises(SystemExit):
                create_cohort(packet, "Bad child", parent="missing")

    def test_membership_validation_idempotence_overlap_and_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            original = packet / "originals/246_FUJI/DSCF1.JPG"
            before = original.read_bytes()
            create_cohort(packet, "One")
            create_cohort(packet, "Two")
            add_files(packet, "one", ["246_FUJI/DSCF1.JPG"])
            add_files(packet, "one", ["246_FUJI/DSCF1.JPG"])
            add_files(packet, "two", ["246_FUJI/DSCF1.JPG"])
            self.assertEqual(len(read_cohort(packet, "one")["files"]), 1)
            self.assertEqual(len(read_cohort(packet, "two")["files"]), 1)
            with self.assertRaises(SystemExit):
                add_files(packet, "one", ["../checksums.sha256"])
            with self.assertRaises(SystemExit):
                add_files(packet, "one", ["246_FUJI/missing.JPG"])
            remove_files(packet, "one", ["246_FUJI/DSCF1.JPG"])
            self.assertEqual(read_cohort(packet, "one")["files"], [])
            self.assertEqual(original.read_bytes(), before)

    def test_natural_range_and_dry_run_style_read_is_side_effect_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            create_cohort(packet, "Range")
            cohort_path = packet / "review/cohorts/range/cohort.json"
            before = cohort_path.read_text(encoding="utf-8")
            selected = range_files(packet, "246_FUJI", "DSCF2.JPG", "DSCF10.JPG")
            self.assertEqual(selected, ["246_FUJI/DSCF2.JPG", "246_FUJI/DSCF10.JPG"])
            self.assertEqual(cohort_path.read_text(encoding="utf-8"), before)
            add_files(packet, "range", selected, event="range_added")
            self.assertEqual(
                [item["relative_path"] for item in read_cohort(packet, "range")["files"]],
                selected,
            )
            with self.assertRaises(SystemExit):
                range_files(packet, "246_FUJI", "DSCF10.JPG", "DSCF2.JPG")

    def test_no_font_available_creates_unlabeled_contact_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            create_cohort(packet, "Sheet")
            add_files(packet, "sheet", ["246_FUJI/DSCF1.JPG", "246_FUJI/DSCF2.JPG"])

            def fake_run(command, **_kwargs):
                output = Path(command[-1])
                output.write_bytes(b"jpeg")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": "font warning"})()

            with patch("core.photo_ingest.cohorts.shutil.which", return_value="/usr/bin/magick"):
                with patch("core.photo_ingest.cohorts.contact_sheet_font", return_value=None):
                    with patch("core.photo_ingest.cohorts.subprocess.run", side_effect=fake_run) as run:
                        result = build_contact_sheet(packet, "sheet")
            self.assertTrue(Path(result["path"]).is_file())
            command = run.call_args.args[0]
            self.assertIn("+label", command)
            self.assertNotIn("-font", command)
            self.assertNotIn("-label", command)
            self.assertFalse(result["labeled"])
            sources = (packet / "review/cohorts/sheet/contact_sheet_sources.txt").read_text()
            self.assertIn("/previews/246_FUJI/DSCF1.JPG", sources)

    def test_invalid_font_configuration_uses_unlabeled_montage(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            create_cohort(packet, "Sheet")
            add_files(packet, "sheet", ["246_FUJI/DSCF1.JPG"])

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"jpeg")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            env = {"LAIA_PHOTO_CONTACT_SHEET_FONT": str(Path(tmp) / "missing-font.ttf")}
            with patch.dict(os.environ, env, clear=False):
                with patch("core.photo_ingest.cohorts.shutil.which", return_value="/usr/bin/magick"):
                    with patch("core.photo_ingest.cohorts.subprocess.run", side_effect=fake_run) as run:
                        result = build_contact_sheet(packet, "sheet")
            command = run.call_args.args[0]
            self.assertIn("+label", command)
            self.assertNotIn("-font", command)
            self.assertFalse(result["labeled"])

    def test_contact_sheet_contains_all_cohort_files_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            create_cohort(packet, "Sheet")
            expected = [
                "246_FUJI/DSCF10.JPG",
                "246_FUJI/DSCF1.JPG",
                "246_FUJI/DSCF11.JPG",
                "246_FUJI/DSCF2.JPG",
            ]
            add_files(packet, "sheet", expected)

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"jpeg")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("core.photo_ingest.cohorts.shutil.which", return_value="/usr/bin/magick"):
                with patch("core.photo_ingest.cohorts.contact_sheet_font", return_value=None):
                    with patch("core.photo_ingest.cohorts.subprocess.run", side_effect=fake_run):
                        result = build_contact_sheet(packet, "sheet")
            files = Path(result["files_path"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(files, expected)
            self.assertEqual(result["file_count"], len(expected))

    def test_verified_font_keeps_labeled_contact_sheet_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root / "packets")
            font = root / "Verified Font.ttf"
            font.write_bytes(b"font")
            create_cohort(packet, "Sheet")
            add_files(packet, "sheet", ["246_FUJI/DSCF1.JPG"])

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"jpeg")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("core.photo_ingest.cohorts.shutil.which", return_value="/usr/bin/magick"):
                with patch("core.photo_ingest.cohorts.contact_sheet_font", return_value=font.resolve()):
                    with patch("core.photo_ingest.cohorts.subprocess.run", side_effect=fake_run) as run:
                        result = build_contact_sheet(packet, "sheet")
            command = run.call_args.args[0]
            self.assertIn("-font", command)
            self.assertEqual(command[command.index("-font") + 1], str(font.resolve()))
            self.assertIn("-label", command)
            self.assertNotIn("+label", command)
            self.assertTrue(result["labeled"])
            self.assertFalse(result["fell_back_to_unlabeled"])

    def test_failed_label_rendering_retries_unlabeled_and_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root / "packets")
            font = root / "Verified Font.ttf"
            font.write_bytes(b"font")
            create_cohort(packet, "Sheet")
            add_files(packet, "sheet", ["246_FUJI/DSCF1.JPG", "246_FUJI/DSCF2.JPG"])
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                if len(calls) == 1:
                    return type(
                        "Result",
                        (),
                        {
                            "returncode": 1,
                            "stdout": "",
                            "stderr": "montage: unable to read font",
                        },
                    )()
                Path(command[-1]).write_bytes(b"jpeg")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("core.photo_ingest.cohorts.shutil.which", return_value="/usr/bin/magick"):
                with patch("core.photo_ingest.cohorts.contact_sheet_font", return_value=font.resolve()):
                    with patch("core.photo_ingest.cohorts.subprocess.run", side_effect=fake_run):
                        result = build_contact_sheet(packet, "sheet")
            self.assertEqual(len(calls), 2)
            self.assertIn("-font", calls[0])
            self.assertIn("+label", calls[1])
            self.assertNotIn("-font", calls[1])
            self.assertNotIn("-label", calls[1])
            self.assertTrue(Path(result["path"]).is_file())
            self.assertFalse(result["labeled"])
            self.assertTrue(result["fell_back_to_unlabeled"])

    def test_export_writes_files_manifest_report_and_preserves_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root / "packets")
            selects = packet / "review/selects.txt"
            before_selects = selects.read_text(encoding="utf-8")
            create_cohort(packet, "Export")
            add_files(packet, "export", ["246_FUJI/DSCF1.JPG"])
            result = export_cohort(packet, "export", str(root / "out"))
            self.assertTrue((root / "out/files/246_FUJI/DSCF1.JPG").is_file())
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["file_count"], 1)
            self.assertTrue(Path(result["report"]).is_file())
            self.assertEqual(selects.read_text(encoding="utf-8"), before_selects)

    def test_registry_fields_and_human_outputs_include_photo_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_packet(root / "packets")
            add_subject(packet, "CLD-3080")
            create_cohort(packet, "CLD-3080", subject="CLD-3080", status="ready")
            add_files(packet, "cld-3080", ["246_FUJI/DSCF1.JPG"])
            record = registry_record("photo", packet)
            self.assertEqual(record["photo_subject_count"], 1)
            self.assertEqual(record["photo_cohort_count"], 1)
            db = root / "registry.db"
            conn = connect_registry(db)
            upsert_registry_record(conn, record)
            conn.commit()
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM packets").fetchone()
            conn.close()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                print_packet_record(row)
            self.assertIn("Photo Subjects:", output.getvalue())
            self.assertIn("CLD-3080", output.getvalue())
            lifecycle = registry_lifecycle(row, packet)
            self.assertIn("Photo Cohorts:", lifecycle)
            self.assertIn("cld-3080: 1 files, ready", lifecycle)

    def test_legacy_packet_without_sidecars_still_scans(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            record = registry_record("photo", packet)
            self.assertEqual(record["photo_subject_count"], 0)
            self.assertEqual(record["photo_cohort_count"], 0)


if __name__ == "__main__":
    unittest.main()
