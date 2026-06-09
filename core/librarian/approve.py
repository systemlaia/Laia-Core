import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from core.librarian.summarize import load_json, optional_json


def require_review(packet_dir: Path) -> Path:
    review_path = packet_dir / "review" / "review.json"
    if not review_path.exists():
        raise SystemExit(f"Packet must be reviewed before approval: missing {review_path}")
    return review_path


def find_pending_review_packet(ingest_root: Path = DEFAULT_INGEST_ROOT) -> Path:
    candidates = []
    for packet_json in ingest_root.rglob("packet.json"):
        packet_dir = packet_json.parent
        review_path = packet_dir / "review" / "review.json"
        if not review_path.exists():
            continue
        if (packet_dir / "approval" / "approval.json").exists():
            continue
        if (packet_dir / "final" / "final.json").exists():
            continue
        try:
            review = load_json(review_path)
        except Exception:
            continue
        if review.get("review_status") != "pending":
            continue
        candidates.append(packet_json)

    if not candidates:
        raise SystemExit("No pending review packet found to approve.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_approval(packet_json: Path) -> tuple[dict[str, Any], bool]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    if (packet_dir / "approval" / "approval.json").exists():
        raise SystemExit(f"Packet is already approved: {packet_dir}")
    if (packet_dir / "final" / "final.json").exists():
        raise SystemExit(f"Packet is already finalized: {packet_dir}")
    review = load_json(require_review(packet_dir))
    classification = optional_json(packet_dir / "classify" / "classification.json") or {}

    source_review_status = str(review.get("review_status") or "")
    if source_review_status != "pending":
        raise SystemExit(f"Only pending reviews can be approved; found review_status={source_review_status}")

    recommended = str(review.get("recommended_action") or "")
    warning_needed = recommended != "approve_classification"
    approved_category = classification.get("primary_category") or review.get("primary_category")
    confidence = classification.get("confidence", review.get("confidence", 0.0))

    approval = {
        "approval_type": "laia.librarian.approval",
        "packet_type": packet.get("packet_type"),
        "project": packet.get("project"),
        "approved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_status": "approved",
        "approved_category": approved_category,
        "confidence": float(confidence or 0.0),
        "source_review_status": source_review_status,
        "recommended_action": recommended,
        "source_packet_dir": str(packet_dir),
        "approved_by": "local_user",
    }
    return approval, warning_needed


def markdown_approval(approval: dict[str, Any]) -> str:
    return (
        "# LAIA Ingest Approval\n\n"
        f"- Packet: {approval['source_packet_dir']}\n"
        f"- Project: {approval.get('project')}\n"
        f"- Approved Category: {approval.get('approved_category')}\n"
        f"- Confidence: {approval.get('confidence', 0.0):.2f}\n"
        f"- Original Recommended Action: {approval.get('recommended_action')}\n"
        f"- Approved At: {approval.get('approved_at')}\n"
        f"- Approved By: {approval.get('approved_by')}\n\n"
        "Approval is recorded as a sidecar only. It does not alter `packet.json` "
        "or the original classification sidecar.\n"
    )


def write_approval(packet_json: Path, approval: dict[str, Any]) -> tuple[Path, Path]:
    approval_dir = packet_json.parent / "approval"
    approval_dir.mkdir(parents=True, exist_ok=True)
    approval_json = approval_dir / "approval.json"
    approval_md = approval_dir / "approval.md"
    approval_json.write_text(json.dumps(approval, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    approval_md.write_text(markdown_approval(approval), encoding="utf-8")
    return approval_json, approval_md


def print_summary(approval: dict[str, Any], approval_json: Path, approval_md: Path, warning_needed: bool) -> None:
    if warning_needed:
        print(
            f"Warning: approving despite recommended_action={approval.get('recommended_action')}"
        )
    print("\nLAIA Librarian Approval Complete\n")
    print(f"Packet: {approval['source_packet_dir']}")
    print(f"Type: {approval['packet_type']}")
    print(f"Project: {approval.get('project')}")
    print(f"Approved Category: {approval.get('approved_category')}")
    print(f"Confidence: {approval.get('confidence', 0.0):.2f}")
    print(f"Review Status: {approval.get('review_status')}")
    print("\nWrote:")
    packet_dir = Path(approval["source_packet_dir"])
    print(f"  {approval_json.relative_to(packet_dir)}")
    print(f"  {approval_md.relative_to(packet_dir)}")
    print("\nNext:")
    print("  laia librarian finalize --last")
    print("")


def command_approve(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian approve --last")
    packet_json = find_pending_review_packet()
    approval, warning_needed = build_approval(packet_json)
    approval_json, approval_md = write_approval(packet_json, approval)
    print_summary(approval, approval_json, approval_md, warning_needed)
