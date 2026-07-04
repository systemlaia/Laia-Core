import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.core_client import ollama_health
from core.projects import record_visual_identification


class FakeOllamaClient:
    host = "http://127.0.0.1:11434"

    def __init__(self, models=None, generate_text=None, embeddings=None):
        self.models = models or []
        self.generate_text = generate_text or {}
        self.embeddings = embeddings or {}

    def version(self):
        return {"version": "0.31.1"}

    def list_models(self):
        return list(self.models)

    def generate(self, model, prompt, images=None):
        key = (model, bool(images))
        value = self.generate_text.get(key)
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return value
        if images:
            return "LAIA VISION OK"
        return "LAIA_HEALTH_OK"

    def embed(self, model, text):
        value = self.embeddings.get(model)
        if isinstance(value, Exception):
            raise value
        return value if value is not None else [0.1, 0.2]


class BrokenVersionClient(FakeOllamaClient):
    def version(self):
        raise OSError("connection refused")


class OllamaModelHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name) / "runtime"
        self.env = patch.dict(os.environ, {"LAIA_RUNTIME_ROOT": str(self.runtime)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_parse_ollama_list(self):
        text = """NAME                    ID              SIZE      MODIFIED
llava:latest            abc123          4.7 GB    2 weeks ago
qwen2.5vl:7b            def456          5.9 GB    1 day ago
"""
        self.assertEqual(ollama_health.parse_ollama_list(text), ["llava:latest", "qwen2.5vl:7b"])

    def test_normalizes_model_to_latest(self):
        result = ollama_health.resolve_model_name("llava", ["llava:latest"])
        self.assertTrue(result["installed"])
        self.assertEqual(result["resolved"], "llava:latest")
        self.assertEqual(result["resolution"], "matched_latest")

    def test_resolves_single_installed_tag(self):
        result = ollama_health.resolve_model_name("qwen2.5vl", ["qwen2.5vl:7b"])
        self.assertTrue(result["installed"])
        self.assertEqual(result["resolved"], "qwen2.5vl:7b")
        self.assertEqual(result["resolution"], "matched_single_installed_tag")

    def test_detects_ambiguous_installed_tags(self):
        result = ollama_health.resolve_model_name("qwen2.5vl", ["qwen2.5vl:7b", "qwen2.5vl:14b"])
        self.assertFalse(result["installed"])
        self.assertIsNone(result["resolved"])
        self.assertEqual(result["resolution"], "ambiguous_installed_tags")

    def test_classifies_unsupported_architecture_error(self):
        self.assertEqual(
            ollama_health.classify_ollama_error("unknown model architecture: 'mllama'"),
            "unsupported_architecture",
        )

    def test_classifies_missing_runner_binary_as_runtime_error(self):
        self.assertEqual(
            ollama_health.classify_ollama_error("error starting llama-server: llama-server binary not found"),
            "model_runtime_error",
        )

    def test_classifies_unavailable_ollama_server(self):
        report = ollama_health.run_ollama_health(client=BrokenVersionClient(["llava:latest"]))
        self.assertFalse(report["ollama"]["server_available"])
        self.assertEqual(report["models"][0]["error_class"], "ollama_unavailable")

    def test_chat_probe_success(self):
        result = ollama_health.run_chat_probe(FakeOllamaClient(), "qwen2.5:7b")
        self.assertTrue(result["loadable"])
        self.assertTrue(result["healthy"])

    def test_vision_probe_success(self):
        path = self.runtime / "ollama" / "health_probe" / "vision_probe.png"
        result = ollama_health.run_vision_probe(FakeOllamaClient(), "llava:latest", path)
        self.assertTrue(path.is_file())
        self.assertTrue(result["loadable"])
        self.assertTrue(result["healthy"])

    def test_embedding_probe_success(self):
        result = ollama_health.run_embedding_probe(FakeOllamaClient(), "nomic-embed-text:latest")
        self.assertTrue(result["loadable"])
        self.assertTrue(result["healthy"])
        self.assertGreater(result["embedding_dimensions"], 0)

    def test_writes_model_health_json_and_markdown(self):
        client = FakeOllamaClient(
            [
                "llava:latest",
                "llama3.2-vision:latest",
                "qwen2.5vl:7b",
                "qwen2.5:7b",
                "phi4-mini:latest",
                "mistral:latest",
                "llama3:latest",
                "nomic-embed-text:latest",
                "mxbai-embed-large:latest",
            ],
            generate_text={("llama3.2-vision:latest", True): RuntimeError("unknown model architecture: 'mllama'")},
        )
        report = ollama_health.run_ollama_health(client=client, write=True)
        self.assertTrue(ollama_health.health_json_path().is_file())
        self.assertTrue(ollama_health.health_markdown_path().is_file())
        saved = json.loads(ollama_health.health_json_path().read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["installed_models"], 9)
        self.assertEqual(saved["ollama"]["endpoint"], "http://127.0.0.1:11434")
        llama = next(row for row in report["models"] if row["configured_name"] == "llama3.2-vision")
        self.assertEqual(llama["resolved_name"], "llama3.2-vision:latest")
        self.assertEqual(llama["error_class"], "unsupported_architecture")
        self.assertIn("# Ollama Model Health", ollama_health.health_markdown_path().read_text(encoding="utf-8"))

    def test_vision_models_uses_cached_health_file(self):
        report = {
            "checked_at": "2026-07-03T00:00:00Z",
            "models": [
                {
                    "configured_name": "qwen2.5vl",
                    "resolved_name": "qwen2.5vl:7b",
                    "healthy": True,
                    "error_class": None,
                    "recommendation": "Available as document/fine-text vision challenger.",
                    "status": "vision-capable",
                }
            ],
        }
        ollama_health.write_health_report(report)
        with patch.object(record_visual_identification, "detected_ollama_models", return_value=(["qwen2.5vl:7b"], None)):
            data = record_visual_identification.configured_vision_models()
        qwen = next(row for row in data["models"] if row["name"] == "qwen2.5vl")
        self.assertTrue(qwen["installed"])
        self.assertEqual(qwen["resolved_model"], "qwen2.5vl:7b")
        self.assertTrue(qwen["healthy"])
        self.assertEqual(qwen["health_status"], "vision-capable")


if __name__ == "__main__":
    unittest.main()
