import base64
import ast
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional


CONFIDENCE_VALUES = {"low", "medium", "high"}
INPUT_STRATEGIES = {
    "approved_photos",
    "listing_photos",
    "front_cover_crop",
    "back_cover_crop",
    "spine_crop",
    "label_crop",
    "matrix_crop",
    "ocr_text",
}
PROMPT_VERSIONS = {
    "record_identity_v1",
    "record_identity_text_only_v1",
    "record_identity_back_cover_v1",
    "record_catalog_text_v1",
}
VISUAL_WARNINGS = [
    "AI visual identification is not confirmed.",
    "Human review is required before metadata promotion.",
]
VISION_MODEL_REGISTRY = {
    "models": [
        {
            "name": "llava:latest",
            "role": "baseline_general_vision",
            "enabled": True,
            "notes": "Baseline local vision model.",
        },
        {
            "name": "llama3.2-vision",
            "role": "general_vision_candidate",
            "enabled": False,
            "notes": "Enable if installed locally.",
        },
        {
            "name": "qwen2.5vl",
            "role": "text_document_vision_candidate",
            "enabled": False,
            "notes": "Enable if installed locally.",
        },
    ]
}


def registry_module():
    try:
        from projects import registry
    except (ImportError, ModuleNotFoundError):
        from core.projects import registry
    return registry


def sale_items_module():
    try:
        from projects import sale_items
    except (ImportError, ModuleNotFoundError):
        from core.projects import sale_items
    return sale_items


def appraisal_module():
    try:
        from projects import appraisal_context
    except (ImportError, ModuleNotFoundError):
        from core.projects import appraisal_context
    return appraisal_context


def record_identity_evidence_module():
    try:
        from projects import record_identity_evidence
    except (ImportError, ModuleNotFoundError):
        from core.projects import record_identity_evidence
    return record_identity_evidence


def ollama_health_module():
    try:
        from core_client import ollama_health
    except (ImportError, ModuleNotFoundError):
        from core.core_client import ollama_health
    return ollama_health


def ollama_host() -> str:
    try:
        from core_client.ollama import ollama_host as configured_host
    except (ImportError, ModuleNotFoundError):
        from core.core_client.ollama import ollama_host as configured_host
    return configured_host()


def project_id(identifier: str) -> str:
    return registry_module().find_project(identifier)


def project_folder(identifier: str) -> Path:
    return registry_module().project_folder(project_id(identifier))


def identity_candidates_root(identifier: str) -> Path:
    return project_folder(identifier) / "appraisal" / "identity_candidates"


def visual_candidate_path(identifier: str) -> Path:
    return identity_candidates_root(identifier) / "visual_candidate.json"


def visual_candidate_markdown_path(identifier: str) -> Path:
    return identity_candidates_root(identifier) / "visual_candidate.md"


def visual_history_path(identifier: str, timestamp: str) -> Path:
    stamp = timestamp.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    return identity_candidates_root(identifier) / "history" / f"{stamp}_visual_candidate.json"


def evaluation_path(identifier: str) -> Path:
    return identity_candidates_root(identifier) / "evaluation.json"


def evaluation_markdown_path(identifier: str) -> Path:
    return identity_candidates_root(identifier) / "evaluation.md"


def evaluation_history_path(identifier: str, timestamp: str) -> Path:
    stamp = timestamp.replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")
    return identity_candidates_root(identifier) / "history" / f"{stamp}_evaluation.json"


def runs_root(identifier: str) -> Path:
    return identity_candidates_root(identifier) / "runs"


def run_root(identifier: str, run_id: str) -> Path:
    return runs_root(identifier) / run_id


def run_candidate_path(identifier: str, run_id: str) -> Path:
    return run_root(identifier, run_id) / "candidate.json"


def run_candidate_markdown_path(identifier: str, run_id: str) -> Path:
    return run_root(identifier, run_id) / "candidate.md"


def run_raw_response_path(identifier: str, run_id: str) -> Path:
    return run_root(identifier, run_id) / "raw_response.txt"


def run_metadata_path(identifier: str, run_id: str) -> Path:
    return run_root(identifier, run_id) / "run.json"


def run_evaluation_path(identifier: str, run_id: str) -> Path:
    return run_root(identifier, run_id) / "evaluation.json"


def run_evaluation_markdown_path(identifier: str, run_id: str) -> Path:
    return run_root(identifier, run_id) / "evaluation.md"


def read_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}: {exc}")


def candidate_prompt() -> str:
    return """You are inspecting photos of a vinyl record cover for inventory metadata.

Return only JSON.

Identify visible text from the front and back cover. Estimate artist/title/label/catalog/year only if visible. If uncertain, use null and explain in uncertain_text. Do not infer from album art alone. Do not claim pressing, rarity, condition, or value. Human confirmation is required.

Fields:
artist
title
label
catalog_number
year
country_or_printing
format
visible_text
front_cover_observations
back_cover_observations
spine_observations
uncertain_text
confidence

Do not estimate price, condition grade, rarity, pressing, or version unless explicitly visible."""


def model_slug(model: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(model or "model")).strip("-").lower()
    return slug or "model"


def model_family(model: str) -> str:
    return str(model or "").split(":", 1)[0] or "unknown"


def source_for_model(model: str) -> str:
    return "llava" if model_family(model) == "llava" else "vision_model"


def model_is_configured(model: str) -> bool:
    return any(row.get("name") == model for row in VISION_MODEL_REGISTRY["models"])


def timestamp_for_id(value: str) -> str:
    return str(value or "").replace("-", "").replace(":", "").replace("T", "-").replace("Z", "")


def next_run_id(project: str, model: str, generated_at: str) -> str:
    base = f"{model_slug(model)}-{timestamp_for_id(generated_at)}"
    candidate = base
    suffix = 2
    while run_root(project, candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def build_run_metadata(
    project: str,
    run_id: str,
    candidate: dict,
    input_strategy: str,
    prompt_version: str,
) -> dict:
    return {
        "run_id": run_id,
        "project": project,
        "task": "record_identity",
        "model": candidate.get("model"),
        "model_family": model_family(candidate.get("model")),
        "input_strategy": input_strategy,
        "prompt_version": prompt_version,
        "status": "candidate",
        "authority": "unconfirmed_ai_candidate",
        "candidate_path": str(run_candidate_path(project, run_id)),
        "raw_response_path": str(run_raw_response_path(project, run_id)),
        "generated_at": candidate.get("generated_at"),
    }


def detected_ollama_models() -> tuple[list[str], Optional[str]]:
    if not shutil.which("ollama"):
        return [], "ollama command not found"
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], str(exc)
    if result.returncode != 0:
        return [], (result.stderr or result.stdout or "ollama list failed").strip()
    models = []
    for line in (result.stdout or "").splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models, None


def configured_vision_models() -> dict:
    detected, error = detected_ollama_models()
    health = ollama_health_module()
    cached_health = health.read_health_report()
    health_rows = health.health_rows_by_model(cached_health)
    rows = []
    for model in VISION_MODEL_REGISTRY["models"]:
        name = model["name"]
        resolution = health.resolve_model_name(name, detected)
        health_row = health_rows.get(name) or health_rows.get(resolution.get("resolved"))
        installed = bool(resolution.get("installed"))
        rows.append(
            {
                **model,
                "resolved_model": resolution.get("resolved"),
                "resolution": resolution.get("resolution"),
                "installed": installed,
                "available": model.get("enabled") and installed,
                "healthy": health_row.get("healthy") if health_row else None,
                "health_error_class": health_row.get("error_class") if health_row else None,
                "health_recommendation": health_row.get("recommendation") if health_row else None,
                "health_status": health_row.get("status") if health_row else None,
            }
        )
    return {
        "models": rows,
        "detected": detected,
        "error": error,
        "health_path": str(health.health_json_path()),
        "health_available": cached_health is not None,
        "health_checked_at": cached_health.get("checked_at") if cached_health else None,
    }


def command_vision_models(args):
    if getattr(args, "health", False):
        health = ollama_health_module()
        report = health.run_ollama_health(write=False)
        data = configured_vision_models()
        rows_by_model = health.health_rows_by_model(report)
        for model in data["models"]:
            row = rows_by_model.get(model["name"]) or rows_by_model.get(model.get("resolved_model"))
            if row:
                model["healthy"] = row.get("healthy")
                model["health_error_class"] = row.get("error_class")
                model["health_recommendation"] = row.get("recommendation")
                model["health_status"] = row.get("status")
        data["health_available"] = True
        data["health_checked_at"] = report.get("checked_at")
    else:
        data = configured_vision_models()
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print("Vision Models")
    print()
    print("Configured:")
    for model in data["models"]:
        if model.get("healthy") is True:
            state = "enabled / healthy" if model.get("enabled") else "installed / healthy"
        elif model.get("health_status") in {"failed_to_load", "unsupported_architecture"}:
            state = f"installed / {model.get('health_status')}"
        elif model.get("installed"):
            if model.get("resolved_model") and model.get("resolved_model") != model.get("name"):
                state = f"installed as {model.get('resolved_model')}"
            else:
                state = "installed"
        else:
            state = "not installed / disabled"
        resolved = model.get("resolved_model") or "-"
        if model.get("healthy") is True:
            health_state = "healthy"
        elif model.get("healthy") is False:
            health_state = model.get("health_error_class") or "unhealthy"
        else:
            health_state = "health unknown"
        print(f"  {model['name']:20} {model['role']:32} {state:24} resolved={resolved} {health_state}")
    if not data.get("health_available"):
        print()
        print("No cached health report found. Run: laia dev ollama-health --write")
    print()
    print("Detected Ollama models:")
    if data.get("error"):
        print(f"  unavailable: {data['error']}")
    elif data.get("detected"):
        for name in data["detected"]:
            print(f"  {name}")
    else:
        print("  none")


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def ollama_visual_generate(model: str, prompt: str, image_paths: list[Path]) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [encode_image(path) for path in image_paths],
        "stream": False,
    }
    request = urllib.request.Request(
        f"{ollama_host().rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama/LLaVA unavailable: {exc}") from exc
    return str(data.get("response", "")).strip()


def extract_json_object(text: str) -> dict:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("LLaVA response did not contain JSON.")
        obj = match.group(0)
        try:
            return json.loads(obj)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(obj)
            except (SyntaxError, ValueError) as exc:
                raise ValueError(str(exc)) from exc
            if not isinstance(parsed, dict):
                raise ValueError("LLaVA response JSON was not an object.")
            return parsed


def list_value(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        values = []
        for key in ["text", "visible_text"]:
            values.extend(list_value(value.get(key)))
        if values:
            return values
        return []
    return [str(value)]


def string_or_none(value):
    if value in (None, ""):
        return None
    return str(value)


def normalized_confidence(value: str) -> str:
    confidence = str(value or "low").strip().lower()
    return confidence if confidence in CONFIDENCE_VALUES else "low"


def normalized_format(value: str) -> str:
    text = str(value or "").strip()
    return "LP" if text.lower() in {"", "vinyl", "record", "vinyl record"} else text


def source_filename(photo: dict) -> str:
    return (
        photo.get("source_filename")
        or photo.get("workspace_filename")
        or photo.get("work_filename")
        or photo.get("filename")
        or Path(photo.get("path", "")).name
    )


def _listing_photo_rows(project: str) -> list[dict]:
    root = project_folder(project) / "listing" / "photos"
    manifest = read_json(root / "photo_manifest.json", {})
    rows = []
    for photo in manifest.get("photos", []):
        path = Path(photo.get("packaged_path") or root / photo.get("listing_filename", ""))
        rows.append({**photo, "path": str(path), "filename": source_filename(photo)})
    return rows


def _photo_edit_rows(project: str) -> list[dict]:
    sale_items = sale_items_module()
    manifest = sale_items.migrate_edit_manifest(read_json(sale_items.edit_manifest_path(project), {}))
    rows = []
    for image in manifest.get("images", []):
        if image.get("review_status") != "approved":
            continue
        path = Path(image.get("export_path") or "")
        rows.append({**image, "path": str(path), "filename": source_filename(image)})
    return rows


def approved_visual_photos(identifier: str) -> dict:
    project = project_id(identifier)
    for rows in [_listing_photo_rows(project), _photo_edit_rows(project)]:
        selected = {}
        for role in ["cover_front", "cover_back"]:
            matches = [
                row for row in rows
                if row.get("role") == role and Path(row.get("path", "")).is_file()
            ]
            if matches:
                selected[role] = matches
        if selected.get("cover_front") and selected.get("cover_back"):
            return selected
    raise FileNotFoundError("No approved cover_front/cover_back photos found.\nRun photo-edit-approve first.")


def normalize_candidate_response(
    project: str,
    raw: str,
    photos: dict,
    model: str,
    input_strategy: str = "approved_photos",
    prompt_version: str = "record_identity_v1",
) -> dict:
    parsed = extract_json_object(raw)
    nested_visible = parsed.get("visible_text") if isinstance(parsed.get("visible_text"), dict) else {}
    merged = {**nested_visible, **parsed} if nested_visible else parsed
    confidence = normalized_confidence(merged.get("confidence"))
    identity = {
        "artist": string_or_none(merged.get("artist")),
        "title": string_or_none(merged.get("title")),
        "label": string_or_none(merged.get("label")),
        "catalog_number": string_or_none(merged.get("catalog_number")),
        "year": string_or_none(merged.get("year")),
        "country_or_printing": string_or_none(merged.get("country_or_printing")),
        "format": normalized_format(merged.get("format")),
        "visible_text": list_value(merged.get("visible_text")) + list_value(merged.get("front_cover")),
        "confidence": confidence,
    }
    warnings = list(VISUAL_WARNINGS)
    if not model_is_configured(model):
        warnings.append("Model is not in the LAIA vision registry.")
    return {
        "project": project,
        "category": "records",
        "source": source_for_model(model),
        "model": model,
        "input_strategy": input_strategy,
        "prompt_version": prompt_version,
        "status": "candidate",
        "authority": "unconfirmed_ai_candidate",
        "input_photos": {
            "cover_front": [source_filename(photo) for photo in photos["cover_front"]],
            "cover_back": [source_filename(photo) for photo in photos["cover_back"]],
        },
        "candidate_identity": identity,
        "evidence": {
            "front_cover_observations": list_value(merged.get("front_cover_observations")),
            "back_cover_observations": list_value(merged.get("back_cover_observations")),
            "spine_observations": list_value(merged.get("spine_observations")),
            "uncertain_text": list_value(merged.get("uncertain_text")),
            "warnings": warnings,
        },
        "raw_model_response": raw,
        "review": {
            "review_status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "corrections": {},
            "notes": None,
        },
        "generated_at": registry_module().utc_now(),
    }


def render_candidate_markdown(candidate: dict) -> str:
    identity = candidate.get("candidate_identity", {})
    evidence = candidate.get("evidence", {})
    lines = [
        f"# Visual Identity Candidate: {candidate.get('project', '')}",
        "",
        f"Source: {candidate.get('source', '')}  ",
        f"Model: {candidate.get('model', '')}  ",
        f"Status: {candidate.get('status', '')}  ",
        f"Authority: {candidate.get('authority', '')}",
        "",
        "## Input photos",
        "",
    ]
    for role, files in candidate.get("input_photos", {}).items():
        lines.append(f"- {role}: {', '.join(files) if files else '-'}")
    lines.extend(
        [
            "",
            "## Candidate identity",
            "",
            f"- Artist: {identity.get('artist') or '-'}",
            f"- Title: {identity.get('title') or '-'}",
            f"- Label: {identity.get('label') or '-'}",
            f"- Catalog number: {identity.get('catalog_number') or '-'}",
            f"- Year: {identity.get('year') or '-'}",
            f"- Country/printing: {identity.get('country_or_printing') or '-'}",
            f"- Format: {identity.get('format') or '-'}",
            f"- Confidence: {identity.get('confidence') or 'low'}",
            "",
            "## Visible text",
        ]
    )
    lines.extend([f"- {text}" for text in identity.get("visible_text", [])] or ["- none"])
    lines.extend(["", "## Observations", ""])
    for key, label in [
        ("front_cover_observations", "Front cover"),
        ("back_cover_observations", "Back cover"),
        ("spine_observations", "Spine"),
        ("uncertain_text", "Uncertain text"),
    ]:
        lines.append(f"{label}:")
        lines.extend([f"- {text}" for text in evidence.get(key, [])] or ["- none"])
        lines.append("")
    lines.append("## Warnings")
    lines.extend(f"- {warning}" for warning in evidence.get("warnings", VISUAL_WARNINGS))
    lines.append("")
    return "\n".join(lines)


def write_candidate(project: str, candidate: dict) -> dict:
    root = identity_candidates_root(project)
    root.mkdir(parents=True, exist_ok=True)
    (root / "history").mkdir(parents=True, exist_ok=True)
    json_path = visual_candidate_path(project)
    md_path = visual_candidate_markdown_path(project)
    history_path = visual_history_path(project, candidate["generated_at"])
    registry = registry_module()
    registry.write_json(json_path, candidate)
    registry.write_json(history_path, candidate)
    md_path.write_text(render_candidate_markdown(candidate), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path), "history": str(history_path)}


def write_candidate_run(project: str, candidate: dict, raw: str, input_strategy: str, prompt_version: str) -> dict:
    run_id = candidate.get("run_id") or next_run_id(project, candidate.get("model", "model"), candidate["generated_at"])
    candidate["run_id"] = run_id
    run_dir = run_root(project, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = run_candidate_path(project, run_id)
    md_path = run_candidate_markdown_path(project, run_id)
    raw_path = run_raw_response_path(project, run_id)
    metadata_path = run_metadata_path(project, run_id)
    metadata = build_run_metadata(project, run_id, candidate, input_strategy, prompt_version)
    registry = registry_module()
    registry.write_json(candidate_path, candidate)
    registry.write_json(metadata_path, metadata)
    md_path.write_text(render_candidate_markdown(candidate), encoding="utf-8")
    raw_path.write_text(raw, encoding="utf-8")
    return {
        "run_id": run_id,
        "run": str(metadata_path),
        "json": str(candidate_path),
        "md": str(md_path),
        "raw": str(raw_path),
        "metadata": metadata,
    }


def list_candidate_runs(identifier: str) -> list[dict]:
    project = project_id(identifier)
    root = runs_root(project)
    if not root.is_dir():
        return []
    runs = []
    for folder in sorted(root.iterdir(), key=lambda path: path.name):
        if not folder.is_dir():
            continue
        metadata = read_json(folder / "run.json", {})
        if not metadata:
            metadata = {
                "run_id": folder.name,
                "project": project,
                "candidate_path": str(folder / "candidate.json"),
                "generated_at": "",
            }
        metadata.setdefault("run_id", folder.name)
        runs.append(metadata)
    return sorted(runs, key=lambda row: row.get("generated_at", ""))


def read_run_candidate(identifier: str, run_id: str) -> dict:
    path = run_candidate_path(identifier, run_id)
    if not path.is_file():
        raise FileNotFoundError(f"Visual identity candidate run not found: {run_id}")
    return read_json(path)


def record_identify_visual(
    identifier: str,
    model: str = "llava:latest",
    runner: Optional[Callable[[str, str, list[Path]], str]] = None,
    input_strategy: str = "approved_photos",
    prompt_version: str = "record_identity_v1",
    set_current: bool = False,
) -> tuple[dict, dict]:
    project = project_id(identifier)
    if input_strategy not in INPUT_STRATEGIES:
        raise ValueError(f"Invalid input strategy: {input_strategy}")
    if prompt_version not in PROMPT_VERSIONS:
        raise ValueError(f"Invalid prompt version: {prompt_version}")
    photos = approved_visual_photos(project)
    image_paths = [Path(row["path"]) for role in ["cover_front", "cover_back"] for row in photos[role]]
    runner = runner or ollama_visual_generate
    raw = runner(model, candidate_prompt(), image_paths)
    candidate = normalize_candidate_response(project, raw, photos, model, input_strategy, prompt_version)
    run_paths = write_candidate_run(project, candidate, raw, input_strategy, prompt_version)
    paths = {"run": run_paths}
    if set_current or not visual_candidate_path(project).is_file():
        paths["current"] = write_candidate(project, candidate)
        paths.update(paths["current"])
    else:
        paths.update({"json": run_paths["json"], "md": run_paths["md"]})
    return candidate, paths


def read_candidate(identifier: str) -> dict:
    path = visual_candidate_path(identifier)
    if not path.is_file():
        raise FileNotFoundError(f"Visual identity candidate not found: {project_id(identifier)}")
    return read_json(path)


def current_confirmed_identity(identifier: str) -> dict:
    sale_items = sale_items_module()
    item = sale_items.load_sale_item(identifier)
    metadata = item.get("record_metadata", {})
    return {
        "artist": metadata.get("artist") or "",
        "title": metadata.get("title") or item.get("title") or "",
        "label": metadata.get("record_label") or item.get("manufacturer") or "",
        "catalog_number": metadata.get("catalog_number") or item.get("model") or "",
    }


def promotion_values_from_args(args, candidate: dict) -> tuple[dict, str]:
    if getattr(args, "use_candidate", False):
        identity = candidate.get("candidate_identity", {})
        if identity.get("confidence") == "low" and not getattr(args, "allow_low_confidence", False):
            raise ValueError("Low-confidence candidate requires --allow-low-confidence.")
        if not identity.get("artist") or not identity.get("title"):
            raise ValueError("--use-candidate requires candidate artist and title.")
        return {
            "artist": identity.get("artist"),
            "title": identity.get("title"),
            "label": identity.get("label") or "",
            "catalog_number": identity.get("catalog_number") or "",
            "year": identity.get("year") or "",
        }, "confirmed"
    values = {
        "artist": getattr(args, "artist", None) or "",
        "title": getattr(args, "title", None) or "",
        "label": getattr(args, "label", None) or "",
        "catalog_number": getattr(args, "catalog_number", None) or "",
        "year": getattr(args, "year", None) or "",
    }
    if not values["artist"] or not values["title"]:
        raise ValueError("Manual confirmation requires --artist and --title.")
    return values, "corrected"


def mark_candidate_review(project: str, candidate: dict, values: dict, status: str, note: str) -> dict:
    candidate.setdefault("review", {})
    candidate["review"].update(
        {
            "review_status": status,
            "reviewed_by": "human",
            "reviewed_at": registry_module().utc_now(),
            "corrections": values if status == "corrected" else {},
            "notes": note or None,
        }
    )
    write_candidate(project, candidate)
    return candidate


def confirm_record_identity(args) -> dict:
    project = project_id(args.identifier)
    candidate = read_candidate(project)
    values, review_status = promotion_values_from_args(args, candidate)
    sale_items = sale_items_module()
    display_title = f"{values['artist']} - {values['title']}"
    item = sale_items.update_sale_item(
        project,
        title=display_title,
        manufacturer=values.get("label", ""),
        model=values.get("catalog_number", ""),
        category="records",
        functional_status="not_applicable",
        record_artist=values["artist"],
        record_title=values["title"],
        record_label=values.get("label", ""),
        catalog_number=values.get("catalog_number", ""),
    )
    metadata = item.setdefault("record_metadata", {})
    if values.get("year"):
        metadata["year"] = values["year"]
        sale_items.write_sale_item(project, item)
    note = getattr(args, "note", "") or "Human confirmed visual identity candidate."
    appraisal = appraisal_module()
    research_entry, research_paths = appraisal.add_appraisal_research_entry(
        project,
        source="Human review",
        source_type="manual_note",
        note=note,
        confidence="high",
    )
    candidate = mark_candidate_review(project, candidate, values, review_status, note)
    context_paths = appraisal.write_appraisal_context(project)
    research_paths = appraisal.write_appraisal_research(project)
    listing_paths = appraisal.write_listing_draft_context(project)
    return {
        "project": project,
        "status": review_status,
        "sale_item": item,
        "candidate": candidate,
        "research_entry": research_entry,
        "paths": {
            "candidate": str(visual_candidate_path(project)),
            "appraisal_context": context_paths,
            "appraisal_research": research_paths,
            "listing_draft": listing_paths,
        },
    }


def print_candidate_summary(candidate: dict, paths: dict) -> None:
    identity = candidate.get("candidate_identity", {})
    print(f"Record Visual Identification: {candidate.get('project', '')}")
    print(f"Source: {candidate.get('source', '')}")
    print(f"Status: {candidate.get('status', '')}")
    print(f"Authority: {candidate.get('authority', '')}")
    print()
    print("Input photos:")
    for role, files in candidate.get("input_photos", {}).items():
        print(f"  {role}: {', '.join(files) if files else '-'}")
    print()
    print("Candidate identity:")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print(f"  Year: {identity.get('year') or '-'}")
    print(f"  Confidence: {identity.get('confidence') or 'low'}")
    print()
    print("Visible text:")
    for text in identity.get("visible_text", []):
        print(f"  - {text}")
    if not identity.get("visible_text"):
        print("  - none")
    print()
    print("Warnings:")
    for warning in candidate.get("evidence", {}).get("warnings", VISUAL_WARNINGS):
        print(f"  {warning}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def command_record_identify_visual(args):
    try:
        candidate, paths = record_identify_visual(
            args.identifier,
            model=getattr(args, "model", "llava:latest"),
            input_strategy=getattr(args, "input_strategy", "approved_photos"),
            prompt_version=getattr(args, "prompt_version", "record_identity_v1"),
            set_current=getattr(args, "set_current", False),
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(candidate, indent=2))
    else:
        print_candidate_summary(candidate, paths)


def command_record_identify_review(args):
    try:
        candidate = read_candidate(args.identifier)
        confirmed = current_confirmed_identity(args.identifier)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    identity = candidate.get("candidate_identity", {})
    print(f"Record Visual Identification Review: {candidate.get('project', '')}")
    print()
    print("Current confirmed identity:")
    print(f"  Artist: {confirmed.get('artist') or '-'}")
    print(f"  Title: {confirmed.get('title') or '-'}")
    print(f"  Label: {confirmed.get('label') or '-'}")
    print(f"  Catalog number: {confirmed.get('catalog_number') or '-'}")
    print()
    print("AI candidate:")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print(f"  Confidence: {identity.get('confidence') or 'low'}")
    print()
    print("Review options:")
    print("  To confirm:")
    print(f"    laia projects record-identify-confirm {candidate.get('project', '')} --use-candidate")
    print("  To correct:")
    print(f"    laia projects record-identify-confirm {candidate.get('project', '')} \\")
    print('      --artist "..." \\')
    print('      --title "..." \\')
    print('      --label "..." \\')
    print('      --catalog-number "..." \\')
    print('      --note "Corrected after human review."')


def command_record_identify_confirm(args):
    try:
        result = confirm_record_identity(args)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    identity = result["sale_item"].get("record_metadata", {})
    print(f"Record identity {result['status']}: {result['project']}")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('record_label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print()
    print("Regenerated:")
    print(f"  {result['paths']['appraisal_context']['json']}")
    print(f"  {result['paths']['appraisal_research']['json']}")
    print(f"  {result['paths']['listing_draft']['json']}")
    print()
    print("Next:")
    print(f"  laia projects record-identify-evaluate {result['project']}")


def normalize_comparison_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_")
    text = re.sub(r"^(the|a|an)\s+", "", text)
    return text


def comparison_tokens(value: str) -> set[str]:
    stopwords = {"a", "an", "and", "the", "in", "of", "on", "for", "to"}
    return {token for token in normalize_comparison_text(value).split() if token and token not in stopwords}


def compare_identity_field(candidate, confirmed) -> dict:
    candidate_text = string_or_none(candidate)
    confirmed_text = string_or_none(confirmed)
    if not confirmed_text:
        note = "No confirmed value to evaluate."
        if candidate_text:
            note = "Candidate claimed value, but no confirmed value exists yet."
        return {
            "candidate": candidate_text,
            "confirmed": confirmed_text,
            "result": "unconfirmed",
            "note": note,
        }
    if not candidate_text:
        return {
            "candidate": candidate_text,
            "confirmed": confirmed_text,
            "result": "missing",
            "note": "Confirmed value exists, but candidate did not provide this field.",
        }
    normalized_candidate = normalize_comparison_text(candidate_text)
    normalized_confirmed = normalize_comparison_text(confirmed_text)
    if normalized_candidate == normalized_confirmed:
        result = "match"
        note = ""
    elif normalized_candidate in normalized_confirmed or normalized_confirmed in normalized_candidate:
        result = "partial"
        note = "One normalized value contains the other."
    else:
        candidate_tokens = comparison_tokens(candidate_text)
        confirmed_tokens = comparison_tokens(confirmed_text)
        overlap = candidate_tokens & confirmed_tokens
        shorter = max(1, min(len(candidate_tokens), len(confirmed_tokens)))
        if overlap and len(overlap) / shorter >= 0.6:
            result = "partial"
            note = "Most normalized tokens overlap."
        else:
            result = "incorrect"
            note = "Candidate value does not match confirmed metadata."
    return {
        "candidate": candidate_text,
        "confirmed": confirmed_text,
        "result": result,
        "note": note,
    }


def confirmed_record_identity(identifier: str) -> tuple[dict, dict]:
    sale_items = sale_items_module()
    item = sale_items.load_sale_item(identifier)
    if str(item.get("category", "")).strip().lower() != "records":
        raise ValueError("Visual identification evaluation requires a record sale item.")
    metadata = item.get("record_metadata", {})
    identity = {
        "artist": string_or_none(metadata.get("artist")),
        "title": string_or_none(metadata.get("title")),
        "label": string_or_none(metadata.get("record_label") or item.get("manufacturer")),
        "catalog_number": string_or_none(metadata.get("catalog_number") or item.get("model")),
        "year": string_or_none(metadata.get("year")),
    }
    if not identity.get("artist") or not identity.get("title"):
        raise ValueError(
            "No confirmed record identity available.\n"
            "Confirm or correct candidate first:\n"
            f"  laia projects record-identify-confirm {project_id(identifier)} ..."
        )
    return identity, item


def identity_evidence_for_project(identifier: str) -> dict:
    evidence_module = record_identity_evidence_module()
    path = evidence_module.identity_evidence_path(identifier)
    if not path.is_file():
        return {}
    try:
        return evidence_module.read_record_identity_evidence(identifier)
    except (FileNotFoundError, ValueError):
        return {}


def model_expected_to_read(visibility: Optional[str]) -> bool:
    return visibility in {"clearly_visible", "partially_visible"}


def apply_field_evidence_context(field_results: dict, evidence: dict) -> dict:
    if not evidence:
        return field_results
    evidence_module = record_identity_evidence_module()
    for field, result in field_results.items():
        summary = evidence_module.field_evidence_summary(evidence, field)
        if not summary:
            continue
        visibility = summary.get("visibility", "unknown")
        result["source_type"] = summary.get("source_type", "unknown")
        result["source_visibility"] = visibility
        result["model_expected_to_read"] = model_expected_to_read(visibility)
        if result.get("result") == "missing":
            note = summary.get("note") or ""
            if visibility == "not_readable_in_current_photos":
                result["note"] = "Confirmed by physical inspection; not readable in current approved photos."
            elif visibility == "not_photographed":
                result["note"] = "Confirmed by non-image evidence; field is not photographed."
            elif note:
                result["note"] = note
    return field_results


def candidate_identity_for_evaluation(candidate: dict) -> dict:
    identity = candidate.get("candidate_identity", {})
    return {
        "artist": string_or_none(identity.get("artist")),
        "title": string_or_none(identity.get("title")),
        "label": string_or_none(identity.get("label")),
        "catalog_number": string_or_none(identity.get("catalog_number")),
        "year": string_or_none(identity.get("year")),
    }


def manual_research_text(project: str) -> str:
    appraisal = appraisal_module()
    research = read_json(appraisal.research_path(project), {})
    notes = []
    for note in research.get("manual_notes", []):
        notes.append(str(note.get("note", "")))
    return " ".join(notes)


def visible_text_evaluation(candidate: dict, confirmed_identity: dict, confirmed_notes: str = "") -> dict:
    identity = candidate.get("candidate_identity", {})
    evidence = candidate.get("evidence", {})
    candidate_visible = []
    candidate_visible.extend(str(value) for value in list_value(identity.get("visible_text")))
    for key in ["front_cover_observations", "back_cover_observations", "spine_observations", "uncertain_text"]:
        candidate_visible.extend(str(value) for value in list_value(evidence.get(key)))
    confirmed_visible = [
        value for value in [
            confirmed_identity.get("artist"),
            confirmed_identity.get("title"),
            confirmed_identity.get("label"),
            confirmed_identity.get("catalog_number"),
            confirmed_identity.get("year"),
        ]
        if value
    ]
    confirmed_blob = normalize_comparison_text(" ".join(confirmed_visible + [confirmed_notes]))
    candidate_blob = normalize_comparison_text(" ".join(candidate_visible))
    missed = [
        value for value in confirmed_visible
        if normalize_comparison_text(value) and normalize_comparison_text(value) not in candidate_blob
    ]
    hallucinated = [
        value for value in candidate_visible
        if normalize_comparison_text(value) and normalize_comparison_text(value) not in confirmed_blob
    ]
    notes = ["Visible text evaluation is conservative until explicit confirmed text fields exist."]
    return {
        "candidate_visible_text": candidate_visible,
        "confirmed_visible_text": confirmed_visible,
        "missed_confirmed_text": missed,
        "possible_hallucinated_text": hallucinated,
        "notes": notes,
    }


def failure_modes_for_results(field_results: dict, candidate: dict) -> list[str]:
    tags = []
    for field, result in field_results.items():
        if result.get("result") == "missing" and result.get("model_expected_to_read") is False:
            tags.append(f"{field}_missing_not_readable")
        else:
            tags.append(f"{field}_{result.get('result')}")
        if result.get("result") == "unconfirmed" and result.get("candidate"):
            tags.append(f"{field}_candidate_unverified")
    confidence = candidate.get("candidate_identity", {}).get("confidence") or "low"
    if confidence == "low":
        tags.append("low_confidence")
    if any(result.get("candidate") and result.get("result") == "unconfirmed" for result in field_results.values()):
        tags.append("candidate_unverified_claims")
    tags.append("human_review_required")
    return sorted(dict.fromkeys(tags))


def evaluation_summary(field_results: dict, candidate: dict) -> dict:
    counts = {key: 0 for key in ["match", "partial", "missing", "incorrect", "unconfirmed"]}
    for result in field_results.values():
        counts[result["result"]] += 1
    evaluated = len(field_results) - counts["unconfirmed"]
    if evaluated and counts["incorrect"] == 0 and counts["missing"] == 0 and counts["partial"] == 0:
        overall = "strong"
    elif evaluated and counts["incorrect"] == 0 and counts["match"] + counts["partial"] >= max(1, evaluated - 1):
        overall = "useful"
    elif evaluated and counts["match"] + counts["partial"] > 0:
        overall = "mixed"
    else:
        overall = "poor"
    confidence = candidate.get("candidate_identity", {}).get("confidence") or "low"
    if overall == "strong":
        utility = "high" if confidence != "low" else "medium"
    elif overall == "useful" and confidence != "low":
        utility = "medium"
    else:
        utility = "low"
    return {
        "evaluated_fields": evaluated,
        "matches": counts["match"],
        "partials": counts["partial"],
        "missing": counts["missing"],
        "incorrect": counts["incorrect"],
        "unconfirmed": counts["unconfirmed"],
        "overall_result": overall,
        "model_utility": utility,
        "human_review_required": True,
    }


def evaluation_recommendations(evaluation: dict) -> list[str]:
    recommendations = ["Keep visual candidates non-authoritative."]
    modes = set(evaluation.get("failure_modes", []))
    if any(mode.endswith("_missing_not_readable") for mode in modes):
        recommendations.append("Capture higher-resolution close-up or spine/label photo for fields not readable in current photos.")
    if any(mode.endswith("_missing") for mode in modes) or any(mode.endswith("_incorrect") for mode in modes):
        recommendations.append("Use higher-resolution crops for spine/catalog text.")
        recommendations.append("Consider separate OCR pass for back cover and spine.")
    if "matrix_runout_unconfirmed" in modes:
        recommendations.append("Capture deadwax/matrix photos only if collector-level identification is needed.")
    if evaluation.get("summary", {}).get("overall_result") in {"useful", "strong"}:
        recommendations.append("Continue using visual candidates as review prompts, not metadata authority.")
    return recommendations


def build_record_identification_evaluation(identifier: str, run_id: Optional[str] = None) -> dict:
    project = project_id(identifier)
    if run_id:
        candidate = read_run_candidate(project, run_id)
        candidate_path = f"appraisal/identity_candidates/runs/{run_id}/candidate.json"
    else:
        candidate_file = visual_candidate_path(project)
        if not candidate_file.is_file():
            raise FileNotFoundError(
                "No visual identification candidate found.\n"
                "Run:\n"
                f"  laia projects record-identify-visual {project}"
            )
        candidate = read_candidate(project)
        candidate_path = "appraisal/identity_candidates/visual_candidate.json"
    confirmed_identity, _item = confirmed_record_identity(project)
    identity_evidence = identity_evidence_for_project(project)
    for field, value in identity_evidence.get("identity", {}).items():
        if field in confirmed_identity and value not in (None, ""):
            confirmed_identity[field] = value
    candidate_identity = candidate_identity_for_evaluation(candidate)
    field_results = {
        field: compare_identity_field(candidate_identity.get(field), confirmed_identity.get(field))
        for field in ["artist", "title", "label", "catalog_number", "year"]
    }
    field_results = apply_field_evidence_context(field_results, identity_evidence)
    visible_eval = visible_text_evaluation(candidate, confirmed_identity, manual_research_text(project))
    summary = evaluation_summary(field_results, candidate)
    evaluation = {
        "project": project,
        "category": "records",
        "profile": "records",
        "candidate_source": {
            "source": candidate.get("source"),
            "model": candidate.get("model"),
            "run_id": run_id or candidate.get("run_id"),
            "input_strategy": candidate.get("input_strategy", "approved_photos"),
            "prompt_version": candidate.get("prompt_version", "record_identity_v1"),
            "candidate_path": candidate_path,
            "candidate_confidence": candidate.get("candidate_identity", {}).get("confidence") or "low",
            "candidate_generated_at": candidate.get("generated_at"),
        },
        "confirmed_identity": confirmed_identity,
        "candidate_identity": candidate_identity,
        "field_results": field_results,
        "visible_text_evaluation": visible_eval,
        "summary": summary,
        "failure_modes": [],
        "recommendations": [],
        "generated_at": registry_module().utc_now(),
    }
    evaluation["failure_modes"] = failure_modes_for_results(field_results, candidate)
    evaluation["recommendations"] = evaluation_recommendations(evaluation)
    return evaluation


def render_evaluation_markdown(evaluation: dict) -> str:
    source = evaluation.get("candidate_source", {})
    confirmed = evaluation.get("confirmed_identity", {})
    candidate = evaluation.get("candidate_identity", {})
    summary = evaluation.get("summary", {})
    lines = [
        f"# Visual Identification Evaluation: {evaluation.get('project', '')}",
        "",
        "## Candidate",
        "",
        f"Source: {source.get('source') or '-'}  ",
        f"Model: {source.get('model') or '-'}  ",
        f"Candidate confidence: {source.get('candidate_confidence') or 'low'}  ",
        "Authority: unconfirmed AI candidate",
        "",
        "## Confirmed identity",
        "",
        f"Artist: {confirmed.get('artist') or '-'}  ",
        f"Title: {confirmed.get('title') or '-'}  ",
        f"Label: {confirmed.get('label') or '-'}  ",
        f"Catalog number: {confirmed.get('catalog_number') or '-'}",
        "",
        "## Candidate identity",
        "",
        f"Artist: {candidate.get('artist') or '-'}  ",
        f"Title: {candidate.get('title') or '-'}  ",
        f"Label: {candidate.get('label') or '-'}  ",
        f"Catalog number: {candidate.get('catalog_number') or '-'}",
        "",
        "## Field results",
        "",
        "| Field | Candidate | Confirmed | Result |",
        "|---|---|---|---|",
    ]
    for field in ["artist", "title", "label", "catalog_number", "year"]:
        result = evaluation.get("field_results", {}).get(field, {})
        lines.append(
            f"| {field} | {result.get('candidate') or '-'} | "
            f"{result.get('confirmed') or '-'} | {result.get('result') or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"Evaluated fields: {summary.get('evaluated_fields', 0)}  ",
            f"Matches: {summary.get('matches', 0)}  ",
            f"Partials: {summary.get('partials', 0)}  ",
            f"Missing: {summary.get('missing', 0)}  ",
            f"Incorrect: {summary.get('incorrect', 0)}  ",
            f"Overall result: {summary.get('overall_result', '')}  ",
            f"Model utility: {summary.get('model_utility', '')}  ",
            f"Human review required: {'yes' if summary.get('human_review_required') else 'no'}",
            "",
            "## Failure modes",
        ]
    )
    lines.extend([f"- {mode}" for mode in evaluation.get("failure_modes", [])] or ["- none"])
    lines.extend(["", "## Recommendations"])
    lines.extend([f"- {item}" for item in evaluation.get("recommendations", [])] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def write_record_identification_evaluation(identifier: str, evaluation: Optional[dict] = None, run_id: Optional[str] = None) -> dict:
    project = project_id(identifier)
    evaluation = evaluation or build_record_identification_evaluation(project, run_id)
    registry = registry_module()
    if run_id:
        root = run_root(project, run_id)
        root.mkdir(parents=True, exist_ok=True)
        json_path = run_evaluation_path(project, run_id)
        md_path = run_evaluation_markdown_path(project, run_id)
        registry.write_json(json_path, evaluation)
        md_path.write_text(render_evaluation_markdown(evaluation), encoding="utf-8")
        return {"json": str(json_path), "md": str(md_path)}
    root = identity_candidates_root(project)
    root.mkdir(parents=True, exist_ok=True)
    (root / "history").mkdir(parents=True, exist_ok=True)
    json_path = evaluation_path(project)
    md_path = evaluation_markdown_path(project)
    history_path = evaluation_history_path(project, evaluation["generated_at"])
    registry.write_json(json_path, evaluation)
    registry.write_json(history_path, evaluation)
    md_path.write_text(render_evaluation_markdown(evaluation), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path), "history": str(history_path)}


def record_identification_evaluation_with_paths(identifier: str, run_id: Optional[str] = None) -> tuple[dict, dict]:
    evaluation = build_record_identification_evaluation(identifier, run_id)
    paths = write_record_identification_evaluation(identifier, evaluation, run_id)
    return evaluation, paths


def evaluate_all_candidate_runs(identifier: str) -> dict:
    project = project_id(identifier)
    evaluated = []
    skipped = []
    for run in list_candidate_runs(project):
        run_id = run.get("run_id")
        if not run_id or not run_candidate_path(project, run_id).is_file():
            skipped.append({"run_id": run_id or "", "reason": "missing candidate"})
            continue
        evaluation, paths = record_identification_evaluation_with_paths(project, run_id)
        evaluated.append({"run_id": run_id, "evaluation": evaluation, "paths": paths})
    return {"project": project, "evaluated": evaluated, "skipped": skipped}


def print_evaluation_summary(evaluation: dict, paths: dict) -> None:
    source = evaluation.get("candidate_source", {})
    summary = evaluation.get("summary", {})
    print(f"Visual Identification Evaluation: {evaluation.get('project', '')}")
    print(f"Source: {source.get('source') or '-'}")
    print(f"Model: {source.get('model') or '-'}")
    print(f"Candidate confidence: {source.get('candidate_confidence') or 'low'}")
    print()
    print("Field results:")
    for field in ["artist", "title", "label", "catalog_number", "year"]:
        print(f"  {field}: {evaluation.get('field_results', {}).get(field, {}).get('result', '-')}")
    print()
    print("Summary:")
    print(f"  Overall result: {summary.get('overall_result', '')}")
    print(f"  Model utility: {summary.get('model_utility', '')}")
    print(f"  Human review required: {'yes' if summary.get('human_review_required') else 'no'}")
    print()
    print("Failure modes:")
    for mode in evaluation.get("failure_modes", []):
        print(f"  {mode}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def command_record_identify_evaluate(args):
    try:
        evaluation, paths = record_identification_evaluation_with_paths(args.identifier, getattr(args, "run_id", None))
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(evaluation, indent=2))
    else:
        print_evaluation_summary(evaluation, paths)


def command_record_identify_evaluation_summary(args):
    try:
        path = evaluation_path(args.identifier)
        evaluation = read_json(path) if path.is_file() else build_record_identification_evaluation(args.identifier)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    print_evaluation_summary(evaluation, {"json": str(evaluation_path(args.identifier)), "md": str(evaluation_markdown_path(args.identifier))})


def command_record_identify_evaluate_batch(args):
    evaluated = 0
    skipped_missing_candidate = 0
    skipped_missing_identity = 0
    skipped_other = []
    for project in record_projects_for_batch(args.prefix, None, args.limit):
        try:
            record_identification_evaluation_with_paths(project)
            evaluated += 1
        except FileNotFoundError:
            skipped_missing_candidate += 1
        except ValueError as exc:
            if "No confirmed record identity available" in str(exc):
                skipped_missing_identity += 1
            else:
                skipped_other.append({"project": project, "reason": str(exc)})
    result = {
        "evaluated": evaluated,
        "skipped_missing_candidate": skipped_missing_candidate,
        "skipped_missing_confirmed_identity": skipped_missing_identity,
        "skipped_other": skipped_other,
    }
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print(f"Evaluated: {evaluated}")
    print(f"Skipped missing candidate: {skipped_missing_candidate}")
    print(f"Skipped missing confirmed identity: {skipped_missing_identity}")
    for row in skipped_other:
        print(f"Skipped {row['project']}: {row['reason']}")


def utility_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(value or "low"), 0)


def result_label(result: dict) -> str:
    if result.get("result") == "missing" and result.get("model_expected_to_read") is False:
        return "missing_not_readable"
    return result.get("result", "-")


def read_run_evaluation(identifier: str, run_id: str) -> dict:
    path = run_evaluation_path(identifier, run_id)
    return read_json(path, {}) if path.is_file() else {}


def build_visual_model_comparison(identifier: str) -> dict:
    project = project_id(identifier)
    confirmed, _item = confirmed_record_identity(project)
    evidence = identity_evidence_for_project(project)
    for field, value in evidence.get("identity", {}).items():
        if field in confirmed and value not in (None, ""):
            confirmed[field] = value
    rows = []
    for run in list_candidate_runs(project):
        run_id = run.get("run_id", "")
        candidate = read_run_candidate(project, run_id) if run_id and run_candidate_path(project, run_id).is_file() else {}
        evaluation = read_run_evaluation(project, run_id)
        identity = candidate.get("candidate_identity", {})
        field_results = evaluation.get("field_results", {})
        summary = evaluation.get("summary", {})
        rows.append(
            {
                "run_id": run_id,
                "model": run.get("model") or candidate.get("model"),
                "prompt_version": run.get("prompt_version") or candidate.get("prompt_version"),
                "input_strategy": run.get("input_strategy") or candidate.get("input_strategy"),
                "candidate_confidence": identity.get("confidence", "low"),
                "overall_result": summary.get("overall_result"),
                "model_utility": summary.get("model_utility"),
                "field_results": {
                    field: result_label(field_results.get(field, {}))
                    for field in ["artist", "title", "label", "catalog_number", "year"]
                },
                "evaluated": bool(evaluation),
                "generated_at": run.get("generated_at") or candidate.get("generated_at"),
            }
        )
    evaluated = [row for row in rows if row.get("evaluated")]
    best = sorted(evaluated, key=lambda row: utility_rank(row.get("model_utility")), reverse=True)[0] if evaluated else None
    recommendations = [
        "Capture close-up label/catalog photos for records when collector-level identification matters.",
        "Keep LLaVA as baseline; do not promote low-confidence candidates automatically.",
    ]
    if any(row.get("field_results", {}).get("catalog_number") == "missing_not_readable" for row in rows):
        recommendations.append("Fine catalog text requires physical inspection or better photo/OCR input for this item.")
    return {
        "project": project,
        "confirmed_identity": confirmed,
        "runs": rows,
        "best_current_use": {
            "broad_identity": best.get("model") if best else None,
            "fine_catalog_text": "physical inspection or better photo/OCR required",
        },
        "recommendations": recommendations,
    }


def print_visual_model_comparison(comparison: dict) -> None:
    confirmed = comparison.get("confirmed_identity", {})
    runs = comparison.get("runs", [])
    print(f"Record Visual Model Comparison: {comparison.get('project', '')}")
    print()
    print("Confirmed identity:")
    print(f"  Artist: {confirmed.get('artist') or '-'}")
    print(f"  Title: {confirmed.get('title') or '-'}")
    print(f"  Label: {confirmed.get('label') or '-'}")
    print(f"  Catalog number: {confirmed.get('catalog_number') or '-'}")
    print()
    print("Runs:")
    if not runs:
        print("  none")
    for row in runs:
        print(f"  {row.get('model') or '-'} / {row.get('prompt_version') or '-'}")
        print(f"    run_id: {row.get('run_id')}")
        print(f"    candidate confidence: {row.get('candidate_confidence') or '-'}")
        print(f"    overall result: {row.get('overall_result') or 'not evaluated'}")
        print(f"    utility: {row.get('model_utility') or '-'}")
        for field, result in row.get("field_results", {}).items():
            print(f"    {field}: {result}")
        print()
    if len(runs) == 1:
        print("Only one candidate run exists. Add another model run to compare:")
        print(f"  laia projects record-identify-visual {comparison.get('project', '')} --model llama3.2-vision")
        print()
    best = comparison.get("best_current_use", {})
    print("Best current use:")
    print(f"  broad identity: {best.get('broad_identity') or '-'}")
    print(f"  fine catalog text: {best.get('fine_catalog_text') or '-'}")
    print()
    print("Recommendations:")
    for recommendation in comparison.get("recommendations", []):
        print(f"  {recommendation}")


def command_record_identify_visual_compare(args):
    try:
        comparison = build_visual_model_comparison(args.identifier)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(comparison, indent=2))
    else:
        print_visual_model_comparison(comparison)


def command_record_identify_evaluate_all(args):
    try:
        result = evaluate_all_candidate_runs(args.identifier)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print(f"Evaluated: {len(result['evaluated'])}")
    for row in result["evaluated"]:
        print(f"  {row['run_id']}: {row['paths']['json']}")
    if result["skipped"]:
        print("Skipped:")
        for row in result["skipped"]:
            print(f"  {row.get('run_id') or '-'}: {row.get('reason')}")


def record_projects_for_batch(prefix: str, start_index: Optional[int], limit: Optional[int]) -> list[str]:
    registry = registry_module()
    rows = [project for project in registry.list_project_ids() if project.startswith(f"{prefix}-")]
    if start_index is not None:
        rows = [project for project in rows if int(re.sub(r"\D", "", project) or 0) >= start_index]
    return rows[:limit] if limit is not None else rows


def command_record_identify_visual_batch(args):
    processed = []
    skipped = []
    for project in record_projects_for_batch(args.prefix, args.start_index, args.limit):
        if visual_candidate_path(project).is_file() and not args.force:
            skipped.append((project, "already identified"))
            continue
        try:
            record_identify_visual(project, model=getattr(args, "model", "llava:latest"))
            processed.append((project, "candidate written"))
        except FileNotFoundError:
            skipped.append((project, "no approved photos"))
        except (ValueError, RuntimeError) as exc:
            skipped.append((project, str(exc)))
    if getattr(args, "json", False):
        print(json.dumps({"processed": processed, "skipped": skipped}, indent=2))
        return
    print("Processed:")
    for project, reason in processed:
        print(f"  {project} {reason}")
    print()
    print("Skipped:")
    for project, reason in skipped:
        print(f"  {project} {reason}")


def register_record_visual_identification_subcommands(projects_sub) -> None:
    models_p = projects_sub.add_parser("vision-models", help="List configured and detected local vision models")
    models_p.add_argument("--json", action="store_true")
    models_p.add_argument("--health", action="store_true", help="Run a live Ollama health check for vision models")
    models_p.set_defaults(func=command_vision_models)

    visual_p = projects_sub.add_parser("record-identify-visual", help="Create an unconfirmed visual identity candidate")
    visual_p.add_argument("identifier")
    visual_p.add_argument("--model", default="llava:latest")
    visual_p.add_argument("--set-current", action="store_true")
    visual_p.add_argument("--input-strategy", choices=sorted(INPUT_STRATEGIES), default="approved_photos")
    visual_p.add_argument("--prompt-version", choices=sorted(PROMPT_VERSIONS), default="record_identity_v1")
    visual_p.add_argument("--json", action="store_true")
    visual_p.set_defaults(func=command_record_identify_visual)

    review_p = projects_sub.add_parser("record-identify-review", help="Review visual identity candidate")
    review_p.add_argument("identifier")
    review_p.set_defaults(func=command_record_identify_review)

    evaluate_p = projects_sub.add_parser("record-identify-evaluate", help="Evaluate visual identity candidate against confirmed metadata")
    evaluate_p.add_argument("identifier")
    evaluate_p.add_argument("--run-id")
    evaluate_p.add_argument("--json", action="store_true")
    evaluate_p.set_defaults(func=command_record_identify_evaluate)

    evaluate_all_p = projects_sub.add_parser("record-identify-evaluate-all", help="Evaluate all visual identity candidate runs")
    evaluate_all_p.add_argument("identifier")
    evaluate_all_p.add_argument("--json", action="store_true")
    evaluate_all_p.set_defaults(func=command_record_identify_evaluate_all)

    evaluation_summary_p = projects_sub.add_parser("record-identify-evaluation-summary", help="Show visual identity evaluation summary")
    evaluation_summary_p.add_argument("identifier")
    evaluation_summary_p.set_defaults(func=command_record_identify_evaluation_summary)

    compare_p = projects_sub.add_parser("record-identify-visual-compare", help="Compare visual model runs for a record")
    compare_p.add_argument("identifier")
    compare_p.add_argument("--json", action="store_true")
    compare_p.set_defaults(func=command_record_identify_visual_compare)

    confirm_p = projects_sub.add_parser("record-identify-confirm", help="Promote or correct record visual identity")
    confirm_p.add_argument("identifier")
    confirm_p.add_argument("--use-candidate", action="store_true")
    confirm_p.add_argument("--allow-low-confidence", action="store_true")
    confirm_p.add_argument("--artist")
    confirm_p.add_argument("--title")
    confirm_p.add_argument("--label", default="")
    confirm_p.add_argument("--catalog-number", default="")
    confirm_p.add_argument("--year", default="")
    confirm_p.add_argument("--note", default="")
    confirm_p.add_argument("--json", action="store_true")
    confirm_p.set_defaults(func=command_record_identify_confirm)

    batch_p = projects_sub.add_parser("record-identify-visual-batch", help="Create visual identity candidates for records")
    batch_p.add_argument("--prefix", default="record")
    batch_p.add_argument("--start-index", type=int)
    batch_p.add_argument("--limit", type=int)
    batch_p.add_argument("--force", action="store_true")
    batch_p.add_argument("--model", default="llava:latest")
    batch_p.add_argument("--json", action="store_true")
    batch_p.set_defaults(func=command_record_identify_visual_batch)

    evaluate_batch_p = projects_sub.add_parser("record-identify-evaluate-batch", help="Evaluate visual identity candidates for records")
    evaluate_batch_p.add_argument("--prefix", default="record")
    evaluate_batch_p.add_argument("--limit", type=int)
    evaluate_batch_p.add_argument("--json", action="store_true")
    evaluate_batch_p.set_defaults(func=command_record_identify_evaluate_batch)
