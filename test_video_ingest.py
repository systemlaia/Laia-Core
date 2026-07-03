import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.packets.registry import connect_registry, registry_lifecycle, registry_record, upsert_registry_record
from core.video_ingest.commands import (
    command_verify_last,
    config_from_env,
    ingest_video,
    normalized_summary,
    probe_video,
    sample_timestamps,
    verify_packet,
)


class VideoIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil_which("ffmpeg") or not shutil_which("ffprobe"):
            raise unittest.SkipTest("ffmpeg/ffprobe required")

    def env(self, root: Path) -> dict:
        return {
            "LAIA_VIDEO_PACKET_ROOT": str(root / "packets"),
            "LAIA_VIDEO_CATALOG_ROOT": str(root / "catalog"),
            "LAIA_VIDEO_LOCAL_ROOT": str(root / "local"),
            "LAIA_PHOTO_PACKET_ROOT": str(root / "photo"),
            "LAIA_PACKET_REGISTRY_DB": str(root / "registry.db"),
        }

    def generate_video(self, path: Path, duration=1.0, audio=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            shutil_which("ffmpeg"),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=160x90:rate=10:duration={duration}",
        ]
        if audio:
            command += ["-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}", "-shortest"]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if audio:
            command += ["-c:a", "aac"]
        command += [str(path)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def test_mov_mp4_and_mkv_are_accepted_and_non_video_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for suffix in [".mov", ".mp4", ".mkv"]:
                path = self.generate_video(root / f"video{suffix}")
                self.assertTrue(any(stream["codec_type"] == "video" for stream in probe_video(path)["streams"]))
            text = root / "not-video.mov"
            text.write_text("not video")
            with self.assertRaises(ValueError):
                probe_video(text)

    def test_missing_packet_root_fails_without_creating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.generate_video(root / "source.mov")
            env = self.env(root)
            packet_root = Path(env["LAIA_VIDEO_PACKET_ROOT"])
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaises(FileNotFoundError):
                    ingest_video(source)
            self.assertFalse(packet_root.exists())

    def test_ingest_preserves_checksum_generates_proxy_stills_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.generate_video(root / "source.mov", duration=1.2, audio=False)
            env = self.env(root)
            Path(env["LAIA_VIDEO_PACKET_ROOT"]).mkdir()
            with patch.dict(os.environ, env, clear=False):
                result = ingest_video(source, name="demo", still_count=3, proxy_width=120)
            packet = Path(result["packet"])
            manifest = json.loads((packet / "packet_manifest.json").read_text())
            summary = json.loads((packet / "metadata/technical_summary.json").read_text())
            self.assertEqual(manifest["packet_type"], "laia.video_ingest")
            self.assertEqual(manifest["source_checksum"], manifest["packet_copy_checksum"])
            self.assertEqual(manifest["source_checksum"], file_hash(source))
            self.assertTrue((packet / "originals/source.mov").is_file())
            self.assertTrue((packet / "proxy/demo_proxy.mp4").is_file())
            self.assertEqual(len(summary["sampled_stills"]), 3)
            self.assertTrue((packet / "stills/contact_sheet.jpg").is_file())
            self.assertEqual(verify_packet(packet, quiet=True)["status"], "ok")
            self.assertFalse(Path(env["LAIA_VIDEO_LOCAL_ROOT"], "working", result["job_id"]).exists())

    def test_checksum_mismatch_stops_ingest_and_keeps_failure_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.generate_video(root / "source.mp4")
            env = self.env(root)
            Path(env["LAIA_VIDEO_PACKET_ROOT"]).mkdir()
            hashes = ["a" * 64, "b" * 64]
            with patch.dict(os.environ, env, clear=False):
                with patch("core.video_ingest.commands.file_sha256", side_effect=hashes):
                    with self.assertRaises(ValueError):
                        ingest_video(source, name="mismatch")
            reports = list(Path(env["LAIA_VIDEO_LOCAL_ROOT"]).glob("working/*/failure_report.md"))
            self.assertEqual(len(reports), 1)
            self.assertFalse(list(Path(env["LAIA_VIDEO_PACKET_ROOT"]).glob("*/*")))

    def test_metadata_normalization_sampling_and_short_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.generate_video(Path(tmp) / "source.mp4", duration=1.0, audio=True)
            summary = normalized_summary(path, probe_video(path))
            self.assertEqual(summary["video_codec"], "h264")
            self.assertEqual(summary["audio_codec"], "aac")
            timestamps = sample_timestamps(65.065, 8)
            self.assertEqual(len(timestamps), 8)
            self.assertAlmostEqual(timestamps[0], 3.253, places=2)
            self.assertAlmostEqual(timestamps[-1], 61.812, places=2)
            self.assertGreaterEqual(len(sample_timestamps(0.2, 8)), 1)

    def test_verification_detects_missing_original_proxy_and_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.generate_video(root / "source.mp4")
            env = self.env(root)
            Path(env["LAIA_VIDEO_PACKET_ROOT"]).mkdir()
            with patch.dict(os.environ, env, clear=False):
                packet = Path(ingest_video(source, still_count=1)["packet"])
                original = next((packet / "originals").iterdir())
                original.rename(packet / "missing.tmp")
                self.assertEqual(verify_packet(packet, quiet=True)["status"], "failed")
                original = packet / "missing.tmp"
                original.rename(packet / "originals" / source.name)
                next((packet / "proxy").glob("*.mp4")).unlink()
                self.assertEqual(verify_packet(packet, quiet=True)["status"], "failed")
                shutil_copy(source, packet / "proxy/proxy.mp4")
                (packet / "checksums.sha256").write_text(f"{'0' * 64}  ./originals/{source.name}\n")
                self.assertIn("Original checksum mismatch.", verify_packet(packet, quiet=True)["errors"])

    def test_verify_last_registry_and_lifecycle_support_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.generate_video(root / "source.mp4")
            env = self.env(root)
            Path(env["LAIA_VIDEO_PACKET_ROOT"]).mkdir()
            with patch.dict(os.environ, env, clear=False):
                packet = Path(ingest_video(source, still_count=1)["packet"])
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_verify_last(None)
                self.assertIn("Verification status: ok", output.getvalue())
                record = registry_record("video_ingest", packet)
                self.assertEqual(record["packet_type"], "laia.video_ingest")
                self.assertEqual(record["video_still_count"], 1)
                conn = connect_registry(root / "registry.db")
                upsert_registry_record(conn, record)
                conn.commit()
                conn.row_factory = __import__("sqlite3").Row
                row = conn.execute("SELECT * FROM packets").fetchone()
                conn.close()
                lifecycle = registry_lifecycle(row, packet)
                self.assertIn("Video:", lifecycle)
                self.assertIn("proxy: present", lifecycle)


def shutil_which(name):
    import shutil

    return shutil.which(name)


def shutil_copy(source, destination):
    import shutil

    shutil.copy2(source, destination)


def file_hash(path):
    from core.video_ingest.commands import file_sha256

    return file_sha256(path)


if __name__ == "__main__":
    unittest.main()
