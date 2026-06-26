import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional


CONFIDENCE_VALUES = {"low", "medium", "high"}
SOURCE_TYPES = {
    "discogs",
    "ebay_sold",
    "ebay_active",
    "local_marketplace",
    "store_reference",
    "manual_note",
    "marketplace",
    "other",
}
RECORD_PHOTO_ROLES = [
    "cover_front",
    "cover_back",
    "label_a",
    "label_b",
    "vinyl_a",
    "vinyl_b",
    "spine",
    "matrix",
    "defect",
    "detail",
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


def blank_to_none(value):
    if value in (None, ""):
        return None
    return value


def display_missing(value: Optional[str]) -> str:
    return str(value) if value not in (None, "") else "missing"


def display_unknown(value) -> str:
    if value is None or value == "":
        return "unknown"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return str(value)


def appraisal_root(project_id: str) -> Path:
    return registry_module().project_folder(project_id) / "appraisal"


def listing_root(project_id: str) -> Path:
    return registry_module().project_folder(project_id) / "listing"


def context_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "context.json"


def research_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "research.json"


def research_markdown_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "research.md"


def condition_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "condition.json"


def condition_markdown_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "condition.md"


def listing_draft_context_path(project_id: str) -> Path:
    return listing_root(project_id) / "draft_context.json"


def listing_draft_markdown_path(project_id: str) -> Path:
    return listing_root(project_id) / "draft.md"


def load_optional_sale_item(project_id: str) -> dict:
    sale_items = sale_items_module()
    try:
        return sale_items.load_sale_item(project_id)
    except FileNotFoundError:
        return {}


def load_optional_photo_edit(project_id: str) -> dict:
    sale_items = sale_items_module()
    return sale_items.migrate_edit_manifest(sale_items.read_json(sale_items.edit_manifest_path(project_id), {}))


def category_profile(sale_item: dict) -> str:
    category = str(sale_item.get("category", "")).strip().lower()
    if category == "records":
        return "records"
    return "generic"


def role_coverage(photo_edit: dict, roles: list[str]) -> dict:
    images = photo_edit.get("images", []) if photo_edit else []
    coverage = {}
    for role in roles:
        role_images = [image for image in images if image.get("role") == role]
        approved = [image for image in role_images if image.get("review_status") == "approved"]
        if len(approved) > 1:
            status = "duplicate"
        elif len(approved) == 1:
            status = "approved"
        elif role_images:
            status = "unapproved"
        else:
            status = "missing"
        files = [
            image.get("work_filename") or image.get("filename", "")
            for image in (approved or role_images)
            if image.get("work_filename") or image.get("filename")
        ]
        coverage[role] = {"status": status, "files": files}
    return coverage


def approved_photo_count(photo_edit: dict) -> int:
    return sum(1 for image in photo_edit.get("images", []) if image.get("review_status") == "approved")


def condition_bool(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "on"}:
        return True
    if text in {"false", "no", "n", "0", "off"}:
        return False
    if text == "unknown":
        return None
    raise ValueError(f"Invalid boolean value: {value}")


def default_bool_from_note(note: str, keyword: str) -> Optional[bool]:
    return True if keyword.lower() in str(note or "").lower() else None


def record_condition_confidence(grading: dict) -> str:
    if grading.get("media_condition") and grading.get("sleeve_condition") and grading.get("overall_condition") != "unassessed":
        return "medium"
    return "low"


def record_condition_safe_disclosure(grading: dict) -> list[str]:
    disclosure = []
    if grading.get("visual_grade_only"):
        disclosure.append("Visual grade only.")
    if not grading.get("playback_tested"):
        disclosure.append("Playback not tested.")
    disclosure.append("See photos for sleeve condition.")
    return disclosure


def record_condition_risks(grading: dict) -> list[str]:
    risks = []
    if not grading.get("media_condition"):
        risks.append("Media condition has not been graded.")
    if not grading.get("sleeve_condition"):
        risks.append("Sleeve condition has not been graded.")
    if not grading.get("playback_tested"):
        risks.append("Playback quality is unknown.")
    return risks


def record_condition_next_steps(grading: dict) -> list[dict]:
    steps = []
    if not grading.get("media_condition"):
        steps.append({"priority": "high", "task": "Inspect vinyl surface and assign media condition."})
    if not grading.get("sleeve_condition"):
        steps.append({"priority": "high", "task": "Inspect sleeve and assign sleeve condition."})
    steps.append({"priority": "medium", "task": "Capture label/vinyl photos if collector pricing matters."})
    return steps


def build_record_condition_capture(project_id_or_identifier: str) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    item = load_optional_sale_item(project_id)
    metadata = item.get("record_metadata", {})
    identity = {
        "artist": blank_to_none(metadata.get("artist") or item.get("artist")),
        "title": blank_to_none(metadata.get("title") or item.get("title")),
        "label": blank_to_none(metadata.get("record_label") or item.get("manufacturer")),
        "catalog_number": blank_to_none(metadata.get("catalog_number") or item.get("model")),
    }
    note = metadata.get("grading_note", "")
    grading = {
        "media_condition": blank_to_none(metadata.get("media_condition")),
        "sleeve_condition": blank_to_none(metadata.get("sleeve_condition")),
        "overall_condition": item.get("condition", {}).get("overall") or "unassessed",
        "grading_standard": metadata.get("grading_standard") or "visual",
        "playback_tested": bool(metadata.get("play_tested")),
        "visual_grade_only": metadata.get("visual_grade_only")
        if "visual_grade_only" in metadata
        else not bool(metadata.get("play_tested")),
        "confidence": "low",
        "grading_note": blank_to_none(note),
    }
    grading["confidence"] = metadata.get("grading_confidence") or record_condition_confidence(grading)
    media_observations = {
        "scratches": blank_to_none(metadata.get("scratches")),
        "scuffs": blank_to_none(metadata.get("scuffs")),
        "warping": blank_to_none(metadata.get("warping")),
        "dust": blank_to_none(metadata.get("dust")),
        "fingerprints": blank_to_none(metadata.get("fingerprints")),
        "label_condition": blank_to_none(metadata.get("label_condition")),
        "notes": metadata.get("media_notes", []),
    }
    sleeve_observations = {
        "ring_wear": blank_to_none(metadata.get("ring_wear")),
        "shelf_wear": blank_to_none(metadata.get("shelf_wear")),
        "corner_wear": blank_to_none(metadata.get("corner_wear")),
        "edge_wear": blank_to_none(metadata.get("edge_wear")),
        "seam_split": blank_to_none(metadata.get("seam_split")),
        "spine_readable": metadata.get("spine_readable")
        if "spine_readable" in metadata
        else default_bool_from_note(note, "spine reads"),
        "writing": blank_to_none(metadata.get("writing")),
        "stickers": blank_to_none(metadata.get("stickers")),
        "water_damage": blank_to_none(metadata.get("water_damage")),
        "notes": metadata.get("sleeve_notes", []),
    }
    included_materials = {
        "poly_sleeve": metadata.get("poly_sleeve")
        if "poly_sleeve" in metadata
        else default_bool_from_note(note, "poly record sleeve"),
        "inner_sleeve": metadata.get("inner_sleeve"),
        "insert": metadata.get("insert"),
        "poster": metadata.get("poster"),
        "other": metadata.get("other_materials", []),
    }
    return {
        "project": project_id,
        "category": item.get("category", ""),
        "profile": "records" if item.get("category") == "records" else "generic",
        "identity": {
            "artist": identity.get("artist"),
            "title": identity.get("title"),
            "label": identity.get("label"),
            "catalog_number": identity.get("catalog_number"),
        },
        "grading": grading,
        "media_observations": media_observations,
        "sleeve_observations": sleeve_observations,
        "included_materials": included_materials,
        "safe_disclosure": record_condition_safe_disclosure(grading),
        "condition_risks": record_condition_risks(grading),
        "next_steps": record_condition_next_steps(grading),
        "generated_at": registry.utc_now(),
    }


def read_record_condition(project_id_or_identifier: str) -> dict:
    return build_record_condition_capture(project_id_or_identifier)


def write_record_condition(project_id_or_identifier: str, condition: Optional[dict] = None) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    condition = condition or read_record_condition(project_id)
    condition["generated_at"] = registry.utc_now()
    root = appraisal_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    json_path = condition_path(project_id)
    md_path = condition_markdown_path(project_id)
    registry.write_json(json_path, condition)
    md_path.write_text(render_record_condition_markdown(condition), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def record_condition_with_paths(project_id_or_identifier: str) -> tuple[dict, dict]:
    condition = read_record_condition(project_id_or_identifier)
    paths = write_record_condition(project_id_or_identifier, condition)
    return condition, paths


def record_condition_update(project_id_or_identifier: str, **values) -> tuple[dict, dict]:
    registry = registry_module()
    sale_items = sale_items_module()
    project_id = registry.find_project(project_id_or_identifier)
    item = sale_items.load_sale_item(project_id)
    metadata = item.setdefault("record_metadata", {})
    item["category"] = item.get("category") or "records"
    item.setdefault("condition", {})["functional"] = "not_applicable"
    if values.get("condition") is not None:
        item["condition"]["overall"] = values["condition"]
    direct_fields = {
        "media_condition": "media_condition",
        "sleeve_condition": "sleeve_condition",
        "grading_standard": "grading_standard",
        "grading_note": "grading_note",
        "scratches": "scratches",
        "scuffs": "scuffs",
        "warping": "warping",
        "dust": "dust",
        "fingerprints": "fingerprints",
        "label_condition": "label_condition",
        "ring_wear": "ring_wear",
        "shelf_wear": "shelf_wear",
        "corner_wear": "corner_wear",
        "edge_wear": "edge_wear",
        "seam_split": "seam_split",
        "writing": "writing",
        "stickers": "stickers",
        "water_damage": "water_damage",
        "inner_sleeve": "inner_sleeve",
        "insert": "insert",
        "poster": "poster",
    }
    for update_key, metadata_key in direct_fields.items():
        if values.get(update_key) is not None:
            metadata[metadata_key] = values[update_key]
    for key in ["playback_tested", "visual_grade_only", "spine_readable", "poly_sleeve"]:
        if values.get(key) is not None:
            metadata["play_tested" if key == "playback_tested" else key] = condition_bool(values[key])
    if values.get("note"):
        metadata.setdefault("condition_notes", []).append(values["note"])
    sale_items.write_sale_item(project_id, item)
    condition = build_record_condition_capture(project_id)
    paths = write_record_condition(project_id, condition)
    return condition, paths


def render_record_condition_markdown(condition: dict) -> str:
    identity = condition.get("identity", {})
    grading = condition.get("grading", {})
    sleeve = condition.get("sleeve_observations", {})
    media = condition.get("media_observations", {})
    included = condition.get("included_materials", {})
    high_steps = [step["task"] for step in condition.get("next_steps", []) if step.get("priority") == "high"]
    medium_steps = [step["task"] for step in condition.get("next_steps", []) if step.get("priority") == "medium"]
    label_line = " ".join(value for value in [identity.get("label"), identity.get("catalog_number")] if value)
    lines = [
        f"# Record Condition: {condition.get('project', '')}",
        "",
        "## Item",
        "",
        f"{identity.get('artist') or '-'} - {identity.get('title') or '-'}  ",
        label_line or "-",
        "",
        "## Grading",
        "",
        f"Media condition: {display_missing(grading.get('media_condition'))}  ",
        f"Sleeve condition: {display_missing(grading.get('sleeve_condition'))}  ",
        f"Overall condition: {grading.get('overall_condition', 'unassessed')}  ",
        f"Grading standard: {grading.get('grading_standard', 'visual')}  ",
        f"Playback tested: {'yes' if grading.get('playback_tested') else 'no'}  ",
        f"Visual grade only: {'yes' if grading.get('visual_grade_only') else 'no'}  ",
        f"Confidence: {grading.get('confidence', 'low')}",
        "",
        "## Sleeve observations",
        "",
        f"- Poly sleeve: {display_unknown(included.get('poly_sleeve'))}",
        f"- Spine readable: {display_unknown(sleeve.get('spine_readable'))}",
        f"- Ring wear: {display_unknown(sleeve.get('ring_wear'))}",
        f"- Shelf wear: {display_unknown(sleeve.get('shelf_wear'))}",
        f"- Corner wear: {display_unknown(sleeve.get('corner_wear'))}",
        f"- Seam split: {display_unknown(sleeve.get('seam_split'))}",
        f"- Writing: {display_unknown(sleeve.get('writing'))}",
        f"- Stickers: {display_unknown(sleeve.get('stickers'))}",
        f"- Water damage: {display_unknown(sleeve.get('water_damage'))}",
        "",
        "## Media observations",
        "",
        f"- Scratches: {display_unknown(media.get('scratches'))}",
        f"- Scuffs: {display_unknown(media.get('scuffs'))}",
        f"- Warping: {display_unknown(media.get('warping'))}",
        f"- Dust: {display_unknown(media.get('dust'))}",
        f"- Fingerprints: {display_unknown(media.get('fingerprints'))}",
        f"- Label condition: {display_unknown(media.get('label_condition'))}",
        "",
        "## Disclosure language",
        *(f"- {item}" for item in condition.get("safe_disclosure", [])),
        "",
        "## Condition risks",
        *(f"- {item}" for item in condition.get("condition_risks", [])),
        "",
        "## Next steps",
        "",
        "High:",
        *(f"- {task}" for task in high_steps),
        *(["- none"] if not high_steps else []),
        "",
        "Medium:",
        *(f"- {task}" for task in medium_steps),
        *(["- none"] if not medium_steps else []),
        "",
    ]
    return "\n".join(lines)


def record_listing_readiness(item: dict, coverage: dict) -> dict:
    metadata = item.get("record_metadata", {})
    pricing = item.get("pricing", {})
    front = coverage.get("cover_front", {}).get("status") == "approved"
    back = coverage.get("cover_back", {}).get("status") == "approved"
    if front and back:
        photo_evidence = "ready_basic"
    elif front:
        photo_evidence = "partial"
    else:
        photo_evidence = "insufficient"
    overall_condition = item.get("condition", {}).get("overall")
    condition_ready = (
        overall_condition not in (None, "", "unassessed")
        or bool(metadata.get("media_condition"))
        or bool(metadata.get("sleeve_condition"))
    )
    readiness = {
        "photo_evidence": photo_evidence,
        "condition": "ready" if condition_ready else "missing",
        "price": "ready" if pricing.get("asking_price") is not None else "missing",
        "description": "ready" if item.get("description") else "missing",
    }
    readiness["overall"] = (
        "ready_basic"
        if all(
            [
                readiness["photo_evidence"] == "ready_basic",
                readiness["condition"] == "ready",
                readiness["price"] == "ready",
                readiness["description"] == "ready",
            ]
        )
        else "not_ready"
    )
    return readiness


def record_known_claims(identity: dict, coverage: dict) -> list[str]:
    claims = []
    if identity.get("artist") and identity.get("title"):
        claims.append("Artist and title confirmed by human review from front/back photos.")
    if coverage.get("cover_front", {}).get("status") == "approved":
        claims.append("Front cover photo approved.")
    if coverage.get("cover_back", {}).get("status") == "approved":
        claims.append("Back cover photo approved.")
    return claims


def record_unverified_claims(identity: dict, condition: dict, item: dict) -> list[str]:
    metadata = item.get("record_metadata", {})
    claims = []
    if not identity.get("pressing"):
        claims.append("Specific pressing/version is not confirmed.")
    if not identity.get("matrix_runout"):
        claims.append("Matrix/runout is not documented.")
    if not condition.get("media_condition"):
        claims.append("Media condition is not graded.")
    if not condition.get("sleeve_condition"):
        claims.append("Sleeve condition is not graded.")
    if not metadata.get("play_tested"):
        claims.append("Playback condition is not tested.")
    claims.append("Completeness such as inserts/posters is not confirmed.")
    return claims


def record_safe_listing_language(condition: dict) -> list[str]:
    safe = ["Used vinyl record."]
    if condition.get("visual_grade_only"):
        safe.append("Visual grade only unless otherwise noted.")
    safe.append("See photos for sleeve condition.")
    if not condition.get("play_tested"):
        safe.append("Playback not tested.")
    return safe


def record_avoid_claiming(identity: dict, condition: dict) -> list[str]:
    avoid = []
    if not identity.get("pressing") or not identity.get("catalog_number") or not identity.get("matrix_runout"):
        avoid.append("Do not claim first pressing without confirmation.")
    if not condition.get("media_condition") or not condition.get("sleeve_condition"):
        avoid.append("Do not claim near mint or excellent condition without grading evidence.")
    if not condition.get("play_tested"):
        avoid.append("Do not claim playback quality unless play-tested.")
    avoid.append("Do not claim complete inserts/posters unless documented.")
    return avoid


def record_next_steps(identity: dict, condition: dict, item: dict, coverage: dict) -> list[dict]:
    steps = []
    if not condition.get("media_condition") or not condition.get("sleeve_condition"):
        steps.append({"priority": "high", "task": "Add media and sleeve condition."})
    if item.get("pricing", {}).get("asking_price") is None:
        steps.append({"priority": "high", "task": "Choose asking price after comparable research."})
    if not identity.get("label") or not identity.get("catalog_number"):
        steps.append({"priority": "medium", "task": "Add label/catalog number if visible."})
    collector_roles = ["label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]
    if any(coverage.get(role, {}).get("status") == "missing" for role in collector_roles):
        steps.append({"priority": "medium", "task": "Capture label/vinyl/matrix photos if collector pricing matters."})
    return steps


def build_record_appraisal_context(project: dict, sale_item: dict, photo_edit: dict) -> dict:
    metadata = sale_item.get("record_metadata", {})
    captured_condition = {}
    condition_file = condition_path(project.get("project_id", ""))
    if condition_file.is_file():
        captured_condition = json.loads(condition_file.read_text(encoding="utf-8"))
    captured_grading = captured_condition.get("grading", {})
    identity = {
        "artist": blank_to_none(metadata.get("artist") or sale_item.get("artist")),
        "title": blank_to_none(metadata.get("title") or sale_item.get("title")),
        "label": blank_to_none(metadata.get("record_label") or sale_item.get("manufacturer")),
        "catalog_number": blank_to_none(metadata.get("catalog_number") or sale_item.get("model")),
        "pressing": blank_to_none(metadata.get("pressing")),
        "matrix_runout": blank_to_none(metadata.get("matrix_runout")),
    }
    coverage = role_coverage(photo_edit, RECORD_PHOTO_ROLES)
    condition = {
        "condition": blank_to_none(
            None
            if (captured_grading.get("overall_condition") or sale_item.get("condition", {}).get("overall")) == "unassessed"
            else (captured_grading.get("overall_condition") or sale_item.get("condition", {}).get("overall"))
        ),
        "media_condition": blank_to_none(captured_grading.get("media_condition") or metadata.get("media_condition")),
        "sleeve_condition": blank_to_none(captured_grading.get("sleeve_condition") or metadata.get("sleeve_condition")),
        "grading_note": blank_to_none(captured_grading.get("grading_note") or metadata.get("grading_note")),
        "play_tested": bool(captured_grading.get("playback_tested") or metadata.get("play_tested")),
        "visual_grade_only": bool(captured_grading.get("visual_grade_only", not bool(metadata.get("play_tested")))),
    }
    readiness = record_listing_readiness(sale_item, coverage)
    known_claims = record_known_claims(identity, coverage)
    unverified_claims = record_unverified_claims(identity, condition, sale_item)
    return {
        "project": project.get("project_id", ""),
        "category": sale_item.get("category", ""),
        "profile": "records",
        "identity": identity,
        "evidence": {
            "photo_coverage": coverage,
            "approved_photo_count": approved_photo_count(photo_edit),
            "minimum_listing_photos_met": (
                coverage.get("cover_front", {}).get("status") == "approved"
                and coverage.get("cover_back", {}).get("status") == "approved"
            ),
        },
        "condition": condition,
        "confirmed_facts": known_claims,
        "photo_evidence": coverage,
        "condition_grading_notes": condition,
        "unknowns": unverified_claims,
        "known_claims": known_claims,
        "unverified_claims": unverified_claims,
        "buyer_expectations": [
            "Record buyers care about pressing identity, media grade, sleeve grade, label/catalog details, and visible defects.",
            "Visual grade only should be disclosed unless playback has been tested.",
            "Front/back cover photos are enough for a basic local listing but not enough for high-confidence collector pricing.",
        ],
        "safe_listing_language": record_safe_listing_language(condition),
        "avoid_claiming": record_avoid_claiming(identity, condition),
        "next_steps": record_next_steps(identity, condition, sale_item, coverage),
        "listing_readiness": readiness,
    }


def build_generic_appraisal_context(project: dict, sale_item: dict, photo_edit: dict) -> dict:
    category = sale_item.get("category") or "unknown"
    images = photo_edit.get("images", []) if photo_edit else []
    roles = sorted({image.get("role") for image in images if image.get("role")})
    coverage = role_coverage(photo_edit, roles)
    return {
        "project": project.get("project_id", ""),
        "category": category,
        "profile": "generic",
        "identity": {
            "title": blank_to_none(sale_item.get("title") or project.get("name")),
            "manufacturer": blank_to_none(sale_item.get("manufacturer")),
            "model": blank_to_none(sale_item.get("model")),
        },
        "evidence": {
            "photo_coverage": coverage,
            "approved_photo_count": approved_photo_count(photo_edit),
        },
        "known_claims": ["Sale item metadata exists."] if sale_item else [],
        "unverified_claims": ["Category-specific appraisal rules are not configured."],
        "safe_listing_language": ["Used item."],
        "avoid_claiming": ["Do not claim condition, completeness, or functionality beyond documented evidence."],
        "next_steps": [{"priority": "medium", "task": "Add category-specific condition and pricing details."}],
        "listing_readiness": {
            "photo_evidence": "ready" if approved_photo_count(photo_edit) else "missing",
            "condition": "ready" if sale_item.get("condition", {}).get("overall") not in (None, "", "unassessed") else "missing",
            "price": "ready" if sale_item.get("pricing", {}).get("asking_price") is not None else "missing",
            "description": "ready" if sale_item.get("description") else "missing",
            "overall": "not_ready",
        },
    }


def build_appraisal_context(project_id_or_identifier: str) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    project = registry.load_project(project_id)
    sale_item = load_optional_sale_item(project_id)
    photo_edit = load_optional_photo_edit(project_id)
    if category_profile(sale_item) == "records":
        return build_record_appraisal_context(project, sale_item, photo_edit)
    return build_generic_appraisal_context(project, sale_item, photo_edit)


def render_appraisal_context_markdown(context: dict) -> str:
    if context.get("profile") == "records":
        return render_record_appraisal_context_markdown(context)
    return render_generic_appraisal_context_markdown(context)


def render_record_appraisal_context_markdown(context: dict) -> str:
    identity = context.get("identity", {})
    condition = context.get("condition", {})
    readiness = context.get("listing_readiness", {})
    coverage = context.get("evidence", {}).get("photo_coverage", {})
    functional = "not applicable" if context.get("category") == "records" else ""
    high_steps = [step["task"] for step in context.get("next_steps", []) if step.get("priority") == "high"]
    medium_steps = [step["task"] for step in context.get("next_steps", []) if step.get("priority") == "medium"]
    lines = [
        f"# Appraisal Context: {context.get('project', '')}",
        "",
        "## Item",
        "",
        f"{identity.get('artist') or '-'} - {identity.get('title') or '-'}",
        "",
        f"Category: {context.get('category', '')}  ",
        f"Functional status: {functional}",
        "",
        "## Confirmed facts",
        *(f"- {claim}" for claim in context.get("known_claims", [])),
        *(["- none"] if not context.get("known_claims") else []),
        "",
        "## Photo evidence",
        "",
        "| Role | Status | Files |",
        "|---|---|---|",
    ]
    for role in ["cover_front", "cover_back", "label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]:
        row = coverage.get(role, {"status": "missing", "files": []})
        files = ", ".join(row.get("files", [])) if row.get("files") else "-"
        lines.append(f"| {role} | {row.get('status', 'missing')} | {files} |")
    lines.extend(
        [
            "",
            "## Condition",
            "",
            f"Media condition: {display_missing(condition.get('media_condition'))}  ",
            f"Sleeve condition: {display_missing(condition.get('sleeve_condition'))}  ",
            f"Grading note: {display_missing(condition.get('grading_note'))}  ",
            f"Playback tested: {'yes' if condition.get('play_tested') else 'no'}  ",
            f"Visual grade only: {'yes' if condition.get('visual_grade_only') else 'no'}",
            "",
            "## Safe claims",
            *(f"- {claim}" for claim in context.get("safe_listing_language", [])),
            "",
            "## Do not claim yet",
            *(f"- {claim}" for claim in context.get("avoid_claiming", [])),
            "",
            "## Buyer expectations",
            "",
            " ".join(context.get("buyer_expectations", [])),
            "",
            "## Recommended next steps",
            "",
            "High:",
            *(f"- {task}" for task in high_steps),
            *(["- none"] if not high_steps else []),
            "",
            "Medium:",
            *(f"- {task}" for task in medium_steps),
            *(["- none"] if not medium_steps else []),
            "",
            "## Listing readiness",
            "",
            f"Photo evidence: {readiness.get('photo_evidence', '')}  ",
            f"Condition: {readiness.get('condition', '')}  ",
            f"Price: {readiness.get('price', '')}  ",
            f"Description: {readiness.get('description', '')}  ",
            f"Overall: {readiness.get('overall', '')}",
            "",
        ]
    )
    return "\n".join(lines)


def render_generic_appraisal_context_markdown(context: dict) -> str:
    readiness = context.get("listing_readiness", {})
    return "\n".join(
        [
            f"# Appraisal Context: {context.get('project', '')}",
            "",
            "## Item",
            "",
            f"Category: {context.get('category', '')}",
            f"Profile: {context.get('profile', '')}",
            "",
            "## Listing readiness",
            "",
            f"Photo evidence: {readiness.get('photo_evidence', '')}",
            f"Condition: {readiness.get('condition', '')}",
            f"Price: {readiness.get('price', '')}",
            f"Description: {readiness.get('description', '')}",
            f"Overall: {readiness.get('overall', '')}",
            "",
        ]
    )


def write_appraisal_context(project_id_or_identifier: str, context: Optional[dict] = None) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    context = context or build_appraisal_context(project_id)
    root = appraisal_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "context.json"
    md_path = root / "context.md"
    registry.write_json(json_path, context)
    md_path.write_text(render_appraisal_context_markdown(context), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def context_with_paths(project_id_or_identifier: str) -> tuple[dict, dict]:
    context = build_appraisal_context(project_id_or_identifier)
    paths = write_appraisal_context(project_id_or_identifier, context)
    return context, paths


def load_or_build_appraisal_context(project_id_or_identifier: str) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    path = context_path(project_id)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    context, _paths = context_with_paths(project_id)
    return context


def current_appraisal_context(project_id_or_identifier: str) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    if not context_path(project_id).is_file():
        context, _paths = context_with_paths(project_id)
        return context
    return build_appraisal_context(project_id)


def read_research(project_id_or_identifier: str) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    path = research_path(project_id)
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        return refresh_appraisal_research(project_id, existing)
    return build_appraisal_research(project_id)


def bool_arg(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def decimal_arg(value, field: str):
    if value in (None, ""):
        return None
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid decimal for {field}: {value}")


def validate_choice(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Invalid {field}: {value}")
    return normalized


def evidence_limits_from_context(context: dict) -> list[str]:
    limits = []
    unknowns = context.get("unknowns") or context.get("unverified_claims") or []
    mapping = {
        "Specific pressing/version is not confirmed.": "Pressing/version not confirmed",
        "Matrix/runout is not documented.": "Matrix/runout not documented",
        "Media condition is not graded.": "Media condition missing",
        "Sleeve condition is not graded.": "Sleeve condition missing",
        "Playback condition is not tested.": "Playback not tested",
    }
    for unknown in unknowns:
        if unknown in mapping:
            limits.append(mapping[unknown])
    return limits


def default_research_status(context: dict, entry_count: int, pricing_summary: dict) -> dict:
    reason = pricing_summary.get("rationale") or "Insufficient researched comparables."
    if entry_count == 0 and context.get("profile") == "records":
        reason = "No comparable research entries yet. Pressing and condition are not confirmed."
    return {
        "entry_count": entry_count,
        "pricing_confidence": pricing_summary.get("confidence", "low"),
        "reason": reason,
        "recommended_next_step": "Add condition notes and researched comparable sale entries.",
    }


def research_guardrails(context: dict) -> list[str]:
    if context.get("profile") == "records":
        return [
            "Do not price as a collector pressing without pressing/catalog/matrix confirmation.",
            "Do not compare against Near Mint copies unless media and sleeve condition support that comparison.",
            "Prefer sold-price comps over active listings.",
            "Disclose visual grade only unless playback has been tested.",
        ]
    return [
        "Do not price beyond documented category, condition, and comparable evidence.",
        "Prefer sold-price comps over active listings.",
    ]


def pricing_summary_for_research(context: dict, comparables: list[dict]) -> dict:
    priced = [entry for entry in comparables if entry.get("price") is not None]
    condition = context.get("condition", {})
    identity = context.get("identity", {})
    condition_missing = not condition.get("condition") and not condition.get("media_condition") and not condition.get("sleeve_condition")
    pressing_missing = not identity.get("pressing") or not identity.get("catalog_number") or not identity.get("matrix_runout")
    warnings = []
    if condition_missing:
        warnings.append("condition missing")
    if pressing_missing:
        warnings.append("pressing not confirmed")
    if not priced:
        rationale = (
            "No researched comparables. Pressing and condition are not confirmed."
            if context.get("profile") == "records"
            else "Insufficient researched comparables."
        )
        return {
            "low": None,
            "high": None,
            "suggested_asking_price": None,
            "confidence": "low",
            "rationale": rationale,
            "warnings": warnings,
        }
    if all(entry.get("match_confidence") == "low" for entry in priced):
        return {
            "low": None,
            "high": None,
            "suggested_asking_price": None,
            "confidence": "low",
            "rationale": "Comparable exists but match/condition confidence is low.",
            "warnings": warnings,
        }
    sold_relevant = [
        entry
        for entry in priced
        if entry.get("sold")
        and entry.get("match_confidence") in {"medium", "high"}
        and entry.get("price_confidence") in {"medium", "high"}
    ]
    if len(sold_relevant) >= 2:
        prices = [float(entry["price"]) for entry in sold_relevant]
        low = min(prices)
        high = max(prices)
        confidence = "medium"
        suggested = None if condition_missing or pressing_missing else round((low + high) / 2)
        rationale = "Observed range from medium/high confidence sold comparables."
        if condition_missing or pressing_missing:
            rationale += " Recommendation remains conservative because condition or pressing evidence is incomplete."
        return {
            "low": low,
            "high": high,
            "suggested_asking_price": suggested,
            "confidence": confidence,
            "rationale": rationale,
            "warnings": warnings,
        }
    return {
        "low": None,
        "high": None,
        "suggested_asking_price": None,
        "confidence": "low",
        "rationale": "Comparables exist, but sold-price confidence is insufficient for a price range.",
        "warnings": warnings,
    }


def build_appraisal_research(project_id_or_identifier: str, comparables: Optional[list] = None, manual_notes: Optional[list] = None) -> dict:
    context = current_appraisal_context(project_id_or_identifier)
    comparables = comparables or []
    manual_notes = manual_notes or []
    pricing_summary = pricing_summary_for_research(context, comparables)
    entry_count = len(comparables) + len(manual_notes)
    return {
        "project": context.get("project", ""),
        "category": context.get("category", ""),
        "profile": context.get("profile", "generic"),
        "identity": context.get("identity", {}),
        "research_status": default_research_status(context, entry_count, pricing_summary),
        "evidence_limits": evidence_limits_from_context(context),
        "listing_readiness": context.get("listing_readiness", {}),
        "comparables": comparables,
        "manual_notes": manual_notes,
        "pricing_summary": pricing_summary,
        "guardrails": research_guardrails(context),
        "generated_at": registry_module().utc_now(),
    }


def refresh_appraisal_research(project_id_or_identifier: str, existing: dict) -> dict:
    refreshed = build_appraisal_research(
        project_id_or_identifier,
        comparables=existing.get("comparables", []),
        manual_notes=existing.get("manual_notes", []),
    )
    if "pricing_history" in existing:
        refreshed["pricing_history"] = existing["pricing_history"]
    return refreshed


def write_appraisal_research(project_id_or_identifier: str, research: Optional[dict] = None) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    research = refresh_appraisal_research(project_id, research or read_research(project_id))
    research["generated_at"] = registry.utc_now()
    root = appraisal_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    json_path = research_path(project_id)
    md_path = research_markdown_path(project_id)
    registry.write_json(json_path, research)
    md_path.write_text(render_appraisal_research_markdown(research), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def next_id(rows: list[dict], prefix: str) -> str:
    numbers = []
    for row in rows:
        text = str(row.get("id", ""))
        if text.startswith(prefix + "-"):
            try:
                numbers.append(int(text.split("-", 1)[1]))
            except ValueError:
                continue
    return f"{prefix}-{(max(numbers) + 1 if numbers else 1):03d}"


def add_appraisal_research_entry(project_id_or_identifier: str, **values) -> tuple[dict, dict]:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    context = current_appraisal_context(project_id)
    research = read_research(project_id)
    source_type = validate_choice(values.get("source_type") or "other", SOURCE_TYPES, "source type")
    price = decimal_arg(values.get("price"), "price")
    observed_date = values.get("observed_date") or registry.utc_now()[:10]
    confidence = validate_choice(values.get("confidence") or "low", CONFIDENCE_VALUES, "confidence")
    identity = context.get("identity", {})
    if price is None:
        note = {
            "id": next_id(research.get("manual_notes", []), "note"),
            "source": values.get("source") or "",
            "source_type": source_type,
            "observed_date": observed_date,
            "note": values.get("note") or "",
            "confidence": confidence,
        }
        research.setdefault("manual_notes", []).append(note)
        entry = note
    else:
        comparable = {
            "id": next_id(research.get("comparables", []), "comp"),
            "source": values.get("source") or "",
            "source_type": source_type,
            "url": blank_to_none(values.get("url")),
            "observed_date": observed_date,
            "artist": blank_to_none(values.get("artist") or identity.get("artist")),
            "title": blank_to_none(values.get("title") or identity.get("title")),
            "label": blank_to_none(values.get("label") or identity.get("label")),
            "catalog_number": blank_to_none(values.get("catalog_number") or identity.get("catalog_number")),
            "pressing": blank_to_none(values.get("pressing") or identity.get("pressing")),
            "format": values.get("format") or ("LP" if context.get("profile") == "records" else ""),
            "condition_media": blank_to_none(values.get("condition_media")),
            "condition_sleeve": blank_to_none(values.get("condition_sleeve")),
            "price": price,
            "currency": values.get("currency") or "USD",
            "sold": bool_arg(values.get("sold"), False),
            "shipping_included": bool_arg(values.get("shipping_included"), False),
            "match_confidence": validate_choice(values.get("match_confidence") or "low", CONFIDENCE_VALUES, "match confidence"),
            "price_confidence": validate_choice(values.get("price_confidence") or "low", CONFIDENCE_VALUES, "price confidence"),
            "notes": values.get("note") or "",
        }
        research.setdefault("comparables", []).append(comparable)
        entry = comparable
    paths = write_appraisal_research(project_id, research)
    return entry, paths


def render_price(value, currency="USD") -> str:
    if value is None:
        return "-"
    return f"${float(value):.2f} {currency}"


def render_appraisal_research_markdown(research: dict) -> str:
    identity = research.get("identity", {})
    pricing = research.get("pricing_summary", {})
    range_text = "-"
    if pricing.get("low") is not None and pricing.get("high") is not None:
        range_text = f"${pricing['low']:.2f} - ${pricing['high']:.2f} USD"
    lines = [
        f"# Appraisal Research: {research.get('project', '')}",
        "",
        "## Item",
        "",
        f"{identity.get('artist') or '-'} - {identity.get('title') or '-'}",
        "",
        f"Category: {research.get('category', '')}  ",
        f"Pricing confidence: {pricing.get('confidence', 'low')}",
        "",
        "## Current evidence limits",
        "",
    ]
    limits = research.get("evidence_limits", [])
    lines.extend([f"- {limit}." for limit in limits] or ["- none"])
    lines.extend(["", "## Comparables", ""])
    if research.get("comparables"):
        lines.extend(
            [
                "| ID | Source | Sold | Price | Match | Price confidence | Notes |",
                "|---|---|---:|---:|---|---|---|",
            ]
        )
        for entry in research["comparables"]:
            sold = "yes" if entry.get("sold") else "no"
            lines.append(
                f"| {entry.get('id', '')} | {entry.get('source', '')} | {sold} | "
                f"{render_price(entry.get('price'), entry.get('currency') or 'USD')} | "
                f"{entry.get('match_confidence', '')} | {entry.get('price_confidence', '')} | "
                f"{entry.get('notes', '')} |"
            )
    else:
        lines.append("No comparable entries yet.")
    lines.extend(["", "## Manual notes", ""])
    if research.get("manual_notes"):
        for note in research["manual_notes"]:
            lines.append(f"- {note.get('id', '')} {note.get('source', '')}: {note.get('note', '')}")
    else:
        lines.append("No manual notes yet.")
    lines.extend(
        [
            "",
            "## Pricing summary",
            "",
            f"Suggested asking price: {render_price(pricing.get('suggested_asking_price'))}  ",
            f"Range: {range_text}  ",
            f"Confidence: {pricing.get('confidence', 'low')}  ",
            "",
            f"Rationale: {pricing.get('rationale', '')}",
            "",
            "## Guardrails",
            "",
            *(f"- {guardrail}" for guardrail in research.get("guardrails", [])),
            "",
        ]
    )
    return "\n".join(lines)


def approved_role_files_from_context(context: dict) -> dict:
    coverage = context.get("evidence", {}).get("photo_coverage", {})
    return {
        role: row.get("files", [])
        for role, row in coverage.items()
        if row.get("status") == "approved" and row.get("files")
    }


def year_from_text(*values) -> Optional[str]:
    for value in values:
        match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
        if match:
            return match.group(1)
    return None


def record_visual_note(item: dict, research: dict) -> str:
    metadata = item.get("record_metadata", {})
    if metadata.get("grading_note"):
        return metadata["grading_note"]
    for note in research.get("manual_notes", []):
        text = note.get("note", "")
        if "spine" in text.lower() or "printed in" in text.lower():
            return text
    return ""


def record_draft_title(identity: dict) -> str:
    base = " - ".join(value for value in [identity.get("artist"), identity.get("title")] if value) or "Used vinyl record"
    if identity.get("label") and identity.get("catalog_number"):
        title_label = re.sub(r"\s+Records\b", "", identity["label"], flags=re.IGNORECASE).strip()
        return f"{base} LP - {title_label} {identity['catalog_number']}"
    return f"{base} LP"


def record_readiness(item: dict, context: dict, draft_description: str) -> dict:
    identity = context.get("identity", {})
    condition = context.get("condition", {})
    pricing = item.get("pricing", {})
    photo_roles = approved_role_files_from_context(context)
    has_front_back = bool(photo_roles.get("cover_front")) and bool(photo_roles.get("cover_back"))
    has_condition = (
        item.get("condition", {}).get("overall") not in (None, "", "unassessed")
        or bool(condition.get("media_condition"))
        or bool(condition.get("sleeve_condition"))
    )
    has_price = pricing.get("asking_price") is not None
    missing = []
    if not has_front_back:
        missing.append("front_back_photos")
    if not has_condition:
        missing.append("condition")
    if not has_price:
        missing.append("asking_price")
    if not draft_description:
        missing.append("description")
    can_publish = not missing
    collector_roles = ["label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]
    collector_photos = all(photo_roles.get(role) for role in collector_roles)
    if can_publish and collector_photos and identity.get("pressing") and identity.get("matrix_runout"):
        state = "ready_collector"
    elif can_publish:
        state = "ready_basic"
    elif "condition" in missing:
        state = "needs_condition"
    elif "asking_price" in missing:
        state = "needs_price"
    else:
        state = "draft_context_only"
    reasons = []
    if "condition" in missing:
        reasons.append("Condition")
    if "asking_price" in missing:
        reasons.append("asking price")
    reason = " and ".join(reasons) + " are missing." if reasons else "Draft is ready for basic publication."
    warnings = []
    if not condition.get("play_tested"):
        warnings.append("Playback not tested.")
    if not identity.get("pressing"):
        warnings.append("Pressing/version not confirmed.")
    if not condition.get("media_condition") and not condition.get("sleeve_condition"):
        warnings.append("Media and sleeve condition are not graded.")
    return {
        "can_publish": can_publish,
        "state": state,
        "reason": reason,
        "missing": missing,
        "warnings": warnings,
    }


def record_condition_disclosure(condition: dict) -> str:
    parts = []
    if condition.get("media_condition"):
        parts.append(f"Media condition: {condition['media_condition']}, visually graded.")
    else:
        parts.append("Media condition: not yet graded.")
    if condition.get("sleeve_condition"):
        parts.append(f"Sleeve condition: {condition['sleeve_condition']}.")
    else:
        parts.append("Sleeve condition: not yet graded.")
    parts.append("Playback tested: yes." if condition.get("play_tested") else "Playback has not been tested.")
    if condition.get("visual_grade_only"):
        parts.append("Visual grade only.")
    return "\n".join(parts)


def record_full_description(identity: dict, condition: dict, visual_note: str) -> str:
    title = identity.get("title") or "this record"
    artist = identity.get("artist") or "the artist"
    label = identity.get("label")
    catalog = identity.get("catalog_number")
    if label and catalog:
        first = f"Used copy of {title} by {artist} on {label}, catalog number {catalog}."
    else:
        first = f"Used copy of {title} by {artist}."
    lines = [first]
    if visual_note:
        lines.append(f"Visual inspection note: {visual_note}")
    if not condition.get("play_tested"):
        lines.append("Playback has not been tested.")
    if not condition.get("media_condition") and not condition.get("sleeve_condition"):
        lines.append("Media and sleeve condition are not yet graded.")
    else:
        if condition.get("media_condition"):
            lines.append(f"Media condition: {condition['media_condition']}, visually graded.")
        if condition.get("sleeve_condition"):
            lines.append(f"Sleeve condition: {condition['sleeve_condition']}.")
    lines.append("Please review the photos for visible sleeve condition.")
    return "\n\n".join(lines)


def record_safe_claims(identity: dict, context: dict, condition: dict, photo_roles: dict, visual_note: str) -> list[str]:
    claims = ["Used vinyl record."]
    if identity.get("label") and identity.get("catalog_number"):
        claims.append(f"{identity['label']} {identity['catalog_number']}.")
    if "PRINTED IN U.S.A" in visual_note.upper() or "PRINTED IN U.S.A." in visual_note.upper():
        claims.append("Printed in U.S.A. text observed.")
    if photo_roles.get("cover_front") and photo_roles.get("cover_back"):
        claims.append("Front and back cover photos are available.")
    if not condition.get("play_tested"):
        claims.append("Playback not tested.")
    for claim in context.get("safe_listing_language", []):
        if claim not in claims:
            claims.append(claim)
    return claims


def record_avoid_claims(context: dict) -> list[str]:
    return [
        "Do not claim first pressing.",
        "Do not claim specific pressing/version.",
        "Do not claim playback quality.",
        "Do not claim Near Mint/Excellent condition.",
        "Do not claim inserts/posters are included.",
    ]


def record_draft_next_steps(readiness: dict) -> list[dict]:
    steps = []
    if "condition" in readiness.get("missing", []):
        steps.append({"priority": "high", "task": "Add media and sleeve condition."})
    if "asking_price" in readiness.get("missing", []):
        steps.append({"priority": "high", "task": "Set asking price."})
    steps.append({"priority": "medium", "task": "Capture label/vinyl/matrix photos if collector pricing matters."})
    return steps


def build_record_listing_draft_context(project_id_or_identifier: str, item: dict, context: dict, research: dict) -> dict:
    identity = dict(context.get("identity", {}))
    visual_note = record_visual_note(item, research)
    identity["year"] = year_from_text(visual_note, item.get("title"))
    condition = {
        "condition": item.get("condition", {}).get("overall") or "unassessed",
        "media_condition": context.get("condition", {}).get("media_condition"),
        "sleeve_condition": context.get("condition", {}).get("sleeve_condition"),
        "grading_note": context.get("condition", {}).get("grading_note") or visual_note or None,
        "playback_tested": bool(context.get("condition", {}).get("play_tested")),
        "visual_grade_only": bool(context.get("condition", {}).get("visual_grade_only", True)),
    }
    photo_roles = approved_role_files_from_context(context)
    pricing = item.get("pricing", {})
    research_pricing = research.get("pricing_summary", {})
    title = record_draft_title(identity)
    full_description = record_full_description(identity, condition, visual_note)
    readiness = record_readiness(item, context, full_description)
    pricing_note = research_pricing.get("rationale") or "Price pending until condition and comps are confirmed."
    if pricing.get("asking_price") is not None and research_pricing.get("confidence") == "low":
        readiness.setdefault("warnings", []).append("Pricing confidence low.")
    return {
        "project": registry_module().find_project(project_id_or_identifier),
        "category": item.get("category", ""),
        "profile": context.get("profile", "generic"),
        "readiness": readiness,
        "identity": identity,
        "photo_evidence": {
            "approved_photo_count": context.get("evidence", {}).get("approved_photo_count", 0),
            "roles": photo_roles,
        },
        "pricing": {
            "asking_price": pricing.get("asking_price"),
            "research_confidence": research_pricing.get("confidence", "low"),
            "suggested_asking_price": research_pricing.get("suggested_asking_price"),
            "pricing_note": pricing_note,
        },
        "condition": condition,
        "safe_claims": record_safe_claims(identity, context, condition, photo_roles, visual_note),
        "avoid_claiming": record_avoid_claims(context),
        "drafts": {
            "title": title,
            "short_description": (
                f"Used copy of {identity.get('artist') or 'the artist'} - {identity.get('title') or 'this record'}"
                + (f" on {identity.get('label')}, catalog {identity.get('catalog_number')}." if identity.get("label") and identity.get("catalog_number") else ".")
                + " Playback not tested. See photos for sleeve condition."
            ),
            "full_description": full_description,
            "condition_disclosure": record_condition_disclosure(condition),
            "photo_note": "Front and back cover photos are available." if photo_roles.get("cover_front") and photo_roles.get("cover_back") else "Photo coverage is incomplete.",
            "pricing_disclosure": "Price pending until condition and comps are confirmed." if pricing.get("asking_price") is None else f"Asking price: ${pricing.get('asking_price')}.",
        },
        "next_steps": record_draft_next_steps(readiness),
        "generated_at": registry_module().utc_now(),
    }


def build_generic_listing_draft_context(project_id_or_identifier: str, item: dict, context: dict, research: dict) -> dict:
    pricing = item.get("pricing", {})
    missing = []
    if item.get("condition", {}).get("overall") in (None, "", "unassessed"):
        missing.append("condition")
    if pricing.get("asking_price") is None:
        missing.append("asking_price")
    return {
        "project": registry_module().find_project(project_id_or_identifier),
        "category": item.get("category") or context.get("category", "unknown"),
        "profile": "generic",
        "readiness": {
            "can_publish": not missing,
            "state": "ready_basic" if not missing else "draft_context_only",
            "reason": "Condition or asking price is missing." if missing else "Draft is ready for basic publication.",
            "missing": missing,
            "warnings": ["Category-specific listing draft rules are not configured."],
        },
        "identity": context.get("identity", {}),
        "photo_evidence": {
            "approved_photo_count": context.get("evidence", {}).get("approved_photo_count", 0),
            "roles": approved_role_files_from_context(context),
        },
        "pricing": {
            "asking_price": pricing.get("asking_price"),
            "research_confidence": research.get("pricing_summary", {}).get("confidence", "low"),
            "suggested_asking_price": research.get("pricing_summary", {}).get("suggested_asking_price"),
            "pricing_note": research.get("pricing_summary", {}).get("rationale", ""),
        },
        "condition": item.get("condition", {}),
        "safe_claims": context.get("safe_listing_language", []),
        "avoid_claiming": context.get("avoid_claiming", []),
        "drafts": {
            "title": item.get("title") or context.get("identity", {}).get("title") or "Used item",
            "short_description": "Used item. See photos and notes for condition.",
            "full_description": "Used item. See photos and notes for condition.",
            "condition_disclosure": "Condition details should be confirmed before posting.",
            "photo_note": "See approved listing photos.",
            "pricing_disclosure": "Price pending until condition and comps are confirmed." if pricing.get("asking_price") is None else f"Asking price: ${pricing.get('asking_price')}.",
        },
        "next_steps": [{"priority": "medium", "task": "Add category-specific listing details."}],
        "generated_at": registry_module().utc_now(),
    }


def build_listing_draft_context(project_id_or_identifier: str) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    item = load_optional_sale_item(project_id)
    context = current_appraisal_context(project_id)
    write_appraisal_context(project_id, context)
    research = read_research(project_id)
    write_appraisal_research(project_id, research)
    if context.get("profile") == "records":
        return build_record_listing_draft_context(project_id, item, context, research)
    return build_generic_listing_draft_context(project_id, item, context, research)


def write_listing_draft_context(project_id_or_identifier: str, draft: Optional[dict] = None) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    draft = draft or build_listing_draft_context(project_id)
    root = listing_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    json_path = listing_draft_context_path(project_id)
    md_path = listing_draft_markdown_path(project_id)
    registry.write_json(json_path, draft)
    md_path.write_text(render_listing_draft_markdown(draft), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def listing_draft_with_paths(project_id_or_identifier: str) -> tuple[dict, dict]:
    draft = build_listing_draft_context(project_id_or_identifier)
    paths = write_listing_draft_context(project_id_or_identifier, draft)
    return draft, paths


def render_listing_draft_markdown(draft: dict) -> str:
    if draft.get("profile") == "records":
        return render_record_listing_draft_markdown(draft)
    return render_generic_listing_draft_markdown(draft)


def render_record_listing_draft_markdown(draft: dict) -> str:
    readiness = draft.get("readiness", {})
    drafts = draft.get("drafts", {})
    condition = draft.get("condition", {})
    pricing = draft.get("pricing", {})
    high_steps = [step["task"] for step in draft.get("next_steps", []) if step.get("priority") == "high"]
    medium_steps = [step["task"] for step in draft.get("next_steps", []) if step.get("priority") == "medium"]
    lines = [
        f"# Listing Draft: {draft.get('project', '')}",
        "",
        "## Status",
        "",
        f"Publish ready: {'yes' if readiness.get('can_publish') else 'no'}  ",
        f"Reason: {readiness.get('reason', '')}",
        "",
        "## Draft title",
        "",
        drafts.get("title", ""),
        "",
        "## Draft description",
        "",
        drafts.get("full_description", ""),
        "",
        "## Condition disclosure",
        "",
        f"- Media condition: {condition.get('media_condition') or 'not yet graded'}",
        f"- Sleeve condition: {condition.get('sleeve_condition') or 'not yet graded'}",
        f"- Playback tested: {'yes' if condition.get('playback_tested') else 'no'}",
        f"- Visual grade only: {'yes' if condition.get('visual_grade_only') else 'no'}",
        "",
        "## Pricing",
        "",
        f"Asking price: {render_price(pricing.get('asking_price')) if pricing.get('asking_price') is not None else 'not set'}  ",
        f"Pricing confidence: {pricing.get('research_confidence', 'low')}  ",
        f"Suggested asking price: {render_price(pricing.get('suggested_asking_price'))}  ",
        f"Pricing note: {pricing.get('pricing_note', '')}",
        "",
        "## Photos",
        "",
        "Approved listing photos:",
    ]
    roles = draft.get("photo_evidence", {}).get("roles", {})
    for role in ["cover_front", "cover_back", "label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]:
        if roles.get(role):
            lines.append(f"- {role}: {', '.join(roles[role])}")
    lines.extend(["", "## Safe claims"])
    lines.extend(f"- {claim}" for claim in draft.get("safe_claims", []))
    lines.extend(["", "## Do not claim"])
    claim_labels = {
        "Do not claim first pressing.": "First pressing.",
        "Do not claim specific pressing/version.": "Specific pressing/version.",
        "Do not claim playback quality.": "Playback quality.",
        "Do not claim Near Mint/Excellent condition.": "Near Mint or Excellent condition.",
        "Do not claim inserts/posters are included.": "Complete inserts/posters.",
    }
    lines.extend(f"- {claim_labels.get(claim, claim)}" for claim in draft.get("avoid_claiming", []))
    lines.extend(
        [
            "",
            "## Next steps before posting",
            "",
            "High:",
            *(f"- {task}" for task in high_steps),
            *(["- none"] if not high_steps else []),
            "",
            "Medium:",
            *(f"- {task}" for task in medium_steps),
            *(["- none"] if not medium_steps else []),
            "",
        ]
    )
    return "\n".join(lines)


def render_generic_listing_draft_markdown(draft: dict) -> str:
    readiness = draft.get("readiness", {})
    return "\n".join(
        [
            f"# Listing Draft: {draft.get('project', '')}",
            "",
            f"Publish ready: {'yes' if readiness.get('can_publish') else 'no'}",
            f"State: {readiness.get('state', '')}",
            "",
            "## Draft title",
            "",
            draft.get("drafts", {}).get("title", ""),
            "",
        ]
    )


def print_appraisal_context_summary(context: dict, paths: dict) -> None:
    print(f"Appraisal Context: {context.get('project', '')}")
    print(f"Category: {context.get('category', '')}")
    print(f"Profile: {context.get('profile', '')}")
    print()
    if context.get("profile") == "records":
        print_record_summary(context)
    else:
        readiness = context.get("listing_readiness", {})
        print("Listing readiness:")
        for key in ["photo_evidence", "condition", "price", "description", "overall"]:
            print(f"  {key.replace('_', ' ').title()}: {readiness.get(key, '')}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def print_record_summary(context: dict) -> None:
    identity = context.get("identity", {})
    condition = context.get("condition", {})
    readiness = context.get("listing_readiness", {})
    coverage = context.get("evidence", {}).get("photo_coverage", {})
    print("Identity:")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print()
    print("Evidence:")
    for role in ["cover_front", "cover_back", "label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]:
        print(f"  {role}: {coverage.get(role, {}).get('status', 'missing')}")
    print()
    print("Condition:")
    print(f"  Media: {display_missing(condition.get('media_condition'))}")
    print(f"  Sleeve: {display_missing(condition.get('sleeve_condition'))}")
    print(f"  Playback tested: {'yes' if condition.get('play_tested') else 'no'}")
    print(f"  Visual grade only: {'yes' if condition.get('visual_grade_only') else 'no'}")
    print()
    print("Listing readiness:")
    print(f"  Photo evidence: {readiness.get('photo_evidence', '')}")
    print(f"  Condition: {readiness.get('condition', '')}")
    print(f"  Price: {readiness.get('price', '')}")
    print(f"  Description: {readiness.get('description', '')}")
    print(f"  Overall: {readiness.get('overall', '')}")
    print()
    print("Next steps:")
    for step in context.get("next_steps", []):
        print(f"  {step.get('priority', '').upper()} {step.get('task', '')}")


def research_with_paths(project_id_or_identifier: str) -> tuple[dict, dict]:
    research = read_research(project_id_or_identifier)
    paths = write_appraisal_research(project_id_or_identifier, research)
    return research, paths


def print_appraisal_research_summary(research: dict, paths: dict) -> None:
    identity = research.get("identity", {})
    status = research.get("research_status", {})
    pricing = research.get("pricing_summary", {})
    print(f"Appraisal Research: {research.get('project', '')}")
    print(f"Category: {research.get('category', '')}")
    print(f"Profile: {research.get('profile', '')}")
    print()
    print("Identity:")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print(f"  Pressing: {identity.get('pressing') or '-'}")
    print(f"  Matrix/runout: {identity.get('matrix_runout') or '-'}")
    print()
    print("Research:")
    print(f"  Comparables: {len(research.get('comparables', []))}")
    print(f"  Manual notes: {len(research.get('manual_notes', []))}")
    print(f"  Pricing confidence: {status.get('pricing_confidence', pricing.get('confidence', 'low'))}")
    print(f"  Suggested asking price: {render_price(pricing.get('suggested_asking_price'))}")
    print(f"  Reason: {status.get('reason') or pricing.get('rationale', '')}")
    print()
    print("Evidence limits:")
    for limit in research.get("evidence_limits", []):
        print(f"  {limit}")
    print()
    print("Next step:")
    print(f"  {status.get('recommended_next_step', '')}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def print_listing_draft_summary(draft: dict, paths: dict) -> None:
    readiness = draft.get("readiness", {})
    pricing = draft.get("pricing", {})
    print(f"Listing Draft Context: {draft.get('project', '')}")
    print(f"Category: {draft.get('category', '')}")
    print(f"Profile: {draft.get('profile', '')}")
    print()
    print("Draft title:")
    print(f"  {draft.get('drafts', {}).get('title', '')}")
    print()
    print("Readiness:")
    print(f"  Can publish: {'yes' if readiness.get('can_publish') else 'no'}")
    print(f"  State: {readiness.get('state', '')}")
    print(f"  Missing: {', '.join(readiness.get('missing', [])) if readiness.get('missing') else '-'}")
    print()
    print("Warnings:")
    for warning in readiness.get("warnings", []):
        print(f"  {warning.rstrip('.')}")
    print()
    print("Photos:")
    roles = draft.get("photo_evidence", {}).get("roles", {})
    for role in ["cover_front", "cover_back", "label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]:
        if roles.get(role):
            print(f"  {role}: {', '.join(roles[role])}")
    print()
    print("Pricing:")
    asking = pricing.get("asking_price")
    print(f"  Asking price: {render_price(asking) if asking is not None else '-'}")
    print(f"  Research confidence: {pricing.get('research_confidence', 'low')}")
    print(f"  Suggested asking price: {render_price(pricing.get('suggested_asking_price'))}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def print_record_condition_summary(condition: dict, paths: dict) -> None:
    identity = condition.get("identity", {})
    grading = condition.get("grading", {})
    sleeve = condition.get("sleeve_observations", {})
    media = condition.get("media_observations", {})
    included = condition.get("included_materials", {})
    print(f"Record Condition: {condition.get('project', '')}")
    print(f"Category: {condition.get('category', '')}")
    print()
    print("Identity:")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print()
    print("Grading:")
    print(f"  Media condition: {display_missing(grading.get('media_condition'))}")
    print(f"  Sleeve condition: {display_missing(grading.get('sleeve_condition'))}")
    print(f"  Overall condition: {grading.get('overall_condition', 'unassessed')}")
    print(f"  Grading standard: {grading.get('grading_standard', 'visual')}")
    print(f"  Playback tested: {'yes' if grading.get('playback_tested') else 'no'}")
    print(f"  Visual grade only: {'yes' if grading.get('visual_grade_only') else 'no'}")
    print(f"  Confidence: {grading.get('confidence', 'low')}")
    print()
    print("Sleeve observations:")
    print(f"  Poly sleeve: {display_unknown(included.get('poly_sleeve'))}")
    print(f"  Spine readable: {display_unknown(sleeve.get('spine_readable'))}")
    print(f"  Ring wear: {display_unknown(sleeve.get('ring_wear'))}")
    print(f"  Shelf wear: {display_unknown(sleeve.get('shelf_wear'))}")
    print(f"  Corner wear: {display_unknown(sleeve.get('corner_wear'))}")
    print(f"  Seam split: {display_unknown(sleeve.get('seam_split'))}")
    print()
    print("Media observations:")
    print(f"  Scratches: {display_unknown(media.get('scratches'))}")
    print(f"  Scuffs: {display_unknown(media.get('scuffs'))}")
    print(f"  Warping: {display_unknown(media.get('warping'))}")
    print(f"  Dust: {display_unknown(media.get('dust'))}")
    print()
    print("Safe disclosure:")
    for item in condition.get("safe_disclosure", []):
        print(f"  {item}")
    print()
    print("Next steps:")
    for step in condition.get("next_steps", []):
        print(f"  {step.get('priority', '').upper()} {step.get('task', '')}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def command_appraisal_context(args):
    context, paths = context_with_paths(args.identifier)
    if args.json:
        print(json.dumps(context, indent=2))
    else:
        print_appraisal_context_summary(context, paths)


def command_appraisal_context_export(args):
    context, paths = context_with_paths(args.identifier)
    if getattr(args, "json", False):
        print(json.dumps({"context": context, "paths": paths}, indent=2))
    else:
        print("Appraisal context exported:")
        print(f"  {paths['json']}")
        print(f"  {paths['md']}")


def command_appraisal_research(args):
    research, paths = research_with_paths(args.identifier)
    if args.json:
        print(json.dumps(research, indent=2))
    else:
        print_appraisal_research_summary(research, paths)


def command_appraisal_research_add(args):
    values = vars(args).copy()
    values.pop("identifier", None)
    values.pop("func", None)
    values.pop("json", None)
    try:
        entry, paths = add_appraisal_research_entry(args.identifier, **values)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps({"entry": entry, "paths": paths}, indent=2))
    else:
        print(f"Added appraisal research: {entry.get('id', '')}")
        print("Wrote:")
        print(f"  {paths['json']}")
        print(f"  {paths['md']}")


def command_appraisal_research_export(args):
    research, paths = research_with_paths(args.identifier)
    if getattr(args, "json", False):
        print(json.dumps({"research": research, "paths": paths}, indent=2))
    else:
        print("Appraisal research exported:")
        print(f"  {paths['json']}")
        print(f"  {paths['md']}")


def command_listing_draft_context(args):
    draft, paths = listing_draft_with_paths(args.identifier)
    if args.json:
        print(json.dumps(draft, indent=2))
    else:
        print_listing_draft_summary(draft, paths)


def command_listing_draft_export(args):
    draft, paths = listing_draft_with_paths(args.identifier)
    if getattr(args, "json", False):
        print(json.dumps({"draft": draft, "paths": paths}, indent=2))
    else:
        print("Listing draft exported:")
        print(f"  {paths['json']}")
        print(f"  {paths['md']}")


def command_record_condition(args):
    condition, paths = record_condition_with_paths(args.identifier)
    if args.json:
        print(json.dumps(condition, indent=2))
    else:
        print_record_condition_summary(condition, paths)


def command_record_condition_update(args):
    values = vars(args).copy()
    values.pop("identifier", None)
    values.pop("func", None)
    values.pop("json", None)
    try:
        condition, paths = record_condition_update(args.identifier, **values)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(condition, indent=2))
    else:
        print_record_condition_summary(condition, paths)


def command_record_condition_export(args):
    condition, paths = record_condition_with_paths(args.identifier)
    if getattr(args, "json", False):
        print(json.dumps({"condition": condition, "paths": paths}, indent=2))
    else:
        print("Record condition exported:")
        print(f"  {paths['json']}")
        print(f"  {paths['md']}")


def register_appraisal_context_subcommands(projects_sub) -> None:
    context_p = projects_sub.add_parser("appraisal-context", help="Build appraisal context for a project")
    context_p.add_argument("identifier")
    context_p.add_argument("--json", action="store_true")
    context_p.set_defaults(func=command_appraisal_context)

    export_p = projects_sub.add_parser("appraisal-context-export", help="Write appraisal context files")
    export_p.add_argument("identifier")
    export_p.add_argument("--json", action="store_true")
    export_p.set_defaults(func=command_appraisal_context_export)

    research_p = projects_sub.add_parser("appraisal-research", help="Show appraisal research for a project")
    research_p.add_argument("identifier")
    research_p.add_argument("--json", action="store_true")
    research_p.set_defaults(func=command_appraisal_research)

    add_p = projects_sub.add_parser("appraisal-research-add", help="Append appraisal comparable or note")
    add_p.add_argument("identifier")
    add_p.add_argument("--source", required=True)
    add_p.add_argument("--source-type", choices=sorted(SOURCE_TYPES), default="other")
    add_p.add_argument("--price")
    add_p.add_argument("--currency", default="USD")
    add_p.add_argument("--sold", default="false")
    add_p.add_argument("--shipping-included", default="false")
    add_p.add_argument("--match-confidence", choices=sorted(CONFIDENCE_VALUES), default="low")
    add_p.add_argument("--price-confidence", choices=sorted(CONFIDENCE_VALUES), default="low")
    add_p.add_argument("--confidence", choices=sorted(CONFIDENCE_VALUES), default="low")
    add_p.add_argument("--note", default="")
    add_p.add_argument("--url")
    add_p.add_argument("--observed-date")
    add_p.add_argument("--artist")
    add_p.add_argument("--title")
    add_p.add_argument("--label")
    add_p.add_argument("--catalog-number")
    add_p.add_argument("--pressing")
    add_p.add_argument("--format")
    add_p.add_argument("--condition-media")
    add_p.add_argument("--condition-sleeve")
    add_p.add_argument("--json", action="store_true")
    add_p.set_defaults(func=command_appraisal_research_add)

    research_export_p = projects_sub.add_parser("appraisal-research-export", help="Write appraisal research files")
    research_export_p.add_argument("identifier")
    research_export_p.add_argument("--json", action="store_true")
    research_export_p.set_defaults(func=command_appraisal_research_export)

    draft_p = projects_sub.add_parser("listing-draft-context", help="Build listing draft context for a project")
    draft_p.add_argument("identifier")
    draft_p.add_argument("--json", action="store_true")
    draft_p.set_defaults(func=command_listing_draft_context)

    draft_export_p = projects_sub.add_parser("listing-draft-export", help="Write listing draft files")
    draft_export_p.add_argument("identifier")
    draft_export_p.add_argument("--json", action="store_true")
    draft_export_p.set_defaults(func=command_listing_draft_export)

    condition_p = projects_sub.add_parser("record-condition", help="Show record condition capture")
    condition_p.add_argument("identifier")
    condition_p.add_argument("--json", action="store_true")
    condition_p.set_defaults(func=command_record_condition)

    condition_update_p = projects_sub.add_parser("record-condition-update", help="Update record condition capture")
    condition_update_p.add_argument("identifier")
    condition_update_p.add_argument("--media-condition")
    condition_update_p.add_argument("--sleeve-condition")
    condition_update_p.add_argument("--condition", choices=["new", "excellent", "very_good", "good", "fair", "poor", "parts_only", "unassessed"])
    condition_update_p.add_argument("--grading-standard", default="visual")
    condition_update_p.add_argument("--playback-tested")
    condition_update_p.add_argument("--visual-grade-only")
    condition_update_p.add_argument("--grading-note")
    condition_update_p.add_argument("--scratches")
    condition_update_p.add_argument("--scuffs")
    condition_update_p.add_argument("--warping")
    condition_update_p.add_argument("--dust")
    condition_update_p.add_argument("--fingerprints")
    condition_update_p.add_argument("--label-condition")
    condition_update_p.add_argument("--ring-wear")
    condition_update_p.add_argument("--shelf-wear")
    condition_update_p.add_argument("--corner-wear")
    condition_update_p.add_argument("--edge-wear")
    condition_update_p.add_argument("--seam-split")
    condition_update_p.add_argument("--spine-readable")
    condition_update_p.add_argument("--writing")
    condition_update_p.add_argument("--stickers")
    condition_update_p.add_argument("--water-damage")
    condition_update_p.add_argument("--poly-sleeve")
    condition_update_p.add_argument("--inner-sleeve")
    condition_update_p.add_argument("--insert")
    condition_update_p.add_argument("--poster")
    condition_update_p.add_argument("--note")
    condition_update_p.add_argument("--json", action="store_true")
    condition_update_p.set_defaults(func=command_record_condition_update)

    condition_export_p = projects_sub.add_parser("record-condition-export", help="Write record condition files")
    condition_export_p.add_argument("identifier")
    condition_export_p.add_argument("--json", action="store_true")
    condition_export_p.set_defaults(func=command_record_condition_export)
