import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import (
    add_project_task,
    add_task_checklist_item,
    add_task_work_log,
    add_task_work_note,
    archive_task_work_note,
    command_projects_active,
    command_projects_briefing,
    command_projects_task_checklist,
    command_projects_task_checklist_add,
    command_projects_task_checklist_complete,
    command_projects_task_checklist_reopen,
    command_projects_task_checklist_update,
    command_projects_task_complete,
    command_projects_task_context,
    command_projects_task_link_artifact,
    command_projects_task_link_packet,
    command_projects_task_log,
    command_projects_task_logs,
    command_projects_task_note,
    command_projects_task_note_archive,
    command_projects_task_note_update,
    command_projects_task_notes,
    command_projects_task_reopen,
    command_projects_task_start,
    command_projects_task_start,
    ensure_project_record,
    link_artifact_to_task,
    link_packet_to_task,
    load_project_tasks,
    set_task_checklist_status,
    task_context_data,
    task_work_logs,
    task_work_notes,
    update_task_checklist_item,
    update_task_work_note,
)


class ProjectTaskContextTests(unittest.TestCase):
    def env(self, project_root):
        return {
            "LAIA_PROJECT_REGISTRY_ROOT": str(project_root),
            "LAIA_PACKET_REGISTRY_DB": str(project_root.parent / "registry.db"),
            "LAIA_PACKET_ROOTS": str(project_root.parent / "unused"),
        }

    def setup_project(self, root, name="Receipts"):
        project_root = root / "projects_registry"
        with patch.dict("os.environ", self.env(project_root), clear=False):
            ensure_project_record(name)
        return project_root

    def capture(self, func, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            func(argparse.Namespace(**kwargs))
        return output.getvalue()

    def test_old_task_records_load_with_empty_work_context_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task_path = project_root / "receipts" / "tasks.json"
                task_path.write_text(
                    json.dumps({"project_id": "receipts", "tasks": [{"task_id": "task-old", "title": "Old", "status": "open"}]}),
                    encoding="utf-8",
                )
                task = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(task["work_notes"], [])
            self.assertEqual(task["checklist"], [])
            self.assertEqual(task["work_log"], [])
            self.assertEqual(task["linked_packets"], [])
            self.assertEqual(task["linked_artifacts"], [])

    def test_task_note_append_update_archive_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                note = add_task_work_note(task["task_id"], "Confirm cutoff")
                update_task_work_note(task["task_id"], note["note_id"], "Confirm May cutoff")
                archive_task_work_note(task["task_id"], note["note_id"])
                notes = task_work_notes(task["task_id"])
                out = self.capture(command_projects_task_notes, task_id=task["task_id"], project=None, status=None, json=False)

            self.assertEqual(notes[0]["text"], "Confirm May cutoff")
            self.assertEqual(notes[0]["status"], "archived")
            self.assertIn(note["note_id"], out)

    def test_task_note_command_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                out = self.capture(command_projects_task_note, task_id=task["task_id"], text="Ready", project=None, status="active", json=True)

            data = json.loads(out)
            self.assertTrue(data["note_id"].startswith("task-note-"))

    def test_checklist_add_list_complete_reopen_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                item = add_task_checklist_item(task["task_id"], "Gather packets")
                update_task_checklist_item(task["task_id"], item["item_id"], "Gather May packets")
                set_task_checklist_status(task["task_id"], item["item_id"], "complete")
                complete = load_project_tasks("receipts")["tasks"][0]["checklist"][0]
                set_task_checklist_status(task["task_id"], item["item_id"], "open")
                reopened = load_project_tasks("receipts")["tasks"][0]["checklist"][0]
                out = self.capture(command_projects_task_checklist, task_id=task["task_id"], project=None, status=None, json=False)

            self.assertEqual(complete["status"], "complete")
            self.assertIsNotNone(complete["completed_at"])
            self.assertEqual(reopened["status"], "open")
            self.assertIsNone(reopened["completed_at"])
            self.assertIn("Gather May packets", out)

    def test_checklist_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                item_json = self.capture(command_projects_task_checklist_add, task_id=task["task_id"], text="Verify finalized state", project=None, json=True)
                item = json.loads(item_json)
                self.capture(command_projects_task_checklist_update, task_id=task["task_id"], item_id=item["item_id"], text="Verify packet finalized", project=None)
                self.capture(command_projects_task_checklist_complete, task_id=task["task_id"], item_id=item["item_id"], project=None)
                self.capture(command_projects_task_checklist_reopen, task_id=task["task_id"], item_id=item["item_id"], project=None)
                loaded = load_project_tasks("receipts")["tasks"][0]["checklist"][0]

            self.assertEqual(loaded["text"], "Verify packet finalized")
            self.assertEqual(loaded["status"], "open")

    def test_task_log_appends_immutable_entries_and_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                first = add_task_work_log(task["task_id"], "Started work")
                second = add_task_work_log(task["task_id"], "Checked packet state")
                logs = task_work_logs(task["task_id"])
                out = self.capture(command_projects_task_logs, task_id=task["task_id"], project=None, json=False)

            self.assertEqual([log["log_id"] for log in logs], [first["log_id"], second["log_id"]])
            self.assertIn("Checked packet state", out)

    def test_task_log_command_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                out = self.capture(command_projects_task_log, task_id=task["task_id"], text="Started", project=None, json=True)

            self.assertTrue(json.loads(out)["log_id"].startswith("log-"))

    def test_task_link_packet_and_artifact_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            artifact = Path(tmp) / "artifact"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                link_packet_to_task(task["task_id"], "packet-1")
                link_packet_to_task(task["task_id"], "packet-1")
                link_artifact_to_task(task["task_id"], str(artifact))
                link_artifact_to_task(task["task_id"], str(artifact))
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(loaded["linked_packets"], ["packet-1"])
            self.assertEqual(loaded["source_packet_id"], "packet-1")
            self.assertEqual(loaded["linked_artifacts"], [str(artifact)])
            self.assertEqual(loaded["artifact_path"], str(artifact))

    def test_task_link_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            artifact = Path(tmp) / "artifact"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                self.capture(command_projects_task_link_packet, task_id=task["task_id"], packet_id="packet-1", project=None)
                self.capture(command_projects_task_link_artifact, task_id=task["task_id"], artifact_path=str(artifact), project=None)
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(loaded["linked_packets"], ["packet-1"])
            self.assertEqual(loaded["linked_artifacts"], [str(artifact)])

    def test_active_shows_detailed_context_for_single_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts", description="Reconcile totals")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
                add_task_checklist_item(task["task_id"], "Gather packets")
                add_task_work_note(task["task_id"], "Confirm cutoff")
                add_task_work_log(task["task_id"], "Started")
                out = self.capture(command_projects_active, project=None, json=False)

            self.assertIn("LAIA Project Task Context", out)
            self.assertIn("Checklist:", out)
            self.assertIn("Gather packets", out)
            self.assertIn("Suggested Next Step:", out)

    def test_active_handles_no_and_multiple_active_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                empty = self.capture(command_projects_active, project=None, json=False)
                first = add_project_task("receipts", "One")
                second = add_project_task("receipts", "Two")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=first["task_id"]))
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=second["task_id"]))
                multi = self.capture(command_projects_active, project=None, json=False)

            self.assertIn("No active project tasks.", empty)
            self.assertIn("LAIA Active Project Tasks", multi)
            self.assertIn(first["task_id"], multi)
            self.assertIn(second["task_id"], multi)

    def test_task_context_shows_links_notes_checklist_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            artifact = Path(tmp) / "artifact"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts", description="Reconcile totals")
                add_task_checklist_item(task["task_id"], "Gather packets")
                add_task_work_note(task["task_id"], "Confirm cutoff")
                add_task_work_log(task["task_id"], "Started")
                link_packet_to_task(task["task_id"], "packet-1")
                link_artifact_to_task(task["task_id"], str(artifact))
                out = self.capture(command_projects_task_context, task_id=task["task_id"], project=None, json=False)

            self.assertIn("packet-1", out)
            self.assertIn(str(artifact), out)
            self.assertIn("Confirm cutoff", out)
            self.assertIn("Started", out)

    def test_suggested_next_step_uses_first_open_checklist_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts", description="Description fallback")
                add_task_checklist_item(task["task_id"], "First open item")
                data = task_context_data(task["task_id"])

            self.assertEqual(data["suggested_next_step"], "First open item")

    def test_task_complete_warns_on_open_checklist_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                add_task_checklist_item(task["task_id"], "Gather packets")
                out = self.capture(command_projects_task_complete, identifier="receipts", task_id=task["task_id"], note="")

            self.assertIn("Warning: 1 checklist items remain open.", out)

    def test_task_reopen_preserves_work_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                add_task_checklist_item(task["task_id"], "Gather packets")
                add_task_work_note(task["task_id"], "Keep this")
                add_task_work_log(task["task_id"], "Started")
                command_projects_task_complete(argparse.Namespace(identifier="receipts", task_id=task["task_id"], note=""))
                command_projects_task_reopen(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(len(loaded["checklist"]), 1)
            self.assertEqual(len(loaded["work_notes"]), 1)
            self.assertEqual(len(loaded["work_log"]), 1)

    def test_tasks_markdown_includes_checklist_notes_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                add_task_checklist_item(task["task_id"], "Gather packets")
                add_task_work_note(task["task_id"], "Confirm cutoff")
                add_task_work_log(task["task_id"], "Started")
                markdown = (project_root / "receipts" / "tasks.md").read_text(encoding="utf-8")

            self.assertIn("- [ ] Gather packets", markdown)
            self.assertIn("Confirm cutoff", markdown)
            self.assertIn("Started", markdown)

    def test_fleet_briefing_includes_active_checklist_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
                add_task_checklist_item(task["task_id"], "Gather packets")
                add_task_work_log(task["task_id"], "Started")
                out = self.capture(command_projects_briefing, identifier=None, json=False)

            self.assertIn("Active tasks: 1", out)
            self.assertIn("Checklist items open: 1", out)
            self.assertIn("Tasks with recent work logs: 1", out)
            self.assertIn("Next checklist item: Gather packets.", out)

    def test_per_project_briefing_includes_next_checklist_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task = add_project_task("receipts", "Import May receipts")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
                add_task_checklist_item(task["task_id"], "Gather packets")
                add_task_work_log(task["task_id"], "Started")
                out = self.capture(command_projects_briefing, identifier="receipts", json=False)

            self.assertIn("active context:", out)
            self.assertIn("next: Gather packets", out)
            self.assertIn("Next checklist item: Gather packets.", out)


if __name__ == "__main__":
    unittest.main()
