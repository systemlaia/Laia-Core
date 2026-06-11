# LAIA Stardate Momentum Manual Install

## Purpose

Use this path when Momentum firmware is installed and `ufbt launch` cannot
handshake with the Flipper, even though macOS exposes a USB serial device.

This is a manual FAP copy/install route only. Do not flash firmware, update
firmware, repair firmware, format the SD card, or erase SD contents while using
this procedure.

## Verified build

Verified on 2026-06-07:

```bash
cd /Users/iv/LAIA
make full-test
```

Result:

- Python tests: passed
- C tests: passed
- Flipper uFBT build: passed
- FAP check: passed, target 7, API 87.1

## FAP artifacts

Freshly verified artifacts:

```text
/Users/iv/LAIA/flipper_staging/laia_stardate/dist/laia_stardate.fap
/Users/iv/.ufbt/build/laia_stardate.fap
/Users/iv/LAIA/manual_install/momentum_sd/apps/Tools/laia_stardate.fap
```

Release archive artifact:

```text
/Users/iv/LAIA/releases/laia_stardate_flipper_v0.4.4_build_verified/laia_stardate.fap
```

The preferred manual-install file is:

```text
/Users/iv/LAIA/manual_install/momentum_sd/apps/Tools/laia_stardate.fap
```

It mirrors the intended SD-card destination:

```text
/ext/apps/Tools/laia_stardate.fap
```

## Checksums

```text
8519e2f78ccd5a9758a5be6441d492494a4b3aabd9ccbf35a6244a7d5a9e3e9d  flipper_staging/laia_stardate/dist/laia_stardate.fap
8519e2f78ccd5a9758a5be6441d492494a4b3aabd9ccbf35a6244a7d5a9e3e9d  /Users/iv/.ufbt/build/laia_stardate.fap
8519e2f78ccd5a9758a5be6441d492494a4b3aabd9ccbf35a6244a7d5a9e3e9d  manual_install/momentum_sd/apps/Tools/laia_stardate.fap
caad5d926ba64e7c509de23dff9f29bd75e536132b06a8e261c7f85e1e2da6c6  releases/laia_stardate_flipper_v0.4.4_build_verified/laia_stardate.fap
```

The staged manual-install copy matches the freshly built staging and uFBT
artifacts.

## qFlipper path

1. Install and open qFlipper.
2. Connect the Flipper on the normal Momentum home screen.
3. Use file/browser access only.
4. Navigate to the SD card path:

```text
/ext/apps/Tools/
```

5. Upload or copy:

```text
/Users/iv/LAIA/manual_install/momentum_sd/apps/Tools/laia_stardate.fap
```

6. Eject or disconnect cleanly.
7. On the Flipper, open the apps/tools area and launch `LAIA Stardate`.

Do not use qFlipper firmware update, repair, flash, format, or SD erase actions
for this smoke test.

## Flipper Lab path

1. Open Flipper Lab in a compatible browser.
2. Connect the Flipper on the normal Momentum home screen.
3. Use file/browser access only.
4. Navigate to the SD card path:

```text
/ext/apps/Tools/
```

5. Upload:

```text
/Users/iv/LAIA/manual_install/momentum_sd/apps/Tools/laia_stardate.fap
```

6. Disconnect cleanly.
7. On the Flipper, open the apps/tools area and launch `LAIA Stardate`.

Do not use Flipper Lab firmware update, repair, flash, format, or SD erase
actions for this smoke test.

## Direct SD-card path

If the SD card can be mounted directly on the Mac, copy the staged file to:

```text
apps/Tools/laia_stardate.fap
```

on the mounted SD card. Then eject the SD card cleanly, reinsert it into the
Flipper, and launch `LAIA Stardate` from the apps/tools area.

## Continue smoke test

After the app launches, continue with `FLIPPER_SMOKE_TEST.md`:

- App launch and readable stardate display
- Left/Right color cycling
- Up/Down tag cycling
- RGB LED cue
- OK save
- Back exit
- SD log at `/apps_data/laia_stardate/log.txt`

Record results in `FLIPPER_SMOKE_TEST_RESULTS.md`.
