import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from librarian.index import find_latest_packet, load_packet, path_from_packet
    from librarian.summarize import load_json
except ModuleNotFoundError:
    from core.librarian.index import find_latest_packet, load_packet, path_from_packet
    from core.librarian.summarize import load_json


RULES_VERSION = "scan-keywords-v0"
KEYWORDS = {
    "medical": ["doctor", "clinic", "patient", "diagnosis", "prescription", "medication", "hospital", "health"],
    "dental": ["dentist", "dental", "root canal", "endodontist", "tooth", "teeth", "crown", "x-ray", "periodontal"],
    "insurance": ["insurance", "policy", "claim", "coverage", "premium", "member id", "healthnet", "medical"],
    "receipt": ["receipt", "subtotal", "total", "tax", "paid", "visa", "mastercard", "cash", "change"],
    "tax": ["tax year", "irs", "w-2", "1099", "franchise tax board", "deduction"],
    "vehicle": ["vehicle", "ford", "ranger", "vin", "registration", "mechanic", "tire", "smog"],
    "home": ["lease", "rent", "utility", "electricity", "gas", "water", "landlord", "tenant"],
    "legal": ["court", "notice", "agreement", "contract", "legal", "attorney"],
    "identity": ["passport", "driver license", "social security", "birth certificate"],
    "financial": ["bank", "statement", "account", "invoice", "payment", "balance"],
}


def require_summary(packet_dir: Path) -> Path:
    summary_path = packet_dir / "summary" / "summary.json"
    if not summary_path.exists():
        raise SystemExit(f"Packet must be summarized before classification: missing {summary_path}")
    return summary_path


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def keyword_matches(normalized_text: str) -> dict[str, list[str]]:
    matches = {}
    for category, keywords in KEYWORDS.items():
        found = []
        for keyword in keywords:
            needle = normalize_text(keyword)
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", normalized_text):
                found.append(keyword)
        if found:
            matches[category] = found
    return matches


def confidence_for(matches: dict[str, list[str]], primary: str) -> float:
    if primary == "unknown":
        return 0.0
    primary_count = len(matches.get(primary, []))
    category_count = len(matches)
    if primary_count >= 2 and category_count >= 2:
        return 0.9
    if primary_count >= 2:
        return 0.7
    return 0.4


def read_ocr_text(packet: dict[str, Any]) -> str:
    text_path = path_from_packet(packet, "text")
    if not text_path or not text_path.exists():
        return ""
    return text_path.read_text(encoding="utf-8", errors="replace")


def build_classification(packet_json: Path) -> dict[str, Any]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    summary = load_json(require_summary(packet_dir))
    tags = packet.get("tags") or []
    text_parts = [
        read_ocr_text(packet),
        str(summary.get("text_preview") or ""),
        str(packet.get("project") or ""),
        " ".join(str(tag) for tag in tags),
    ]
    normalized = normalize_text(" ".join(text_parts))
    matches = keyword_matches(normalized)
    categories = sorted(matches, key=lambda category: len(matches[category]), reverse=True)
    primary = categories[0] if categories else "unknown"

    return {
        "packet_type": packet.get("packet_type"),
        "project": packet.get("project"),
        "primary_category": primary,
        "categories": categories,
        "confidence": confidence_for(matches, primary),
        "matched_keywords": matches,
        "rules_version": RULES_VERSION,
        "classified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_packet_dir": str(packet_dir),
    }


def markdown_classification(classification: dict[str, Any]) -> str:
    lines = [
        "# LAIA Ingest Classification",
        "",
        "This is a transparent rule-based first pass, not final truth.",
        "",
        f"- Packet: {classification['source_packet_dir']}",
        f"- Primary Category: {classification['primary_category']}",
        f"- Confidence: {classification['confidence']:.2f}",
        f"- Rules Version: {classification['rules_version']}",
        "",
        "## Matched Categories",
        "",
    ]
    matches = classification.get("matched_keywords") or {}
    if matches:
        for category in classification.get("categories", []):
            lines.append(f"- {category}: {', '.join(matches[category])}")
    else:
        lines.append("- unknown: no keyword rules matched")
    lines.append("")
    return "\n".join(lines)


def write_classification(packet_json: Path, classification: dict[str, Any]) -> tuple[Path, Path]:
    classify_dir = packet_json.parent / "classify"
    classify_dir.mkdir(parents=True, exist_ok=True)
    classification_json = classify_dir / "classification.json"
    classification_md = classify_dir / "classification.md"
    classification_json.write_text(
        json.dumps(classification, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    classification_md.write_text(markdown_classification(classification), encoding="utf-8")
    return classification_json, classification_md


def print_summary(classification: dict[str, Any], classification_json: Path, classification_md: Path) -> None:
    print("\nLAIA Librarian Classification Complete\n")
    print(f"Packet: {classification['source_packet_dir']}")
    print(f"Type: {classification['packet_type']}")
    print(f"Project: {classification.get('project')}")
    print(f"Primary Category: {classification['primary_category']}")
    print(f"Confidence: {classification['confidence']:.2f}")
    print("Matched:")
    matches = classification.get("matched_keywords") or {}
    if matches:
        for category in classification.get("categories", []):
            print(f"  {category}: {', '.join(matches[category])}")
    else:
        print("  unknown: no keyword rules matched")
    print("\nWrote:")
    packet_dir = Path(classification["source_packet_dir"])
    print(f"  {classification_json.relative_to(packet_dir)}")
    print(f"  {classification_md.relative_to(packet_dir)}")
    print("\nNext:")
    print("  laia librarian review --last")
    print("")


def command_classify(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian classify --last")
    packet_json = find_latest_packet()
    classification = build_classification(packet_json)
    classification_json, classification_md = write_classification(packet_json, classification)
    print_summary(classification, classification_json, classification_md)
