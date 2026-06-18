import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.registry import (
    active_next_step_data,
    add_project_task,
    add_task_checklist_item,
    command_projects_active_complete_next,
    command_projects_active_next,
    command_projects_briefing,
    command_projects_task_checklist_reopen,
    command_projects_task_complete_next,
    command_projects_task_next_step,
    command_projects_task_start,
    command_projects_task_step_history,
    complete_next_checklist_item,
    ensure_project_record,
    load_project_tasks,
    set_task_checklist_status,
    task_next_step_data,
    write_project_tasks,
)


class ProjectTaskStepTests(unittest.TestCase):
    def env(self, project_root):
        return {
            "LAIA_PROJECT_REGISTRY_ROOT": str(project_root),
            "LAIA_PACKET_REGISTRY_DB": str(project_root.parent / "registry.db"),
            "LAIA_PACKET_ROOTS": str(project_root.parent / "unused"),
        }

    def capture(self, func, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            func(argparse.Namespace(**kwargs))
        return output.getvalue()

    def make_task(self, project_root, *, status="in_progress", checklist=True):
        with patch.dict("os.environ", self.env(project_root), clear=False):
            ensure_project_record("Receipts")
            task = add_project_task("receipts", "Import May receipts", description="Reconcile totals", priority="high")
            if status == "in_progress":
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=task["task_id"]))
            if checklist:
                first = add_task_checklist_item(task["task_id"], "Gather finalized May receipt packets")
                second = add_task_checklist_item(task["task_id"], "Link May packets to the Receipts project")
                third = add_task_checklist_item(task["task_id"], "Reconcile extracted totals")
            else:
                first = second = third = None
            task = load_project_tasks("receipts")["tasks"][0]
        return task, first, second, third

    def test_task_next_step_returns_first_open_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, _, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                data = task_next_step_data(task["task_id"])
                out = self.capture(command_projects_task_next_step, task_id=task["task_id"], project=None, json=False)

            self.assertEqual(data["item_id"], first["item_id"])
            self.assertIn("Gather finalized May receipt packets", out)
            self.assertIn("checklist_progress: 0/3", out)

    def test_task_next_step_skips_completed_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, second, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                set_task_checklist_status(task["task_id"], first["item_id"], "complete")
                data = task_next_step_data(task["task_id"])

            self.assertEqual(data["item_id"], second["item_id"])

    def test_active_next_uses_in_progress_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, _, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                data = active_next_step_data()
                out = self.capture(command_projects_active_next, project=None, json=False)

            self.assertEqual(data["task_id"], task["task_id"])
            self.assertEqual(data["item_id"], first["item_id"])
            self.assertIn("LAIA Project Task Next Step", out)

    def test_active_next_falls_back_to_open_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, _, _ = self.make_task(project_root, status="open")
            with patch.dict("os.environ", self.env(project_root), clear=False):
                data = active_next_step_data()

            self.assertEqual(data["task_id"], task["task_id"])
            self.assertEqual(data["item_id"], first["item_id"])

    def test_task_complete_next_completes_exactly_one_item_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, second, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                result = complete_next_checklist_item(task["task_id"])
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertTrue(result["mutated"])
            self.assertEqual(result["completed_item"]["item_id"], first["item_id"])
            self.assertEqual(result["next_item"]["item_id"], second["item_id"])
            self.assertEqual(sum(1 for item in loaded["checklist"] if item["status"] == "complete"), 1)
            self.assertIn("Completed checklist item: Gather finalized", loaded["work_log"][0]["text"])

    def test_task_complete_next_custom_log_and_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, _, _, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                result = complete_next_checklist_item(task["task_id"], log_text="Custom progress", note_text="Remember cutoff")
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(result["log_text"], "Custom progress")
            self.assertEqual(loaded["work_log"][0]["text"], "Custom progress")
            self.assertEqual(loaded["work_notes"][0]["text"], "Remember cutoff")

    def test_task_complete_next_command_json_returns_next_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, _, second, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                out = self.capture(
                    command_projects_task_complete_next,
                    task_id=task["task_id"],
                    project=None,
                    log=None,
                    note=None,
                    complete_task=False,
                    json=True,
                )

            data = json.loads(out)
            self.assertEqual(data["next_item"]["item_id"], second["item_id"])

    def test_no_open_items_causes_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, second, third = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                for item in (first, second, third):
                    set_task_checklist_status(task["task_id"], item["item_id"], "complete")
                before = json.dumps(load_project_tasks("receipts"), sort_keys=True)
                result = complete_next_checklist_item(task["task_id"])
                after = json.dumps(load_project_tasks("receipts"), sort_keys=True)

            self.assertFalse(result["mutated"])
            self.assertEqual(before, after)

    def test_complete_task_flag_completes_only_after_final_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, second, third = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                refused = complete_next_checklist_item(task["task_id"], complete_task=True)
                loaded_refused = load_project_tasks("receipts")["tasks"][0]

            self.assertTrue(refused["task_completion_refused"])
            self.assertFalse(refused["completed_task"])
            self.assertEqual(loaded_refused["status"], "in_progress")

        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                single = add_project_task("receipts", "Single step", priority="high")
                command_projects_task_start(argparse.Namespace(identifier="receipts", task_id=single["task_id"]))
                add_task_checklist_item(single["task_id"], "Only step")
                completed = complete_next_checklist_item(single["task_id"], complete_task=True)
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertTrue(completed["completed_task"])
            self.assertEqual(loaded["status"], "complete")
            self.assertIn("Completed final checklist item and completed task.", loaded["work_log"][-1]["text"])

    def test_active_complete_next_uses_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, _, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                out = self.capture(command_projects_active_complete_next, project=None, log=None, note=None, complete_task=False, json=False)
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertIn(first["item_id"], out)
            self.assertEqual(loaded["checklist"][0]["status"], "complete")

    def test_checklist_history_records_complete_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, _, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                set_task_checklist_status(task["task_id"], first["item_id"], "complete")
                command_projects_task_checklist_reopen(argparse.Namespace(task_id=task["task_id"], item_id=first["item_id"], project=None))
                out = self.capture(command_projects_task_step_history, task_id=task["task_id"], project=None, json=False)
                item = load_project_tasks("receipts")["tasks"][0]["checklist"][0]

            events = [entry["event"] for entry in item["history"]]
            self.assertIn("completed", events)
            self.assertIn("reopened", events)
            self.assertIn("reopened", out)

    def test_old_checklist_items_without_history_are_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            with patch.dict("os.environ", self.env(project_root), clear=False):
                ensure_project_record("Receipts")
                task_path = project_root / "receipts" / "tasks.json"
                task_path.write_text(
                    json.dumps({
                        "project_id": "receipts",
                        "tasks": [{
                            "task_id": "task-old",
                            "title": "Old",
                            "status": "in_progress",
                            "priority": "normal",
                            "checklist": [{"item_id": "check-old", "text": "Old step", "status": "open"}],
                        }],
                    }),
                    encoding="utf-8",
                )
                data = task_next_step_data("task-old")
                result = complete_next_checklist_item("task-old")

            self.assertEqual(data["item_id"], "check-old")
            self.assertTrue(result["mutated"])

    def test_tasks_markdown_updates_checkboxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, _, _ = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                set_task_checklist_status(task["task_id"], first["item_id"], "complete")
                markdown = (project_root / "receipts" / "tasks.md").read_text(encoding="utf-8")

            self.assertIn("- [x] Gather finalized May receipt packets", markdown)
            self.assertIn("- [ ] Link May packets to the Receipts project", markdown)

    def test_briefing_changes_when_checklist_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp) / "projects_registry"
            task, first, second, third = self.make_task(project_root)
            with patch.dict("os.environ", self.env(project_root), clear=False):
                for item in (first, second, third):
                    set_task_checklist_status(task["task_id"], item["item_id"], "complete")
                out = self.capture(command_projects_briefing, identifier=None, json=False)

            self.assertIn("Complete or update receipts/Import May receipts.", out)


if __name__ == "__main__":
    unittest.main()
