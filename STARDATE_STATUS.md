# LAIA Stardate Status

## Current milestone

| Milestone | Status |
|---|---|
| v0.4.0 | Flipper Zero app scaffold created |
| v0.4.1 | Flipper staging build pass on mini with uFBT |
| v0.4.2 | Replace fixed vector with Flipper RTC time |
| v0.4.3 | Text-based color/tag selector complete |
| v0.4.3a | RGB LED cue for selected notebook color |
| v0.4.4 | Append-only SD log for current stardate entry |
| v0.4.5 | Hardware smoke test |
| v0.6 | Pebble app scaffold |

## Validated commands

```bash
cd /Users/iv/LAIA
make test
make flipper-build
make full-test
```

- `make test` = Python + portable C validation
- `make flipper-build` = Flipper FAP build only
- `make full-test` = Python + C + Flipper build
- No hardware flash or deployment is performed by these targets.

## Canonical test vector

- Real datetime: `2026-06-07 21:14:00`
- Offset: `347`
- Expected stardate: `50432.6`

## Build status by target

- Python: passing
- C core: passing
- Flipper: uFBT build passing, RTC/local time in runtime, not hardware-tested
- Pebble: staged only, not SDK-tested

## Notes

- uFBT is installed in the local venv at `.venv-flipper`.
- The current Flipper scaffold uses `ViewPort` and input callbacks, reads Flipper RTC/local datetime, and supports text-based notebook labels.
- The app supports left/right to cycle a notebook color label, up/down to cycle a tag label, OK to append an SD log entry, and Back to exit.
- Supported notebook colors are: Orange, Purple, Yellow, Pink, Silver, White, Green.
- SD log entry path: `/apps_data/laia_stardate/log.txt`.
- Log line format: `YYYY-MM-DD HH:MM:SS | stardate XXXXX.X | Color / Tag`.
- No persistence of selected color/tag beyond the current session.
- RGB LED cue now follows the selected notebook color label with approximate LEDs only, while the screen remains monochrome.
- `make flipper-build` builds the Flipper staging package only; no hardware flash or deployment occurs.
- Release archive path: `releases/laia_stardate_flipper_v0.4.4_build_verified/`
- v0.4.5 hardware smoke test attempted; serial device visible on `/dev/cu.usbmodemCDkbio011`, but uFBT/CLI report: "Is Flipper connected via USB and not in DFU mode?"
- 2026-06-07 focused USB reconnect retry: `/dev/cu.usbmodemCDkbio011` and `/dev/tty.usbmodemCDkbio011` still detected, USB profiler filter returned no matching Flipper/CDC/DFU lines, and `python -m ufbt cli` still failed with "Failed to find connected Flipper". Launch was not attempted because CLI did not connect.
- Momentum firmware is installed.
- uFBT launch is blocked despite the serial path, so manual install via qFlipper, Flipper Lab, or SD card is now the recommended path.
- 2026-06-07 Momentum manual-install path prepared: `manual_install/momentum_sd/apps/Tools/laia_stardate.fap`, documented in `FLIPPER_MOMENTUM_INSTALL.md`.
- 2026-06-07 Flipper SD card mounted directly at `/Volumes/FLIPPER SD`; map and selective backup created under `flipper_sd_map/2026-06-07_134154_flipper_sd_map/` and `flipper_sd_backup/2026-06-07_134154_flipper_sd_backup/`.
- SD card route is now preferred because qFlipper/uFBT device handshakes failed on this mini.
- 2026-06-07 FAP installed by direct SD card copy to `/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap`; checksum matched release source `2714eed4f82ab9fa4d293239d39b66cd60f4968c`.
- Launch was attempted on Momentum and failed with `invalid file err_02`.
- Current FAP build metadata is `Target: 7, API: 87.1`; likely cause is a FAP API/firmware/fork mismatch with Momentum.
- Hardware test is blocked until a Momentum-compatible build exists.
- 2026-06-07 Momentum app-only build succeeded using `/Users/iv/SDKs/Momentum-Firmware`.
- Momentum-built FAP: `/Users/iv/SDKs/Momentum-Firmware/build/f7-firmware-C/.extapps/laia_stardate.fap`.
- Momentum release folder: `releases/laia_stardate_momentum_v0.4.4_build_verified/`.
- Momentum manual install candidate: `manual_install/momentum_sd_momentum_build/apps/Tools/laia_stardate.fap`.
- No SD write was performed during the Momentum build pass.
- 2026-06-07 Momentum-built FAP copied to SD at `/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap`, replacing the previous stock/uFBT FAP after backup to `flipper_sd_backup/preinstall_replaced_laia_stardate/laia_stardate_replaced_20260607_140732.fap`.
- Momentum SD copy checksum matched `65f2f32703415e85261575f9eb6ef84c117a7a7b`; no firmware flash or SD erase occurred.
- See `FLIPPER_USB_DEBUG.md` for physical troubleshooting steps

## Next actions

- Reinsert the SD card into the Flipper, launch LAIA Stardate from Apps -> Tools or the Momentum equivalent, then continue `FLIPPER_SMOKE_TEST.md`
- After uFBT CLI connects, retry v0.4.5 hardware smoke test
- Pebble SDK setup/build
- Hardware verification before adding more Flipper features
