import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.photo_ingest.cohorts import (
    add_files,
    create_cohort,
    read_cohort,
    read_cohort_project_links,
)
from core.photo_ingest.commands import (
    command_cohort_link_project,
    command_cohort_project_links,
    command_cohort_unlink_project,
)
from core.packets.registry import connect_registry, registry_lifecycle, registry_record, upsert_registry_record
from core.projects.registry import (
    command_projects_briefing,
    command_projects_cohort,
    command_projects_cohorts,
    command_projects_inspect,
    command_projects_list,
    load_project_artifacts,
    load_project_cohorts,
    load_project_packets,
)


class PhotoCohortProjectTests(unittest.TestCase):
    def env(self, root: Path) -> dict:
        return {
            "LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects"),
            "LAIA_PHOTO_PACKET_ROOT": str(root / "packets"),
            "LAIA_PHOTO_COHORT_EXPORT_ROOT": str(root / "exports"),
            "LAIA_PACKET_REGISTRY_DB": str(root / "registry.db"),
        }

    def make_packet(self, root: Path, job_id: str, cohort_id="cld-3080") -> tuple[Path, Path]:
        packet = root / "packets" / "2026" / job_id
        for folder in ["originals/DCIM", "previews/DCIM", "metadata", "contact_sheet", "logs", "review"]:
            (packet / folder).mkdir(parents=True, exist_ok=True)
        for index in range(2):
            name = f"IMG_{index + 1}.JPG"
            (packet / "originals/DCIM" / name).write_bytes(name.encode())
            (packet / "previews/DCIM" / name).write_bytes(b"preview")
        (packet / "packet_manifest.json").write_text(
            json.dumps(
                {
                    "packet_type": "laia.photo_ingest",
                    "packet_version": "0.1",
                    "job_id": job_id,
                    "packet_path": str(packet),
                    "photo_count": 2,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        cohort = create_cohort(packet, cohort_id.upper(), status="ready")
        add_files(packet, cohort["cohort_id"], ["DCIM/IMG_1.JPG", "DCIM/IMG_2.JPG"])
        cohort_folder = packet / "review/cohorts" / cohort["cohort_id"]
        (cohort_folder / "contact_sheet.jpg").write_bytes(b"sheet")
        export = root / "exports" / job_id / cohort["cohort_id"]
        export.mkdir(parents=True)
        (export / "cohort_manifest.json").write_text("{}\n", encoding="utf-8")
        return packet, export

    def link(self, packet: Path, project: str, artifact: Path, cohort="cld-3080"):
        return command_cohort_link_project(
            argparse.Namespace(
                packet=str(packet),
                cohort=cohort,
                project=project,
                type="project",
                artifact=str(artifact),
                note="precise provenance",
                json=False,
            )
        )

    def capture(self, func, **kwargs) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            func(argparse.Namespace(**kwargs))
        return output.getvalue()

    def test_link_creates_project_and_bidirectional_idempotent_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, export = self.make_packet(root, "packet-one")
            with patch.dict(os.environ, self.env(root), clear=False):
                self.link(packet, "CLD-3080", export)
                self.link(packet, "CLD-3080", export)
                project = root / "projects/cld-3080"
                self.assertTrue((project / "project.json").is_file())
                self.assertEqual(len(load_project_packets("cld-3080")["packets"]), 1)
                self.assertEqual(len(load_project_artifacts("cld-3080")["artifacts"]), 1)
                self.assertEqual(len(load_project_cohorts("cld-3080")["cohorts"]), 1)
                links = read_cohort_project_links(packet, "cld-3080")["links"]
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0]["artifact_path"], str(export))
                history = [event["event"] for event in read_cohort(packet, "cld-3080")["history"]]
                self.assertEqual(history.count("project_linked"), 1)

    def test_unlink_removes_only_cohort_edge_and_deletes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, export = self.make_packet(root, "packet-one")
            original = packet / "originals/DCIM/IMG_1.JPG"
            with patch.dict(os.environ, self.env(root), clear=False):
                self.link(packet, "CLD-3080", export)
                command_cohort_unlink_project(
                    argparse.Namespace(packet=str(packet), cohort="cld-3080", project="CLD-3080")
                )
                self.assertEqual(load_project_cohorts("cld-3080")["cohorts"], [])
                self.assertEqual(read_cohort_project_links(packet, "cld-3080")["links"], [])
                self.assertEqual(len(load_project_packets("cld-3080")["packets"]), 1)
                self.assertEqual(len(load_project_artifacts("cld-3080")["artifacts"]), 1)
                self.assertTrue(original.is_file())
                self.assertTrue(export.is_dir())

    def test_projects_and_cohorts_support_many_to_many_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_one, export_one = self.make_packet(root, "packet-one")
            packet_two, export_two = self.make_packet(root, "packet-two")
            with patch.dict(os.environ, self.env(root), clear=False):
                self.link(packet_one, "Combined", export_one)
                self.link(packet_two, "Combined", export_two)
                self.link(packet_one, "Second Project", export_one)
                self.assertEqual(len(load_project_cohorts("combined")["cohorts"]), 2)
                self.assertEqual(len(read_cohort_project_links(packet_one, "cld-3080")["links"]), 2)

    def test_project_commands_show_cohort_contribution_and_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, export = self.make_packet(root, "packet-one")
            with patch.dict(os.environ, self.env(root), clear=False):
                self.link(packet, "CLD-3080", export)
                links = self.capture(
                    command_cohort_project_links,
                    packet=str(packet),
                    cohort="cld-3080",
                    json=False,
                )
                cohorts = self.capture(command_projects_cohorts, identifier="cld-3080", json=False)
                inspect = self.capture(command_projects_inspect, identifier="cld-3080")
                contribution = self.capture(
                    command_projects_cohort,
                    identifier="cld-3080",
                    cohort_id="cld-3080",
                    json=False,
                )
                listing = self.capture(command_projects_list)
                briefing = self.capture(command_projects_briefing, identifier="cld-3080", json=False)
                self.assertIn("cld-3080", links)
                self.assertIn("packet-one", cohorts)
                self.assertIn("Linked cohorts: 1", inspect)
                self.assertIn("Export exists: yes", contribution)
                self.assertIn("cohort_count", listing)
                self.assertIn("Photo Cohorts:", briefing)
                self.assertIn("export: exists", briefing)
                self.assertIn("contact sheet: exists", briefing)
                self.assertIn("Review or continue work with the CLD-3080 cohort export.", briefing)

    def test_missing_export_and_contact_sheet_produce_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, export = self.make_packet(root, "packet-one")
            with patch.dict(os.environ, self.env(root), clear=False):
                self.link(packet, "CLD-3080", export)
                export.rename(root / "moved-export")
                (packet / "review/cohorts/cld-3080/contact_sheet.jpg").unlink()
                briefing = self.capture(command_projects_briefing, identifier="cld-3080", json=False)
                portfolio = self.capture(command_projects_briefing, identifier=None, json=False)
                self.assertIn("Re-export or relink the missing cohort artifact.", briefing)
                self.assertIn("Generate the cohort contact sheet.", briefing)
                self.assertIn("Missing cohort exports: 1", portfolio)
                self.assertIn("Missing cohort contact sheets: 1", portfolio)

    def test_packet_lifecycle_shows_cohort_project_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, export = self.make_packet(root, "packet-one")
            with patch.dict(os.environ, self.env(root), clear=False):
                self.link(packet, "CLD-3080", export)
                record = registry_record("photo", packet)
                conn = connect_registry(root / "registry.db")
                upsert_registry_record(conn, record)
                conn.commit()
                conn.row_factory = __import__("sqlite3").Row
                row = conn.execute("SELECT * FROM packets").fetchone()
                conn.close()
                lifecycle = registry_lifecycle(row, packet)
                self.assertIn("cld-3080: 2 files, ready, projects: cld-3080", lifecycle)


if __name__ == "__main__":
    unittest.main()
