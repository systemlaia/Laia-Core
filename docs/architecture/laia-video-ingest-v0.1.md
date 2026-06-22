# LAIA Video Ingest v0.1

LAIA video ingest preserves one ffmpeg-readable camera original per immutable packet. Common inputs include MOV, MP4, MKV, M4V, AVI, MTS, and WebM.

## Packet layout

Video packets live under `LAIA_VIDEO_PACKET_ROOT/YYYY/<job-id>/` and contain:

- `originals/` — unchanged source video
- `proxy/` — H.264/AAC MP4 editing and web proxy
- `stills/` — evenly sampled JPEGs and an unlabeled contact sheet
- `metadata/` — ffprobe, optional mediainfo, and normalized technical metadata
- `review/` — review status, role, and notes
- `logs/`, checksum, manifest, and ingest report

The original is copied with metadata preserved and verified against the source SHA-256 before derivative generation. It is never remuxed or transcoded.

## Atomic publication

The packet is built and verified in the configured local working root. A verified copy is then written to a hidden incoming directory beside the final NAS destination, verified again, and atomically renamed into place.

## Proxy and still policy

The required proxy is MP4/H.264 at a configurable maximum width, with AAC audio when the source has audio. Stills are sampled deterministically between approximately 5% and 95% of runtime. Contact sheets are unlabeled and have no font dependency.

## Verification and registry

`laia video verify` recalculates the original checksum, probes original and proxy files, and checks required derivatives. `laia packets scan` indexes `laia.video_ingest` packets alongside photo and paper packets.

## Project evidence

Verified packets can be linked with `laia video link-project`. The project receives a packet link, proxy artifact, and `video_evidence.json` provenance record. Video ingestion never changes a sale item's human-assessed functional state.

## Legacy command

`video_ingest/bin/laia_video_ingest_mkv.sh` remains as a deprecation shim and delegates directly to `laia video ingest`.
