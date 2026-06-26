import json
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


def appraisal_root(project_id: str) -> Path:
    return registry_module().project_folder(project_id) / "appraisal"


def context_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "context.json"


def research_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "research.json"


def research_markdown_path(project_id: str) -> Path:
    return appraisal_root(project_id) / "research.md"


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
            if sale_item.get("condition", {}).get("overall") == "unassessed"
            else sale_item.get("condition", {}).get("overall")
        ),
        "media_condition": blank_to_none(metadata.get("media_condition")),
        "sleeve_condition": blank_to_none(metadata.get("sleeve_condition")),
        "grading_note": blank_to_none(metadata.get("grading_note")),
        "play_tested": bool(metadata.get("play_tested")),
        "visual_grade_only": not bool(metadata.get("play_tested")),
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
