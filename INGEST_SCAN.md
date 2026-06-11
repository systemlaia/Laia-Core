# LAIA Scan Ingest

`laia ingest scan` is a core LAIA ingest command, not a scanner UI.

The Canon DR-3010C is equipment. The command grammar is the interface. The
packet is the product.

Core rule:

- No media enters LAIA loose.
- Everything enters through an ingest command.
- Every ingest creates a packet.
- Every packet has metadata.
- The Librarian decides routing, indexing, dedupe, summaries, and long-term
  archive placement later.

## Commands

```bash
laia ingest scan --test
laia ingest scan --list-options
laia ingest scan --profile document
laia ingest scan --profile receipt
laia ingest scan --profile archive-color
laia ingest scan --profile document --project "Dental"
laia ingest scan --profile document --project "Dental" --tags dental,insurance,medical
laia ingest scan --profile document --project "Inbox" --dry-run
```

## First Hardware Checks

First:

```bash
laia ingest scan --test
```

Second:

```bash
laia ingest scan --list-options
```

First real scan:

```bash
laia ingest scan --profile document --project "Inbox"
```

## Packet Layout

Packets are created under:

```text
~/LAIA/Inbox/Ingest/Scans/YYYY-MM-DD_HHMMSS_project-slug/
```

Each packet contains:

```text
packet.json
source/
output/
logs/
```

Source page images are never deleted by the command.

## Profiles

Profiles live in:

```text
core/ingest/profiles/
```

Current v0 profiles:

```text
document.yaml
receipt.yaml
archive-color.yaml
```

`document` defaults to duplex gray 300 dpi.

## Dependencies

- `scanimage` is required for scanning.
- `img2pdf` is preferred for PDF assembly.
- `ocrmypdf` is optional for OCR.

If OCR is unavailable, the packet is still created with source images and any
available PDF output, and `packet.json` records OCR as unavailable.
