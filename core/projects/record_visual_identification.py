import base64
import ast
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional


CONFIDENCE_VALUES = {"low", "medium", "high"}
VISUAL_WARNINGS = [
    "AI visual identification is not confirmed.",
    "Human review is required before metadata promotion.",
]


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


def normalize_candidate_response(project: str, raw: str, photos: dict, model: str) -> dict:
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
    return {
        "project": project,
        "category": "records",
        "source": "llava",
        "model": model,
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
            "warnings": list(VISUAL_WARNINGS),
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


def record_identify_visual(
    identifier: str,
    model: str = "llava:latest",
    runner: Optional[Callable[[str, str, list[Path]], str]] = None,
) -> tuple[dict, dict]:
    project = project_id(identifier)
    photos = approved_visual_photos(project)
    image_paths = [Path(row["path"]) for role in ["cover_front", "cover_back"] for row in photos[role]]
    runner = runner or ollama_visual_generate
    raw = runner(model, candidate_prompt(), image_paths)
    candidate = normalize_candidate_response(project, raw, photos, model)
    return candidate, write_candidate(project, candidate)


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
        candidate, paths = record_identify_visual(args.identifier, model=getattr(args, "model", "llava:latest"))
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
    visual_p = projects_sub.add_parser("record-identify-visual", help="Create an unconfirmed visual identity candidate")
    visual_p.add_argument("identifier")
    visual_p.add_argument("--model", default="llava:latest")
    visual_p.add_argument("--json", action="store_true")
    visual_p.set_defaults(func=command_record_identify_visual)

    review_p = projects_sub.add_parser("record-identify-review", help="Review visual identity candidate")
    review_p.add_argument("identifier")
    review_p.set_defaults(func=command_record_identify_review)

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
