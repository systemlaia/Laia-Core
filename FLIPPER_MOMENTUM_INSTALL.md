# LAIA Stardate Momentum Install

## Why this exists

The LAIA Stardate uFBT build works, but `ufbt launch` cannot handshake with the
Momentum Flipper. macOS still sees the serial path at
`/dev/cu.usbmodemCDkbio011`, but qFlipper/uFBT device handshakes have been
unreliable on this mini. The SD-card route is now the preferred manual install
path after mapping and backing up the mounted card.

Momentum is custom firmware based on official Flipper firmware. App folder
names and menus may differ slightly from stock firmware.

Do not flash firmware, update firmware, repair firmware, format the SD card, or
erase SD contents for this install path.

## FAP sources

Preferred FAP source:

```text
/Users/iv/LAIA/releases/laia_stardate_flipper_v0.4.4_build_verified/laia_stardate.fap
```

Fresh build FAP source:

```text
/Users/iv/.ufbt/build/laia_stardate.fap
```

Prepared manual staging copy:

```text
/Users/iv/LAIA/manual_install/momentum_sd/apps/Tools/laia_stardate.fap
```

## Option A - qFlipper

1. Install and open qFlipper.
2. Confirm qFlipper sees the Flipper.
3. Open the file browser.
4. Copy `laia_stardate.fap` to the external apps folder.
5. Prefer the `Tools` category/folder if it is available.
6. Eject or disconnect cleanly.
7. Launch `LAIA Stardate` from the Flipper apps/tools menu.

Do not use qFlipper firmware update, repair, flash, format, or SD erase actions.

## Option B - Flipper Lab web file browser

1. Open Flipper Lab in a WebSerial-capable browser.
2. Confirm the device connection.
3. Open the web file browser.
4. Copy `laia_stardate.fap` into the external apps folder.
5. Prefer `Tools` if it is available.
6. Disconnect cleanly.
7. Launch `LAIA Stardate` from the Flipper apps/tools menu.

Do not use Flipper Lab firmware update, repair, flash, format, or SD erase
actions.

## Option C - SD card direct copy

1. Remove and mount the Flipper SD card only if safe.
2. Find the external apps folder matching Momentum's app layout.
3. Copy `laia_stardate.fap` into that external apps folder.
4. Prefer an app folder corresponding to `Tools`.
5. Eject the SD card cleanly before reinserting it into the Flipper.
6. Launch `LAIA Stardate` from the Flipper apps/tools menu.

For the currently mapped Momentum card, the recommended destination is:

```text
/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap
```

Install status: copied by direct SD card copy on 2026-06-07. Source and
destination checksums matched:

```text
2714eed4f82ab9fa4d293239d39b66cd60f4968c
```

Launch was attempted on Momentum and failed with:

```text
invalid file err_02
```

Current FAP metadata is:

```text
Target: 7, API: 87.1
```

Likely cause: FAP API, firmware version, or firmware fork mismatch. Hardware
launch/smoke test is blocked until LAIA Stardate is rebuilt against
Momentum-compatible firmware/API.

## Momentum Build Candidate

Momentum app-only build succeeded on 2026-06-07 using:

```text
/Users/iv/SDKs/Momentum-Firmware
```

Output FAP:

```text
/Users/iv/SDKs/Momentum-Firmware/build/f7-firmware-C/.extapps/laia_stardate.fap
```

Release folder:

```text
releases/laia_stardate_momentum_v0.4.4_build_verified/
```

Manual install candidate:

```text
manual_install/momentum_sd_momentum_build/apps/Tools/laia_stardate.fap
```

Checksum:

```text
65f2f32703415e85261575f9eb6ef84c117a7a7b
```

No SD write was performed during the Momentum build pass. Next install should
copy the staged Momentum-built FAP to `/Volumes/FLIPPER SD/apps/Tools/` only
after backing up any existing `laia_stardate.fap` on the SD card.

## Momentum SD Install

Installed on 2026-06-07 by direct SD copy:

```text
/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap
```

Source:

```text
manual_install/momentum_sd_momentum_build/apps/Tools/laia_stardate.fap
```

The previous stock/uFBT FAP was backed up before replacement:

```text
flipper_sd_backup/preinstall_replaced_laia_stardate/laia_stardate_replaced_20260607_140732.fap
```

Source and SD destination checksums matched:

```text
65f2f32703415e85261575f9eb6ef84c117a7a7b
```

No firmware flash or SD erase occurred. Hardware launch test is next.

## Momentum-specific notes

- Momentum is custom firmware based on official firmware.
- App folder names or menus may differ slightly from stock.
- If `Tools` is not visible, inspect the SD card/app folders before copying.
- Do not overwrite unrelated apps.
- If a matching folder is unclear, stop and list the folder tree before copying.

## Smoke test continuation

After the app launches, continue with `FLIPPER_SMOKE_TEST.md` and record results
in `FLIPPER_SMOKE_TEST_RESULTS.md`.
