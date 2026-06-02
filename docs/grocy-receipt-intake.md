# Grocy Receipt Intake

Grocy is the safe first real-world integration before NAS because it is useful, bounded, and reversible. A receipt workflow can produce structured review packets without touching archive originals, moving source files, or changing inventory automatically. That makes it a practical bridge between local extraction tools and human-approved real-world actions.

## Receipt Intake Loop

```text
receipt image/file
-> OCR/extraction
-> receipt packet
-> human review
-> Grocy entry later
```

The first version should stop at the receipt packet. Grocy writes come later, after review and explicit approval.

## Initial Receipt Packet Fields

- `vendor`
- `date`
- `total`
- `items`
- `tax`
- `payment_hint`
- `receipt_image_path`
- `extraction_status`
- `review_status`
- `proposed_grocy_actions`

## Safety Rules

- No automatic inventory changes at first.
- No automatic purchases.
- No deletion/move of source receipts.
- Human review is required before Grocy write actions.

## First Milestone

Create a receipt packet from a saved receipt without writing to Grocy.

## Future Commands

```sh
python3 cli/laia.py receipt ingest <path>
python3 cli/laia.py receipt show <receipt_packet_id>
python3 cli/laia.py receipt review <receipt_packet_id>
python3 cli/laia.py receipt apply <receipt_packet_id>  # future, explicit approval only
```
