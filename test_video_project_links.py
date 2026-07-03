import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import command_projects_briefing, ensure_project_record, project_artifacts, project_packets, project_video_evidence
from core.video_ingest.commands import ingest_video, link_video_project


class VideoProjectLinkTests(unittest.TestCase):
    def setup_env(self, root: Path):
        env = {
            "LAIA_VIDEO_PACKET_ROOT": str(root / "packets"),
            "LAIA_VIDEO_LOCAL_ROOT": str(root / "local"),
            "LAIA_VIDEO_CATALOG_ROOT": str(root / "catalog"),
            "LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects"),
            "LAIA_PHOTO_PACKET_ROOT": str(root / "photo"),
            "LAIA_PACKET_REGISTRY_DB": str(root / "registry.db"),
        }
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        Path(env["LAIA_VIDEO_PACKET_ROOT"]).mkdir()
        ensure_project_record("CLD-3080")
        return env

    def video(self, path: Path):
        command = [
            __import__("shutil").which("ffmpeg"),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x54:rate=5:duration=0.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_project_link_is_idempotent_and_briefing_shows_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_env(root)
            source = root / "demo.mov"
            self.video(source)
            packet = Path(ingest_video(source, still_count=1)["packet"])
            link_video_project(packet, "cld-3080", "functional_demo", "works")
            link_video_project(packet, "cld-3080", "functional_demo", "works")
            self.assertEqual(len(project_packets("cld-3080")), 1)
            self.assertEqual(len(project_artifacts("cld-3080")), 1)
            self.assertEqual(len(project_video_evidence("cld-3080")), 1)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                command_projects_briefing(type("Args", (), {"identifier": "cld-3080", "json": False})())
            text = output.getvalue()
            self.assertIn("Video Evidence:", text)
            self.assertIn("functional_demo", text)
            self.assertIn("verification: ok", text)

    def test_link_does_not_change_sale_functional_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.setup_env(root)
            from core.projects.sale_items import init_sale_item, load_sale_item

            init_sale_item("cld-3080")
            source = root / "demo.mp4"
            self.video(source)
            packet = Path(ingest_video(source, still_count=1)["packet"])
            link_video_project(packet, "cld-3080", "functional_demo")
            self.assertEqual(load_sale_item("cld-3080")["condition"]["functional"], "untested")

    def test_compatibility_script_delegates_to_cli(self):
        script = Path(__file__).resolve().parent / "video_ingest/bin/laia_video_ingest_mkv.sh"
        text = script.read_text()
        self.assertIn("Deprecated: use 'laia video ingest FILE'.", text)
        self.assertIn('"$REPO_ROOT/bin/laia" video ingest "$@"', text)
        self.assertNotIn("ffmpeg", text)


if __name__ == "__main__":
    unittest.main()
