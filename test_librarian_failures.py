import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.modules.setdefault("yaml", types.SimpleNamespace(safe_load=lambda _text: None))

from core.librarian.failures import mark_failure_dirs
from core.workflow import scan_document


class LibrarianFailureTests(unittest.TestCase):
    def make_log_only_scan(self, root: Path, name: str, log_text: str) -> Path:
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / name
        logs_dir = packet_dir / "logs"
        logs_dir.mkdir(parents=True)
        (logs_dir / "scanimage.log").write_text(log_text, encoding="utf-8")
        return packet_dir

    def test_mark_failures_writes_failure_sidecars_for_log_only_scan_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_dir = self.make_log_only_scan(
                root,
                "2026-06-08_141750_receipts",
                "STDERR\nscanimage: Document feeder jammed\n",
            )

            written = mark_failure_dirs(root / "Inbox" / "Ingest" / "Scans")

            self.assertEqual(len(written), 1)
            failure_json = packet_dir / "failure" / "failure.json"
            failure_md = packet_dir / "failure" / "failure.md"
            self.assertTrue(failure_json.exists())
            self.assertTrue(failure_md.exists())
            data = json.loads(failure_json.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "failed")
            self.assertEqual(data["failure_status"], "Document feeder jammed")

    def test_mark_failures_ignores_folders_with_packet_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_dir = self.make_log_only_scan(
                root,
                "2026-06-08_141750_receipts",
                "STDERR\nscanimage failed\n",
            )
            (packet_dir / "packet.json").write_text('{"packet_type": "laia.ingest.scan"}\n', encoding="utf-8")

            written = mark_failure_dirs(root / "Inbox" / "Ingest" / "Scans")

            self.assertEqual(written, [])
            self.assertFalse((packet_dir / "failure" / "failure.json").exists())

    def test_workflow_failure_writes_failure_sidecar_when_packet_dir_is_known(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_dir = Path(tmp) / "Inbox" / "Ingest" / "Scans" / "2026-06-08_141750_receipts"
            (packet_dir / "logs").mkdir(parents=True)
            (packet_dir / "logs" / "scanimage.log").write_text("STDERR\nscanimage failed\n", encoding="utf-8")

            def failing_stage(_args):
                raise SystemExit(f"scanimage failed; see {packet_dir / 'logs' / 'scanimage.log'}")

            with self.assertRaises(SystemExit):
                scan_document.run_stage(
                    "ingest scan",
                    failing_stage,
                    SimpleNamespace(),
                    mark_failure=True,
                )

            failure_json = packet_dir / "failure" / "failure.json"
            failure_md = packet_dir / "failure" / "failure.md"
            self.assertTrue(failure_json.exists())
            self.assertTrue(failure_md.exists())
            data = json.loads(failure_json.read_text(encoding="utf-8"))
            self.assertEqual(data["stage"], "ingest scan")
            self.assertEqual(data["status"], "failed")


if __name__ == "__main__":
    unittest.main()
