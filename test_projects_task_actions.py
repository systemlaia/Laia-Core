import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.packets.registry import PacketRoot, scan_roots
from core.packets.standard import write_packet_manifest
from core.projects.registry import (
    active_run_next_action,
    add_project_task,
    add_task_checklist_item,
    checklist_action_data,
    clear_checklist_action,
    command_projects_active_run_next,
    command_projects_briefing,
    command_projects_reconciliation,
    command_projects_task_context,
    command_projects_task_run_next,
    command_projects_task_run_step,
    command_projects_task_step_action,
    command_projects_task_step_action_history,
    command_projects_task_step_action_set,
    ensure_project_record,
    load_project_artifacts,
    load_project_notes,
    load_project_packets,
    load_project_tasks,
    run_checklist_action,
    run_next_checklist_action,
    set_checklist_action,
    set_project_task_status,
    task_context_data,
)


class ProjectTaskActionTests(unittest.TestCase):
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

    def make_task(self, root, *, project="Receipts", task_status="in_progress"):
        with patch.dict("os.environ", self.env(root), clear=False):
            ensure_project_record(project)
            task = add_project_task("receipts", "Import May receipts", priority="high")
            if task_status != "open":
                set_project_task_status("receipts", task["task_id"], task_status)
            item = add_task_checklist_item(task["task_id"], "Link May packets")
            task = load_project_tasks("receipts")["tasks"][0]
        return task, item

    def make_packet(self, root, job_id="packet-one"):
        packet = root / "packets" / "2026" / job_id
        for name in ["originals", "metadata", "logs"]:
            (packet / name).mkdir(parents=True, exist_ok=True)
        (packet / "originals" / "one.jpg").write_bytes(b"one")
        (packet / "checksums.sha256").write_text("a" * 64 + "  ./originals/one.jpg\n", encoding="utf-8")
        (packet / "ingest_report.md").write_text("# report\n", encoding="utf-8")
        write_packet_manifest(
            packet,
            {
                "packet_type": "laia.photo_ingest",
                "packet_version": "0.1",
                "job_id": job_id,
                "source": "card",
                "packet_path": str(packet),
                "asset_count": 1,
                "photo_count": 1,
                "created_at": "2026-06-10T18:42:34Z",
            },
        )
        scan_roots(root / "packet_registry.db", [PacketRoot("photo_ingest", root / "packets")])
        return packet

    def make_paper_receipt_packet(self, root, job_id, *, total="5.99", correction_total=None, merchant="VONS"):
        packet = root / "paper" / "2026" / job_id
        for name in ["originals", "metadata", "logs", "review", "extract"]:
            (packet / name).mkdir(parents=True, exist_ok=True)
        (packet / "originals" / "page.tif").write_bytes(b"paper")
        (packet / "checksums.sha256").write_text("b" * 64 + "  ./originals/page.tif\n", encoding="utf-8")
        (packet / "ingest_report.md").write_text("# report\n", encoding="utf-8")
        write_packet_manifest(
            packet,
            {
                "packet_type": "laia.paper_ingest",
                "packet_version": "0.1",
                "job_id": job_id,
                "source": "scanner",
                "packet_path": str(packet),
                "asset_count": 1,
                "page_count": 1,
                "created_at": "2026-06-08T11:26:04Z",
            },
        )
        extraction = {
            "packet_id": job_id,
            "fields": {
                "merchant": merchant,
                "transaction_date": "2026-04-28",
                "subtotal": "4.50",
                "tax": "0.49",
                "tip": None,
                "total": total,
                "currency": "USD",
            },
            "warnings": [],
        }
        (packet / "extract" / "extract.json").write_text(json.dumps(extraction), encoding="utf-8")
        if correction_total is not None:
            correction = {"corrections": {"total": {"original": total, "corrected": correction_total}}}
            (packet / "extract" / "correction.json").write_text(json.dumps(correction), encoding="utf-8")
        scan_roots(root / "packet_registry.db", [PacketRoot("paper_ingest", root / "paper")])
        return packet

    def test_action_set_show_and_clear_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "task_log", {"text": "Did work"})
                data = checklist_action_data(task["task_id"], item["item_id"])
                self.assertEqual(data["item"]["action"]["action_type"], "task_log")
                clear_checklist_action(task["task_id"], item["item_id"])
                cleared = checklist_action_data(task["task_id"], item["item_id"])

            self.assertIsNone(cleared["item"]["action"])
            self.assertEqual(cleared["item"]["action_status"], "none")
            self.assertEqual([event["event"] for event in cleared["item"]["action_history"]], ["configured", "cleared"])

    def test_command_set_and_show_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                out = self.capture(
                    command_projects_task_step_action_set,
                    task_id=task["task_id"],
                    item_id=item["item_id"],
                    type="task_log",
                    params_json='{"text":"Logged"}',
                    project=None,
                    json=False,
                )
                shown = self.capture(command_projects_task_step_action, task_id=task["task_id"], item_id=item["item_id"], project=None, json=False)

            self.assertIn("action_type: task_log", out)
            self.assertIn("action_status: configured", shown)

    def test_dry_run_has_no_side_effects_or_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "task_log", {"text": "Should not write"})
                before = json.dumps(load_project_tasks("receipts"), sort_keys=True)
                result = run_checklist_action(task["task_id"], item["item_id"], dry_run=True)
                after = json.dumps(load_project_tasks("receipts"), sort_keys=True)

            self.assertEqual(result["result"]["status"], "dry_run")
            self.assertEqual(before, after)

    def test_task_log_executes_and_completes_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "task_log", {"text": "Imported receipts"})
                result = run_checklist_action(task["task_id"], item["item_id"])
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(result["result"]["status"], "executed")
            self.assertTrue(result["completed_item"])
            self.assertEqual(loaded["checklist"][0]["status"], "complete")
            self.assertIn("Imported receipts", "\n".join(log["text"] for log in loaded["work_log"]))
            self.assertIn("Executed checklist action task_log", loaded["work_log"][-1]["text"])

    def test_manual_action_reports_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "manual", {})
                result = run_checklist_action(task["task_id"], item["item_id"])
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertFalse(result["mutated"])
            self.assertEqual(loaded["checklist"][0]["status"], "open")

    def test_project_note_action_adds_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "project_note", {"project": "receipts", "text": "Ready for bookkeeping"})
                run_checklist_action(task["task_id"], item["item_id"])
                notes = load_project_notes("receipts")["notes"]

            self.assertEqual(notes[0]["text"], "Ready for bookkeeping")

    def test_checklist_complete_action_completes_target_not_self(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, first = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                second = add_task_checklist_item(task["task_id"], "Target")
                set_checklist_action(task["task_id"], first["item_id"], "checklist_complete", {"target_item_id": second["item_id"]})
                result = run_checklist_action(task["task_id"], first["item_id"], complete_on_success=False)
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(result["result"]["status"], "executed")
            self.assertEqual(loaded["checklist"][0]["status"], "open")
            self.assertEqual(loaded["checklist"][1]["status"], "complete")

    def test_checklist_complete_refuses_self_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "checklist_complete", {"target_item_id": item["item_id"]})
                result = run_checklist_action(task["task_id"], item["item_id"])
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(result["result"]["status"], "failed")
            self.assertEqual(loaded["checklist"][0]["status"], "open")

    def test_artifact_link_action_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "outputs" / "handoff.md"
            artifact.parent.mkdir()
            artifact.write_text("handoff", encoding="utf-8")
            task, first = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                second = add_task_checklist_item(task["task_id"], "Link again")
                params = {"project": "receipts", "artifact_paths": [str(artifact)], "source_packet_id": "packet-one", "artifact_type": "handoff"}
                set_checklist_action(task["task_id"], first["item_id"], "artifact_link", params)
                set_checklist_action(task["task_id"], second["item_id"], "artifact_link", params)
                run_checklist_action(task["task_id"], first["item_id"])
                run_checklist_action(task["task_id"], second["item_id"])
                artifacts = load_project_artifacts("receipts")["artifacts"]

            self.assertEqual(len(artifacts), 1)
            self.assertEqual(artifacts[0]["artifact_type"], "handoff")

    def test_packet_link_action_partial_leaves_item_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, "packet-one")
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "packet_link", {"project": "receipts", "packet_ids": ["packet-one", "missing"]})
                result = run_checklist_action(task["task_id"], item["item_id"])
                loaded = load_project_tasks("receipts")["tasks"][0]
                packets = load_project_packets("receipts")["packets"]

            self.assertEqual(result["result"]["status"], "partial")
            self.assertEqual(loaded["checklist"][0]["status"], "open")
            self.assertEqual(len(packets), 1)

    def test_registry_scan_and_lifecycle_export_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, "packet-one")
            (root / "packet_registry.db").unlink()
            task, first = self.make_task(root)
            export_root = root / "lifecycles"
            with patch.dict("os.environ", self.env(root), clear=False):
                second = add_task_checklist_item(task["task_id"], "Export lifecycle")
                set_checklist_action(task["task_id"], first["item_id"], "registry_scan", {"roots": [str(root / "packets")]})
                scan_result = run_checklist_action(task["task_id"], first["item_id"])
                set_checklist_action(task["task_id"], second["item_id"], "lifecycle_export", {"packet_ids": ["packet-one"], "format": "both", "output_root": str(export_root)})
                export_result = run_checklist_action(task["task_id"], second["item_id"])

            self.assertEqual(scan_result["result"]["status"], "executed")
            self.assertEqual(export_result["result"]["status"], "executed")
            self.assertTrue((export_root / "packet-one" / "lifecycle_report.md").exists())
            self.assertTrue((export_root / "packet-one" / "lifecycle_report.json").exists())

    def test_receipt_reconcile_corrected_total_overrides_raw_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_paper_receipt_packet(root, "receipt-one", total="5.99", correction_total="4.99")
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                params = {"project": "receipts", "packet_ids": ["receipt-one"], "currency": "USD", "output_name": "may-receipt-reconciliation"}
                set_checklist_action(task["task_id"], item["item_id"], "receipt_reconcile", params)
                result = run_checklist_action(task["task_id"], item["item_id"])
                report_path = root / "projects_registry" / "receipts" / "reconciliation" / "may-receipt-reconciliation.json"
                md_path = report_path.with_suffix(".md")
                report = json.loads(report_path.read_text(encoding="utf-8"))
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(result["result"]["status"], "executed")
            self.assertEqual(report["grand_total"], "4.99")
            self.assertEqual(report["receipts"][0]["total"], "4.99")
            self.assertEqual(report["receipts"][0]["value_source"], "corrected")
            self.assertTrue(md_path.exists())
            self.assertEqual(loaded["checklist"][0]["status"], "complete")
            self.assertIn("Reconciled 1 receipt packets. Grand total: $4.99.", loaded["work_log"][-1]["text"])

    def test_receipt_reconcile_uses_raw_total_without_correction_and_sums_decimals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_paper_receipt_packet(root, "receipt-one", total="4.99")
            self.make_paper_receipt_packet(root, "receipt-two", total="10.01", merchant="TARGET")
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                params = {"project": "receipts", "packet_ids": ["receipt-one", "receipt-two"], "output_name": "sum"}
                set_checklist_action(task["task_id"], item["item_id"], "receipt_reconcile", params)
                result = run_checklist_action(task["task_id"], item["item_id"])
                report = json.loads((root / "projects_registry" / "receipts" / "reconciliation" / "sum.json").read_text(encoding="utf-8"))

            self.assertEqual(result["result"]["status"], "executed")
            self.assertEqual(report["grand_total"], "15.00")
            self.assertEqual(report["receipts"][0]["value_source"], "raw")

    def test_receipt_reconcile_missing_total_is_partial_and_leaves_item_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_paper_receipt_packet(root, "receipt-one", total=None)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                params = {"project": "receipts", "packet_ids": ["receipt-one"], "output_name": "missing"}
                set_checklist_action(task["task_id"], item["item_id"], "receipt_reconcile", params)
                result = run_checklist_action(task["task_id"], item["item_id"])
                report = json.loads((root / "projects_registry" / "receipts" / "reconciliation" / "missing.json").read_text(encoding="utf-8"))
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(result["result"]["status"], "partial")
            self.assertEqual(report["missing_total_count"], 1)
            self.assertEqual(loaded["checklist"][0]["status"], "open")
            self.assertIn("Receipt reconciliation report created with 1 warnings.", loaded["work_log"][-1]["text"])

    def test_receipt_reconcile_invalid_total_warns_and_inspection_command_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_paper_receipt_packet(root, "receipt-one", total="not-money")
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                params = {"project": "receipts", "packet_ids": ["receipt-one"], "output_name": "invalid"}
                set_checklist_action(task["task_id"], item["item_id"], "receipt_reconcile", params)
                result = run_checklist_action(task["task_id"], item["item_id"])
                out = self.capture(command_projects_reconciliation, identifier="receipts", report_name="invalid", json=False)

            self.assertEqual(result["result"]["status"], "partial")
            self.assertIn("invalid_total_count: 1", out)
            self.assertIn("Invalid numeric value", out)

    def test_receipt_reconcile_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_paper_receipt_packet(root, "receipt-one", total="4.99")
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                params = {"project": "receipts", "packet_ids": ["receipt-one"], "output_name": "dry"}
                set_checklist_action(task["task_id"], item["item_id"], "receipt_reconcile", params)
                result = run_checklist_action(task["task_id"], item["item_id"], dry_run=True)

            self.assertEqual(result["result"]["status"], "dry_run")
            self.assertFalse((root / "projects_registry" / "receipts" / "reconciliation").exists())

    def test_receipt_reconcile_fails_when_no_packet_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                params = {"project": "receipts", "packet_ids": ["missing"], "output_name": "fail"}
                set_checklist_action(task["task_id"], item["item_id"], "receipt_reconcile", params)
                result = run_checklist_action(task["task_id"], item["item_id"])
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual(result["result"]["status"], "failed")
            self.assertEqual(loaded["checklist"][0]["status"], "open")
            self.assertFalse((root / "projects_registry" / "receipts" / "reconciliation").exists())

    def test_run_next_and_active_run_next_use_first_open_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, first = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                second = add_task_checklist_item(task["task_id"], "Second")
                set_checklist_action(task["task_id"], first["item_id"], "task_log", {"text": "first"})
                set_checklist_action(task["task_id"], second["item_id"], "task_log", {"text": "second"})
                run_next_checklist_action(task["task_id"])
                active_run_next_action()
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertEqual([item["status"] for item in loaded["checklist"]], ["complete", "complete"])

    def test_unconfigured_run_next_reports_no_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                result = run_next_checklist_action(task["task_id"])
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertFalse(result["mutated"])
            self.assertEqual(result["message"], "No action configured.")
            self.assertEqual(loaded["checklist"][0]["status"], "open")

    def test_commands_run_step_next_active_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "task_log", {"text": "command run"})
                out = self.capture(command_projects_task_run_step, task_id=task["task_id"], item_id=item["item_id"], project=None, dry_run=False, complete_on_success=True, json=False)
                history = self.capture(command_projects_task_step_action_history, task_id=task["task_id"], item_id=item["item_id"], project=None, json=False)

            self.assertIn("status: executed", out)
            self.assertIn("executed", history)

            with tempfile.TemporaryDirectory() as tmp2:
                root2 = Path(tmp2)
                task2, item2 = self.make_task(root2)
                with patch.dict("os.environ", self.env(root2), clear=False):
                    set_checklist_action(task2["task_id"], item2["item_id"], "task_log", {"text": "next"})
                    next_out = self.capture(command_projects_task_run_next, task_id=task2["task_id"], project=None, dry_run=False, complete_on_success=True, json=False)
                    active_out = self.capture(command_projects_active_run_next, project=None, dry_run=True, complete_on_success=True, json=False)
                self.assertIn("status: executed", next_out)
                self.assertIn("No open checklist items", active_out)

    def test_context_and_briefing_are_action_aware(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                set_checklist_action(task["task_id"], item["item_id"], "packet_link", {"project": "receipts", "packet_ids": ["packet-one"]})
                context = task_context_data(task["task_id"])
                context_out = self.capture(command_projects_task_context, task_id=task["task_id"], project=None, json=False)
                briefing = self.capture(command_projects_briefing, identifier=None, json=False)

            self.assertEqual(context["suggested_next_step"], "Run action: packet_link")
            self.assertIn("action: packet_link", context_out)
            self.assertIn("Run packet_link for receipts/Import May receipts.", briefing)

    def test_json_commands_are_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                out = self.capture(
                    command_projects_task_step_action_set,
                    task_id=task["task_id"],
                    item_id=item["item_id"],
                    type="task_log",
                    params_json='{"text":"json"}',
                    project=None,
                    json=True,
                )
                run_out = self.capture(command_projects_task_run_step, task_id=task["task_id"], item_id=item["item_id"], project=None, dry_run=True, complete_on_success=True, json=True)

            self.assertEqual(json.loads(out)["item"]["action"]["action_type"], "task_log")
            self.assertEqual(json.loads(run_out)["result"]["status"], "dry_run")

    def test_invalid_action_parameters_fail_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task, item = self.make_task(root)
            with patch.dict("os.environ", self.env(root), clear=False):
                with self.assertRaises(ValueError):
                    set_checklist_action(task["task_id"], item["item_id"], "packet_link", {"project": "receipts", "packet_ids": "not-list"})
                loaded = load_project_tasks("receipts")["tasks"][0]

            self.assertIsNone(loaded["checklist"][0]["action"])


if __name__ == "__main__":
    unittest.main()
