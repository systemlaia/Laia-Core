import os
import json
import tempfile
import unittest
import argparse
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

from test_packets_registry import PacketRegistryTests
from core.packets.registry import (
    BUILTIN_VIEWS,
    command_packets_views,
    command_packets_view,
    search_packets,
    load_registry_rows,
    scan_roots,
    PacketRoot,
)
from core.packets.standard import write_review_sidecar, write_packet_manifest
from core.paper_ingest.standardize import write_workflow_state


class PacketViewsTests(unittest.TestCase):
    def setUp(self):
        self.helper = PacketRegistryTests()

    def test_views_command_lists_builtins(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            command_packets_views(argparse.Namespace())
        text = out.getvalue()
        # ensure a few known views appear
        self.assertIn("all", text)
        self.assertIn("promoted", text)
        self.assertIn("ready-unrouted", text)

    def test_view_promoted_returns_promoted_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.helper.make_search_registry(Path(tmp))
            env = self.helper.registry_env(db_path)
            with patch.dict(os.environ, env, clear=False):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="promoted", json=False, limit=None))
                text = out.getvalue()
                self.assertIn("search-photo", text)

    def test_view_publication_and_project_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            # create registry and a promoted publication
            db_path = self.helper.make_search_registry(Path(tmp))
            # promote another packet to project
            root = Path(tmp)
            photo = self.helper.make_photo_packet(root / "photo", job_id="project-photo")
            write_review_sidecar(photo, {"review_status": "reviewed"})
            (photo / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            env = self.helper.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(root / "promoted")
            env["LAIA_PACKET_EXPORT_ROOT"] = str(root / "exports")
            with patch.dict(os.environ, env, clear=False):
                from core.packets.registry import command_packets_route, command_packets_execute_route, command_packets_review_output, command_packets_promote

                # route, execute, and review before promoting to project
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="project-photo", destination_type="export", destination="", note=""))
                    command_packets_execute_route(argparse.Namespace(identifier="project-photo", dry_run=False))
                # refresh registry
                scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="project-photo", status="reviewed", note="review note"))
                # promote to project
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(argparse.Namespace(identifier="project-photo", destination_type="project", destination="My Project", note="note", dry_run=False))
                scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
                with patch.dict(os.environ, env, clear=False):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        command_packets_view(argparse.Namespace(view="publication-ready", json=False, limit=None))
                    self.assertIn("search-photo", out.getvalue())
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        command_packets_view(argparse.Namespace(view="project-ready", json=False, limit=None))
                    self.assertIn("project-photo", out.getvalue())

    def test_view_attention_ready_unrouted_executed_unreviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = Path(tmp) / "registry.db"
            # attention packet
            bad = self.helper.make_photo_packet(root / "photo", job_id="needs-att", missing_report=True)
            # ready packet
            ready = self.helper.make_photo_packet(root / "photo", job_id="ready-pkt")
            write_review_sidecar(ready, {"review_status": "reviewed"})
            # routed packet
            route = self.helper.make_photo_packet(root / "photo", job_id="routed-pkt")
            write_review_sidecar(route, {"review_status": "reviewed"})
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            env = self.helper.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(root / "exports")
            with patch.dict(os.environ, env, clear=False):
                from core.packets.registry import command_packets_route, command_packets_execute_route, command_packets_review_output

                # route and execute a packet to create executed-unreviewed
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="routed-pkt", destination_type="export", destination="", note=""))
                    command_packets_execute_route(argparse.Namespace(identifier="routed-pkt", dry_run=False))
                # now executed-unreviewed should include routed-pkt
                # refresh registry to pick up executed state
                scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="executed-unreviewed", json=False, limit=None))
                self.assertIn("routed-pkt", out.getvalue())
                # attention view
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="attention", json=False, limit=None))
                self.assertIn("needs-att", out.getvalue())
                # ready-unrouted should include ready-pkt and exclude routed-pkt
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="ready-unrouted", json=False, limit=None))
                text = out.getvalue()
                self.assertIn("ready-pkt", text)
                self.assertNotIn("routed-pkt", text)

    def test_reviewed_unpromoted_and_reviewed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, db_path, _ = self.helper.reviewed_temp_export(Path(tmp), job_id="view-photo")
            env = self.helper.registry_env(db_path)
            with patch.dict(os.environ, env, clear=False):
                # reviewed-outputs should include it
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="reviewed-outputs", json=False, limit=None))
                self.assertIn("view-photo", out.getvalue())
                # unpromoted-reviewed-outputs should include it before promotion
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="unpromoted-reviewed-outputs", json=False, limit=None))
                self.assertIn("view-photo", out.getvalue())

    def test_healthy_photo_paper_and_unknown_json_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.helper.make_photo_packet(root / "photo", job_id="healthy-photo")
            write_review_sidecar(photo, {"review_status": "reviewed"})
            # add a second photo to test limit behavior
            photo2 = self.helper.make_photo_packet(root / "photo", job_id="healthy-photo2")
            write_review_sidecar(photo2, {"review_status": "reviewed"})
            paper = self.helper.make_paper_packet(root / "paper", job_id="healthy-paper")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = Path(tmp) / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])
            env = self.helper.registry_env(db_path)
            with patch.dict(os.environ, env, clear=False):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="healthy", json=False, limit=None))
                self.assertIn("healthy-photo", out.getvalue())
                # photo view
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="photo", json=False, limit=None))
                self.assertIn("healthy-photo", out.getvalue())
                # paper view
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="paper", json=False, limit=None))
                self.assertIn("healthy-paper", out.getvalue())
                # unknown view
                with self.assertRaises(SystemExit):
                    command_packets_view(argparse.Namespace(view="no-such-view", json=False, limit=None))
                # json output
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="photo", json=True, limit=1))
                data = json.loads(out.getvalue())
                self.assertIsInstance(data, list)
                # limit: request JSON and ensure only one entry is returned
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    command_packets_view(argparse.Namespace(view="photo", json=True, limit=1))
                data = json.loads(out.getvalue())
                self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
