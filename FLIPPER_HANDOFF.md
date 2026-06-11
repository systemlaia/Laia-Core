# LAIA Stardate Flipper Handoff

## Purpose

This document is for moving the staged LAIA Stardate app from the mini/reference
repo into the real Flipper build environment on the laptop.

The goal of v0.4.1 is only:

- copy staged app into the Flipper lab
- build with ufbt
- fix manifest/API syntax issues
- produce a FAP if possible

The current staging package has already progressed to live RTC time and a
text-based color/tag selector. Do not add SD logging, persistence, or hardware
deployment yet.

> Note: the mini is being prepared as the LAIA Stardate SDK/build host. A local uFBT virtual environment exists at `/Users/iv/LAIA/.venv-flipper`, and the staged package now builds successfully from `/Users/iv/LAIA/flipper_staging/laia_stardate/`.
>
> No hardware flash or deployment has been performed.
>
> Hardware smoke test v0.4.5 was attempted locally, but no connected Flipper device was detected by uFBT.

## Source Package

Staging source is located at:

```text
/Users/iv/LAIA/flipper_staging/laia_stardate/|Expected files:
```

```text
README.md
application.fam
laia_stardate.c
stardate_core.h
stardate_core.c
```

## Destination

Likely destination on the Flipper lab machine:

```text
~/Projects/LAIA-Flipper-Lab/apps/laia_stardate/
```

Existing working app, if present, should not be modified:

```text
~/Projects/LAIA-Flipper-Lab/apps/laia_hello_console/
```

## Transfer Steps

Example copy commands for the laptop:

```bash
cd ~/Projects/LAIA-Flipper-Lab
mkdir -p apps/laia_stardate
cp -R /path/to/laia_stardate/* apps/laia_stardate/
```

A safer rsync option:

```bash
rsync -av --exclude='.DS_Store' /path/to/laia_stardate/ apps/laia_stardate/
```

## Pre-Build Check

Run these checks before attempting the build:

```bash
cd ~/Projects/LAIA-Flipper-Lab
find apps/laia_stardate -maxdepth 2 -type f | sort
python -m ufbt --help
```

## Build Attempt

Build only:

```bash
cd ~/Projects/LAIA-Flipper-Lab
python -m ufbt
```

In the local repo, the equivalent validation target is:

```bash
make flipper-build
```

This runs the Flipper FAP build only and does not flash or deploy.

- Do not flash yet.
- Build only.
- If the build fails, capture the first compiler or manifest error.

## Expected Test Vector

Fixed display target:

```text
2026-06-07 21:14:00, offset 347
Expected: Stardate 50432.6
```

Current scaffold details:

- The app now reads Flipper RTC/local time at runtime.
- The current staging package supports `ViewPort` input callbacks and a
  monochrome text-based color/tag selector.
- Supported notebook colors are: Orange, Purple, Yellow, Pink, Silver, White, Green.
- The fixed test vector remains a canonical reference for documentation and
  Python/C tests.
- The app now supports `OK` to append a log entry to `/apps_data/laia_stardate/log.txt`.
- Log line format: `YYYY-MM-DD HH:MM:SS | stardate XXXXX.X | Color / Tag`.
- No persistence of selected color/tag beyond the current session.
- RGB LED cue now follows the selected notebook color label with approximate LEDs only; the screen remains monochrome.

## Likely Fix Areas

Likely areas that may need tuning once the real Flipper SDK is available:

- `application.fam` syntax
- app entry point signature
- GUI/ViewPort headers
- input callback signature
- canvas draw calls
- event loop / Back button behavior
- math library availability for `NAN`, `snprintf`, or floating-point formatting

## Rules for v0.4.1

- Do not modify `laia_hello_console`
- Do not flash hardware
- Do not add RTC
- Do not add color/tag picker
- Do not add SD logging
- Fix only what is required to build the scaffold
- Keep the fixed test vector display
- Do not add more Flipper features before v0.4.5 hardware smoke testing

## Success Criteria

v0.4.1 is successful when:

```text
ufbt builds LAIA Stardate without breaking existing apps
the generated FAP exists
the app still targets the fixed vector Stardate 50432.6
```

## Next Milestones

```text
v0.4.1 — Build scaffold inside real Flipper lab
v0.4.2 — Replace fixed vector with Flipper RTC time
v0.4.3 — Text-based color/tag selector complete
v0.4.3a — RGB LED cue for selected notebook color
v0.4.4 — Append-only SD log for current stardate entry
v0.4.5 — Hardware smoke test
v0.6   — Pebble scaffold
```
