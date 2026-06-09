import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.index import find_latest_packet, load_packet
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.index import find_latest_packet, load_packet
    from core.librarian.summarize import load_json, optional_json


def require_sidecar(packet_dir: Path, relative_path: str, stage: str) -> Path:
    path = packet_dir / relative_path
    if not path.exists():
        raise SystemExit(f"Packet must have {stage} before review: missing {path}")
    return path


def recommended_action(
    primary_category: str,
    confidence: float,
    ocr_text_available: bool,
    ocr_status: Optional[str],
) -> str:
    normalized_ocr = str(ocr_status or "").strip().lower()
    if not ocr_text_available or normalized_ocr in {"", "missing", "failed", "incomplete"}:
        return "rescan_or_manual_review"
    if primary_category == "unknown":
        return "manual_review"
    if confidence >= 0.7:
        return "approve_classification"
    return "manual_review"


def build_review(packet_json: Path) -> dict[str, Any]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent

    index = load_json(require_sidecar(packet_dir, "index/index.json", "an index"))
    summary = load_json(require_sidecar(packet_dir, "summary/summary.json", "a summary"))
    classification = load_json(
        require_sidecar(packet_dir, "classify/classification.json", "a classification")
    )
    route = optional_json(packet_dir / "route" / "route.json")

    text_stats = index.get("text_stats") or {}
    primary_category = classification.get("primary_category") or "unknown"
    confidence = float(classification.get("confidence") or 0.0)
    routed = bool(route)
    ocr_status = summary.get("ocr_status")
    action = recommended_action(
        primary_category=primary_category,
        confidence=confidence,
        ocr_text_available=bool(index.get("ocr_text_available")),
        ocr_status=ocr_status,
    )

    return {
        "review_type": "laia.librarian.review",
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "packet_type": packet.get("packet_type"),
        "project": packet.get("project"),
        "created_at": packet.get("created_at"),
        "page_count": packet.get("page_count", 0),
        "word_count": text_stats.get("word_count", summary.get("word_count", 0)),
        "ocr_status": ocr_status,
        "pdf_status": summary.get("pdf_status"),
        "routed": routed,
        "destination_packet_dir": route.get("destination_packet_dir") if route else "",
        "primary_category": primary_category,
        "confidence": confidence,
        "categories": classification.get("categories") or [],
        "matched_keywords": classification.get("matched_keywords") or {},
        "review_status": "pending",
        "recommended_action": action,
        "source_packet_dir": str(packet_dir),
        "text_preview": summary.get("text_preview") or "",
    }


def markdown_review(review: dict[str, Any]) -> str:
    routed = "yes" if review.get("routed") else "no"
    destination = review.get("destination_packet_dir") or "not routed"
    preview = review.get("text_preview") or "_No OCR text preview available._"
    matches = review.get("matched_keywords") or {}
    lines = [
        "# LAIA Ingest Review",
        "",
        f"- Packet: {review['source_packet_dir']}",
        f"- Project: {review.get('project')}",
        f"- Created: {review.get('created_at')}",
        f"- Pages: {review.get('page_count')}",
        f"- OCR: {review.get('ocr_status')}",
        f"- PDF: {review.get('pdf_status')}",
        f"- Routed: {routed}",
        f"- Destination: {destination}",
        f"- Primary Category: {review.get('primary_category')}",
        f"- Confidence: {review.get('confidence', 0.0):.2f}",
        "- Review Status: Pending",
        f"- Recommended Action: {review.get('recommended_action')}",
        "",
        "## Matched Keywords",
        "",
    ]
    if matches:
        for category in review.get("categories", []):
            lines.append(f"- {category}: {', '.join(matches.get(category, []))}")
    else:
        lines.append("- unknown: no keyword rules matched")

    lines.extend(
        [
            "",
            "## Text Preview",
            "",
            preview,
            "",
            "## Next Commands",
            "",
            "```bash",
            "laia librarian approve --last",
            "laia librarian correct --last --category <category>",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_review(packet_json: Path, review: dict[str, Any]) -> tuple[Path, Path]:
    review_dir = packet_json.parent / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_md = review_dir / "review.md"
    review_json = review_dir / "review.json"
    review_md.write_text(markdown_review(review), encoding="utf-8")
    review_json.write_text(json.dumps(review, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return review_md, review_json


def print_summary(review: dict[str, Any], review_md: Path, review_json: Path) -> None:
    print("\nLAIA Librarian Review Complete\n")
    print(f"Packet: {review['source_packet_dir']}")
    print(f"Type: {review['packet_type']}")
    print(f"Project: {review.get('project')}")
    print(f"Primary Category: {review.get('primary_category')}")
    print(f"Confidence: {review.get('confidence', 0.0):.2f}")
    print(f"Review Status: {review.get('review_status')}")
    print(f"Recommended Action: {review.get('recommended_action')}")
    print("\nWrote:")
    packet_dir = Path(review["source_packet_dir"])
    print(f"  {review_md.relative_to(packet_dir)}")
    print(f"  {review_json.relative_to(packet_dir)}")
    print("\nNext:")
    print("  laia librarian approve --last")
    print("  laia librarian correct --last --category <category>")
    print("")


def command_review(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian review --last")
    packet_json = find_latest_packet()
    review = build_review(packet_json)
    review_md, review_json = write_review(packet_json, review)
    print_summary(review, review_md, review_json)
