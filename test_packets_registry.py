import os
import json
import sqlite3
import subprocess
import tempfile
import unittest
import argparse
import contextlib
import csv
import io
from pathlib import Path
from unittest.mock import patch

from core.packets.registry import (
    PacketRoot,
    command_packets_attention,
    command_packets_briefing,
    command_packets_clear_route,
    command_packets_execute_route,
    command_packets_execute_routes,
    command_packets_export_lifecycle,
    command_packets_export_lifecycles,
    command_packets_lifecycle,
    command_packets_lifecycle_files,
    command_packets_open,
    command_packets_output,
    command_packets_output_files,
    command_packets_output_history,
    command_packets_outputs,
    command_packets_promote,
    command_packets_promotion_files,
    command_packets_promotion_history,
    command_packets_promotion_status,
    command_packets_promotions,
    command_packets_queue,
    command_packets_ready,
    command_packets_review_output,
    command_packets_route,
    command_packets_route_history,
    command_packets_route_status,
    command_packets_routes,
    command_packets_search,
    config_from_env,
    connect_registry,
    export_csv_path,
    export_registry_csv,
    load_registry_rows,
    registry_record,
    registry_briefing,
    registry_report,
    read_routing,
    scan_roots,
    search_packets,
    write_routing,
)
from core.packets.standard import write_packet_manifest, write_review_sidecar
from core.paper_ingest.standardize import write_workflow_state


ROOT = Path(__file__).resolve().parent


class PacketRegistryTests(unittest.TestCase):
    def make_photo_packet(
        self,
        root,
        job_id="20260610-184234_DSD_sd_ingest",
        *,
        photo_count=2,
        missing_report=False,
    ):
        packet = Path(root) / "2026" / job_id
        for name in ["originals", "metadata", "logs"]:
            (packet / name).mkdir(parents=True, exist_ok=True)
        (packet / "originals" / "one.jpg").write_bytes(b"one")
        (packet / "originals" / "two.jpg").write_bytes(b"two")
        (packet / "checksums.sha256").write_text(
            "a" * 64 + "  ./one.jpg\n" + "b" * 64 + "  ./two.jpg\n",
            encoding="utf-8",
        )
        if not missing_report:
            (packet / "ingest_report.md").write_text("# report\n", encoding="utf-8")
        write_packet_manifest(
            packet,
            {
                "packet_type": "laia.photo_ingest",
                "packet_version": "0.1",
                "job_id": job_id,
                "source": "/Volumes/CARD/DCIM",
                "packet_path": str(packet),
                "photo_count": photo_count,
                "packet_size": "24K",
                "created_at": "2026-06-10T18:42:34Z",
            },
        )
        return packet

    def make_paper_packet(self, root, job_id="20260611-101500_paper", *, missing_report=False):
        packet = Path(root) / "2026" / job_id
        for name in ["originals", "metadata", "logs", "review"]:
            (packet / name).mkdir(parents=True, exist_ok=True)
        (packet / "originals" / "page_0001.tif").write_bytes(b"paper page")
        (packet / "checksums.sha256").write_text("c" * 64 + "  ./page_0001.tif\n", encoding="utf-8")
        if not missing_report:
            (packet / "ingest_report.md").write_text("# paper report\n", encoding="utf-8")
        write_packet_manifest(
            packet,
            {
                "packet_type": "laia.paper_ingest",
                "packet_version": "0.1",
                "job_id": job_id,
                "source": "/tmp/scanner",
                "packet_path": str(packet),
                "page_count": 1,
                "asset_count": 1,
                "packet_size": "10K",
                "created_at": "2026-06-11T10:15:00Z",
            },
        )
        return packet

    def registry_env(self, db_path):
        return {
            "LAIA_PACKET_REGISTRY_DB": str(db_path),
            "LAIA_PACKET_ROOTS": str(Path(db_path).parent / "unused"),
        }

    def execute_temp_export(self, root, job_id="output-photo", *, review_status="reviewed"):
        packet = self.make_photo_packet(root / "photo", job_id=job_id)
        write_review_sidecar(packet, {"review_status": review_status})
        (packet / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
        db_path = root / "registry.db"
        export_root = root / "exports"
        scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
        env = self.registry_env(db_path)
        env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
        with patch.dict(os.environ, env, clear=False):
            with contextlib.redirect_stdout(io.StringIO()):
                command_packets_route(argparse.Namespace(identifier=job_id, destination_type="export", destination="", note="export"))
                command_packets_execute_route(argparse.Namespace(identifier=job_id, dry_run=False))
        scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
        return packet, db_path, export_root / job_id

    def reviewed_temp_export(self, root, job_id="promote-photo", status="reviewed"):
        packet, db_path, output_path = self.execute_temp_export(root, job_id=job_id)
        with patch.dict(os.environ, self.registry_env(db_path), clear=False):
            with contextlib.redirect_stdout(io.StringIO()):
                command_packets_review_output(argparse.Namespace(identifier=job_id, status=status, note="review note"))
        scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
        return packet, db_path, output_path

    def make_search_registry(self, root):
        photo, db_path, _ = self.reviewed_temp_export(root, job_id="search-photo")
        promotion_root = root / "promoted"
        env = self.registry_env(db_path)
        env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)
        with patch.dict(os.environ, env, clear=False):
            with contextlib.redirect_stdout(io.StringIO()):
                command_packets_promote(
                    argparse.Namespace(
                        identifier="search-photo",
                        destination_type="publication",
                        destination="Photo selects",
                        note="promotion note",
                        dry_run=False,
                    )
                )
        paper = self.make_paper_packet(root / "paper", job_id="search-paper")
        (paper / "final").mkdir()
        (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
        write_workflow_state(paper)
        self.make_photo_packet(root / "photo", job_id="search-bad", missing_report=True)
        scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])
        return db_path

    def test_registry_record_reads_photo_manifest_review_and_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_photo_packet(Path(tmp) / "photo")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            selects = packet / "review" / "selects.txt"
            selects.write_text("# selects\none.jpg\n\n two.jpg \n", encoding="utf-8")

            record = registry_record("photo_ingest", packet)

            self.assertEqual(record["job_id"], packet.name)
            self.assertEqual(record["packet_type"], "laia.photo_ingest")
            self.assertEqual(record["asset_count"], 2)
            self.assertEqual(record["review_status"], "reviewed")
            self.assertEqual(record["select_count"], 2)
            self.assertEqual(record["verification_status"], "ok")
            self.assertEqual(record["missing_required_items"], "")
            self.assertEqual(record["workflow_status"], "")

    def test_registry_record_reports_missing_required_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self.make_photo_packet(Path(tmp) / "photo", missing_report=True)

            record = registry_record("photo_ingest", packet)

            self.assertEqual(record["verification_status"], "missing_required_items")
            self.assertEqual(record["missing_required_items"], "ingest_report.md")

    def test_scan_roots_builds_sqlite_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "photo"
            packet = self.make_photo_packet(packet_root)
            db_path = Path(tmp) / "registry" / "packet_registry.db"

            count = scan_roots(db_path, [PacketRoot("photo_ingest", packet_root)])

            self.assertEqual(count, 1)
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT job_id, packet_type, asset_count, verification_status FROM packets"
            ).fetchone()
            conn.close()
            self.assertEqual(row, (packet.name, "laia.photo_ingest", 2, "ok"))

    def test_config_defaults_to_photo_roots_and_registry_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "LAIA_PHOTO_PACKET_ROOT": str(Path(tmp) / "packets"),
                "LAIA_PHOTO_CATALOG_ROOT": str(Path(tmp) / "catalogs"),
            }
            old = os.environ.copy()
            try:
                os.environ.update(env)
                os.environ.pop("LAIA_PACKET_REGISTRY_DB", None)
                os.environ.pop("LAIA_PACKET_ROOTS", None)
                cfg = config_from_env()
            finally:
                os.environ.clear()
                os.environ.update(old)

            self.assertEqual(cfg.roots[0].name, "photo_ingest")
            self.assertEqual(cfg.roots[0].path, Path(env["LAIA_PHOTO_PACKET_ROOT"]))
            self.assertEqual(cfg.db_path, Path(env["LAIA_PHOTO_CATALOG_ROOT"]) / "packet_registry.db")

    def test_config_includes_paper_root_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "LAIA_PHOTO_PACKET_ROOT": str(Path(tmp) / "photo"),
                "LAIA_PAPER_PACKET_ROOT": str(Path(tmp) / "paper"),
                "LAIA_VIDEO_PACKET_ROOT": str(Path(tmp) / "video"),
                "LAIA_PHOTO_CATALOG_ROOT": str(Path(tmp) / "catalogs"),
            }
            old = os.environ.copy()
            try:
                os.environ.update(env)
                os.environ.pop("LAIA_PACKET_ROOTS", None)
                cfg = config_from_env()
            finally:
                os.environ.clear()
                os.environ.update(old)

            self.assertEqual([root.name for root in cfg.roots], ["photo_ingest", "paper_ingest", "video_ingest"])
            self.assertEqual(cfg.roots[1].path, Path(env["LAIA_PAPER_PACKET_ROOT"]))
            self.assertEqual(cfg.roots[2].path, Path(env["LAIA_VIDEO_PACKET_ROOT"]))

    def test_laia_packet_roots_override_known_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "override"
            env = {
                "LAIA_PHOTO_PACKET_ROOT": str(Path(tmp) / "photo"),
                "LAIA_PAPER_PACKET_ROOT": str(Path(tmp) / "paper"),
                "LAIA_PACKET_ROOTS": str(override),
            }
            old = os.environ.copy()
            try:
                os.environ.update(env)
                cfg = config_from_env()
            finally:
                os.environ.clear()
                os.environ.update(old)

            self.assertEqual(len(cfg.roots), 1)
            self.assertEqual(cfg.roots[0].name, "root1")
            self.assertEqual(cfg.roots[0].path, override)

    def test_cli_scan_list_inspect_status_and_verify_path_use_temp_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "packets"
            catalog_root = Path(tmp) / "catalogs"
            packet = self.make_photo_packet(packet_root)
            env = os.environ.copy()
            env.update(
                {
                    "LAIA_PHOTO_PACKET_ROOT": str(packet_root),
                    "LAIA_PHOTO_CATALOG_ROOT": str(catalog_root),
                    "LAIA_PACKET_REGISTRY_DB": str(catalog_root / "packet_registry.db"),
                    "LAIA_PACKET_ROOTS": str(packet_root),
                }
            )

            scan = subprocess.run(
                [str(ROOT / "bin" / "laia"), "packets", "scan"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(scan.returncode, 0, scan.stderr)
            self.assertIn("Packets:  1", scan.stdout)

            listed = subprocess.run(
                [str(ROOT / "bin" / "laia"), "packets", "list"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn(packet.name, listed.stdout)
            self.assertIn("laia.photo_ingest", listed.stdout)

            inspected = subprocess.run(
                [str(ROOT / "bin" / "laia"), "packets", "inspect", packet.name],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.assertIn(f"Job ID:              {packet.name}", inspected.stdout)

            verified = subprocess.run(
                [str(ROOT / "bin" / "laia"), "packets", "verify", str(packet)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertIn("Verification Status: ok", verified.stdout)

            status = subprocess.run(
                [str(ROOT / "bin" / "laia"), "packets", "status"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("Packets:  1", status.stdout)
            self.assertIn("Verified: 1", status.stdout)

    def test_registry_scans_paper_packet_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper_root = Path(tmp) / "paper"
            packet = self.make_paper_packet(paper_root)
            db_path = Path(tmp) / "registry.db"

            count = scan_roots(db_path, [PacketRoot("paper_ingest", paper_root)])

            self.assertEqual(count, 1)
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT job_id, packet_type, asset_count, verification_status FROM packets"
            ).fetchone()
            conn.close()
            self.assertEqual(row, (packet.name, "laia.paper_ingest", 1, "ok"))

    def test_registry_scan_uses_derived_paper_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper_root = Path(tmp) / "paper"
            packet = self.make_paper_packet(paper_root, job_id="paper-approved")
            (packet / "approval").mkdir()
            (packet / "approval" / "approval.json").write_text('{"approved_category":"receipt"}\n', encoding="utf-8")
            write_workflow_state(packet)
            db_path = Path(tmp) / "registry.db"

            scan_roots(db_path, [PacketRoot("paper_ingest", paper_root)])

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT review_status, workflow_status, approval_status FROM packets WHERE job_id = ?",
                ("paper-approved",),
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("approved", "approved", "approved"))

    def test_registry_report_includes_mapped_paper_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper_root = Path(tmp) / "paper"
            packet = self.make_paper_packet(paper_root, job_id="paper-final")
            (packet / "final").mkdir()
            (packet / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(packet)
            db_path = Path(tmp) / "registry.db"
            scan_roots(db_path, [PacketRoot("paper_ingest", paper_root)])

            report = registry_report(db_path, load_registry_rows(db_path))

            self.assertIn("By review status:", report)
            self.assertIn("  finalized: 1", report)

    def test_registry_report_includes_photo_and_paper_packet_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo_root = Path(tmp) / "photo"
            paper_root = Path(tmp) / "paper"
            self.make_photo_packet(photo_root)
            self.make_paper_packet(paper_root)
            db_path = Path(tmp) / "registry.db"
            scan_roots(
                db_path,
                [
                    PacketRoot("photo_ingest", photo_root),
                    PacketRoot("paper_ingest", paper_root),
                ],
            )

            report = registry_report(db_path, load_registry_rows(db_path))

            self.assertIn("  laia.photo_ingest: 1", report)
            self.assertIn("  laia.paper_ingest: 1", report)
            self.assertIn("  Total assets: 3", report)

    def test_missing_paper_required_items_show_in_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper_root = Path(tmp) / "paper"
            self.make_paper_packet(paper_root, job_id="paper-missing", missing_report=True)
            db_path = Path(tmp) / "registry.db"
            scan_roots(db_path, [PacketRoot("paper_ingest", paper_root)])

            report = registry_report(db_path, load_registry_rows(db_path))

            self.assertIn("Needs attention:", report)
            self.assertIn("paper-missing (missing_required_items): ingest_report.md", report)

    def test_report_output_includes_summary_type_review_and_attention_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "packets"
            good = self.make_photo_packet(packet_root, job_id="good", photo_count=3)
            bad = self.make_photo_packet(packet_root, job_id="bad", photo_count=4, missing_report=True)
            write_review_sidecar(good, {"review_status": "reviewed"})
            (good / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = Path(tmp) / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", packet_root)])

            report = registry_report(db_path, load_registry_rows(db_path))

            self.assertIn("LAIA Packet Registry Report", report)
            self.assertIn(f"Registry: {db_path}", report)
            self.assertIn("Summary:", report)
            self.assertIn("  Packets: 2", report)
            self.assertIn("  Verified: 1", report)
            self.assertIn("  Missing required: 1", report)
            self.assertIn("  Total assets: 7", report)
            self.assertIn("  Packets with selects: 1", report)
            self.assertIn("By type:", report)
            self.assertIn("  laia.photo_ingest: 2", report)
            self.assertIn("By review status:", report)
            self.assertIn("  reviewed: 1", report)
            self.assertIn("Needs attention:", report)
            self.assertIn("bad (missing_required_items): ingest_report.md", report)

    def test_report_handles_empty_registry_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "registry.db"
            conn = connect_registry(db_path)
            conn.close()

            report = registry_report(db_path, load_registry_rows(db_path))

            self.assertIn("  Packets: 0", report)
            self.assertIn("By type:\n  none", report)
            self.assertIn("By review status:\n  none", report)
            self.assertIn("Needs attention:\n  none", report)

    def test_attention_section_lists_missing_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "packets"
            self.make_photo_packet(packet_root, job_id="needs-attention", missing_report=True)
            db_path = Path(tmp) / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", packet_root)])

            report = registry_report(db_path, load_registry_rows(db_path))

            self.assertIn("Needs attention:", report)
            self.assertIn("needs-attention", report)
            self.assertIn("ingest_report.md", report)

    def test_export_csv_writes_expected_headers_and_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "packets"
            packet = self.make_photo_packet(packet_root)
            db_path = Path(tmp) / "registry" / "packet_registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", packet_root)])
            rows = load_registry_rows(db_path)
            destination = export_csv_path(None, db_path)

            export_registry_csv(rows, destination)

            with destination.open("r", encoding="utf-8", newline="") as f:
                csv_rows = list(csv.DictReader(f))
            self.assertEqual(destination, db_path.parent / "packet_registry_export.csv")
            self.assertEqual(csv_rows[0]["job_id"], packet.name)
            self.assertEqual(csv_rows[0]["packet_type"], "laia.photo_ingest")
            self.assertEqual(csv_rows[0]["packet_path"], str(packet))
            self.assertIn("missing_required", csv_rows[0])

    def test_export_csv_supports_explicit_file_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "packets"
            self.make_photo_packet(packet_root)
            db_path = Path(tmp) / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", packet_root)])
            destination = Path(tmp) / "custom" / "registry.csv"

            path = export_registry_csv(load_registry_rows(db_path), destination)

            self.assertEqual(path, destination)
            self.assertTrue(destination.exists())
            self.assertIn("job_id,packet_type,packet_version", destination.read_text(encoding="utf-8"))

    def test_open_resolves_packet_id_to_path_without_requiring_finder(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_root = Path(tmp) / "packets"
            catalog_root = Path(tmp) / "catalogs"
            packet = self.make_photo_packet(packet_root)
            env = {
                "LAIA_PHOTO_PACKET_ROOT": str(packet_root),
                "LAIA_PHOTO_CATALOG_ROOT": str(catalog_root),
                "LAIA_PACKET_REGISTRY_DB": str(catalog_root / "packet_registry.db"),
            }
            scan_roots(Path(env["LAIA_PACKET_REGISTRY_DB"]), [PacketRoot("photo_ingest", packet_root)])
            output = io.StringIO()

            with patch.dict(os.environ, env, clear=False):
                with patch("core.packets.registry.platform.system", return_value="Darwin"):
                    with patch("core.packets.registry.subprocess.run") as run:
                        command_packets_open(argparse.Namespace(identifier=packet.name))

            run.assert_called_once_with(["open", str(packet)], check=False)

            with patch.dict(os.environ, env, clear=False):
                with patch("core.packets.registry.platform.system", return_value="Linux"):
                    with contextlib.redirect_stdout(output):
                        command_packets_open(argparse.Namespace(identifier=packet.name))

            self.assertEqual(output.getvalue().strip(), str(packet))

    def test_queue_groups_packets_by_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.make_photo_packet(root / "photo", job_id="photo-reviewed")
            write_review_sidecar(photo, {"review_status": "reviewed"})
            paper = self.make_paper_packet(root / "paper", job_id="paper-final")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_queue(argparse.Namespace(status=None))

            text = output.getvalue()
            self.assertIn("LAIA Packet Queue", text)
            self.assertIn("Total packets: 2", text)
            self.assertIn("reviewed: 1", text)
            self.assertIn("finalized: 1", text)

    def test_queue_status_filters_by_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed = self.make_photo_packet(root / "photo", job_id="photo-reviewed")
            write_review_sidecar(reviewed, {"review_status": "reviewed"})
            self.make_photo_packet(root / "photo", job_id="photo-new")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_queue(argparse.Namespace(status="reviewed"))

            text = output.getvalue()
            self.assertIn("photo-reviewed", text)
            self.assertNotIn("photo-new", text)

    def test_queue_status_also_matches_workflow_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = self.make_paper_packet(root / "paper", job_id="paper-final")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            self.make_photo_packet(root / "photo", job_id="photo-new")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("paper_ingest", root / "paper"), PacketRoot("photo_ingest", root / "photo")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_queue(argparse.Namespace(status="finalized"))

            text = output.getvalue()
            self.assertIn("paper-final", text)
            self.assertNotIn("photo-new", text)

    def test_attention_includes_missing_required_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="missing", missing_report=True)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_attention(argparse.Namespace())

            text = output.getvalue()
            self.assertIn("missing", text)
            self.assertIn("ingest_report.md", text)

    def test_attention_includes_failed_workflow_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = self.make_paper_packet(root / "paper", job_id="paper-failed")
            (paper / "failure").mkdir()
            (paper / "failure" / "failure.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("paper_ingest", root / "paper")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_attention(argparse.Namespace())

            text = output.getvalue()
            self.assertIn("paper-failed", text)
            self.assertIn("failed", text)

    def test_attention_says_none_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="clean")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_attention(argparse.Namespace())

            self.assertIn("No packets need attention.", output.getvalue())

    def test_ready_includes_reviewed_and_finalized_verified_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.make_photo_packet(root / "photo", job_id="photo-reviewed")
            write_review_sidecar(photo, {"review_status": "reviewed"})
            paper = self.make_paper_packet(root / "paper", job_id="paper-final")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_ready(argparse.Namespace())

            text = output.getvalue()
            self.assertIn("photo-reviewed", text)
            self.assertIn("paper-final", text)

    def test_ready_excludes_new_failed_and_missing_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="new")
            self.make_photo_packet(root / "photo", job_id="missing", missing_report=True)
            failed = self.make_paper_packet(root / "paper", job_id="failed")
            (failed / "failure").mkdir()
            (failed / "failure" / "failure.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(failed)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_ready(argparse.Namespace())

            text = output.getvalue()
            self.assertIn("Ready packets: 0", text)
            self.assertNotIn("new", text)
            self.assertNotIn("missing", text)
            self.assertNotIn("failed", text)

    def test_queue_output_handles_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "registry.db"
            conn = connect_registry(db_path)
            conn.close()
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_queue(argparse.Namespace(status=None))

            text = output.getvalue()
            self.assertIn("Total packets: 0", text)
            self.assertIn("No packets found.", text)

    def test_briefing_includes_archive_health_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.make_photo_packet(root / "photo", job_id="photo-reviewed", photo_count=3)
            write_review_sidecar(photo, {"review_status": "reviewed"})
            paper = self.make_paper_packet(root / "paper", job_id="paper-final")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("LAIA Packet Briefing", text)
            self.assertIn("Archive Health:", text)
            self.assertIn("  Packets: 2", text)
            self.assertIn("  Verified: 2", text)
            self.assertIn("  Attention: 0", text)
            self.assertIn("  Ready: 2", text)
            self.assertIn("  Total assets: 4", text)
            self.assertIn("Packet Types:", text)
            self.assertIn("  laia.paper_ingest: 1", text)
            self.assertIn("  laia.photo_ingest: 1", text)

    def test_briefing_includes_ready_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.make_photo_packet(root / "photo", job_id="photo-reviewed", photo_count=305)
            write_review_sidecar(photo, {"review_status": "reviewed"})
            (photo / "review" / "selects.txt").write_text("one.jpg\ntwo.jpg\n", encoding="utf-8")
            paper = self.make_paper_packet(root / "paper", job_id="paper-final")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Ready:", text)
            self.assertIn("paper-final - laia.paper_ingest, finalized/finalized, 1 assets", text)
            self.assertIn("photo-reviewed - laia.photo_ingest, reviewed, 305 assets, 2 selects", text)

    def test_briefing_says_attention_none_for_clean_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.make_photo_packet(root / "photo", job_id="clean")
            write_review_sidecar(photo, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Attention:\n  none", text)

    def test_briefing_lists_attention_packets_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="needs-attention", missing_report=True)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Attention:", text)
            self.assertIn("needs-attention - laia.photo_ingest", text)
            self.assertIn("missing_required=ingest_report.md", text)

    def test_briefing_lists_in_progress_new_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="photo-new")
            paper = self.make_paper_packet(root / "paper", job_id="paper-classified")
            (paper / "classify").mkdir()
            (paper / "classify" / "classification.json").write_text('{"category":"receipt"}\n', encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("In Progress:", text)
            self.assertIn("photo-new - laia.photo_ingest, new", text)
            self.assertIn("paper-classified - laia.paper_ingest, new/classified", text)

    def test_briefing_includes_recent_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="older")
            self.make_paper_packet(root / "paper", job_id="newer")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Recent Activity:", text)
            self.assertIn("newer - laia.paper_ingest", text)
            self.assertIn("older - laia.photo_ingest", text)

    def test_briefing_suggestions_change_by_registry_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected_photo = self.make_photo_packet(root / "photo", job_id="selected-photo")
            write_review_sidecar(selected_photo, {"review_status": "reviewed"})
            (selected_photo / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            self.make_photo_packet(root / "photo", job_id="new-photo")
            self.make_photo_packet(root / "photo", job_id="bad-photo", missing_report=True)
            finalized_paper = self.make_paper_packet(root / "paper", job_id="final-paper")
            (finalized_paper / "final").mkdir()
            (finalized_paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(finalized_paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Resolve packets needing attention before new ingest.", text)
            self.assertIn("Route or archive finalized paper packets.", text)
            self.assertIn("Review/export photo selects or promote them to a project packet.", text)
            self.assertIn("Continue review for new or in-progress packets.", text)
            self.assertNotIn("Archive is healthy; continue ingest or downstream routing.", text)

    def test_briefing_handles_empty_registry_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "registry.db"
            conn = connect_registry(db_path)
            conn.close()

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("  Packets: 0", text)
            self.assertIn("Packet Types:\n  none", text)
            self.assertIn("Ready:\n  none", text)
            self.assertIn("Attention:\n  none", text)
            self.assertIn("In Progress:\n  none", text)
            self.assertIn("Recent Activity:\n  none", text)
            self.assertIn("Run an ingest or scan packet roots.", text)

    def test_briefing_command_reads_temp_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="briefing-photo")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_briefing(argparse.Namespace())

            self.assertIn("LAIA Packet Briefing", output.getvalue())
            self.assertIn("briefing-photo", output.getvalue())

    def test_route_command_writes_routing_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="route-photo")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_route(
                        argparse.Namespace(
                            identifier="route-photo",
                            destination_type="project",
                            destination="Receipts",
                            note="Ready for bookkeeping",
                        )
                    )

            route = read_routing(packet)
            self.assertEqual(route["route_status"], "queued")
            self.assertEqual(route["destination_type"], "project")
            self.assertEqual(route["destination"], "Receipts")
            self.assertEqual(route["history"][0]["note"], "Ready for bookkeeping")
            self.assertIn("Status:      queued", output.getvalue())

    def test_route_status_reports_assigned_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="route-status")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(
                        argparse.Namespace(identifier="route-status", destination_type="export", destination="Photo selects", note="Review")
                    )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_route_status(argparse.Namespace(identifier="route-status"))

            text = output.getvalue()
            self.assertIn("Route Status:     queued", text)
            self.assertIn("Destination Type: export", text)
            self.assertIn("Destination:      Photo selects", text)
            self.assertIn("History Count:    1", text)

    def test_route_appends_history_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="route-history")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="route-history", destination_type="project", destination="A", note="first"))
                    command_packets_route(argparse.Namespace(identifier="route-history", destination_type="catalog", destination="B", note="second"))

            route = read_routing(packet)
            self.assertEqual(route["destination_type"], "catalog")
            self.assertEqual(len(route["history"]), 2)
            self.assertEqual(route["history"][0]["note"], "first")
            self.assertEqual(route["history"][1]["note"], "second")

    def test_clear_route_sets_cleared_and_appends_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="clear-route")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="clear-route", destination_type="project", destination="Receipts", note="queue"))
                    command_packets_clear_route(argparse.Namespace(identifier="clear-route", note="pause"))

            route = read_routing(packet)
            self.assertEqual(route["route_status"], "cleared")
            self.assertEqual(route["destination_type"], "")
            self.assertEqual(route["destination"], "")
            self.assertEqual(len(route["history"]), 2)
            self.assertEqual(route["history"][1]["route_status"], "cleared")
            self.assertEqual(route["history"][1]["note"], "pause")

    def test_registry_scan_captures_route_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="scan-route")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="scan-route", destination_type="project", destination="Receipts", note="route"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT route_status, route_destination_type, route_destination FROM packets WHERE job_id = ?",
                ("scan-route",),
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("queued", "project", "Receipts"))

    def test_routes_command_lists_routed_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="routes-list")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="routes-list", destination_type="review", destination="Desk", note="route"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            output = io.StringIO()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(output):
                    command_packets_routes(argparse.Namespace())

            text = output.getvalue()
            self.assertIn("routes-list", text)
            self.assertIn("queued", text)
            self.assertIn("Desk", text)

    def test_briefing_suggests_assigning_routes_when_ready_packets_have_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="ready-unrouted")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Assign downstream routes for 1 ready packets.", text)

    def test_briefing_with_only_queued_routes_says_execute_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="ready-routed")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="ready-routed", destination_type="archive", destination="", note="route"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("1 routes are queued.", text)
            self.assertIn("Execute downstream routes or continue ingest.", text)
            self.assertIn("Routes:\n  queued: 1", text)

    def test_briefing_all_ready_packets_routed_omits_redundant_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.make_photo_packet(root / "photo", job_id="routed-photo")
            write_review_sidecar(photo, {"review_status": "reviewed"})
            (photo / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            paper = self.make_paper_packet(root / "paper", job_id="routed-paper")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(
                        argparse.Namespace(
                            identifier="routed-photo",
                            destination_type="export",
                            destination="Photo selects",
                            note="selects",
                        )
                    )
                    command_packets_route(
                        argparse.Namespace(
                            identifier="routed-paper",
                            destination_type="project",
                            destination="Receipts",
                            note="receipts",
                        )
                    )
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo"), PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("2 routes are queued.", text)
            self.assertIn("Execute downstream routes or continue ingest.", text)
            self.assertIn("Archive is healthy.", text)
            self.assertIn("Routes:\n  queued: 2", text)
            self.assertNotIn("Assign downstream routes", text)
            self.assertNotIn("Route or archive finalized paper packets.", text)
            self.assertNotIn("Review/export photo selects or promote them to a project packet.", text)

    def test_briefing_some_ready_packets_unrouted_suggests_assignment_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            routed = self.make_photo_packet(root / "photo", job_id="some-routed")
            write_review_sidecar(routed, {"review_status": "reviewed"})
            unrouted = self.make_photo_packet(root / "photo", job_id="some-unrouted")
            write_review_sidecar(unrouted, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="some-routed", destination_type="archive", destination="", note="route"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("1 routes are queued.", text)
            self.assertIn("Execute downstream routes or continue ingest.", text)
            self.assertIn("Assign downstream routes for 1 ready packets.", text)

    def test_briefing_finalized_paper_suggestion_only_when_unrouted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = self.make_paper_packet(root / "paper", job_id="paper-ready")
            (paper / "final").mkdir()
            (paper / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(paper)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))
            self.assertIn("Route or archive finalized paper packets.", text)

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="paper-ready", destination_type="project", destination="Receipts", note="route"))
            scan_roots(db_path, [PacketRoot("paper_ingest", root / "paper")])

            text = registry_briefing(load_registry_rows(db_path))
            self.assertNotIn("Route or archive finalized paper packets.", text)

    def test_briefing_photo_selects_suggestion_only_when_unrouted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = self.make_photo_packet(root / "photo", job_id="photo-selects")
            write_review_sidecar(photo, {"review_status": "reviewed"})
            (photo / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))
            self.assertIn("Review/export photo selects or promote them to a project packet.", text)

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="photo-selects", destination_type="export", destination="Photo selects", note="route"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))
            self.assertNotIn("Review/export photo selects or promote them to a project packet.", text)

    def test_briefing_attention_suggestion_stays_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ready = self.make_photo_packet(root / "photo", job_id="attention-ready")
            write_review_sidecar(ready, {"review_status": "reviewed"})
            self.make_photo_packet(root / "photo", job_id="attention-bad", missing_report=True)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))
            suggestions = text.split("Suggested Next Actions:", 1)[1].strip().splitlines()

            self.assertEqual(suggestions[0].strip(), "- Resolve packets needing attention before new ingest.")

    def test_execute_export_route_copies_selected_photo_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="export-photo")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            (packet / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(
                        argparse.Namespace(identifier="export-photo", destination_type="export", destination="Photo selects", note="export")
                    )
                    command_packets_execute_route(argparse.Namespace(identifier="export-photo", dry_run=False))

            output = export_root / "Photo selects"
            self.assertTrue((output / "one.jpg").exists())
            self.assertFalse((output / "two.jpg").exists())
            self.assertEqual(read_routing(packet)["route_status"], "executed")
            self.assertEqual(read_routing(packet)["execution_result"], "exported")

    def test_export_route_writes_export_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="export-manifest")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            (packet / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="export-manifest", destination_type="export", destination="", note="export"))
                    command_packets_execute_route(argparse.Namespace(identifier="export-manifest", dry_run=False))

            manifest = json.loads((export_root / "export-manifest" / "export_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["job_id"], "export-manifest")
            self.assertEqual(manifest["copied_count"], 1)
            self.assertEqual(manifest["exported_files"][0]["source"], "one.jpg")

    def test_export_route_without_selects_creates_handoff_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="export-no-selects")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="export-no-selects", destination_type="export", destination="", note="export"))
                    command_packets_execute_route(argparse.Namespace(identifier="export-no-selects", dry_run=False))

            output = export_root / "export-no-selects"
            self.assertTrue((output / "packet_handoff.md").exists())
            self.assertTrue((output / "export_manifest.json").exists())
            self.assertFalse((output / "one.jpg").exists())
            self.assertEqual(read_routing(packet)["execution_result"], "handoff_created")

    def test_project_route_creates_handoff_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_paper_packet(root / "paper", job_id="project-paper")
            (packet / "final").mkdir()
            (packet / "final" / "final.json").write_text("{}\n", encoding="utf-8")
            write_workflow_state(packet)
            db_path = root / "registry.db"
            project_root = root / "projects"
            scan_roots(db_path, [PacketRoot("paper_ingest", root / "paper")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROJECT_ROOT"] = str(project_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="project-paper", destination_type="project", destination="Receipts", note="bookkeeping"))
                    command_packets_execute_route(argparse.Namespace(identifier="project-paper", dry_run=False))

            output = project_root / "Receipts"
            self.assertTrue((output / "packet_handoff.md").exists())
            self.assertTrue((output / "packet_handoff.json").exists())
            handoff = json.loads((output / "packet_handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["job_id"], "project-paper")
            self.assertEqual(handoff["destination"], "Receipts")

    def test_archive_route_marks_executed_without_moving_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="archive-photo")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            original_path = packet
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="archive-photo", destination_type="archive", destination="", note="archive"))
                    command_packets_execute_route(argparse.Namespace(identifier="archive-photo", dry_run=False))

            route = read_routing(packet)
            self.assertTrue(original_path.exists())
            self.assertEqual(route["route_status"], "executed")
            self.assertEqual(route["execution_result"], "acknowledged")
            self.assertIn("archive-ready", route["last_execution_note"])

    def test_execute_route_dry_run_does_not_create_files_or_modify_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="dry-export")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            (packet / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="dry-export", destination_type="export", destination="", note="dry"))
                before = read_routing(packet)
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_execute_route(argparse.Namespace(identifier="dry-export", dry_run=True))

            self.assertEqual(read_routing(packet), before)
            self.assertFalse(export_root.exists())

    def test_execute_route_refuses_non_queued_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="already-executed")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="already-executed", destination_type="archive", destination="", note="archive"))
                    command_packets_execute_route(argparse.Namespace(identifier="already-executed", dry_run=False))
                with self.assertRaisesRegex(SystemExit, "Route is not queued"):
                    command_packets_execute_route(argparse.Namespace(identifier="already-executed", dry_run=False))

    def test_execute_routes_executes_multiple_queued_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one = self.make_photo_packet(root / "photo", job_id="batch-one")
            two = self.make_photo_packet(root / "photo", job_id="batch-two")
            write_review_sidecar(one, {"review_status": "reviewed"})
            write_review_sidecar(two, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="batch-one", destination_type="archive", destination="", note="archive"))
                    command_packets_route(argparse.Namespace(identifier="batch-two", destination_type="hold", destination="", note="hold"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_execute_routes(argparse.Namespace(dry_run=False))

            self.assertIn("Executed: 2", output.getvalue())
            self.assertEqual(read_routing(one)["route_status"], "executed")
            self.assertEqual(read_routing(two)["route_status"], "executed")

    def test_route_history_prints_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="history-route")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="history-route", destination_type="hold", destination="", note="later"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_route_history(argparse.Namespace(identifier="history-route"))

            self.assertIn("1. queued hold", output.getvalue())
            self.assertIn("note: later", output.getvalue())

    def test_registry_scan_sees_executed_route_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="scan-executed")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="scan-executed", destination_type="archive", destination="", note="archive"))
                    command_packets_execute_route(argparse.Namespace(identifier="scan-executed", dry_run=False))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            row = load_registry_rows(db_path)[0]
            self.assertEqual(row["route_status"], "executed")

    def test_registry_scan_captures_route_execution_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="scan-output")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            (packet / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="scan-output", destination_type="export", destination="", note="export"))
                    command_packets_execute_route(argparse.Namespace(identifier="scan-output", dry_run=False))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            row = load_registry_rows(db_path)[0]
            self.assertEqual(row["route_status"], "executed")
            self.assertEqual(row["route_execution_result"], "exported")
            self.assertEqual(row["route_execution_output_path"], str(export_root / "scan-output"))
            self.assertTrue(row["route_executed_at"])

    def test_briefing_with_only_executed_routes_says_review_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="executed-briefing")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            (packet / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="executed-briefing", destination_type="export", destination="", note="export"))
                    command_packets_execute_route(argparse.Namespace(identifier="executed-briefing", dry_run=False))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("1 packet routes have been executed.", text)
            self.assertIn("Review executed route outputs.", text)
            self.assertNotIn("Review route outputs or continue ingest.", text)
            self.assertNotIn("Execute downstream routes or continue ingest.", text)

    def test_briefing_with_queued_and_executed_routes_mentions_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executed = self.make_photo_packet(root / "photo", job_id="mixed-executed")
            queued = self.make_photo_packet(root / "photo", job_id="mixed-queued")
            write_review_sidecar(executed, {"review_status": "reviewed"})
            write_review_sidecar(queued, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="mixed-executed", destination_type="archive", destination="", note="archive"))
                    command_packets_execute_route(argparse.Namespace(identifier="mixed-executed", dry_run=False))
                    command_packets_route(argparse.Namespace(identifier="mixed-queued", destination_type="archive", destination="", note="archive"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("1 routes are queued.", text)
            self.assertIn("1 packet routes have been executed.", text)
            self.assertIn("Execute queued routes; review executed outputs.", text)

    def test_briefing_includes_executed_outputs_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="output-briefing")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            (packet / "review" / "selects.txt").write_text("one.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="output-briefing", destination_type="export", destination="", note="export"))
                    command_packets_execute_route(argparse.Namespace(identifier="output-briefing", dry_run=False))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Executed Outputs:", text)
            self.assertIn(f"output-briefing -> {export_root / 'output-briefing'}", text)

    def test_briefing_omits_executed_outputs_without_output_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="no-output-briefing")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="no-output-briefing", destination_type="archive", destination="", note="archive"))
                    command_packets_execute_route(argparse.Namespace(identifier="no-output-briefing", dry_run=False))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("1 packet routes have been executed.", text)
            self.assertNotIn("Executed Outputs:", text)
            self.assertNotIn("Review route outputs or continue ingest.", text)
            self.assertNotIn("Review executed route outputs.", text)

    def test_output_command_shows_executed_output_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, db_path, output_path = self.execute_temp_export(root, job_id="output-details")

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_output(argparse.Namespace(identifier="output-details"))

            text = output.getvalue()
            self.assertIn("Route Status:         executed", text)
            self.assertIn("Execution Result:     exported", text)
            self.assertIn(f"Execution Output:     {output_path}", text)
            self.assertIn("Output File Count:    3", text)

    def test_output_command_handles_missing_output_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="missing-output")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_output(argparse.Namespace(identifier="missing-output"))

            self.assertIn("No executed output found.", output.getvalue())

    def test_outputs_command_lists_executed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="outputs-list")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_outputs(argparse.Namespace(status=None, destination_type=None))

            text = output.getvalue()
            self.assertIn("outputs-list", text)
            self.assertIn("exported", text)
            self.assertIn("new", text)

    def test_output_files_lists_export_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="output-files")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_output_files(argparse.Namespace(identifier="output-files"))

            text = output.getvalue()
            self.assertIn("one.jpg", text)
            self.assertIn("export_manifest.json", text)
            self.assertIn("packet_handoff.md", text)

    def test_review_output_writes_fields_and_appends_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, _ = self.execute_temp_export(root, job_id="review-output")
            before = len(read_routing(packet)["history"])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="review-output", status="reviewed", note="looks good"))

            route = read_routing(packet)
            self.assertEqual(route["output_review_status"], "reviewed")
            self.assertEqual(route["output_review_note"], "looks good")
            self.assertTrue(route["output_reviewed_at"])
            self.assertEqual(len(route["history"]), before + 1)
            self.assertEqual(route["history"][-1]["route_status"], "output_reviewed")

    def test_review_output_default_status_is_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, _ = self.execute_temp_export(root, job_id="review-default")

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="review-default", status=None, note=""))

            self.assertEqual(read_routing(packet)["output_review_status"], "reviewed")

    def test_review_output_supports_needs_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, _ = self.execute_temp_export(root, job_id="review-needs-work")

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="review-needs-work", status="needs_work", note="missing context"))

            self.assertEqual(read_routing(packet)["output_review_status"], "needs_work")

    def test_output_history_prints_review_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="output-history")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="output-history", status="needs_work", note="check export"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_output_history(argparse.Namespace(identifier="output-history"))

            text = output.getvalue()
            self.assertIn("output_reviewed", text)
            self.assertIn("output_review_status=needs_work", text)
            self.assertIn("note: check export", text)

    def test_registry_scan_captures_output_review_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, db_path, _ = self.execute_temp_export(root, job_id="scan-output-review")

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="scan-output-review", status="reviewed", note="done"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            row = load_registry_rows(db_path)[0]
            self.assertEqual(row["output_review_status"], "reviewed")
            self.assertEqual(row["output_review_note"], "done")
            self.assertTrue(row["output_reviewed_at"])

    def test_briefing_shows_output_review_counts_and_unreviewed_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="briefing-output-new")
            db_path = root / "registry.db"

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Output Review:\n  new: 1", text)
            self.assertIn("Review executed route outputs.", text)

    def test_briefing_changes_when_all_outputs_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="briefing-output-reviewed")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="briefing-output-reviewed", status="reviewed", note="done"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Output Review:\n  reviewed: 1", text)
            self.assertIn("Promote reviewed outputs or continue ingest.", text)
            self.assertNotIn("Review executed route outputs.", text)
            self.assertNotIn("Review route outputs or continue ingest.", text)
            self.assertIn("Archive is healthy.", text)

    def test_briefing_suggests_resolving_outputs_marked_needs_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="briefing-output-needs-work")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_review_output(argparse.Namespace(identifier="briefing-output-needs-work", status="needs_work", note="fix"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Output Review:\n  needs_work: 1", text)
            self.assertIn("Resolve outputs marked needs_work.", text)

    def test_promote_refuses_unreviewed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="promote-unreviewed")
            db_path = root / "registry.db"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(root / "promoted")

            with patch.dict(os.environ, env, clear=False):
                with self.assertRaisesRegex(SystemExit, "Output must be reviewed before promotion"):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="promote-unreviewed",
                            destination_type="project",
                            destination="Project",
                            note="",
                            dry_run=False,
                        )
                    )

    def test_promote_refuses_needs_work_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="promote-needs-work", status="needs_work")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with self.assertRaisesRegex(SystemExit, "needs_work"):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="promote-needs-work",
                            destination_type="project",
                            destination="Project",
                            note="",
                            dry_run=False,
                        )
                    )

    def test_project_promotion_copies_reviewed_output_to_promotion_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, _ = self.reviewed_temp_export(root, job_id="project-promote")
            promotion_root = root / "promoted"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)

            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="project-promote",
                            destination_type="project",
                            destination="Receipts",
                            note="promote",
                            dry_run=False,
                        )
                    )

            output = promotion_root / "projects" / "Receipts"
            self.assertTrue((output / "one.jpg").exists())
            self.assertTrue((output / "promotion_manifest.json").exists())
            self.assertTrue((output / "promotion_report.md").exists())
            self.assertEqual(read_routing(packet)["promotion_status"], "promoted")
            self.assertEqual(read_routing(packet)["promotion_output_path"], str(output))

    def test_publication_promotion_copies_reviewed_output_to_promotion_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="publication-promote")
            promotion_root = root / "promoted"
            env = self.registry_env(root / "registry.db")
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)

            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="publication-promote",
                            destination_type="publication",
                            destination="Gallery",
                            note="stage",
                            dry_run=False,
                        )
                    )

            output = promotion_root / "publication" / "Gallery"
            self.assertTrue((output / "one.jpg").exists())
            self.assertTrue((output / "promotion_manifest.json").exists())

    def test_archive_promotion_is_sidecar_only_and_does_not_move_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, _ = self.reviewed_temp_export(root, job_id="archive-promote")
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(root / "promoted")

            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="archive-promote",
                            destination_type="archive",
                            destination="",
                            note="archive",
                            dry_run=False,
                        )
                    )

            self.assertTrue(packet.exists())
            route = read_routing(packet)
            self.assertEqual(route["promotion_status"], "promoted")
            self.assertEqual(route["promotion_result"], "archive_ready")
            self.assertEqual(route["promotion_output_path"], "")

    def test_hold_promotion_is_sidecar_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, _ = self.reviewed_temp_export(root, job_id="hold-promote")

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="hold-promote",
                            destination_type="hold",
                            destination="",
                            note="wait",
                            dry_run=False,
                        )
                    )

            route = read_routing(packet)
            self.assertEqual(route["promotion_status"], "held")
            self.assertEqual(route["promotion_result"], "held")
            self.assertEqual(route["promotion_note"], "wait")

    def test_promotion_manifest_and_report_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="manifest-promote")
            promotion_root = root / "promoted"
            env = self.registry_env(root / "registry.db")
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)

            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="manifest-promote",
                            destination_type="project",
                            destination="Project",
                            note="manifest note",
                            dry_run=False,
                        )
                    )

            output = promotion_root / "projects" / "Project"
            manifest = json.loads((output / "promotion_manifest.json").read_text(encoding="utf-8"))
            report = (output / "promotion_report.md").read_text(encoding="utf-8")
            self.assertEqual(manifest["packet_id"], "manifest-promote")
            self.assertEqual(manifest["promotion_note"], "manifest note")
            self.assertIn("LAIA Packet Promotion", report)

    def test_promotion_dry_run_creates_nothing_and_does_not_modify_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, _ = self.reviewed_temp_export(root, job_id="dry-promote")
            before = read_routing(packet)
            promotion_root = root / "promoted"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)

            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(
                            identifier="dry-promote",
                            destination_type="project",
                            destination="Project",
                            note="dry",
                            dry_run=True,
                        )
                    )

            self.assertEqual(read_routing(packet), before)
            self.assertFalse(promotion_root.exists())

    def test_promotions_command_lists_promoted_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="promotions-list")
            promotion_root = root / "promoted"
            db_path = root / "registry.db"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="promotions-list", destination_type="archive", destination="", note="", dry_run=False)
                    )
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_promotions(argparse.Namespace(status=None, destination_type=None))

            self.assertIn("promotions-list", output.getvalue())
            self.assertIn("archive_ready", output.getvalue())

    def test_promotion_status_shows_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="promotion-status")
            db_path = root / "registry.db"
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="promotion-status", destination_type="archive", destination="", note="archive", dry_run=False)
                    )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_promotion_status(argparse.Namespace(identifier="promotion-status"))

            text = output.getvalue()
            self.assertIn("Promotion Status:      promoted", text)
            self.assertIn("Promotion Result:      archive_ready", text)
            self.assertIn("Promotion Note:        archive", text)

    def test_promotion_files_lists_copied_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="promotion-files")
            db_path = root / "registry.db"
            promotion_root = root / "promoted"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="promotion-files", destination_type="project", destination="Project", note="", dry_run=False)
                    )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_promotion_files(argparse.Namespace(identifier="promotion-files"))

            text = output.getvalue()
            self.assertIn("one.jpg", text)
            self.assertIn("promotion_manifest.json", text)
            self.assertIn("promotion_report.md", text)

    def test_promotion_history_shows_promotion_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="promotion-history")
            db_path = root / "registry.db"
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="promotion-history", destination_type="archive", destination="", note="history", dry_run=False)
                    )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_promotion_history(argparse.Namespace(identifier="promotion-history"))

            self.assertIn("promoted archive", output.getvalue())
            self.assertIn("note: history", output.getvalue())

    def test_registry_scan_captures_promotion_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="scan-promotion")
            db_path = root / "registry.db"
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="scan-promotion", destination_type="archive", destination="", note="archive", dry_run=False)
                    )
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            row = load_registry_rows(db_path)[0]
            self.assertEqual(row["promotion_status"], "promoted")
            self.assertEqual(row["promotion_destination_type"], "archive")
            self.assertEqual(row["promotion_result"], "archive_ready")
            self.assertTrue(row["promoted_at"])

    def test_briefing_shows_promotions_section_and_suggests_unpromoted_reviewed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="briefing-promote-next")
            db_path = root / "registry.db"

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Promote reviewed outputs or continue ingest.", text)
            self.assertNotIn("Promotions:", text)

    def test_briefing_changes_after_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="briefing-promoted")
            db_path = root / "registry.db"
            promotion_root = root / "promoted"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="briefing-promoted", destination_type="project", destination="Project", note="", dry_run=False)
                    )
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            text = registry_briefing(load_registry_rows(db_path))

            self.assertIn("Promotions:\n  promoted: 1", text)
            self.assertIn("Promoted Outputs:", text)
            self.assertIn("1 packet outputs have been promoted.", text)
            self.assertIn("Promoted outputs are ready for downstream use.", text)
            self.assertNotIn("Promote reviewed outputs or continue ingest.", text)

    def test_lifecycle_for_promoted_packet_includes_complete_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="lifecycle-promoted")
            db_path = root / "registry.db"
            promotion_root = root / "promoted"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="lifecycle-promoted", destination_type="publication", destination="Photo selects", note="publish", dry_run=False)
                    )
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier="lifecycle-promoted"))

            text = output.getvalue()
            self.assertIn("LAIA Packet Lifecycle", text)
            self.assertIn("Packet:", text)
            self.assertIn("Verification:", text)
            self.assertIn("Review / Workflow:", text)
            self.assertIn("Route:", text)
            self.assertIn("Execution:", text)
            self.assertIn("Output Review:", text)
            self.assertIn("Promotion:", text)
            self.assertIn("promotion_destination_type: publication", text)
            self.assertIn("promotion_note: publish", text)
            self.assertIn("Current state: promoted and ready for downstream use.", text)

    def test_lifecycle_output_reviewed_packet_reports_ready_for_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="lifecycle-reviewed")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier="lifecycle-reviewed"))

            self.assertIn("Current state: output reviewed and ready for promotion.", output.getvalue())

    def test_lifecycle_executed_unreviewed_packet_reports_awaiting_output_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.execute_temp_export(root, job_id="lifecycle-executed")
            db_path = root / "registry.db"

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier="lifecycle-executed"))

            self.assertIn("Current state: route executed; output awaiting review.", output.getvalue())

    def test_lifecycle_queued_route_reports_awaiting_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="lifecycle-queued")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(argparse.Namespace(identifier="lifecycle-queued", destination_type="archive", destination="", note="queue"))
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier="lifecycle-queued"))

            text = output.getvalue()
            self.assertIn("route_status: queued", text)
            self.assertIn("route_note: queue", text)
            self.assertIn("Current state: route queued; awaiting execution.", text)

    def test_lifecycle_ready_unrouted_packet_reports_ready_for_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="lifecycle-ready")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier="lifecycle-ready"))

            text = output.getvalue()
            self.assertIn("Route:\n  none", text)
            self.assertIn("Current state: ready for routing.", text)

    def test_lifecycle_attention_packet_reports_needs_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="lifecycle-bad", missing_report=True)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier="lifecycle-bad"))

            text = output.getvalue()
            self.assertIn("missing_required: ingest_report.md", text)
            self.assertIn("Current state: needs attention.", text)

    def test_lifecycle_timeline_orders_known_timestamps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.reviewed_temp_export(root, job_id="lifecycle-timeline")
            db_path = root / "registry.db"
            promotion_root = root / "promoted"
            env = self.registry_env(db_path)
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_promote(
                        argparse.Namespace(identifier="lifecycle-timeline", destination_type="archive", destination="", note="", dry_run=False)
                    )
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier="lifecycle-timeline"))

            text = output.getvalue()
            timeline = text.split("Timeline:", 1)[1]
            self.assertLess(timeline.index("packet created"), timeline.index("route queued"))
            self.assertLess(timeline.index("route queued"), timeline.index("route executed"))
            self.assertLess(timeline.index("route executed"), timeline.index("output reviewed"))
            self.assertLess(timeline.index("output reviewed"), timeline.index("promoted"))

    def test_lifecycle_direct_packet_path_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="lifecycle-direct")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            connect_registry(db_path).close()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle(argparse.Namespace(identifier=str(packet)))

            self.assertIn("job_id: lifecycle-direct", output.getvalue())

    def test_lifecycle_unknown_packet_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "registry.db"
            connect_registry(db_path).close()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with self.assertRaisesRegex(SystemExit, "Packet not found"):
                    command_packets_lifecycle(argparse.Namespace(identifier="missing-packet"))

    def test_export_lifecycle_writes_markdown_and_json_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="export-life-default")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="export-life-default", format="both", output_dir=None))

            self.assertTrue((packet / "lifecycle" / "lifecycle_report.md").exists())
            self.assertTrue((packet / "lifecycle" / "lifecycle_report.json").exists())

    def test_export_lifecycle_format_md_writes_only_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="export-life-md")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="export-life-md", format="md", output_dir=None))

            self.assertTrue((packet / "lifecycle" / "lifecycle_report.md").exists())
            self.assertFalse((packet / "lifecycle" / "lifecycle_report.json").exists())

    def test_export_lifecycle_format_json_writes_only_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="export-life-json")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="export-life-json", format="json", output_dir=None))

            self.assertFalse((packet / "lifecycle" / "lifecycle_report.md").exists())
            self.assertTrue((packet / "lifecycle" / "lifecycle_report.json").exists())

    def test_export_lifecycle_output_dir_writes_outside_packet_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="export-life-outside")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            output_dir = root / "reports" / "one"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="export-life-outside", format="both", output_dir=str(output_dir)))

            self.assertTrue((output_dir / "lifecycle_report.md").exists())
            self.assertTrue((output_dir / "lifecycle_report.json").exists())
            self.assertFalse((packet / "lifecycle").exists())

    def test_export_lifecycles_writes_reports_for_all_registry_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one = self.make_photo_packet(root / "photo", job_id="export-life-one")
            two = self.make_photo_packet(root / "photo", job_id="export-life-two")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_export_lifecycles(argparse.Namespace(format="both", output_root=None))

            self.assertIn("Packets Exported: 2", output.getvalue())
            self.assertTrue((one / "lifecycle" / "lifecycle_report.md").exists())
            self.assertTrue((two / "lifecycle" / "lifecycle_report.json").exists())

    def test_export_lifecycles_output_root_creates_one_folder_per_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="export-root-one")
            self.make_photo_packet(root / "photo", job_id="export-root-two")
            db_path = root / "registry.db"
            output_root = root / "lifecycle-exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycles(argparse.Namespace(format="json", output_root=str(output_root)))

            self.assertTrue((output_root / "export-root-one" / "lifecycle_report.json").exists())
            self.assertTrue((output_root / "export-root-two" / "lifecycle_report.json").exists())
            self.assertFalse((output_root / "export-root-one" / "lifecycle_report.md").exists())

    def test_lifecycle_files_reports_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="life-files")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="life-files", format="both", output_dir=None))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle_files(argparse.Namespace(identifier="life-files"))

            text = output.getvalue()
            self.assertIn(str(packet / "lifecycle" / "lifecycle_report.md"), text)
            self.assertIn("Generated At:", text)

    def test_lifecycle_files_handles_missing_reports_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="life-files-missing")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_lifecycle_files(argparse.Namespace(identifier="life-files-missing"))

            self.assertIn("No lifecycle reports found.", output.getvalue())

    def test_exported_lifecycle_json_contains_stable_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="life-json-shape")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="life-json-shape", format="json", output_dir=None))

            data = json.loads((packet / "lifecycle" / "lifecycle_report.json").read_text(encoding="utf-8"))
            self.assertEqual(data["report_type"], "laia.packet_lifecycle")
            self.assertEqual(data["report_version"], "0.1")
            self.assertTrue(data["generated_at"])
            self.assertEqual(data["packet"]["job_id"], "life-json-shape")
            self.assertIn("timeline", data)
            self.assertEqual(data["current_state"], "ready for routing")

    def test_exported_lifecycle_markdown_contains_expected_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="life-md-shape")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="life-md-shape", format="md", output_dir=None))

            text = (packet / "lifecycle" / "lifecycle_report.md").read_text(encoding="utf-8")
            self.assertIn("# LAIA Packet Lifecycle Report", text)
            self.assertIn("Packet:", text)
            self.assertIn("Verification:", text)
            self.assertIn("Timeline:", text)
            self.assertIn("Current state:", text)

    def test_export_lifecycle_direct_packet_path_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="life-export-direct")
            db_path = root / "registry.db"
            connect_registry(db_path).close()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_export_lifecycle(argparse.Namespace(identifier=str(packet), format="json", output_dir=None))

            self.assertTrue((packet / "lifecycle" / "lifecycle_report.json").exists())

    def test_export_lifecycle_unknown_packet_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "registry.db"
            connect_registry(db_path).close()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with self.assertRaisesRegex(SystemExit, "Packet not found"):
                    command_packets_export_lifecycle(argparse.Namespace(identifier="missing-life", format="both", output_dir=None))

    def test_search_by_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"packet_type": "laia.paper_ingest"})
            self.assertEqual([row["job_id"] for row in rows], ["search-paper"])

    def test_search_by_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"review": "reviewed"})
            self.assertIn("search-photo", [row["job_id"] for row in rows])

    def test_search_by_workflow_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"workflow": "finalized"})
            self.assertEqual([row["job_id"] for row in rows], ["search-paper"])

    def test_search_by_route_status_and_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"route_status": "executed", "route_type": "export"})
            self.assertEqual([row["job_id"] for row in rows], ["search-photo"])

    def test_search_by_output_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"output_review": "reviewed"})
            self.assertEqual([row["job_id"] for row in rows], ["search-photo"])

    def test_search_by_promotion_status_and_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"promotion_status": "promoted", "promotion_type": "publication"})
            self.assertEqual([row["job_id"] for row in rows], ["search-photo"])

    def test_search_by_destination_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"destination": "photo"})
            self.assertEqual([row["job_id"] for row in rows], ["search-photo"])

    def test_search_by_free_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"text": "promotion note"}, include_sidecars=True)
            self.assertEqual([row["job_id"] for row in rows], ["search-photo"])

    def test_search_ready_and_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            ready = search_packets(load_registry_rows(db_path), {"ready": True})
            attention = search_packets(load_registry_rows(db_path), {"attention": True})
            self.assertIn("search-photo", [row["job_id"] for row in ready])
            self.assertEqual([row["job_id"] for row in attention], ["search-bad"])

    def test_search_shortcuts_promoted_executed_reviewed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(
                load_registry_rows(db_path),
                {"promotion_status": "promoted", "route_status": "executed", "output_review": "reviewed"},
            )
            self.assertEqual([row["job_id"] for row in rows], ["search-photo"])

    def test_search_combined_filters_use_and_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            rows = search_packets(load_registry_rows(db_path), {"packet_type": "laia.paper_ingest", "promotion_status": "promoted"})
            self.assertEqual(rows, [])

    def test_search_empty_results_print_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_search(
                        argparse.Namespace(
                            packet_type="none",
                            review=None,
                            workflow=None,
                            verification=None,
                            route_status=None,
                            route_type=None,
                            output_review=None,
                            promotion_status=None,
                            promotion_type=None,
                            destination=None,
                            text=None,
                            created_after=None,
                            created_before=None,
                            ready=False,
                            attention=False,
                            promoted=False,
                            routed=False,
                            executed=False,
                            reviewed_output=False,
                            limit=50,
                            json=False,
                        )
                    )
            self.assertIn("No packets matched.", output.getvalue())

    def test_search_json_outputs_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_search(
                        argparse.Namespace(
                            packet_type=None,
                            review=None,
                            workflow=None,
                            verification=None,
                            route_status=None,
                            route_type=None,
                            output_review=None,
                            promotion_status=None,
                            promotion_type=None,
                            destination=None,
                            text=None,
                            created_after=None,
                            created_before=None,
                            ready=False,
                            attention=False,
                            promoted=True,
                            routed=False,
                            executed=False,
                            reviewed_output=False,
                            limit=50,
                            json=True,
                        )
                    )
            data = json.loads(output.getvalue())
            self.assertEqual(data[0]["job_id"], "search-photo")

    def test_search_invalid_date_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = self.make_search_registry(Path(tmp))
            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with self.assertRaisesRegex(SystemExit, "Invalid created-after"):
                    command_packets_search(
                        argparse.Namespace(
                            packet_type=None,
                            review=None,
                            workflow=None,
                            verification=None,
                            route_status=None,
                            route_type=None,
                            output_review=None,
                            promotion_status=None,
                            promotion_type=None,
                            destination=None,
                            text=None,
                            created_after="not-a-date",
                            created_before=None,
                            ready=False,
                            attention=False,
                            promoted=False,
                            routed=False,
                            executed=False,
                            reviewed_output=False,
                            limit=50,
                            json=False,
                        )
                    )

    def test_missing_selected_file_produces_partial_export_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="partial-export")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            (packet / "review" / "selects.txt").write_text("one.jpg\nmissing.jpg\n", encoding="utf-8")
            db_path = root / "registry.db"
            export_root = root / "exports"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            env = self.registry_env(db_path)
            env["LAIA_PACKET_EXPORT_ROOT"] = str(export_root)
            with patch.dict(os.environ, env, clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_packets_route(argparse.Namespace(identifier="partial-export", destination_type="export", destination="", note="export"))
                    command_packets_execute_route(argparse.Namespace(identifier="partial-export", dry_run=False))

            self.assertTrue((export_root / "partial-export" / "one.jpg").exists())
            route = read_routing(packet)
            self.assertEqual(route["execution_result"], "partial")
            self.assertIn("Missing: missing.jpg", output.getvalue())

    def test_execute_route_invalid_destination_type_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="execute-invalid")
            write_review_sidecar(packet, {"review_status": "reviewed"})
            write_routing(
                packet,
                {
                    "route_status": "queued",
                    "destination_type": "invalid",
                    "destination": "",
                    "note": "",
                    "created_at": "2026-06-12T00:00:00Z",
                    "updated_at": "2026-06-12T00:00:00Z",
                    "history": [],
                },
            )
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with self.assertRaisesRegex(SystemExit, "Invalid destination type"):
                    command_packets_execute_route(argparse.Namespace(identifier="execute-invalid", dry_run=False))

    def test_direct_packet_path_routing_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet = self.make_photo_packet(root / "photo", job_id="direct-route")
            db_path = root / "registry.db"
            conn = connect_registry(db_path)
            conn.close()

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_route(
                        argparse.Namespace(identifier=str(packet), destination_type="hold", destination="Later", note="direct")
                    )

            self.assertEqual(read_routing(packet)["destination_type"], "hold")

    def test_invalid_destination_type_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_photo_packet(root / "photo", job_id="bad-destination")
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])

            with patch.dict(os.environ, self.registry_env(db_path), clear=False):
                with self.assertRaisesRegex(SystemExit, "Invalid destination type"):
                    command_packets_route(
                        argparse.Namespace(identifier="bad-destination", destination_type="invalid", destination="", note="")
                    )


if __name__ == "__main__":
    unittest.main()
