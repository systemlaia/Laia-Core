import argparse
import contextlib
import io
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.photo_ingest.commands import (
    build_catalog,
    command_rebuild_index,
    config_from_env,
    ensure_review,
    read_selects,
    verify_packet,
    write_selects,
)


ROOT = Path(__file__).resolve().parent


class PhotoIngestTests(unittest.TestCase):
    def env_for(self, tmp):
        tmp = Path(tmp)
        return {
            "LAIA_PHOTO_PACKET_ROOT": str(tmp / "packets"),
            "LAIA_PHOTO_CATALOG_ROOT": str(tmp / "catalogs"),
            "LAIA_PHOTO_LOCAL_ROOT": str(tmp / "local"),
        }

    def make_packet(self, root, job_id="20260610-184234_DSD_sd_ingest"):
        packet = Path(root) / "2026" / job_id
        for name in ["originals", "previews", "metadata", "contact_sheet", "logs"]:
            (packet / name).mkdir(parents=True, exist_ok=True)

        original = packet / "originals" / "DCIM" / "DSCF0001.JPG"
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(b"photo bytes")

        import hashlib

        checksum = hashlib.sha256(b"photo bytes").hexdigest()
        (packet / "checksums.sha256").write_text(f"{checksum}  ./DCIM/DSCF0001.JPG\n", encoding="utf-8")
        (packet / "contact_sheet" / "contact_sheet.jpg").write_bytes(b"jpg")
        manifest = {
            "packet_type": "laia.photo_ingest",
            "packet_version": "0.1",
            "job_id": job_id,
            "source": "/Volumes/CARD/DCIM",
            "packet_path": str(packet),
            "photo_count": 1,
            "packet_size": "12K",
            "created_at": "2026-06-10T18:42:34Z",
        }
        (packet / "packet_manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        (packet / "ingest_report.md").write_text("# report\n", encoding="utf-8")
        (packet / "metadata" / "exiftool.json").write_text(
            json.dumps(
                [
                    {
                        "SourceFile": str(packet / "originals" / "DCIM" / "DSCF0001.JPG"),
                        "Make": "FUJIFILM",
                        "Model": "X-T5",
                        "LensModel": "XF35mmF1.4",
                        "DateTimeOriginal": "2026:06:10 18:40:00",
                        "ISO": 400,
                        "Aperture": 2.8,
                        "ShutterSpeed": "1/125",
                        "FocalLength": "35.0 mm",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return packet

    def test_config_uses_photo_env_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.env_for(tmp)
            with patch.dict(os.environ, env, clear=False):
                cfg = config_from_env()

            self.assertEqual(cfg.packet_root, Path(env["LAIA_PHOTO_PACKET_ROOT"]))
            self.assertEqual(cfg.catalog_root, Path(env["LAIA_PHOTO_CATALOG_ROOT"]))
            self.assertEqual(cfg.local_root, Path(env["LAIA_PHOTO_LOCAL_ROOT"]))

    def test_verify_packet_accepts_existing_checksum_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = verify_packet(packet)

            self.assertEqual(result, 0)
            self.assertIn("PACKET VERIFIED", output.getvalue())

    def test_verify_packet_accepts_binary_checksum_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            checksum_file = packet / "checksums.sha256"
            checksum_file.write_text(checksum_file.read_text(encoding="utf-8").replace("  ./", " *./"), encoding="utf-8")
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = verify_packet(packet)

            self.assertEqual(result, 0)
            self.assertIn("./DCIM/DSCF0001.JPG: OK", output.getvalue())

    def test_verify_packet_reports_missing_required_photo_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            (packet / "previews").rmdir()
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = verify_packet(packet)

            self.assertEqual(result, 1)
            self.assertIn("MISSING: previews", output.getvalue())

    def test_rebuild_index_writes_compatible_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.env_for(tmp)
            packet = self.make_packet(Path(env["LAIA_PHOTO_PACKET_ROOT"]))

            with patch.dict(os.environ, env, clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_rebuild_index(argparse.Namespace())

            index = Path(env["LAIA_PHOTO_PACKET_ROOT"]) / "photo_ingest_index.csv"
            text = index.read_text(encoding="utf-8")
            self.assertIn("job_id,packet_path,source,photo_count,packet_size,created_at", text)
            self.assertIn(packet.name, text)

    def test_catalog_builds_sqlite_from_packet_without_modifying_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "packets"
            packet = self.make_packet(packet_root)
            manifest = packet / "packet_manifest.json"
            before = manifest.read_text(encoding="utf-8")
            db_path = Path(tmp) / "catalogs" / "photo_packets.db"

            conn = build_catalog(packet_root, db_path)
            conn.close()

            after = manifest.read_text(encoding="utf-8")
            self.assertEqual(before, after)
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM packets").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT camera_model FROM images").fetchone()[0], "X-T5")
            self.assertEqual(conn.execute("SELECT relative_path FROM checksums").fetchone()[0], "./DCIM/DSCF0001.JPG")
            conn.close()

    def test_review_sidecar_defaults_are_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")

            data, review_json, selects_txt = ensure_review(packet)

            self.assertEqual(data["review_status"], "new")
            self.assertTrue(review_json.exists())
            self.assertTrue(selects_txt.exists())

    def test_review_sidecar_invalid_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_packet(Path(tmp) / "packets")
            review_dir = packet / "review"
            review_dir.mkdir()
            (review_dir / "packet_review.json").write_text("{not json}\n", encoding="utf-8")

            data, review_json, selects_txt = ensure_review(packet)

            self.assertEqual(data["review_status"], "new")
            self.assertTrue(review_json.exists())
            self.assertTrue(selects_txt.exists())

    def test_selects_reader_ignores_headers_and_duplicates_are_removed_on_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            selects = Path(tmp) / "selects.txt"
            write_selects(selects, ["a.jpg", "a.jpg", "b.jpg"])

            self.assertEqual(read_selects(selects), ["a.jpg", "b.jpg"])

    def test_laia_photo_recent_limit_is_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.update(self.env_for(tmp))
            packet_root = Path(env["LAIA_PHOTO_PACKET_ROOT"])
            self.make_packet(packet_root)
            build_catalog(packet_root, Path(env["LAIA_PHOTO_CATALOG_ROOT"]) / "photo_packets.db").close()

            result = subprocess.run(
                [str(ROOT / "bin" / "laia"), "photo", "recent", "--limit", "10"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("DSCF0001.JPG", result.stdout)


if __name__ == "__main__":
    unittest.main()
