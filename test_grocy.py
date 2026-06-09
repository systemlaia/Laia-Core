import contextlib
import io
import os
import sys
import types
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("yaml", types.SimpleNamespace(safe_load=lambda _text: None))
CORE_PATH = Path(__file__).resolve().parent / "core"
if str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))
for module_name in list(sys.modules):
    if module_name == "ingest" or module_name.startswith("ingest."):
        del sys.modules[module_name]

from core.cli.laia import build_parser
from core.grocy_service import (
    checkins_draft_markdown,
    command_grocy_checkins_draft,
    command_grocy_status,
    grocy_status,
)


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class GrocyServiceTests(unittest.TestCase):
    def test_cli_parser_accepts_grocy_status(self):
        args = build_parser().parse_args(["grocy", "status"])

        self.assertEqual(args.command, "grocy")
        self.assertEqual(args.subcommand, "status")

    def test_cli_parser_accepts_grocy_checkins_draft(self):
        args = build_parser().parse_args(["grocy", "checkins", "draft"])

        self.assertEqual(args.command, "grocy")
        self.assertEqual(args.subcommand, "checkins")
        self.assertEqual(args.checkins_command, "draft")

    def test_status_handles_missing_service_gracefully(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("core.grocy_service.urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
                status = grocy_status()

        self.assertEqual(status["url"], "http://127.0.0.1:9283")
        self.assertFalse(status["reachable"])
        self.assertFalse(status["api_key_configured"])

    def test_status_reports_api_key_configured_without_printing_key(self):
        output = io.StringIO()
        secret = "super-secret-key"
        with patch.dict(os.environ, {"LAIA_GROCY_URL": "http://grocy.local", "LAIA_GROCY_API_KEY": secret}, clear=True):
            with patch("core.grocy_service.urllib.request.urlopen", return_value=FakeResponse()):
                with contextlib.redirect_stdout(output):
                    command_grocy_status(SimpleNamespace())

        text = output.getvalue()
        self.assertIn("URL: http://grocy.local", text)
        self.assertIn("API key configured: yes", text)
        self.assertNotIn(secret, text)

    def test_checkins_draft_includes_laia_domains(self):
        markdown = checkins_draft_markdown()

        for value in ("pantry", "household", "workshop", "vehicle-ranger", "scanner-maintenance"):
            self.assertIn(value, markdown)

    def test_checkins_draft_command_prints_markdown(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            command_grocy_checkins_draft(SimpleNamespace())

        text = output.getvalue()
        self.assertIn("# LAIA Grocy Check-In Draft", text)
        self.assertIn("Pantry", text)
        self.assertIn("Scanner", text)

    def test_grocy_architecture_doc_exists(self):
        doc = Path("docs/grocy-architecture.md")

        self.assertTrue(doc.exists())
        self.assertIn("No automatic Grocy writes from OCR without review", doc.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
