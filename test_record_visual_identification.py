import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.projects.appraisal_context import (
    listing_draft_context_path,
    research_path,
    context_path,
)
from core.projects.record_visual_identification import (
    approved_visual_photos,
    candidate_prompt,
    compact_candidate_prompt,
    command_record_identify_confirm,
    command_record_identify_review,
    ensure_transport_health,
    extract_json_object,
    ollama_visual_chat,
    record_identify_visual,
    visual_candidate_markdown_path,
    visual_candidate_path,
    vision_transport_profile,
)
from core.projects.registry import add_cohort_to_project, ensure_project_record
from core.projects.sale_items import (
    assign_role,
    init_sale_item,
    load_sale_item,
    package_photos,
    prepare_photo_edit,
    review_images,
    scan_exports,
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


class RecordVisualIdentificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"LAIA_PROJECT_REGISTRY_ROOT": str(self.root / "projects")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def setup_project(self, project_id="record-002"):
        ensure_project_record(project_id)
        export = self.root / f"{project_id}-export"
        files = export / "files"
        files.mkdir(parents=True)
        for name in ["DSCF7418.JPG", "DSCF7419.JPG"]:
            (files / name).write_bytes((name + "-source").encode())
        add_cohort_to_project(
            project_id,
            {
                "packet_id": "20260610-184234_DSD_sd_ingest",
                "packet_path": str(self.root / "packet"),
                "cohort_id": project_id,
                "cohort_name": project_id,
                "cohort_path": str(self.root / "packet/cohort"),
                "cohort_status": "ready",
                "file_count": 2,
                "artifact_path": str(export),
                "linked_at": "2026-06-17T00:00:00Z",
            },
        )
        init_sale_item(project_id, title="Unidentified Record 002", category="records")

    def approve_front_back(self, project_id="record-002", package=True):
        prepare_photo_edit(project_id)
        assign_role(project_id, "DSCF7418.JPG", "cover_front")
        assign_role(project_id, "DSCF7419.JPG", "cover_back")
        exports = self.root / f"projects/{project_id}/photo_edit/exports"
        for filename in ["DSCF7418", "DSCF7419"]:
            (exports / f"{filename}.jpg").write_bytes(JPEG)
        scan_exports(project_id)
        review_images(project_id, ["DSCF7418.JPG", "DSCF7419.JPG"], "approved")
        if package:
            package_photos(project_id)

    def model_response(self, confidence="low"):
        return json.dumps(
            {
                "artist": "Gino Vannelli",
                "title": "A Pauper In Paradise",
                "label": "A&M Records",
                "catalog_number": "SP-4664",
                "year": "1977",
                "country_or_printing": None,
                "format": "LP",
                "visible_text": ["Gino Vannelli", "A Pauper In Paradise", "A&M Records"],
                "front_cover_observations": ["Front cover text is legible."],
                "back_cover_observations": ["Back cover has label and catalog text."],
                "spine_observations": [],
                "uncertain_text": ["Country is not clear."],
                "confidence": confidence,
            }
        )

    def test_prompt_has_conservative_guardrails(self):
        prompt = candidate_prompt()
        self.assertIn("Do not infer from album art alone", prompt)
        self.assertIn("Do not estimate price", prompt)
        self.assertIn("condition grade", prompt)
        self.assertIn("Return only JSON", prompt)

    def test_compact_prompt_is_available_for_qwen_transport(self):
        prompt = compact_candidate_prompt()
        self.assertIn("Return only compact JSON", prompt)
        self.assertIn("visible_text", prompt)
        self.assertLess(len(prompt), len(candidate_prompt()))

    def test_qwen_transport_profile_resolves_chat_single_image(self):
        with patch("core.projects.record_visual_identification.detected_ollama_models", return_value=(["qwen2.5vl:7b"], None)):
            profile = vision_transport_profile("qwen2.5vl")

        self.assertEqual(profile["resolved_model"], "qwen2.5vl:7b")
        self.assertEqual(profile["endpoint"], "/api/chat")
        self.assertEqual(profile["image_mode"], "single_image_first")
        self.assertEqual(profile["options"]["num_ctx"], 8192)

    def test_health_required_profile_blocks_unhealthy_model(self):
        class FakeHealth:
            def read_health_report(self):
                return {"models": [{"resolved_name": "llama3.2-vision:latest", "healthy": False, "status": "unsupported_architecture"}]}

            def health_rows_by_model(self, report):
                return {"llama3.2-vision:latest": report["models"][0]}

        profile = {
            "model": "llama3.2-vision",
            "resolved_model": "llama3.2-vision:latest",
            "health_required": True,
        }

        with patch("core.projects.record_visual_identification.ollama_health_module", return_value=FakeHealth()):
            with self.assertRaises(RuntimeError) as raised:
                ensure_transport_health(profile)

        self.assertIn("unsupported_architecture", str(raised.exception))

    def test_extract_json_object_accepts_json_like_literal(self):
        parsed = extract_json_object("```json\n{'artist': 'A', 'title': 'B', 'confidence': 'low'}\n```")

        self.assertEqual(parsed["artist"], "A")
        self.assertEqual(parsed["title"], "B")

    def test_finds_approved_packaged_cover_front_and_back(self):
        self.setup_project()
        self.approve_front_back()

        photos = approved_visual_photos("record-002")

        self.assertEqual(photos["cover_front"][0]["filename"], "DSCF7418.JPG")
        self.assertEqual(photos["cover_back"][0]["filename"], "DSCF7419.JPG")
        self.assertTrue(Path(photos["cover_front"][0]["path"]).is_file())

    def test_writes_candidate_files_without_updating_sale_item(self):
        self.setup_project()
        self.approve_front_back()
        before = load_sale_item("record-002")

        candidate, paths = record_identify_visual(
            "record-002",
            runner=lambda model, prompt, images: self.model_response(),
        )
        after = load_sale_item("record-002")

        self.assertEqual(before["title"], after["title"])
        self.assertEqual(after["title"], "Unidentified Record 002")
        self.assertEqual(candidate["authority"], "unconfirmed_ai_candidate")
        self.assertEqual(candidate["review"]["review_status"], "pending")
        self.assertTrue(Path(paths["json"]).is_file())
        self.assertTrue(Path(paths["md"]).is_file())
        self.assertTrue(visual_candidate_path("record-002").is_file())
        self.assertTrue(visual_candidate_markdown_path("record-002").is_file())

    def test_llava_default_transport_keeps_full_prompt_and_two_images(self):
        self.setup_project()
        self.approve_front_back()
        captured = {}

        def runner(model, prompt, images):
            captured["model"] = model
            captured["prompt"] = prompt
            captured["images"] = images
            return self.model_response()

        candidate, _paths = record_identify_visual("record-002", model="llava:latest", runner=runner)

        self.assertEqual(captured["model"], "llava:latest")
        self.assertEqual(captured["prompt"], candidate_prompt())
        self.assertEqual(len(captured["images"]), 2)
        self.assertEqual(candidate["prompt_version"], "record_identity_v1")
        self.assertEqual(candidate["transport_profile"]["endpoint"], "/api/generate")

    def test_qwen_record_identify_uses_compact_chat_profile_and_front_image(self):
        self.setup_project()
        self.approve_front_back()
        captured = {}

        def runner(model, prompt, images):
            captured["model"] = model
            captured["prompt"] = prompt
            captured["images"] = images
            return self.model_response("medium")

        with patch("core.projects.record_visual_identification.detected_ollama_models", return_value=(["qwen2.5vl:7b"], None)):
            candidate, _paths = record_identify_visual("record-002", model="qwen2.5vl", runner=runner)

        self.assertEqual(captured["model"], "qwen2.5vl:7b")
        self.assertEqual(captured["prompt"], compact_candidate_prompt())
        self.assertEqual(len(captured["images"]), 1)
        self.assertEqual(candidate["model"], "qwen2.5vl")
        self.assertEqual(candidate["resolved_model"], "qwen2.5vl:7b")
        self.assertEqual(candidate["prompt_version"], "record_identity_compact_v1")
        self.assertEqual(candidate["transport_profile"]["endpoint"], "/api/chat")
        self.assertEqual(candidate["transport_profile"]["options"]["num_ctx"], 8192)

    def test_ollama_visual_chat_sends_chat_payload_with_options(self):
        image_path = self.root / "front.jpg"
        image_path.write_bytes(JPEG)
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({"message": {"content": "{\"artist\":\"A\"}"}}).encode("utf-8")

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return Response()

        with patch("core.projects.record_visual_identification.ollama_host", return_value="http://127.0.0.1:11434"):
            with patch("core.projects.record_visual_identification.urllib.request.urlopen", side_effect=fake_urlopen):
                response = ollama_visual_chat("qwen2.5vl:7b", "prompt", [image_path], {"num_ctx": 8192})

        self.assertEqual(response, "{\"artist\":\"A\"}")
        self.assertEqual(captured["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(captured["payload"]["model"], "qwen2.5vl:7b")
        self.assertEqual(captured["payload"]["options"]["num_ctx"], 8192)
        self.assertEqual(len(captured["payload"]["messages"][0]["images"]), 1)

    def test_nested_visible_text_response_is_salvaged(self):
        self.setup_project()
        self.approve_front_back()
        nested = json.dumps(
            {
                "artist": None,
                "title": None,
                "format": "vinyl",
                "visible_text": {
                    "front_cover_observations": ["Handwritten GEORGE BENN text is visible."],
                    "back_cover_observations": ["IN FLIGHT appears on the back cover."],
                    "front_cover": {"text": ["GEORGE BENN"]},
                    "confidence": "low",
                },
            }
        )

        candidate, _paths = record_identify_visual(
            "record-002",
            runner=lambda model, prompt, images: nested,
        )

        self.assertEqual(candidate["candidate_identity"]["format"], "LP")
        self.assertEqual(candidate["candidate_identity"]["visible_text"], ["GEORGE BENN"])
        self.assertEqual(candidate["evidence"]["front_cover_observations"], ["Handwritten GEORGE BENN text is visible."])
        self.assertEqual(candidate["evidence"]["back_cover_observations"], ["IN FLIGHT appears on the back cover."])

    def test_review_command_shows_current_and_candidate_identity(self):
        self.setup_project()
        self.approve_front_back()
        record_identify_visual("record-002", runner=lambda model, prompt, images: self.model_response())
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            command_record_identify_review(type("Args", (), {"identifier": "record-002"})())

        text = output.getvalue()
        self.assertIn("Current confirmed identity:", text)
        self.assertIn("Title: Unidentified Record 002", text)
        self.assertIn("AI candidate:", text)
        self.assertIn("Gino Vannelli", text)

    def test_low_confidence_use_candidate_requires_allow_low_confidence(self):
        self.setup_project()
        self.approve_front_back()
        record_identify_visual("record-002", runner=lambda model, prompt, images: self.model_response("low"))
        args = type(
            "Args",
            (),
            {
                "identifier": "record-002",
                "use_candidate": True,
                "allow_low_confidence": False,
                "artist": None,
                "title": None,
                "label": "",
                "catalog_number": "",
                "year": "",
                "note": "",
                "json": False,
            },
        )()

        with self.assertRaises(SystemExit) as raised:
            command_record_identify_confirm(args)

        self.assertIn("--allow-low-confidence", str(raised.exception))

    def test_confirm_use_candidate_updates_sale_item_and_regenerates_outputs(self):
        self.setup_project()
        self.approve_front_back()
        record_identify_visual("record-002", runner=lambda model, prompt, images: self.model_response("medium"))
        args = type(
            "Args",
            (),
            {
                "identifier": "record-002",
                "use_candidate": True,
                "allow_low_confidence": False,
                "artist": None,
                "title": None,
                "label": "",
                "catalog_number": "",
                "year": "",
                "note": "Confirmed from human review of approved photos.",
                "json": False,
            },
        )()

        with contextlib.redirect_stdout(io.StringIO()):
            command_record_identify_confirm(args)

        item = load_sale_item("record-002")
        candidate = json.loads(visual_candidate_path("record-002").read_text())
        research = json.loads(research_path("record-002").read_text())
        self.assertEqual(item["title"], "Gino Vannelli - A Pauper In Paradise")
        self.assertEqual(item["record_metadata"]["artist"], "Gino Vannelli")
        self.assertEqual(item["record_metadata"]["record_label"], "A&M Records")
        self.assertEqual(item["record_metadata"]["catalog_number"], "SP-4664")
        self.assertEqual(candidate["review"]["review_status"], "confirmed")
        self.assertTrue(research["manual_notes"])
        self.assertTrue(context_path("record-002").is_file())
        self.assertTrue(listing_draft_context_path("record-002").is_file())

    def test_manual_correction_marks_candidate_corrected(self):
        self.setup_project()
        self.approve_front_back()
        record_identify_visual("record-002", runner=lambda model, prompt, images: self.model_response("low"))
        args = type(
            "Args",
            (),
            {
                "identifier": "record-002",
                "use_candidate": False,
                "allow_low_confidence": False,
                "artist": "Correct Artist",
                "title": "Correct Title",
                "label": "Correct Label",
                "catalog_number": "ABC-123",
                "year": "1978",
                "note": "Human corrected LLaVA candidate after reviewing approved photos.",
                "json": False,
            },
        )()

        with contextlib.redirect_stdout(io.StringIO()):
            command_record_identify_confirm(args)

        item = load_sale_item("record-002")
        candidate = json.loads(visual_candidate_path("record-002").read_text())
        self.assertEqual(item["title"], "Correct Artist - Correct Title")
        self.assertEqual(candidate["review"]["review_status"], "corrected")
        self.assertEqual(candidate["review"]["corrections"]["artist"], "Correct Artist")

    def test_fails_cleanly_without_approved_photos(self):
        self.setup_project()

        with self.assertRaises(FileNotFoundError) as raised:
            approved_visual_photos("record-002")

        self.assertIn("No approved cover_front/cover_back photos found", str(raised.exception))

    def test_fails_cleanly_when_llava_unavailable(self):
        self.setup_project()
        self.approve_front_back()

        with self.assertRaises(RuntimeError) as raised:
            record_identify_visual(
                "record-002",
                runner=lambda model, prompt, images: (_ for _ in ()).throw(RuntimeError("Ollama/LLaVA unavailable: refused")),
            )

        self.assertIn("Ollama/LLaVA unavailable", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
