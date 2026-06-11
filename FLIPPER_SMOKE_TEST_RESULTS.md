# LAIA Stardate Flipper Hardware Smoke Test Results

## Test metadata

- Date: 2026-06-07
- Location: /Users/iv/LAIA
- Install method attempted: uFBT USB app launch, then direct SD card copy
- FAP artifact used: releases/laia_stardate_flipper_v0.4.4_build_verified/laia_stardate.fap
- Release archive: releases/laia_stardate_flipper_v0.4.4_build_verified/
- Manual install staging path: /Users/iv/LAIA/manual_install/momentum_sd/apps/Tools/laia_stardate.fap
- Installed SD path: /Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap

## Device status

- The system exposes a USB serial device at `/dev/cu.usbmodemCDkbio011` and `/dev/tty.usbmodemCDkbio011`.
- Reconnect test on 2026-06-07 again detected `/dev/cu.usbmodemCDkbio011` and `/dev/tty.usbmodemCDkbio011`.
- Requested device state for reconnect test: normal Flipper home screen.
- Back button while plugging in: user was instructed to avoid holding Back; not independently verifiable from the terminal.
- `FLIP_PORT=/dev/cu.usbmodemCDkbio011 python -m ufbt fap_laia_stardate launch` returned:

```text
2026-06-07 04:39:27,062 [ERROR] Failed to find connected Flipper
```

- `python -m ufbt cli` returned:

```text
Failed to find connected Flipper
Is Flipper connected via USB and not in DFU mode?
```

- Reconnect retry of `python -m ufbt cli` returned the same error:

```text
Failed to find connected Flipper
Is Flipper connected via USB and not in DFU mode?
```

- No Flipper mount appeared under `/Volumes`.
- qFlipper is not installed on the system.
- Momentum firmware is installed.
- Flipper SD card is mounted directly at `/Volumes/FLIPPER SD`.

## Smoke test result

- App install/copy: completed by direct SD card copy
- App launch: not verified
- Stardate display: not verified
- Controls: not verified
- LED behavior: not verified
- SD log: not verified

## Notes

- The build is still validated locally by `make full-test`.
- The FAP artifact exists in both `/Users/iv/.ufbt/build/laia_stardate.fap` and `releases/laia_stardate_flipper_v0.4.4_build_verified/laia_stardate.fap`.
- A serial device is visible, but uFBT CLI and app launch cannot complete the connection.
- Error message indicates Flipper may be in DFU mode or not exposing the expected USB interface.
- Hardware smoke test is pending until the Flipper is confirmed as USB-detectable by uFBT.
- Launch was not attempted during the reconnect retry because uFBT CLI still could not connect.
- uFBT launch is blocked despite the serial path, so manual install via qFlipper, Flipper Lab, or SD card is now the recommended path.
- Momentum manual-install path is documented in `FLIPPER_MOMENTUM_INSTALL.md`; a staging copy also exists at `manual_install/momentum_sd/apps/Tools/laia_stardate.fap`.
- SD card map/backup was created in `flipper_sd_map/2026-06-07_134154_flipper_sd_map/` and `flipper_sd_backup/2026-06-07_134154_flipper_sd_backup/`.
- SD card route is now the preferred install path because qFlipper/uFBT device handshakes failed on this mini.
- FAP copied to `/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap` by direct SD card copy.
- Source and destination checksums matched: `2714eed4f82ab9fa4d293239d39b66cd60f4968c`.
- Launch was attempted on Momentum and failed with `invalid file err_02`.
- Current FAP build metadata is `Target: 7, API: 87.1`.
- Likely cause: FAP API/firmware/fork mismatch with Momentum.
- Hardware test is blocked until a Momentum-compatible build exists.
- Momentum app-only build attempted on 2026-06-07 and succeeded.
- Momentum-built FAP path: `/Users/iv/SDKs/Momentum-Firmware/build/f7-firmware-C/.extapps/laia_stardate.fap`.
- Momentum release folder: `releases/laia_stardate_momentum_v0.4.4_build_verified/`.
- Momentum manual install candidate: `manual_install/momentum_sd_momentum_build/apps/Tools/laia_stardate.fap`.
- Momentum-built FAP checksum: `65f2f32703415e85261575f9eb6ef84c117a7a7b`.
- No SD write was performed during the Momentum build pass.
- Momentum-built FAP copied to SD at `/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap`.
- Previous stock/uFBT SD FAP was replaced after backup to `flipper_sd_backup/preinstall_replaced_laia_stardate/laia_stardate_replaced_20260607_140732.fap`.
- Source and SD destination checksums matched: `65f2f32703415e85261575f9eb6ef84c117a7a7b`.
- No firmware flash or SD erase occurred.

## Diagnostic output

```text
CLI error: Is Flipper connected via USB and not in DFU mode?
```

This suggests:
- Flipper may be in DFU mode or bootloader mode
- Flipper may not be properly powered on/awake
- Flipper may not be exposing Flipper-specific USB CDC interfaces (only generic serial)

## Next fix / next step

- Install qFlipper and verify whether the official tool can detect the device.
- Try another Mac user account, another Mac, or a different USB-C adapter/cable path.
- Reinsert the SD card into the Flipper and launch LAIA Stardate from Apps -> Tools or the Momentum equivalent.
- After uFBT CLI connects, re-run the install attempt with `python -m ufbt fap_laia_stardate launch` or via the Flipper USB storage path if mounted.
- Then execute the checklist from `FLIPPER_SMOKE_TEST.md`.
