import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.record_identity_evidence import add_record_identity_evidence
from core.projects.record_visual_identification import (
    build_visual_model_comparison,
    command_record_identify_visual,
    command_vision_models,
    evaluate_all_candidate_runs,
    list_candidate_runs,
    record_identification_evaluation_with_paths,
    record_identify_visual,
    run_candidate_path,
    run_evaluation_path,
    run_raw_response_path,
    visual_candidate_path,
)
from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    init_sale_item,
    package_photos,
    prepare_photo_edit,
    review_images,
    scan_exports,
    update_sale_item,
)


JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/"
    "9oADAMBAAIQAxAAAAEf/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAA"
    "AAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABAf/8QA"
    "FBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPxB//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxB//8QA"
    "FBABAQAAAAAAAAAAAAAAAAAAABH/2gAIAQEAAT8QH//Z"
)


class VisionModelComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def setup_project(self, project_id="record-003"):
        ensure_project_record(project_id)
        export = self.root / f"{project_id}-export"
        files = export / "files"
        files.mkdir(parents=True)
        for name in ["DSCF7420.JPG", "DSCF7421.JPG"]:
            (files / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            project_id,
            {
                "packet_id": "packet-one",
                "cohort_id": project_id,
                "cohort_status": "ready",
                "file_count": 2,
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item(project_id, title="Earth, Wind & Fire - Spirit", category="records")
        update_sale_item(
            project_id,
            title="Earth, Wind & Fire - Spirit",
            category="records",
            functional_status="not_applicable",
            record_artist="Earth, Wind & Fire",
            record_title="Spirit",
            record_label="Columbia",
            catalog_number="PC 34241",
        )
        self.approve_front_back(project_id)
        add_record_identity_evidence(
            project_id,
            field="catalog_number",
            value="PC 34241",
            source_type="physical_inspection",
            visibility="not_readable_in_current_photos",
            confidence="confirmed",
            note="Confirmed by physically holding the record.",
        )

    def approve_front_back(self, project_id="record-003"):
        prepare_photo_edit(project_id)
        assign_role(project_id, "DSCF7420.JPG", "cover_front")
        assign_role(project_id, "DSCF7421.JPG", "cover_back")
        exports = self.root / f"projects/{project_id}/photo_edit/exports"
        for filename in ["DSCF7420", "DSCF7421"]:
            (exports / f"{filename}.jpg").write_bytes(JPEG)
        scan_exports(project_id)
        review_images(project_id, ["DSCF7420.JPG", "DSCF7421.JPG"], "approved")
        package_photos(project_id)

    def response(self, **values):
        payload = {
            "artist": values.get("artist"),
            "title": values.get("title"),
            "label": values.get("label"),
            "catalog_number": values.get("catalog_number"),
            "format": "LP",
            "visible_text": values.get("visible_text", []),
            "front_cover_observations": [],
            "back_cover_observations": [],
            "spine_observations": [],
            "uncertain_text": [],
            "confidence": values.get("confidence", "low"),
        }
        return json.dumps(payload)

    def test_model_run_writes_run_directory(self):
        self.setup_project()

        candidate, paths = record_identify_visual(
            "record-003",
            model="llava:latest",
            runner=lambda model, prompt, images: self.response(title="Earth Wind & Fire"),
        )

        run_id = candidate["run_id"]
        self.assertTrue(run_candidate_path("record-003", run_id).is_file())
        self.assertTrue(run_raw_response_path("record-003", run_id).is_file())
        self.assertEqual(paths["run"]["run_id"], run_id)

    def test_current_candidate_not_overwritten_without_set_current(self):
        self.setup_project()
        first, _paths = record_identify_visual(
            "record-003",
            model="llava:latest",
            runner=lambda model, prompt, images: self.response(title="First"),
        )
        second, _paths = record_identify_visual(
            "record-003",
            model="qwen2.5vl",
            runner=lambda model, prompt, images: self.response(title="Second"),
        )

        current = json.loads(visual_candidate_path("record-003").read_text())
        self.assertEqual(current["run_id"], first["run_id"])
        self.assertNotEqual(first["run_id"], second["run_id"])

    def test_set_current_replaces_current_candidate(self):
        self.setup_project()
        record_identify_visual("record-003", model="llava:latest", runner=lambda model, prompt, images: self.response(title="First"))
        second, _paths = record_identify_visual(
            "record-003",
            model="qwen2.5vl",
            runner=lambda model, prompt, images: self.response(title="Second"),
            set_current=True,
        )

        current = json.loads(visual_candidate_path("record-003").read_text())
        self.assertEqual(current["run_id"], second["run_id"])

    def test_per_run_evaluation_and_evaluate_all(self):
        self.setup_project()
        first, _paths = record_identify_visual("record-003", model="llava:latest", runner=lambda model, prompt, images: self.response(title="Earth Wind & Fire"))
        second, _paths = record_identify_visual(
            "record-003",
            model="qwen2.5vl",
            runner=lambda model, prompt, images: self.response(artist="Earth, Wind & Fire", title="Spirit", label="Columbia", confidence="medium"),
        )

        evaluation, paths = record_identification_evaluation_with_paths("record-003", first["run_id"])
        all_result = evaluate_all_candidate_runs("record-003")

        self.assertTrue(Path(paths["json"]).is_file())
        self.assertTrue(run_evaluation_path("record-003", first["run_id"]).is_file())
        self.assertTrue(run_evaluation_path("record-003", second["run_id"]).is_file())
        self.assertEqual(len(all_result["evaluated"]), 2)
        self.assertIn("catalog_number_missing_not_readable", evaluation["failure_modes"])

    def test_comparison_lists_multiple_runs_and_best_model(self):
        self.setup_project()
        record_identify_visual("record-003", model="llava:latest", runner=lambda model, prompt, images: self.response(title="Earth Wind & Fire"))
        record_identify_visual(
            "record-003",
            model="qwen2.5vl",
            runner=lambda model, prompt, images: self.response(artist="Earth, Wind & Fire", title="Spirit", label="Columbia", confidence="medium"),
        )
        evaluate_all_candidate_runs("record-003")

        comparison = build_visual_model_comparison("record-003")

        self.assertEqual(len(comparison["runs"]), 2)
        self.assertEqual(comparison["best_current_use"]["broad_identity"], "qwen2.5vl")
        self.assertEqual(comparison["runs"][0]["field_results"]["catalog_number"], "missing_not_readable")

    def test_comparison_handles_only_one_model(self):
        self.setup_project()
        record_identify_visual("record-003", model="llava:latest", runner=lambda model, prompt, images: self.response(title="Earth Wind & Fire"))

        comparison = build_visual_model_comparison("record-003")

        self.assertEqual(len(comparison["runs"]), 1)

    def test_unknown_model_records_warning(self):
        self.setup_project()

        candidate, _paths = record_identify_visual(
            "record-003",
            model="unknown-vision",
            runner=lambda model, prompt, images: self.response(title="Spirit"),
        )

        self.assertIn("Model is not in the LAIA vision registry.", candidate["evidence"]["warnings"])

    def test_ollama_unavailable_fails_cleanly(self):
        self.setup_project()
        args = type(
            "Args",
            (),
            {
                "identifier": "record-003",
                "model": "llava:latest",
                "input_strategy": "approved_photos",
                "prompt_version": "record_identity_v1",
                "set_current": False,
                "json": False,
            },
        )()

        with patch("core.projects.record_visual_identification.ollama_visual_generate", side_effect=RuntimeError("Ollama/LLaVA unavailable: refused")):
            with self.assertRaises(SystemExit) as raised:
                command_record_identify_visual(args)

        self.assertIn("Ollama/LLaVA unavailable", str(raised.exception))

    def test_vision_models_command_json(self):
        output = io.StringIO()

        with patch("core.projects.record_visual_identification.detected_ollama_models", return_value=(["llava:latest"], None)):
            with contextlib.redirect_stdout(output):
                command_vision_models(type("Args", (), {"json": True})())

        data = json.loads(output.getvalue())
        self.assertEqual(data["detected"], ["llava:latest"])

    def test_existing_llava_command_backward_compatible_when_no_current(self):
        self.setup_project()

        candidate, _paths = record_identify_visual(
            "record-003",
            runner=lambda model, prompt, images: self.response(title="Spirit"),
        )

        current = json.loads(visual_candidate_path("record-003").read_text())
        self.assertEqual(current["run_id"], candidate["run_id"])
        self.assertEqual(list_candidate_runs("record-003")[0]["model"], "llava:latest")


if __name__ == "__main__":
    unittest.main()
