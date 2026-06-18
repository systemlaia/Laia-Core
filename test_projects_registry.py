import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from test_packets_registry import PacketRegistryTests
from core.packets.registry import (
    PacketRoot,
    command_packets_inspect,
    command_packets_lifecycle,
    command_packets_link_project,
    command_packets_project_links,
    command_packets_unlink_project,
    load_registry_rows,
    read_project_links,
    scan_roots,
)
from core.projects.registry import (
    add_project_task,
    command_projects_artifacts,
    command_projects_briefing,
    command_projects_inspect,
    command_projects_list,
    command_projects_note,
    command_projects_note_archive,
    command_projects_note_update,
    command_projects_notes,
    command_projects_blocked,
    command_projects_in_progress,
    command_projects_packets,
    command_projects_next,
    command_projects_queue,
    command_projects_queue_summary,
    command_projects_search,
    command_projects_start_next,
    command_projects_task_add,
    command_projects_task_block,
    command_projects_task_cancel,
    command_projects_task_complete,
    command_projects_task_reopen,
    command_projects_task_show,
    command_projects_task_start,
    command_projects_task_summary,
    command_projects_task_update,
    command_projects_task_find,
    command_projects_tasks,
    ensure_project_record,
    find_task_global,
    find_project,
    project_queue_rows,
    start_next_project_task,
    load_project_notes,
    load_project_tasks,
    project_artifacts,
    project_folder,
    project_packets,
    search_projects,
    write_project_tasks,
)


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self):
        self.helper = PacketRegistryTests()

    def env(self, db_path, project_root, promotion_root=None):
        env = self.helper.registry_env(db_path)
        env["LAIA_PROJECT_REGISTRY_ROOT"] = str(project_root)
        if promotion_root:
            env["LAIA_PACKET_PROMOTION_ROOT"] = str(promotion_root)
        return env

    def promoted_packet(self, root, job_id="linked-photo"):
        packet, db_path, _ = self.helper.reviewed_temp_export(root, job_id=job_id)
        promotion_root = root / "promoted"
        env = self.env(db_path, root / "projects_registry", promotion_root)
        with patch.dict(os.environ, env, clear=False):
            from core.packets.registry import command_packets_promote

            with contextlib.redirect_stdout(io.StringIO()):
                command_packets_promote(
                    argparse.Namespace(
                        identifier=job_id,
                        destination_type="project",
                        destination="Receipts",
                        note="promote",
                        dry_run=False,
                    )
                )
        scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
        return packet, db_path, promotion_root / "projects" / "Receipts"

    def link_packet(self, root, job_id="linked-photo", project="Receipts", project_type="project", artifact=None):
        packet, db_path, artifact_path = self.promoted_packet(root, job_id=job_id)
        project_root = root / "projects_registry"
        env = self.env(db_path, project_root)
        with patch.dict(os.environ, env, clear=False):
            with contextlib.redirect_stdout(io.StringIO()):
                command_packets_link_project(
                    argparse.Namespace(
                        identifier=job_id,
                        project=project,
                        type=project_type,
                        artifact=str(artifact) if artifact is not None else None,
                        note="link note",
                    )
                )
        return packet, db_path, project_root, artifact_path

    def run_laia_projects(self, project_root, *args):
        env = os.environ.copy()
        env["LAIA_PROJECT_REGISTRY_ROOT"] = str(project_root)
        return subprocess.run(
            [str(Path(__file__).resolve().parent / "bin" / "laia"), "projects", *args],
            cwd=Path(__file__).resolve().parent,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def load_laia_cli_module(self):
        root = Path(__file__).resolve().parent
        core_path = str(root / "core")
        if core_path not in sys.path:
            sys.path.insert(0, core_path)
        for package_name in ("packets", "projects"):
            module = sys.modules.get(package_name)
            module_file = str(getattr(module, "__file__", "")) if module else ""
            expected = str(root / "core" / package_name)
            if module and not module_file.startswith(expected):
                sys.modules.pop(package_name, None)
                sys.modules.pop(f"{package_name}.registry", None)
        if "yaml" not in sys.modules:
            try:
                import yaml  # noqa: F401
            except ModuleNotFoundError:
                sys.modules["yaml"] = types.SimpleNamespace(safe_load=lambda text: {})
        spec = importlib.util.spec_from_file_location("laia_cli_under_test", root / "core" / "cli" / "laia.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_laia_main(self, project_root, *args):
        output = io.StringIO()
        error = io.StringIO()
        with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
            with patch.object(sys, "argv", ["laia", *args]):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    try:
                        self.load_laia_cli_module().main()
                        returncode = 0
                    except SystemExit as exc:
                        returncode = exc.code if isinstance(exc.code, int) else 1
        return argparse.Namespace(returncode=returncode, stdout=output.getvalue(), stderr=error.getvalue())

    def test_link_project_creates_project_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                project_id = find_project("Receipts")

            self.assertEqual(project_id, "receipts")
            self.assertTrue((project_root / "receipts" / "project.json").exists())

    def test_link_project_writes_packet_side_project_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, _, _, artifact_path = self.link_packet(Path(tmp))
            links = read_project_links(packet)["links"]

            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]["project_id"], "receipts")
            self.assertEqual(links[0]["artifact_path"], str(artifact_path))

    def test_link_project_adds_packet_and_artifact_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, artifact_path = self.link_packet(Path(tmp))

            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                self.assertEqual(project_packets("receipts")[0]["job_id"], "linked-photo")
                self.assertEqual(project_artifacts("receipts")[0]["artifact_path"], str(artifact_path))

    def test_link_project_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.link_packet(root)
            db_path = root / "registry.db"
            env = self.env(db_path, root / "projects_registry")
            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_link_project(
                        argparse.Namespace(identifier="linked-photo", project="Receipts", type="project", artifact=None, note="")
                    )

            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(len(project_packets("receipts")), 1)
                self.assertEqual(len(project_artifacts("receipts")), 1)

    def test_unlink_project_removes_bidirectional_link_without_deleting_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet, db_path, project_root, artifact_path = self.link_packet(Path(tmp))
            env = self.env(db_path, project_root)

            with patch.dict(os.environ, env, clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_unlink_project(argparse.Namespace(identifier="linked-photo", project="Receipts"))

            self.assertEqual(read_project_links(packet)["links"], [])
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(project_packets("receipts"), [])
            self.assertTrue(artifact_path.exists())

    def test_projects_list_shows_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_list(argparse.Namespace())

            text = output.getvalue()
            self.assertIn("receipts", text)
            self.assertIn("1", text)

    def test_projects_inspect_packets_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, artifact_path = self.link_packet(Path(tmp))
            env = self.env(db_path, project_root)
            with patch.dict(os.environ, env, clear=False):
                inspect_out = io.StringIO()
                with contextlib.redirect_stdout(inspect_out):
                    command_projects_inspect(argparse.Namespace(identifier="Receipts"))
                packets_out = io.StringIO()
                with contextlib.redirect_stdout(packets_out):
                    command_projects_packets(argparse.Namespace(identifier="Receipts"))
                artifacts_out = io.StringIO()
                with contextlib.redirect_stdout(artifacts_out):
                    command_projects_artifacts(argparse.Namespace(identifier="Receipts"))

            self.assertIn("Linked packets: 1", inspect_out.getvalue())
            self.assertIn("linked-photo", packets_out.getvalue())
            self.assertIn(str(artifact_path), artifacts_out.getvalue())

    def test_projects_search_filters_by_type_status_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp), project_type="publication")
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                rows = search_projects({"type": "publication", "status": "active", "text": "linked-photo"})

            self.assertEqual(rows[0]["project_id"], "receipts")

    def test_projects_search_json_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_search(argparse.Namespace(type=None, status=None, text="receipts", json=True))

            data = json.loads(output.getvalue())
            self.assertEqual(data[0]["project_id"], "receipts")

    def test_project_note_add_creates_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_note(argparse.Namespace(identifier="receipts", text="Need monthly reconciliation.", status="active", json=False))

            notes_doc = json.loads((project_root / "receipts" / "notes.json").read_text(encoding="utf-8"))
            self.assertEqual(notes_doc["notes"][0]["text"], "Need monthly reconciliation.")
            self.assertIn("Need monthly reconciliation.", (project_root / "receipts" / "notes.md").read_text(encoding="utf-8"))
            self.assertIn("Added note note-", output.getvalue())

    def test_project_notes_listing_update_and_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                note = json.loads(self.capture_project_command(command_projects_note, identifier="receipts", text="First note", status="active", json=True))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_notes(argparse.Namespace(identifier="receipts", status=None, json=False))
                command_projects_note_update(argparse.Namespace(identifier="receipts", note_id=note["note_id"], text="Updated note"))
                command_projects_note_archive(argparse.Namespace(identifier="receipts", note_id=note["note_id"]))
                notes = load_project_notes("receipts")["notes"]

            self.assertIn("First note", output.getvalue())
            self.assertEqual(notes[0]["text"], "Updated note")
            self.assertEqual(notes[0]["status"], "archived")

    def capture_project_command(self, command, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            command(argparse.Namespace(**kwargs))
        return output.getvalue()

    def test_project_task_add_creates_json_markdown_and_unique_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                first = add_project_task("receipts", "Import May receipts")
                second = add_project_task("receipts", "Import June receipts")

            tasks_doc = json.loads((project_root / "receipts" / "tasks.json").read_text(encoding="utf-8"))
            self.assertNotEqual(first["task_id"], second["task_id"])
            self.assertEqual(len(tasks_doc["tasks"]), 2)
            self.assertIn("Import May receipts", (project_root / "receipts" / "tasks.md").read_text(encoding="utf-8"))

    def test_project_task_state_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                command_projects_task_add(
                    argparse.Namespace(identifier="receipts", title="Import May receipts", description="", priority="normal", source_packet=None, artifact=None)
                )
                task_id = load_project_tasks("receipts")["tasks"][0]["task_id"]
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=task_id))
                self.assertEqual(load_project_tasks("receipts")["tasks"][0]["status"], "in_progress")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=task_id, note="Waiting on bank export"))
                self.assertEqual(load_project_tasks("receipts")["tasks"][0]["block_note"], "Waiting on bank export")
                command_projects_task_complete(argparse.Namespace(identifier="receipts", task_id=task_id, note="Done"))
                completed = load_project_tasks("receipts")["tasks"][0]
                self.assertEqual(completed["status"], "complete")
                self.assertIsNotNone(completed["completed_at"])
                command_projects_task_cancel(argparse.Namespace(identifier="receipts", task_id=task_id, note="No longer needed"))
                self.assertEqual(load_project_tasks("receipts")["tasks"][0]["status"], "cancelled")
                command_projects_task_reopen(argparse.Namespace(identifier="receipts", task_id=task_id))
                reopened = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(reopened["status"], "open")
            self.assertIsNone(reopened["completed_at"])

    def test_project_task_update_fields_and_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            artifact = Path(tmp) / "artifact"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Old title")
                command_projects_task_update(
                    argparse.Namespace(
                        identifier="receipts",
                        task_id=task["task_id"],
                        title="New title",
                        description="Details",
                        priority="urgent",
                        source_packet="packet-1",
                        artifact=str(artifact),
                    )
                )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_task_show(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
                updated = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(updated["title"], "New title")
            self.assertEqual(updated["priority"], "urgent")
            self.assertIn("New title", output.getvalue())

    def test_project_task_filtering_and_summary_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                high = add_project_task("receipts", "Urgent task", priority="urgent")
                normal = add_project_task("receipts", "Normal task")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=high["task_id"], note="Blocked"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_tasks(argparse.Namespace(identifier="receipts", status="blocked", priority="urgent", json=False))
                summary_out = io.StringIO()
                with contextlib.redirect_stdout(summary_out):
                    command_projects_task_summary(argparse.Namespace(identifier="receipts"))

            self.assertIn(high["task_id"], output.getvalue())
            self.assertNotIn(normal["task_id"], output.getvalue())
            self.assertIn("blocked: 1", summary_out.getvalue())
            self.assertIn("high/urgent open: 1", summary_out.getvalue())

    def test_project_briefing_includes_notes_tasks_and_task_suggestions(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Receipts")
                command_projects_note(argparse.Namespace(identifier="receipts", text="Follow up", status="active", json=False))
                task = add_project_task("receipts", "Urgent blocked task", priority="urgent")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=task["task_id"], note="Blocked"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=False))

            text = output.getvalue()
            self.assertIn("Notes:", text)
            self.assertIn("active: 1", text)
            self.assertIn("Tasks:", text)
            self.assertIn("blocked: 1", text)
            self.assertIn("Resolve 1 blocked project tasks.", text)

    def test_project_briefing_suggests_open_tasks_and_no_open_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Open Project")
                add_project_task("open-project", "Continue this")
                open_out = io.StringIO()
                with contextlib.redirect_stdout(open_out):
                    command_projects_briefing(argparse.Namespace(identifier="open-project", json=False))
            self.assertIn("Start Continue this.", open_out.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=False))
            self.assertIn("Project has no open tasks; add work or mark project complete.", output.getvalue())

    def test_project_fleet_briefing_aggregates_task_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Receipts")
                ensure_project_record("Photo Selects", project_type="publication")
                add_project_task("receipts", "Open task")
                blocked = add_project_task("photo-selects", "High task", priority="high")
                command_projects_task_block(argparse.Namespace(identifier="photo-selects", task_id=blocked["task_id"], note="Blocked"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier=None, json=False))

            text = output.getvalue()
            self.assertIn("Open tasks: 1", text)
            self.assertIn("Blocked tasks: 1", text)
            self.assertIn("Projects with high-priority tasks: 1", text)

    def test_projects_search_task_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Reconcile taxes", priority="high")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=task["task_id"], note="Blocked"))
                rows = search_projects({"has_blocked_tasks": True, "priority": "high", "task_text": "taxes"})

            self.assertEqual(rows[0]["project_id"], "receipts")

    def test_project_queue_aggregates_tasks_from_multiple_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                ensure_project_record("Photo Selects")
                add_project_task("receipts", "Import May receipts", priority="high")
                add_project_task("photo-selects", "Draft captions")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_queue(argparse.Namespace(status=None, priority=None, project=None, text=None, limit=None, json=False))

            text = output.getvalue()
            self.assertIn("Import May receipts", text)
            self.assertIn("Draft captions", text)
            self.assertIn("receipts", text)
            self.assertIn("photo-selects", text)

    def test_project_queue_default_excludes_complete_and_cancelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                done = add_project_task("receipts", "Done")
                cancelled = add_project_task("receipts", "Cancelled")
                open_task = add_project_task("receipts", "Open")
                command_projects_task_complete(argparse.Namespace(identifier="receipts", task_id=done["task_id"], note="done"))
                command_projects_task_cancel(argparse.Namespace(identifier="receipts", task_id=cancelled["task_id"], note="cancel"))
                rows = project_queue_rows({})

            self.assertEqual([row["task_id"] for row in rows], [open_task["task_id"]])

    def test_project_queue_sorting_priority_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                low = add_project_task("receipts", "Low", priority="low")
                normal = add_project_task("receipts", "Normal", priority="normal")
                high_open = add_project_task("receipts", "High open", priority="high")
                high_progress = add_project_task("receipts", "High progress", priority="high")
                high_blocked = add_project_task("receipts", "High blocked", priority="high")
                urgent = add_project_task("receipts", "Urgent", priority="urgent")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=high_progress["task_id"]))
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=high_blocked["task_id"], note="blocked"))
                rows = project_queue_rows({})

            ordered = [row["task_id"] for row in rows]
            self.assertLess(ordered.index(urgent["task_id"]), ordered.index(high_blocked["task_id"]))
            self.assertLess(ordered.index(high_blocked["task_id"]), ordered.index(high_progress["task_id"]))
            self.assertLess(ordered.index(high_progress["task_id"]), ordered.index(high_open["task_id"]))
            self.assertLess(ordered.index(normal["task_id"]), ordered.index(low["task_id"]))

    def test_project_queue_filters_status_priority_project_text_limit_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                ensure_project_record("Photo Selects")
                receipts = add_project_task("receipts", "Import May receipts", priority="high")
                add_project_task("photo-selects", "Draft captions", priority="normal")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=receipts["task_id"], note="waiting"))
                rows = project_queue_rows({"status": "blocked", "priority": "high", "project": "Receipts", "text": "may", "limit": 1})
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_queue(argparse.Namespace(status=None, priority=None, project=None, text=None, limit=1, json=True))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["project_id"], "receipts")
            data = json.loads(output.getvalue())
            self.assertEqual(len(data), 1)

    def test_project_next_returns_highest_ranked_actionable_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                blocked = add_project_task("receipts", "Urgent blocked", priority="urgent")
                high_open = add_project_task("receipts", "High open", priority="high")
                high_progress = add_project_task("receipts", "High progress", priority="high")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=blocked["task_id"], note="blocked"))
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=high_progress["task_id"]))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_next(argparse.Namespace(project=None, json=False))

            text = output.getvalue()
            self.assertIn(high_progress["task_id"], text)
            self.assertNotIn(blocked["task_id"], text)
            self.assertNotIn(high_open["task_id"], text)

    def test_project_next_reports_none_when_no_actionable_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Blocked", priority="urgent")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=task["task_id"], note="blocked"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_next(argparse.Namespace(project=None, json=False))

            self.assertIn("No actionable project tasks.", output.getvalue())

    def test_project_blocked_and_in_progress_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                blocked = add_project_task("receipts", "Blocked", priority="high")
                progress = add_project_task("receipts", "Doing", priority="normal")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=blocked["task_id"], note="waiting"))
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=progress["task_id"]))
                blocked_out = io.StringIO()
                with contextlib.redirect_stdout(blocked_out):
                    command_projects_blocked(argparse.Namespace(project=None, json=False))
                progress_out = io.StringIO()
                with contextlib.redirect_stdout(progress_out):
                    command_projects_in_progress(argparse.Namespace(project=None, json=False))

            self.assertIn(blocked["task_id"], blocked_out.getvalue())
            self.assertIn("waiting", blocked_out.getvalue())
            self.assertIn(progress["task_id"], progress_out.getvalue())

    def test_project_task_find_locates_task_globally(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Photo Selects")
                task = add_project_task("photo-selects", "Review sequence", priority="high")
                row = find_task_global(task["task_id"])
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_task_find(argparse.Namespace(task_id=task["task_id"]))

            self.assertEqual(row["project_id"], "photo-selects")
            self.assertIn("Review sequence", output.getvalue())

    def test_project_queue_handles_malformed_tasks_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Bad Tasks")
                ensure_project_record("Good Tasks")
                (project_root / "bad-tasks" / "tasks.json").write_text("{not json", encoding="utf-8")
                good = add_project_task("good-tasks", "Still visible")
                rows = project_queue_rows({})

            self.assertEqual([row["task_id"] for row in rows], [good["task_id"]])

    def test_project_queue_summary_and_briefing_include_counts_and_next_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Receipts")
                high = add_project_task("receipts", "Import May receipts", priority="high")
                add_project_task("receipts", "Draft captions", priority="normal")
                summary_out = io.StringIO()
                with contextlib.redirect_stdout(summary_out):
                    command_projects_queue_summary(argparse.Namespace())
                briefing_out = io.StringIO()
                with contextlib.redirect_stdout(briefing_out):
                    command_projects_briefing(argparse.Namespace(identifier=None, json=False))

            self.assertIn("open: 2", summary_out.getvalue())
            self.assertIn("high open: 1", summary_out.getvalue())
            self.assertIn("Actionable tasks: 2", briefing_out.getvalue())
            self.assertIn(f"Next task: receipts/{high['title']}", briefing_out.getvalue())

    def test_fleet_briefing_queue_aware_suggestions_are_concise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, db_path, project_root, _ = self.link_packet(root, project="Receipts", project_type="project")
            self.link_packet(root, job_id="pub-photo", project="Photo Selects", project_type="publication")
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                receipts_task = add_project_task("receipts", "Import May receipts", priority="high")
                add_project_task("photo-selects", "Review publication sequence", priority="high")
                add_project_task("photo-selects", "Draft captions", priority="normal")
                receipts_doc = load_project_tasks("receipts")
                receipts_doc["tasks"][0]["created_at"] = "2026-06-14T00:00:00Z"
                receipts_doc["tasks"][0]["updated_at"] = receipts_task["updated_at"]
                write_project_tasks("receipts", receipts_doc)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier=None, json=False))

            text = output.getvalue()
            self.assertIn("Start receipts/Import May receipts.", text)
            self.assertIn("2 high-priority tasks remain across 2 projects.", text)
            self.assertIn("Project portfolio is healthy.", text)
            self.assertIn("Review publication staging outputs.", text)
            self.assertNotIn("Continue open project tasks.", text)
            self.assertNotIn("Continue the project work queue.", text)
            self.assertNotIn("Work the highest-priority project tasks.", text)

    def test_fleet_briefing_blocked_overrides_start_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Blocked thing", priority="urgent")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=task["task_id"], note="waiting"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier=None, json=False))

            text = output.getvalue()
            self.assertIn("Resolve 1 blocked project tasks.", text)
            self.assertNotIn("Start receipts/Blocked thing.", text)

    def test_fleet_briefing_in_progress_produces_continue_suggestion(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Already moving", priority="high")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier=None, json=False))

            text = output.getvalue()
            self.assertIn("Continue receipts/Already moving.", text)
            self.assertNotIn("Start receipts/Already moving.", text)

    def test_project_briefing_names_next_project_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Receipts")
                add_project_task("receipts", "Import May receipts", priority="high")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=False))

            self.assertIn("Start Import May receipts.", output.getvalue())

    def test_start_next_starts_highest_ranked_open_task_and_regenerates_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                high = add_project_task("receipts", "Import May receipts", priority="high")
                add_project_task("receipts", "Draft captions", priority="normal")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_start_next(argparse.Namespace(project=None, json=False))
                task = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(task["task_id"], high["task_id"])
            self.assertEqual(task["status"], "in_progress")
            self.assertEqual(task["created_at"], high["created_at"])
            self.assertTrue(task.get("started_at"))
            self.assertIn("LAIA Started Next Project Task", output.getvalue())
            self.assertIn("Status: in_progress", (project_root / "receipts" / "tasks.md").read_text(encoding="utf-8"))

    def test_start_next_prefers_in_progress_without_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Already moving", priority="high")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
                before = load_project_tasks("receipts")["tasks"][0]
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_start_next(argparse.Namespace(project=None, json=False))
                after = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(before["updated_at"], after["updated_at"])
            self.assertEqual(before["started_at"], after["started_at"])
            self.assertIn("Already In Progress", output.getvalue())

    def test_start_next_respects_project_filter_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                ensure_project_record("Photo Selects")
                add_project_task("receipts", "Import May receipts", priority="urgent")
                photo = add_project_task("photo-selects", "Review publication sequence", priority="high")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_start_next(argparse.Namespace(project="photo-selects", json=True))

            data = json.loads(output.getvalue())
            self.assertEqual(data["task_id"], photo["task_id"])
            self.assertEqual(data["project_id"], "photo-selects")
            self.assertEqual(data["status"], "in_progress")

    def test_start_next_handles_no_actionable_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Blocked", priority="urgent")
                command_projects_task_block(argparse.Namespace(identifier="receipts", task_id=task["task_id"], note="waiting"))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_start_next(argparse.Namespace(project=None, json=False))

            self.assertIn("No actionable project tasks.", output.getvalue())

    def test_projects_fleet_briefing_shows_counts_and_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, db_path, project_root, _ = self.link_packet(root, project="Receipts", project_type="project")
            self.link_packet(root, job_id="pub-photo", project="Photo Selects", project_type="publication")
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier=None, json=False))

            text = output.getvalue()
            self.assertIn("LAIA Project Briefing", text)
            self.assertIn("Projects: 2", text)
            self.assertIn("project: 1", text)
            self.assertIn("publication: 1", text)
            self.assertIn("Linked packets: 2", text)
            self.assertIn("Linked artifacts: 2", text)

    def test_projects_fleet_briefing_shows_unhealthy_project_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_packet = self.helper.make_photo_packet(root / "photo", job_id="bad-project-packet", missing_report=True)
            db_path = root / "registry.db"
            scan_roots(db_path, [PacketRoot("photo_ingest", root / "photo")])
            project_root = root / "projects_registry"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_link_project(
                        argparse.Namespace(identifier=bad_packet.name, project="Needs Work", type="project", artifact=None, note="")
                    )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier=None, json=False))

            text = output.getvalue()
            self.assertIn("Packet problems: 1", text)
            self.assertIn("Resolve packet issues in affected projects.", text)

    def test_project_briefing_shows_packet_lifecycle_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=False))

            text = output.getvalue()
            self.assertIn("Packet Health:", text)
            self.assertIn("linked-photo", text)
            self.assertIn("reviewed", text)
            self.assertIn("executed", text)
            self.assertIn("promoted", text)
            self.assertIn("promoted and ready for downstream use", text)

    def test_project_briefing_shows_artifact_existence_and_file_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, artifact_path = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=False))

            text = output.getvalue()
            self.assertIn("Artifact Status:", text)
            self.assertIn(str(artifact_path), text)
            self.assertIn("yes", text)

    def test_project_briefing_flags_missing_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing-artifact"
            _, db_path, project_root, _ = self.link_packet(root, artifact=missing)
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=False))

            text = output.getvalue()
            self.assertIn("warning", text)
            self.assertIn(str(missing), text)
            self.assertIn("no", text)
            self.assertIn("Repair or relink missing artifact.", text)

    def test_project_briefing_suggests_publication_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp), project="Photo Selects", project_type="publication")
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="photo-selects", json=False))

            self.assertIn("Review publication staging and prepare next editorial step.", output.getvalue())

    def test_project_briefing_suggests_regular_project_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=False))

            self.assertIn("Continue project work or link additional source packets.", output.getvalue())

    def test_project_briefing_handles_project_with_no_packets_or_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            db_path = Path(tmp) / "registry.db"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                ensure_project_record("Empty Project")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="empty-project", json=False))

            text = output.getvalue()
            self.assertIn("health: warning", text)
            self.assertIn("Packet Health:\n  none", text)
            self.assertIn("Artifact Status:\n  none", text)

    def test_project_briefing_json_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command_projects_briefing(argparse.Namespace(identifier="receipts", json=True))

            data = json.loads(output.getvalue())
            self.assertEqual(data["project"]["project_id"], "receipts")
            self.assertEqual(data["health"], "healthy")
            self.assertEqual(data["packets"][0]["job_id"], "linked-photo")
            self.assertIn("suggested_actions", data)

    def test_project_briefing_unknown_project_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(Path(tmp) / "projects_registry")}, clear=False):
                with self.assertRaisesRegex(FileNotFoundError, "Project not found"):
                    command_projects_briefing(argparse.Namespace(identifier="missing", json=False))

    def test_packet_inspect_and_lifecycle_show_linked_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, db_path, project_root, _ = self.link_packet(Path(tmp))
            env = self.env(db_path, project_root)
            with patch.dict(os.environ, env, clear=False):
                inspect_out = io.StringIO()
                with contextlib.redirect_stdout(inspect_out):
                    command_packets_inspect(argparse.Namespace(identifier="linked-photo"))
                lifecycle_out = io.StringIO()
                with contextlib.redirect_stdout(lifecycle_out):
                    command_packets_lifecycle(argparse.Namespace(identifier="linked-photo"))

            self.assertIn("Linked Projects:", inspect_out.getvalue())
            self.assertIn("receipts", lifecycle_out.getvalue())

    def test_direct_packet_path_linking_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet, db_path, artifact_path = self.promoted_packet(root, job_id="direct-link")
            project_root = root / "projects_registry"
            with patch.dict(os.environ, self.env(db_path, project_root), clear=False):
                with contextlib.redirect_stdout(io.StringIO()):
                    command_packets_link_project(
                        argparse.Namespace(identifier=str(packet), project="Direct Project", type="project", artifact=str(artifact_path), note="")
                    )

            self.assertEqual(read_project_links(packet)["links"][0]["project_id"], "direct-project")

    def test_unknown_project_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(project_root)}, clear=False):
                with self.assertRaisesRegex(FileNotFoundError, "Project not found"):
                    find_project("Missing Project")

    def test_cli_projects_help_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_laia_projects(Path(tmp) / "projects_registry", "--help")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("list", result.stdout)
            self.assertIn("inspect", result.stdout)

    def test_cli_projects_parser_destinations(self):
        args = self.load_laia_cli_module().build_parser().parse_args(["projects", "list"])

        self.assertEqual(args.command, "projects")
        self.assertEqual(args.projects_command, "list")
        self.assertTrue(callable(args.func))

    def test_cli_main_projects_dispatches_to_handlers(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project_root, artifact_path = self.link_packet(Path(tmp))
            cases = [
                (["projects", "list"], ["LAIA Project Records", "receipts"]),
                (["projects", "inspect", "receipts"], ["LAIA Project Record", "Linked packets: 1"]),
                (["projects", "packets", "receipts"], ["LAIA Project Packets: receipts", "linked-photo"]),
                (["projects", "artifacts", "receipts"], ["LAIA Project Artifacts: receipts", str(artifact_path)]),
                (["projects", "search"], ["LAIA Project Search", "receipts"]),
            ]

            for argv, expected in cases:
                with self.subTest(argv=argv):
                    result = self.run_laia_main(project_root, *argv)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for text in expected:
                        self.assertIn(text, result.stdout)
                    self.assertNotIn("Available commands", result.stdout)

    def test_cli_projects_list_invokes_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project_root, _ = self.link_packet(Path(tmp))
            result = self.run_laia_projects(project_root, "list")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LAIA Project Records", result.stdout)
            self.assertIn("receipts", result.stdout)
            self.assertNotIn("usage: laia", result.stdout)

    def test_cli_projects_inspect_invokes_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project_root, _ = self.link_packet(Path(tmp))
            result = self.run_laia_projects(project_root, "inspect", "receipts")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LAIA Project Record", result.stdout)
            self.assertIn("Linked packets: 1", result.stdout)

    def test_cli_projects_packets_invokes_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project_root, _ = self.link_packet(Path(tmp))
            result = self.run_laia_projects(project_root, "packets", "receipts")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LAIA Project Packets: receipts", result.stdout)
            self.assertIn("linked-photo", result.stdout)

    def test_cli_projects_artifacts_invokes_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project_root, artifact_path = self.link_packet(Path(tmp))
            result = self.run_laia_projects(project_root, "artifacts", "receipts")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LAIA Project Artifacts: receipts", result.stdout)
            self.assertIn(str(artifact_path), result.stdout)

    def test_cli_projects_search_invokes_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, project_root, _ = self.link_packet(Path(tmp))
            result = self.run_laia_projects(project_root, "search", "--text", "receipts")

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("LAIA Project Search", result.stdout)
            self.assertIn("receipts", result.stdout)

    def test_cli_unknown_project_subcommand_fails_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_laia_projects(Path(tmp) / "projects_registry", "bogus")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid choice", result.stderr)
            self.assertNotIn("LAIA Project Records", result.stdout)


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(ProjectRegistryTests))
    return suite


if __name__ == "__main__":
    unittest.main()
