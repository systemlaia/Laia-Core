# LAIA Stardate Momentum Rebuild Plan

## Problem

The current LAIA Stardate FAP builds successfully, installs successfully by
direct SD card copy, and matches the copied checksum, but Momentum rejects it at
launch with:

```text
invalid file err_02
```

Current uFBT build metadata:

```text
APPCHK /Users/iv/.ufbt/build/laia_stardate.fap
Target: 7, API: 87.1
```

## Likely cause

The likely cause is a FAP API, firmware version, or firmware fork mismatch. The
app was built against the current stock/uFBT SDK API, while the device is
running Momentum firmware.

This should not be fixed by changing LAIA Stardate source logic yet.

## Correct fix

Rebuild LAIA Stardate against the same Momentum firmware/API as the device.

Do not overwrite the existing build-verified release archive:

```text
releases/laia_stardate_flipper_v0.4.4_build_verified/
```

Keep any Momentum-compatible output in a separate build/release path until it is
verified on hardware.

## Local tool search result

Local safe searches found:

```text
/Users/iv/.ufbt
/Users/iv/.ufbt/current/scripts/ufbt
/Users/iv/LAIA/manual_install/momentum_sd
```

Local safe searches did not find a Momentum firmware source tree or local
Momentum `fbt` build script under `/Users/iv` at the searched depths.

## SDK workspace

Created external SDK workspace:

```text
/Users/iv/SDKs/
```

Large Momentum repos are kept outside `/Users/iv/LAIA`.

Cloned Momentum repos:

```text
/Users/iv/SDKs/Momentum-Firmware
/Users/iv/SDKs/Momentum-Apps
```

Repo revisions:

```text
Momentum-Firmware
branch: dev
commit: 8ed809fba8af7ac3f09b9495a597d8963f9178a8
remote: https://github.com/Next-Flip/Momentum-Firmware.git

Momentum-Apps
branch: dev
commit: b05485f7d13ee1595d06745c881f1d3aadb3d45d
remote: https://github.com/Next-Flip/Momentum-Apps.git
```

Running `./fbt --help` in `Momentum-Firmware` bootstrapped the local Momentum
toolchain and initialized submodules. It did not build or flash firmware.

## Momentum app layout findings

`Momentum-Firmware` has these relevant app locations:

```text
applications/external/
applications_user/
```

`applications_user/README.md` says custom applications belong in
`applications_user`.

`Momentum-Apps` is a bundle of external apps tweaked for Momentum. Its README
states these apps are already included with Momentum releases and the repo is
used to keep them updated and maintained. This makes it useful as a reference
for app folder structure, but less ideal than `applications_user` for a private
LAIA rebuild.

Simple Tools-category example from `Momentum-Apps`:

```text
calculator/
calculator/application.fam
calculator/calculator.c
calculator/tinyexpr.c
calculator/tinyexpr.h
calculator/calcIcon.png
calculator/img/
```

The calculator manifest uses:

```text
apptype=FlipperAppType.EXTERNAL
fap_category="Tools"
```

LAIA Stardate already uses the same external app category pattern:

```text
apptype=FlipperAppType.EXTERNAL
fap_category="Tools"
```

## Prepared external source copy

Created a safe external source copy:

```text
/Users/iv/SDKs/laia_momentum_apps/laia_stardate/
```

Contents:

```text
README.md
application.fam
laia_stardate.c
stardate_core.c
stardate_core.h
```

This copy is outside both Momentum repos and outside `/Users/iv/LAIA` source
ownership. It is source-only and has no app logic changes.

## App-only build command found

Momentum `./fbt --help` documents app-only targets:

```text
fap_{APPID}, build APPSRC={APPID}; launch APPSRC={APPID}
```

Momentum docs also show:

```text
./fbt launch APPSRC=your_appid
```

Example app docs in `Momentum-Apps` show:

```text
./fbt fap_coleco
./fbt launch_app APPSRC=applications_user/flipper_atomicdiceroller
```

Recommended first build path, without USB launch:

```bash
cd /Users/iv/SDKs/Momentum-Firmware
ln -s /Users/iv/SDKs/laia_momentum_apps/laia_stardate applications_user/laia_stardate
./fbt fap_laia_stardate
```

Expected FAP output path is likely under the Momentum firmware build tree,
similar to:

```text
/Users/iv/SDKs/Momentum-Firmware/build/f7-firmware-D/.extapps/laia_stardate.fap
```

The exact output path should be confirmed from the build output before copying
anything to SD.

## Momentum app-only build result

Build attempted on 2026-06-07:

```bash
cd /Users/iv/SDKs/Momentum-Firmware
./fbt fap_laia_stardate
```

Result: succeeded.

Momentum-built FAP:

```text
/Users/iv/SDKs/Momentum-Firmware/build/f7-firmware-C/.extapps/laia_stardate.fap
```

Relevant build output:

```text
API version 87.1 is up to date
APPCHK build/f7-firmware-C/.extapps/laia_stardate.fap
```

Momentum-Firmware emitted warnings for existing bundled external app manifests
`cli_bridge` and `mtp`; these warnings were not from LAIA Stardate and did not
block the build.

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

No SD write was performed during this build pass.

## Momentum SD install result

Installed on 2026-06-07 by direct SD copy from:

```text
manual_install/momentum_sd_momentum_build/apps/Tools/laia_stardate.fap
```

to:

```text
/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap
```

The previous stock/uFBT FAP on the SD card was backed up before replacement:

```text
flipper_sd_backup/preinstall_replaced_laia_stardate/laia_stardate_replaced_20260607_140732.fap
```

Source and SD destination checksums matched:

```text
65f2f32703415e85261575f9eb6ef84c117a7a7b
```

No firmware flash or SD erase occurred. Hardware launch test is next.

## Candidate build paths

1. Use `Momentum-Firmware` with a symlink or copy in `applications_user`.
2. Use `Momentum-Apps` as a structure/reference repo; it appears better for
   maintaining bundled external apps than as the private LAIA build root.
3. If Momentum provides newer SDK-compatible app build instructions later,
   follow those instead of stock uFBT.
4. As a fallback, install official firmware only if the user chooses that path
   later. Do not do that automatically.

## Prepared source package

Source-only package for a Momentum rebuild:

```text
momentum_rebuild/laia_stardate/
```

Contents:

```text
application.fam
laia_stardate.c
stardate_core.c
stardate_core.h
README.md
```

These files are copied from the current buildable Flipper staging app without
feature changes.

## Next recommended command/path

After obtaining the matching Momentum firmware source or SDK instructions,
place or reference:

```text
/Users/iv/LAIA/momentum_rebuild/laia_stardate/
```

or the external copy:

```text
/Users/iv/SDKs/laia_momentum_apps/laia_stardate/
```

as a Momentum external/user app and run the Momentum app-only build command.
Then install that Momentum-built FAP to:

```text
/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap
```

only after backing up any existing `laia_stardate.fap` on the SD card.
