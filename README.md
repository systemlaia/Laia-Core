# DS9-era Stardate Notebook Generator

This repository contains `stardate.py`, a small Python 3 script for generating
Deep Space Nine / late TNG-style stardates for personal notebook entries.

## Purpose

Use `stardate.py` to add a compact personal reference such as:

    (stardate: 50123.4) [Purple / Project]

This is intended for personal notes, not formal reports. The script maps real
calendar dates into a fixed Star Trek timeline offset so your notebook entries
stay in the DS9-era range.

## Usage

Examples:

    python3 stardate.py
    python3 stardate.py --color Purple --tag Project
    python3 stardate.py --color Orange --tag Priority
    python3 stardate.py --date "2026-06-07 21:14" --color Yellow --tag Idea
    python3 stardate.py --json
    python3 stardate.py --explain

## Options

- `--date "YYYY-MM-DD HH:MM"` — calculate for a specific datetime
- `--utc` — interpret the date as UTC
- `--precision N` — decimal places for the stardate (default: 1)
- `--offset-years N` — timeline offset (default: 347)
- `--no-offset` — use the real year directly
- `--color TEXT` — optional notebook color label
- `--tag TEXT` — optional short note tag
- `--json` — output JSON
- `--explain` — print the formula explanation

## Testing

Run the test suite with:

    python3 -m unittest test_stardate.py

The tests cover stardate computation, personal reference formatting, and
argument parsing validation.

## Development

Use the top-level Makefile to run validation, examples, and Flipper build checks:

```bash
make test
make flipper-build
make flipper-clean
make full-test
make example
make clean
```

- `make test` runs Python and portable C validation only.
- `make flipper-build` builds the Flipper staging app with local uFBT only.
- The current Flipper staging app uses RTC/local time, `ViewPort` input callbacks,
  a text-based color/tag selector, OK to append an SD log entry, and an RGB LED cue for the selected notebook color.
- Supported notebook colors are: Orange, Purple, Yellow, Pink, Silver, White, Green.
- Log path: `/apps_data/laia_stardate/log.txt`
- Log line format: `YYYY-MM-DD HH:MM:SS | stardate XXXXX.X | Color / Tag`
- Next Flipper milestone: v0.4.5 hardware smoke test.
- `make full-test` runs Python + C validation and the Flipper build.
- `make flipper-clean` removes generated Flipper staging build output without deleting source or the `.venv-flipper` venv.
- No hardware flash or deployment is performed by these targets.
- v0.4.5 hardware smoke test attempted; serial device visible on `/dev/cu.usbmodemCDkbio011`, but uFBT/CLI report: "Is Flipper connected via USB and not in DFU mode?" (see `FLIPPER_USB_DEBUG.md`)
- Momentum firmware is installed on the test Flipper. uFBT launch is blocked despite the serial path, so manual install via qFlipper, Flipper Lab, or SD card is now the recommended path. See `FLIPPER_MOMENTUM_INSTALL.md`.
- The Flipper SD card was mapped and selectively backed up from `/Volumes/FLIPPER SD`; see `FLIPPER_SD_LAYOUT.md`. The stock/uFBT FAP installed successfully but Momentum launch failed with `invalid file err_02`. A Momentum app-only rebuild now exists at `releases/laia_stardate_momentum_v0.4.4_build_verified/`; its FAP replaced the previous SD copy at `/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap` after backing up the old FAP, and checksum `65f2f32703415e85261575f9eb6ef84c117a7a7b` matched.

## Scan Ingest

`laia ingest scan` is the v0 core command for Canon DR-3010C document scanning
through SANE/`scanimage`. It creates packetized scan ingests under
`~/LAIA/Inbox/Ingest/Scans/`; see `INGEST_SCAN.md`.

First hardware checks:

```bash
laia ingest scan --test
laia ingest scan --list-options
```

First real scan:

```bash
laia ingest scan --profile document --project "Inbox"
```

## Release archive

A build-verified release archive has been created at:

`releases/laia_stardate_flipper_v0.4.4_build_verified/`

It contains the current source files, generated Flipper FAP, and release notes for the v0.4.4 local archive.
