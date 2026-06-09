import json
import tempfile
import unittest
from pathlib import Path

from core.librarian.pending import list_pending_packets


class LibrarianPendingTests(unittest.TestCase):
    def make_packet(
        self,
        root: Path,
        name: str = "2026-06-08_150538_receipts",
        created_at: str = "2026-06-08T15:05:38-07:00",
        with_review: bool = True,
        with_approval: bool = False,
        with_final: bool = False,
    ) -> Path:
        packet_dir = root / "Inbox" / "Ingest" / "Scans" / name
        packet_dir.mkdir(parents=True)
        packet = {
            "packet_type": "laia.ingest.scan",
            "created_at": created_at,
            "project": "Receipts",
            "page_count": 2,
            "paths": {"packet_dir": str(packet_dir)},
        }
        packet_json = packet_dir / "packet.json"
        packet_json.write_text(json.dumps(packet, indent=2), encoding="utf-8")

        classify_dir = packet_dir / "classify"
        classify_dir.mkdir()
        classification = {
            "primary_category": "receipt",
            "confidence": 0.4,
        }
        (classify_dir / "classification.json").write_text(json.dumps(classification), encoding="utf-8")

        if with_review:
            review_dir = packet_dir / "review"
            review_dir.mkdir()
            review = {
                "review_status": "pending",
                "primary_category": "receipt",
                "confidence": 0.4,
                "recommended_action": "manual_review",
            }
            (review_dir / "review.json").write_text(json.dumps(review), encoding="utf-8")

        if with_approval:
            approval_dir = packet_dir / "approval"
            approval_dir.mkdir()
            (approval_dir / "approval.json").write_text('{"review_status": "approved"}\n', encoding="utf-8")

        if with_final:
            final_dir = packet_dir / "final"
            final_dir.mkdir()
            (final_dir / "final.json").write_text('{"catalog_status": "finalized"}\n', encoding="utf-8")

        return packet_json

    def test_pending_lists_packets_with_review_but_no_approval_or_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json = self.make_packet(root)

            records = list_pending_packets(root / "Inbox" / "Ingest")

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source_packet_dir"], str(packet_json.parent))

    def test_pending_excludes_approved_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, with_approval=True)

            records = list_pending_packets(root / "Inbox" / "Ingest")

            self.assertEqual(records, [])

    def test_pending_excludes_finalized_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, with_final=True)

            records = list_pending_packets(root / "Inbox" / "Ingest")

            self.assertEqual(records, [])

    def test_pending_excludes_packets_without_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, with_review=False)

            records = list_pending_packets(root / "Inbox" / "Ingest")

            self.assertEqual(records, [])

    def test_pending_sorts_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(
                root,
                name="2026-06-08_150000_receipts",
                created_at="2026-06-08T15:00:00-07:00",
            )
            self.make_packet(
                root,
                name="2026-06-08_150538_receipts",
                created_at="2026-06-08T15:05:38-07:00",
            )

            records = list_pending_packets(root / "Inbox" / "Ingest")

            self.assertEqual(records[0]["packet_folder"], "2026-06-08_150538_receipts")

    def test_pending_supports_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = list_pending_packets(Path(tmp) / "Inbox" / "Ingest")

            self.assertEqual(records, [])

    def test_pending_supports_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_packet(root, name="2026-06-08_150000_receipts", created_at="2026-06-08T15:00:00-07:00")
            self.make_packet(root, name="2026-06-08_150100_receipts", created_at="2026-06-08T15:01:00-07:00")

            records = list_pending_packets(root / "Inbox" / "Ingest", limit=1)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["packet_folder"], "2026-06-08_150100_receipts")

    def test_pending_does_not_modify_packet_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            packet_json = self.make_packet(root)
            before = packet_json.read_text(encoding="utf-8")

            list_pending_packets(root / "Inbox" / "Ingest")
            after = packet_json.read_text(encoding="utf-8")

            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
