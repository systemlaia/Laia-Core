import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from core.librarian.approve import build_approval, find_pending_review_packet, print_summary, write_approval


class LibrarianApproveTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        packet_type: str = "laia.ingest.scan",
        with_review: bool = True,
        primary_category: str = "receipt",
        confidence: float = 0.9,
        review_status: str = "pending",
        recommended_action: str = "approve_classification",
        name: str = "2026-06-07_171935_inbox",
        with_approval: bool = False,
        with_final: bool = False,
    ):
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / name
        packet_dir.mkdir(parents=True)

        packet = {
            "packet_type": packet_type,
            "created_at": "2026-06-07T17:19:35-07:00",
            "project": "Inbox",
            "page_count": 2,
            "paths": {
                "packet_dir": str(packet_dir),
            },
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet, indent=2), encoding="utf-8")

        classify_dir = packet_dir / "classify"
        classify_dir.mkdir()
        classification = {
            "packet_type": packet_type,
            "project": "Inbox",
            "primary_category": primary_category,
            "categories": [primary_category] if primary_category != "unknown" else [],
            "confidence": confidence,
            "matched_keywords": {"receipt": ["receipt", "subtotal"]},
        }
        (classify_dir / "classification.json").write_text(json.dumps(classification), encoding="utf-8")

        if with_review:
            review_dir = packet_dir / "review"
            review_dir.mkdir()
            review = {
                "review_type": "laia.librarian.review",
                "packet_type": packet_type,
                "project": "Inbox",
                "primary_category": primary_category,
                "confidence": confidence,
                "review_status": review_status,
                "recommended_action": recommended_action,
                "source_packet_dir": str(packet_dir),
            }
            (review_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")

        if with_approval:
            approval_dir = packet_dir / "approval"
            approval_dir.mkdir()
            approval = {
                "approval_type": "laia.librarian.approval",
                "review_status": "approved",
            }
            (approval_dir / "approval.json").write_text(json.dumps(approval), encoding="utf-8")

        if with_final:
            final_dir = packet_dir / "final"
            final_dir.mkdir()
            (final_dir / "final.json").write_text('{"catalog_status": "finalized"}\n', encoding="utf-8")

        return packet_json

    def test_approve_requires_review_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), with_review=False)

            with self.assertRaises(SystemExit):
                build_approval(packet_json)

    def test_approval_files_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            approval, _warning = build_approval(packet_json)
            approval_json, approval_md = write_approval(packet_json, approval)

            self.assertTrue(approval_json.exists())
            self.assertTrue(approval_md.exists())
            self.assertIn("# LAIA Ingest Approval", approval_md.read_text(encoding="utf-8"))

    def test_approve_preserves_packet_json_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp))
            before = packet_json.read_text(encoding="utf-8")
            approval, _warning = build_approval(packet_json)
            write_approval(packet_json, approval)
            after = packet_json.read_text(encoding="utf-8")

            self.assertEqual(before, after)

    def test_approve_works_for_high_confidence_approve_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(
                Path(tmp),
                primary_category="receipt",
                confidence=0.9,
                recommended_action="approve_classification",
            )
            approval, warning = build_approval(packet_json)

            self.assertFalse(warning)
            self.assertEqual(approval["review_status"], "approved")
            self.assertEqual(approval["approved_category"], "receipt")
            self.assertEqual(approval["recommended_action"], "approve_classification")

    def test_approve_warns_but_works_for_manual_review_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(
                Path(tmp),
                primary_category="unknown",
                confidence=0.0,
                recommended_action="manual_review",
            )
            approval, warning = build_approval(packet_json)
            approval_json, approval_md = write_approval(packet_json, approval)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                print_summary(approval, approval_json, approval_md, warning)

            self.assertTrue(warning)
            self.assertIn("Warning: approving despite recommended_action=manual_review", output.getvalue())
            self.assertEqual(approval["review_status"], "approved")
            self.assertEqual(approval["approved_category"], "unknown")

    def test_rejects_non_pending_review_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), review_status="approved")

            with self.assertRaises(SystemExit):
                build_approval(packet_json)

    def test_rejects_non_laia_ingest_packet_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet_json = self.make_packet(Path(tmp), packet_type="external.scan")

            with self.assertRaises(SystemExit):
                build_approval(packet_json)

    def test_approve_ignores_already_approved_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, name="2026-06-08_100000_receipts", with_approval=True)
            pending = self.make_packet(root, name="2026-06-08_100100_receipts")

            selected = find_pending_review_packet(root / "Inbox" / "Ingest")

            self.assertEqual(selected, pending)

    def test_approve_ignores_finalized_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, name="2026-06-08_100000_receipts", with_final=True)
            pending = self.make_packet(root, name="2026-06-08_100100_receipts")

            selected = find_pending_review_packet(root / "Inbox" / "Ingest")

            self.assertEqual(selected, pending)

    def test_approve_picks_newest_pending_review_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            older = self.make_packet(root, name="2026-06-08_100000_receipts")
            newer = self.make_packet(root, name="2026-06-08_100100_receipts")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))

            selected = find_pending_review_packet(root / "Inbox" / "Ingest")

            self.assertEqual(selected, newer)

    def test_approve_fails_when_no_pending_packet_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, name="2026-06-08_100000_receipts", with_approval=True)

            with self.assertRaisesRegex(SystemExit, "No pending review packet found to approve"):
                find_pending_review_packet(root / "Inbox" / "Ingest")


if __name__ == "__main__":
    unittest.main()
