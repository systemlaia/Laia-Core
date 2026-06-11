# LAIA Stardate Flipper Smoke Test

## Purpose

This checklist is for the first real-device test of the buildable LAIA Stardate
FAP. The goal is to verify behavior only, not add features. This document
captures physical-device validation before continuing with further Flipper
feature development.

## Pre-Test Requirements

- Flipper has SD card inserted
- Flipper date/time is set correctly
- App FAP has been copied/installed safely
- Battery is sufficient
- No important SD files are at risk
- Current build passed:
  - `make flipper-build`
  - `make full-test`

## Build Command

```bash
cd /Users/iv/LAIA
make full-test
```

## App Launch Test

- App appears as `LAIA Stardate`
- App launches without crash
- Screen is readable
- Stardate value appears
- Real date/time shown looks plausible, if displayed

## Control Test

- Left cycles notebook color backward
- Right cycles notebook color forward
- Up cycles tag backward
- Down cycles tag forward
- Back exits cleanly

Expected color labels:

- Orange
- Purple
- Yellow
- Pink
- Silver
- White
- Green

Expected tag labels:

- Priority
- Project
- Idea
- Personal
- Reference
- Neutral
- Done

Default:

- Purple / Project

## RGB LED Cue Test

- LED changes when color changes
- LED does not change when only tag changes
- LED cue is approximate
- LED resets/off after app exits, if implemented

Expected approximate cues:

- Orange: red + green
- Purple: red + blue
- Yellow: red + green
- Pink: red + blue
- Silver: dim/cool white approximation
- White: red + green + blue
- Green: green only

## SD Log Test

- Press OK once
- App shows a saved/success message
- Press OK again with a different color/tag
- App still responds
- No crash or freeze

Expected path:

```text
/apps_data/laia_stardate/log.txt
```

Expected line format:

```text
YYYY-MM-DD HH:MM:SS | stardate XXXXX.X | Color / Tag
```

Example:

```text
2026-06-07 21:14:32 | stardate 50432.6 | Purple / Project
```

## Post-Test Verification

- Connect Flipper or inspect SD card
- Locate `/apps_data/laia_stardate/log.txt`
- Confirm entries were appended
- Confirm color/tag labels match selected values
- Confirm timestamps are plausible

## Failure Notes

| Test area | Symptom | Notes | Next fix |
|---|---|---|---|
| Launch | | | |
| RTC | | | |
| Controls | | | |
| LED | | | |
| SD log | | | |
| Exit/reset | | | |

## Rules

- Do not add features during smoke test
- Record behavior exactly
- Fix only one failure at a time afterward
- Keep Python/C/Flipper build tests passing

## Pass Criteria

The smoke test passes if:

- App launches
- Current stardate displays
- Controls work
- LED cue changes with color
- OK creates/appends log entry
- Back exits
- `log.txt` contains at least one valid entry
