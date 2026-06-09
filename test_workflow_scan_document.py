import contextlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.modules.setdefault("yaml", types.SimpleNamespace(safe_load=lambda _text: None))
CORE_PATH = Path(__file__).resolve().parent / "core"
if str(CORE_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_PATH))
for module_name in list(sys.modules):
    if module_name == "ingest" or module_name.startswith("ingest."):
        del sys.modules[module_name]

from core.cli.laia import build_parser
from core.workflow import scan_document


class PatchModule:
    def __init__(self, module, **replacements):
        self.module = module
        self.replacements = replacements
        self.originals = {}

    def __enter__(self):
        for name, value in self.replacements.items():
            self.originals[name] = getattr(self.module, name)
            setattr(self.module, name, value)

    def __exit__(self, exc_type, exc, tb):
        for name, value in self.originals.items():
            setattr(self.module, name, value)


class WorkflowScanDocumentTests(unittest.TestCase):
    def test_workflow_parser_accepts_scan_document_dry_run(self):
        parser = build_parser()
        args = parser.parse_args(
            ["workflow", "scan-document", "--profile", "document", "--project", "Inbox", "--dry-run"]
        )

        self.assertEqual(args.command, "workflow")
        self.assertEqual(args.subcommand, "scan-document")
        self.assertEqual(args.profile, "document")
        self.assertEqual(args.project, "Inbox")
        self.assertTrue(args.dry_run)

    def test_workflow_parser_accepts_scan_document_verbose(self):
        parser = build_parser()
        args = parser.parse_args(
            ["workflow", "scan-document", "--profile", "document", "--project", "Inbox", "--verbose"]
        )

        self.assertEqual(args.command, "workflow")
        self.assertEqual(args.subcommand, "scan-document")
        self.assertEqual(args.profile, "document")
        self.assertEqual(args.project, "Inbox")
        self.assertTrue(args.verbose)

    def test_default_mode_suppresses_per_stage_output(self):
        def stage(name):
            def _inner(_args):
                print(f"{name} output")
            return _inner

        summary = {
            "packet_dir": "/tmp/packet",
            "packet": {
                "project": "Inbox",
                "profile": "document",
                "page_count": 1,
                "ocr_status": "complete",
            },
            "classification": {"primary_category": "receipt", "confidence": 0.9},
            "review": {"review_status": "pending", "recommended_action": "approve_classification"},
        }

        with PatchModule(
            scan_document,
            command_scan=stage("ingest scan"),
            command_index=stage("librarian index"),
            command_route=stage("librarian route"),
            command_summarize=stage("librarian summarize"),
            command_classify=stage("librarian classify"),
            command_review=stage("librarian review"),
            find_latest_packet=lambda: Path("/tmp/packet/packet.json"),
            workflow_summary=lambda _packet_json: summary,
        ):
            args = SimpleNamespace(profile="document", project="Inbox", tags="", dry_run=False, verbose=False)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                scan_document.command_scan_document(args)

        text = output.getvalue()
        self.assertIn("LAIA Scan Document Workflow Complete", text)
        self.assertNotIn("ingest scan output", text)
        self.assertNotIn("librarian index output", text)
        self.assertNotIn("librarian review output", text)

    def test_verbose_mode_includes_per_stage_output(self):
        def stage(name):
            def _inner(_args):
                print(f"{name} output")
            return _inner

        summary = {
            "packet_dir": "/tmp/packet",
            "packet": {
                "project": "Inbox",
                "profile": "document",
                "page_count": 1,
                "ocr_status": "complete",
            },
            "classification": {"primary_category": "receipt", "confidence": 0.9},
            "review": {"review_status": "pending", "recommended_action": "approve_classification"},
        }

        with PatchModule(
            scan_document,
            command_scan=stage("ingest scan"),
            command_index=stage("librarian index"),
            command_route=stage("librarian route"),
            command_summarize=stage("librarian summarize"),
            command_classify=stage("librarian classify"),
            command_review=stage("librarian review"),
            find_latest_packet=lambda: Path("/tmp/packet/packet.json"),
            workflow_summary=lambda _packet_json: summary,
        ):
            args = SimpleNamespace(profile="document", project="Inbox", tags="", dry_run=False, verbose=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                scan_document.command_scan_document(args)

        text = output.getvalue()
        self.assertIn("ingest scan output", text)
        self.assertIn("librarian index output", text)
        self.assertIn("librarian review output", text)
        self.assertIn("LAIA Scan Document Workflow Complete", text)

    def test_dry_run_does_not_create_packet_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = SimpleNamespace(profile="document", project="Inbox", tags="", dry_run=True)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                scan_document.command_scan_document(args)

            self.assertIn("LAIA Scan Document Workflow Dry Run", output.getvalue())
            self.assertFalse((root / "Inbox" / "Ingest").exists())

    def test_workflow_calls_stages_in_correct_order(self):
        calls = []
        packet_json = Path("/tmp/packet/packet.json")

        def stage(name):
            def _inner(_args):
                calls.append(name)
            return _inner

        def fake_summary(_packet_json):
            calls.append("summary")
            return {
                "packet_dir": "/tmp/packet",
                "packet": {
                    "project": "Inbox",
                    "profile": "document",
                    "page_count": 2,
                    "ocr_status": "complete",
                },
                "classification": {"primary_category": "receipt", "confidence": 0.9},
                "review": {
                    "review_status": "pending",
                    "recommended_action": "approve_classification",
                },
            }

        with PatchModule(
            scan_document,
            command_scan=stage("ingest scan"),
            command_index=stage("librarian index"),
            command_route=stage("librarian route"),
            command_summarize=stage("librarian summarize"),
            command_classify=stage("librarian classify"),
            command_review=stage("librarian review"),
            find_latest_packet=lambda: packet_json,
            workflow_summary=fake_summary,
        ):
            args = SimpleNamespace(profile="document", project="Inbox", tags="", dry_run=False)
            with contextlib.redirect_stdout(io.StringIO()):
                scan_document.command_scan_document(args)

        self.assertEqual(
            calls,
            [
                "ingest scan",
                "librarian index",
                "librarian route",
                "librarian summarize",
                "librarian classify",
                "librarian review",
                "summary",
            ],
        )

    def test_workflow_stops_if_scan_stage_fails(self):
        calls = []

        def failing_scan(_args):
            calls.append("scan")
            raise SystemExit("scan failed")

        def index(_args):
            calls.append("index")

        with PatchModule(scan_document, command_scan=failing_scan, command_index=index):
            args = SimpleNamespace(profile="document", project="Inbox", tags="", dry_run=False)
            output = io.StringIO()
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stdout(output):
                    scan_document.command_scan_document(args)

        self.assertEqual(calls, ["scan"])
        self.assertIn("Stage: ingest scan", output.getvalue())

    def test_workflow_stops_if_index_stage_fails(self):
        calls = []

        def scan(_args):
            calls.append("scan")

        def index(_args):
            calls.append("index")
            raise SystemExit("index failed")

        def route(_args):
            calls.append("route")

        with PatchModule(
            scan_document,
            command_scan=scan,
            command_index=index,
            command_route=route,
            find_latest_packet=lambda: Path("/tmp/packet/packet.json"),
        ):
            args = SimpleNamespace(profile="document", project="Inbox", tags="", dry_run=False)
            output = io.StringIO()
            with self.assertRaises(SystemExit):
                with contextlib.redirect_stdout(output):
                    scan_document.command_scan_document(args)

        self.assertEqual(calls, ["scan", "index"])
        self.assertIn("Stage: librarian index", output.getvalue())

    def test_workflow_summary_includes_recommended_next_commands(self):
        summary = {
            "packet_dir": "/tmp/packet",
            "packet": {
                "project": "Inbox",
                "profile": "document",
                "page_count": 2,
                "ocr_status": "complete",
            },
            "classification": {"primary_category": "receipt", "confidence": 0.9},
            "review": {"review_status": "pending", "recommended_action": "approve_classification"},
        }
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            scan_document.print_summary(summary)

        text = output.getvalue()
        self.assertIn("laia librarian approve --last", text)
        self.assertIn("laia librarian finalize --last", text)
        self.assertIn("laia librarian catalog --last", text)

    def test_standalone_commands_still_parse(self):
        parser = build_parser()
        commands = [
            ["ingest", "scan", "--test"],
            ["librarian", "index", "--last"],
            ["librarian", "route", "--last"],
            ["librarian", "summarize", "--last"],
            ["librarian", "classify", "--last"],
            ["librarian", "review", "--last"],
            ["librarian", "approve", "--last"],
            ["librarian", "finalize", "--last"],
            ["librarian", "dedupe", "--last"],
            ["librarian", "extract", "--last"],
            ["librarian", "extract", "--project", "Receipts", "--limit", "30"],
            ["librarian", "extract", "--project", "Receipts", "--limit", "30", "--force"],
            ["librarian", "extract", "--category", "receipt", "--limit", "30"],
            ["librarian", "extract", "--json"],
            ["librarian", "export", "--project", "Receipts", "--format", "csv"],
            ["librarian", "export", "--project", "Receipts", "--format", "csv", "--apply-corrections"],
            ["librarian", "export", "--project", "Receipts", "--format", "csv", "--raw"],
            ["librarian", "export", "--project", "Receipts", "--format", "json"],
            ["librarian", "export", "--category", "receipt", "--format", "csv", "--limit", "5"],
            ["librarian", "export", "--project", "Receipts", "--format", "csv", "--output", "/tmp/receipts.csv"],
            ["librarian", "extract-report", "--project", "Receipts"],
            ["librarian", "extract-report", "--project", "Receipts", "--limit", "30"],
            ["librarian", "extract-report", "--category", "receipt"],
            ["librarian", "extract-report", "--project", "Receipts", "--json"],
            ["librarian", "extract-report", "--project", "Receipts", "--raw"],
            ["librarian", "correct-extract", "--packet", "X", "--total", "4.99"],
            ["librarian", "correct-extract", "--packet", "X", "--merchant", "VONS", "--total", "4.99", "--note", "manual correction"],
            ["librarian", "inspect-extract", "--packet", "X"],
            ["librarian", "inspect-extract", "--packet", "X", "--lines", "20"],
            ["librarian", "inspect-extract", "--packet", "X", "--json"],
            ["librarian", "catalog", "--last"],
            ["librarian", "catalog", "--project", "Receipts", "--limit", "10"],
            ["librarian", "catalog", "--category", "receipt", "--json"],
            ["librarian", "mark-failures"],
            ["librarian", "pending"],
            ["librarian", "pending", "--limit", "5"],
            ["librarian", "pending", "--json"],
            ["grocy", "status"],
            ["grocy", "checkins", "draft"],
        ]

        for command in commands:
            with self.subTest(command=command):
                args = parser.parse_args(command)
                self.assertTrue(args.command)

    def test_make_test_includes_dedupe_test(self):
        makefile = Path(__file__).resolve().parent / "Makefile"
        text = makefile.read_text(encoding="utf-8")

        self.assertIn("test_librarian_dedupe.py", text)


if __name__ == "__main__":
    unittest.main()
