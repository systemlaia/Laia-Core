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
    bulk_export_completed_task_reports,
    command_projects_briefing,
    command_projects_task_report,
    command_projects_task_report_export,
    command_projects_task_report_files,
    command_projects_task_reports,
    command_projects_task_reports_export,
    completed_task_report_rows,
    ensure_project_record,
    gather_task_report_data,
    load_project_tasks,
    render_task_report_markdown,
    set_project_task_status,
    task_report_files_data,
    write_project_tasks,
    write_task_report,
)


class ProjectTaskReportTests(unittest.TestCase):
    def env(self, root):
        return {
            "LAIA_PROJECT_REGISTRY_ROOT": str(root / "projects_registry"),
            "LAIA_PACKET_REGISTRY_DB": str(root / "packet_registry.db"),
            "LAIA_PACKET_ROOTS": str(root / "unused_packets"),
        }

    def capture(self, func, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            func(argparse.Namespace(**kwargs))
        return output.getvalue()

    def make_completed_task(self, root, *, status="complete", with_actions=True):
        with patch.dict("os.environ", self.env(root), clear=False):
            ensure_project_record("Receipts")
            task = add_project_task("receipts", "Reconcile Canter's Deli receipt", description="Reconcile extracted totals", priority="high")
            set_project_task_status("receipts", task["task_id"], "in_progress")
            add_task_work_note(task["task_id"], "Use corrected receipt total.", project="receipts")
            first = add_task_checklist_item(task["task_id"], "Gather finalized May receipt packets", project="receipts")
            second = add_task_checklist_item(task["task_id"], "Link May packets to the Receipts project", project="receipts")
            third = add_task_checklist_item(task["task_id"], "Reconcile extracted totals", project="receipts")
            add_task_work_log(task["task_id"], "Started reconciliation.", project="receipts")
            tasks_doc = load_project_tasks("receipts")
            task_doc = tasks_doc["tasks"][0]
            task_doc["linked_packets"] = ["2026-06-08_112604_receipts"]
            task_doc["linked_artifacts"] = [str(root / "promoted" / "Receipts")]
            task_doc["artifact_path"] = str(root / "promoted" / "Receipts")
            for item in task_doc["checklist"]:
                item["status"] = "complete" if status == "complete" else item.get("status", "open")
                item["completed_at"] = "2026-06-13T00:00:00Z" if status == "complete" else None
                item.setdefault("history", []).append({"status": item["status"], "timestamp": "2026-06-13T00:00:00Z", "event": "completed"})
            if with_actions:
                task_doc["checklist"][1]["action"] = {"action_type": "packet_link", "parameters": {"project": "receipts", "packet_ids": ["2026-06-08_112604_receipts"]}}
                task_doc["checklist"][1]["action_status"] = "executed"
                task_doc["checklist"][1]["action_result"] = {
                    "status": "executed",
                    "action_type": "packet_link",
                    "started_at": "2026-06-13T00:01:00Z",
                    "completed_at": "2026-06-13T00:01:01Z",
                    "summary": "Linked 1 packet to project receipts.",
                    "details": [{"target": "2026-06-08_112604_receipts", "status": "linked"}],
                }
                task_doc["checklist"][1]["action_history"] = [{"timestamp": "2026-06-13T00:01:01Z", "event": "executed", "action_type": "packet_link", "result": task_doc["checklist"][1]["action_result"], "detail": ""}]
                partial = {
                    "status": "partial",
                    "action_type": "receipt_reconcile",
                    "started_at": "2026-06-13T00:02:00Z",
                    "completed_at": "2026-06-13T00:02:01Z",
                    "summary": "Receipt reconciliation report created with 1 warnings.",
                    "details": [{"json_path": str(root / "reports" / "partial.json"), "md_path": str(root / "reports" / "partial.md"), "packet_count": 1, "grand_total": "0.00", "warnings": ["total missing"]}],
                }
                success = {
                    "status": "executed",
                    "action_type": "receipt_reconcile",
                    "started_at": "2026-06-13T00:03:00Z",
                    "completed_at": "2026-06-13T00:03:01Z",
                    "summary": "Reconciled 1 receipt packets. Grand total: $31.86.",
                    "details": [{"json_path": str(root / "reports" / "final.json"), "md_path": str(root / "reports" / "final.md"), "packet_count": 1, "grand_total": "31.86", "warnings": []}],
                }
                task_doc["checklist"][2]["action"] = {"action_type": "receipt_reconcile", "parameters": {"project": "receipts", "packet_ids": ["2026-06-08_112604_receipts"]}}
                task_doc["checklist"][2]["action_status"] = "executed"
                task_doc["checklist"][2]["action_result"] = success
                task_doc["checklist"][2]["action_history"] = [
                    {"timestamp": "2026-06-13T00:02:01Z", "event": "executed", "action_type": "receipt_reconcile", "result": partial, "detail": ""},
                    {"timestamp": "2026-06-13T00:03:01Z", "event": "executed", "action_type": "receipt_reconcile", "result": success, "detail": ""},
                ]
            task_doc["status"] = status
            task_doc["started_at"] = "2026-06-12T23:58:00Z"
            task_doc["updated_at"] = "2026-06-13T00:05:00Z"
            task_doc["completed_at"] = "2026-06-13T00:05:00Z" if status == "complete" else None
            task_doc["completion_note"] = "Receipt reconciled."
            task_doc["work_log"].append({"log_id": "log-final", "text": "Reconciled 1 receipt packets. Grand total: $31.86.", "created_at": "2026-06-13T00:04:00Z"})
            write_project_tasks("receipts", tasks_doc)
            return task_doc, (first, second, third)

    def test_completed_task_exports_markdown_and_json_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                result = write_task_report(task["task_id"], "receipts")
                report = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
                markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")

            self.assertEqual(result["reports_written"], 2)
            self.assertEqual(report["report_type"], "laia.project_task_report")
            self.assertIn("# LAIA Completed Task Report", markdown)

    def test_report_for_incomplete_task_is_allowed_and_marked_in_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root, status="in_progress", with_actions=False)
            with patch.dict("os.environ", self.env(root), clear=False):
                report = gather_task_report_data(task["task_id"], "receipts")
                markdown = render_task_report_markdown(report)

            self.assertEqual(report["task"]["status"], "in_progress")
            self.assertIn("in_progress - checklist", markdown)

    def test_format_md_and_json_write_only_requested_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                md_dir = root / "md-only"
                json_dir = root / "json-only"
                md_result = write_task_report(task["task_id"], "receipts", "md", str(md_dir))
                json_result = write_task_report(task["task_id"], "receipts", "json", str(json_dir))

            self.assertTrue((md_dir / "task_report.md").exists())
            self.assertFalse((md_dir / "task_report.json").exists())
            self.assertEqual(md_result["reports_written"], 1)
            self.assertTrue((json_dir / "task_report.json").exists())
            self.assertFalse((json_dir / "task_report.md").exists())
            self.assertEqual(json_result["reports_written"], 1)

    def test_custom_output_directory_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            output_dir = root / "custom" / "task"
            with patch.dict("os.environ", self.env(root), clear=False):
                result = write_task_report(task["task_id"], "receipts", output_dir=str(output_dir))

            self.assertEqual(Path(result["output_dir"]), output_dir)
            self.assertTrue((output_dir / "task_report.md").exists())

    def test_bulk_export_includes_only_completed_tasks_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                incomplete = add_project_task("receipts", "Open task")
                result = bulk_export_completed_task_reports("receipts")

            self.assertEqual(result["tasks_exported"], 1)
            self.assertTrue((root / "projects_registry" / "receipts" / "task_reports" / complete["task_id"] / "task_report.json").exists())
            self.assertFalse((root / "projects_registry" / "receipts" / "task_reports" / incomplete["task_id"]).exists())

    def test_json_contains_full_case_file_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                report = gather_task_report_data(task["task_id"], "receipts")

            for key in ["project", "task", "context", "notes", "checklist", "work_log", "actions", "outcomes", "timeline", "summary"]:
                self.assertIn(key, report)
            self.assertEqual(report["checklist"]["complete"], 3)

    def test_markdown_contains_checklist_work_log_actions_outcomes_final_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                text = render_task_report_markdown(gather_task_report_data(task["task_id"], "receipts"))

            self.assertIn("- [x] Reconcile extracted totals", text)
            self.assertIn("## Action History", text)
            self.assertIn("## Work Log", text)
            self.assertIn("## Outcomes", text)
            self.assertIn("Complete - all 3 checklist items finished.", text)

    def test_partial_attempt_and_successful_retry_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                report = gather_task_report_data(task["task_id"], "receipts")
                statuses = [entry["status"] for entry in report["actions"]["entries"]]

            self.assertIn("partial", statuses)
            self.assertIn("executed", statuses)
            self.assertEqual(report["actions"]["partial_attempts"], 1)

    def test_receipt_reconciliation_outcome_includes_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                report = gather_task_report_data(task["task_id"], "receipts")

            self.assertIn("$31.86", report["summary"]["final_result"])
            self.assertEqual(report["outcomes"][-1]["grand_total"], "31.86")

    def test_timeline_is_chronologically_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                report = gather_task_report_data(task["task_id"], "receipts")
                timestamps = [item["timestamp"] for item in report["timeline"]]

            self.assertEqual(timestamps, sorted(timestamps))

    def test_report_generation_does_not_mutate_task_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            task_file = root / "projects_registry" / "receipts" / "tasks.json"
            with patch.dict("os.environ", self.env(root), clear=False):
                before = task_file.read_text(encoding="utf-8")
                gather_task_report_data(task["task_id"], "receipts")
                write_task_report(task["task_id"], "receipts")
                after = task_file.read_text(encoding="utf-8")

            self.assertEqual(before, after)

    def test_legacy_task_without_context_fields_exports_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict("os.environ", self.env(root), clear=False):
                ensure_project_record("Receipts")
                tasks_doc = {
                    "project_id": "receipts",
                    "tasks": [{"task_id": "legacy", "title": "Legacy", "status": "complete", "priority": "normal"}],
                }
                write_project_tasks("receipts", tasks_doc)
                result = write_task_report("legacy", "receipts")

            self.assertTrue(Path(result["json_path"]).exists())

    def test_report_files_handles_existing_and_missing_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                missing = task_report_files_data(task["task_id"], "receipts")
                missing_out = self.capture(command_projects_task_report_files, identifiers=["receipts", task["task_id"]], project=None, json=False)
                write_task_report(task["task_id"], "receipts")
                existing = task_report_files_data(task["task_id"], "receipts")
                existing_out = self.capture(command_projects_task_report_files, identifiers=["receipts", task["task_id"]], project=None, json=False)

            self.assertEqual(missing["json_path"], "")
            self.assertIn("No task reports found.", missing_out)
            self.assertTrue(existing["json_path"])
            self.assertIn("generated_at:", existing_out)

    def test_completed_task_reports_listing_and_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                export_out = self.capture(command_projects_task_report_export, identifiers=["receipts", task["task_id"]], project=None, format="both", output_dir=None, json=False)
                show_out = self.capture(command_projects_task_report, identifiers=[task["task_id"]], project="receipts", json=False)
                rows = completed_task_report_rows("receipts")
                list_out = self.capture(command_projects_task_reports, project="receipts", json=False)

            self.assertIn("reports_written: 2", export_out)
            self.assertIn("final_result:", show_out)
            self.assertEqual(len(rows), 1)
            self.assertIn(task["task_id"], list_out)

    def test_bulk_export_command_supports_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            output_root = root / "exports"
            with patch.dict("os.environ", self.env(root), clear=False):
                out = self.capture(command_projects_task_reports_export, project="receipts", format="json", output_root=str(output_root), json=False)

            self.assertIn("tasks_exported: 1", out)
            self.assertTrue((output_root / "receipts" / task["task_id"] / "task_report.json").exists())

    def test_project_briefing_identifies_missing_and_present_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, _items = self.make_completed_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                before = self.capture(command_projects_briefing, identifier="receipts", json=False)
                write_task_report(task["task_id"], "receipts")
                after = self.capture(command_projects_briefing, identifier="receipts", json=False)

            self.assertIn("missing reports: 1", before)
            self.assertIn("Export completed task reports.", before)
            self.assertIn("missing reports: 0", after)
            self.assertNotIn("Export completed task reports.", after)


if __name__ == "__main__":
    unittest.main()
