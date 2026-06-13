# LAIA Packet Standard v0.1

Status: Draft  
Applies to: LAIA ingest/archive packets

## Purpose

A LAIA packet is a self-contained archive unit for captured source material, derived outputs, metadata, review state, logs, and catalog records. Packets must be readable without the original ingest tool and stable enough for NAS-first archival workflows.

Version 0.1 describes the common packet contract. Media-specific ingest tools may add folders and fields, but they should not remove or reinterpret the required core files.

## Packet Location

Packet roots are grouped by packet family and year:

```text
<packet-root>/<year>/<job-id>/
```

Examples:

```text
/Volumes/Public/LAIA/packets/photo_ingest/2026/20260610-184234_DSD_sd_ingest/
archive/Ingest/Scans/inbox/2026/06/2026-06-09_181428_mailinbox/
```

Packet paths should be treated as archive paths once written. Tools may add sidecars, derived outputs, catalog indexes, and verification reports, but must not mutate original source files in place.

## Required Folders

Every v0.1 packet should contain:

```text
originals/
metadata/
logs/
```

Folder roles:

- `originals/`: Source files copied from the capture device or source workflow. These are archival originals.
- `metadata/`: Machine-readable metadata extracted from originals or produced by ingest.
- `logs/`: Ingest, verification, and tool logs needed to audit packet creation.

## Required Files

Every v0.1 packet should contain:

```text
packet_manifest.json
checksums.sha256
ingest_report.md
```

File roles:

- `packet_manifest.json`: Required packet identity and summary metadata.
- `checksums.sha256`: SHA-256 checksums for original source files.
- `ingest_report.md`: Human-readable ingest summary.

## Optional Media-Specific Folders

Packet families may define additional folders. Current known examples:

- `previews/`: JPEG or other lightweight derivatives for review.
- `contact_sheet/`: Visual overview artifacts such as `contact_sheet.jpg`.
- `output/`: OCR PDFs, text, rendered documents, or other workflow outputs.
- `pages/`: Page image derivatives or normalized page assets.
- `ocr/`: OCR outputs when a packet family separates OCR from general output.
- `classify/`: Classification sidecars and reports.
- `route/`: Routing decisions or downstream archive placement metadata.
- `review/`: Human review sidecars, notes, and selects.
- `extract/`: Structured extraction results and corrections.
- `dedupe/`: Duplicate-detection reports.

Optional folders must be additive. A cataloger or verifier should still be able to interpret the core packet without understanding every optional folder.

## Manifest Fields

`packet_manifest.json` must be UTF-8 JSON object data.

Required common fields:

- `packet_type`: Stable packet family identifier, such as `laia.photo_ingest` or `laia.ingest.scan`.
- `packet_version`: Packet format version for the family.
- `job_id` or `packet_id`: Stable packet identifier unique within its packet family.
- `source`: Human-readable source location or source description.
- `packet_path`: Archive path where the packet was written.
- `created_at`: UTC ISO-8601 timestamp when the packet was created.

Recommended common fields:

- `photo_count`, `page_count`, `file_count`, or another family-specific source count.
- `packet_size`: Human-readable packet size captured at ingest completion.
- `created_by`: Tool or workflow name.
- `storage_role`: Expected storage role, such as `archive`, `local-cache`, or `export`.

Rules:

- Unknown manifest fields must be preserved by readers.
- Manifest timestamps should use UTC and end with `Z` when possible.
- Manifests describe packet identity and summary state; detailed per-file metadata belongs in `metadata/` or catalog tables.

## Checksum Rules

`checksums.sha256` uses the standard `shasum -a 256` compatible format:

```text
<sha256><whitespace><relative-path>
```

Rules:

- Checksums cover files under `originals/`.
- Paths are relative to `originals/`.
- Paths may begin with `./` for compatibility.
- Both text mode (`<hash>  ./path`) and binary mode (`<hash> *./path`) parser forms are accepted.
- Blank lines are ignored.
- Malformed lines should be reported by validation tools.
- Verification must recompute SHA-256 from the archived original and compare it to the recorded value.

The checksum count should normally match the number of files under `originals/`. Exceptions must be called out in the ingest report or validation output.

## Review Sidecar Rules

Human review state lives under:

```text
review/packet_review.json
review/selects.txt
```

`packet_review.json` should be UTF-8 JSON object data with these common fields:

- `review_status`: One of `new`, `reviewed`, `selected`, `rejected`, `exported`, or `published`.
- `rating_pass`: Optional rating or pass marker.
- `notes`: Freeform human note text.
- `reviewed_at`: UTC ISO-8601 timestamp, or `null`.
- `updated_at`: UTC ISO-8601 timestamp.

`selects.txt` stores one selected original path per non-comment line:

- Paths are relative to `originals/`.
- Blank lines and lines beginning with `#` are ignored.
- Writers should de-duplicate paths while preserving order.

Review sidecars may be created after ingest. Creating or updating review sidecars must not modify originals, checksums, or the packet manifest.

## Catalog Expectations

Catalogs are derived indexes, not the packet source of truth.

Catalog tools should:

- Read packet manifests, checksums, metadata, review sidecars, and file stats.
- Store packet-level identity and summary fields.
- Store per-original rows where useful.
- Preserve packet compatibility by tolerating unknown manifest and metadata fields.
- Be rebuildable from packet archives.
- Avoid modifying packets while querying or rebuilding catalogs, except when explicitly writing review or correction sidecars.

Current catalog forms include:

- CSV packet indexes for lightweight browsing.
- SQLite catalogs for packet/image/file queries.
- JSONL catalogs for finalized document workflows.

## Storage Roles

LAIA distinguishes storage roles:

- NAS packet archive: Durable packet root. This is the primary archive for NAS-first workflows.
- Local working root: Logs, temporary files, and local workflow state. This is not the primary archive.
- Catalog root: Rebuildable indexes and query databases derived from packets.
- Export root: User-facing copies of selected outputs. Exports are not canonical originals.
- Source media: SD cards, scanners, inbox folders, or other capture sources. Source media is read during ingest and is not the archive.

Environment variables may select roots for a packet family. For photo ingest:

- `LAIA_PHOTO_PACKET_ROOT`: NAS-first photo packet archive root.
- `LAIA_PHOTO_CATALOG_ROOT`: Rebuildable photo catalog root.
- `LAIA_PHOTO_LOCAL_ROOT`: Local logs and workflow state.

For paper ingest:

- `LAIA_PAPER_PACKET_ROOT`: Paper packet archive or working packet root.

Paper packet standardization is additive for legacy scan packets. It may create missing standard folders and sidecars, but it must not move, delete, or rewrite original scan/OCR/classification outputs unless a command explicitly requests a sidecar rewrite with `--force`.

Tools must default conservatively and should make root paths visible in command output.
