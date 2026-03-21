from pathlib import Path
import os
import yaml
import json
import urllib.request


def laia_root() -> Path:
    return Path(os.environ.get("LAIA_ROOT", os.path.expanduser("~/LAIA")))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_yaml(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def core_services_config():
    runtime_path = laia_root() / "core" / "configs" / "core-services.yaml"
    repo_path = repo_root() / "configs" / "core" / "core-services.yaml"

    if runtime_path.exists():
        return load_yaml(runtime_path)
    if repo_path.exists():
        return load_yaml(repo_path)

    raise FileNotFoundError("Missing core services config")


def ollama_host() -> str:
    cfg = core_services_config()
    return cfg["ollama_host"].rstrip("/")


def ollama_generate(model: str, prompt: str) -> str:
    url = f"{ollama_host()}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data.get("response", "").strip()


def clean_note_text(raw_text: str, model: str = "mistral") -> str:
    prompt = f"""You are cleaning a dictated personal note for a system called LAIA.

Task:
- Rewrite the note into clean, readable Markdown.
- Preserve the user's meaning.
- Fix obvious transcription problems.
- Keep it concise but do not remove important details.
- Do not invent facts.
- Do not add commentary.
- Return only the cleaned note body in Markdown.

Raw note:
{raw_text}
"""
    return ollama_generate(model, prompt)


def structure_task(raw_text: str, model: str = "mistral") -> dict:
    prompt = f"""You are turning a rough dictated thought into a task for a system called LAIA.

Return only valid JSON with exactly these keys:
title
notes
priority
time_estimate
energy_type

Rules:
- title: short, actionable, imperative if possible
- notes: 1-3 short sentences, plain text
- priority: one of Critical, High, Medium, Low
- time_estimate: one of 15m, 30m, 1h, 2h, Half Day, Full Day
- energy_type: one of Deep Work, Admin, Errands, Creative, Research, Maintenance
- preserve the user's intent
- do not invent project IDs or dependencies
- no markdown
- no extra keys
- no explanation

Raw input:
{raw_text}
"""
    response = ollama_generate(model, prompt)
    return json.loads(response)
