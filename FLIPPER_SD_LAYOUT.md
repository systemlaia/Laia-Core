# Flipper SD Layout Snapshot

## Mapping pass

- Volume path: `/Volumes/FLIPPER SD`
- Timestamp: `2026-06-07_134154`
- Map folder: `flipper_sd_map/2026-06-07_134154_flipper_sd_map/`
- Backup folder: `flipper_sd_backup/2026-06-07_134154_flipper_sd_backup/`
- Firmware context: Momentum firmware installed
- SD filesystem: FAT32
- Total SD size: 30 GiB
- Used space: 2.5 GiB

No files were modified on the SD card during the mapping pass. In the later
install pass, exactly one FAP was copied to the SD card:

```text
/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap
```

## Map files

The map folder contains:

```text
tree_depth_2.txt
tree_depth_4.txt
all_files.txt
all_dirs.txt
apps_files.txt
apps_data_files.txt
metadata.txt
install_candidates.txt
backup_contents.txt
```

## Backup contents

Selective backup contents:

```text
apps/
apps_data/
apps_assets/
apps_manifests/
top_level_files/
```

Small top-level files backed up:

```text
.blackjack.settings
Manifest
favorites.txt
sam.txt
```

Backup size:

```text
930M
```

## App layout findings

- `/Volumes/FLIPPER SD/apps` exists.
- `/Volumes/FLIPPER SD/apps/Tools` exists.
- `/Volumes/FLIPPER SD/apps_data` exists.
- `/Volumes/FLIPPER SD/ext/apps` does not exist.
- `/Volumes/FLIPPER SD/ext/apps/Tools` does not exist.
- `/Volumes/FLIPPER SD/ext/apps_data` does not exist.

Existing `.fap` files live under the root `apps` tree, grouped by category.
There are 277 `.fap` files total. `/Volumes/FLIPPER SD/apps/Tools` contains 37
direct `.fap` files, including:

```text
/Volumes/FLIPPER SD/apps/Tools/bad_kb.fap
/Volumes/FLIPPER SD/apps/Tools/barcode_app.fap
/Volumes/FLIPPER SD/apps/Tools/brainfuck.fap
/Volumes/FLIPPER SD/apps/Tools/calculator.fap
/Volumes/FLIPPER SD/apps/Tools/hex_viewer.fap
/Volumes/FLIPPER SD/apps/Tools/qrcode.fap
/Volumes/FLIPPER SD/apps/Tools/text_viewer.fap
/Volumes/FLIPPER SD/apps/Tools/totp.fap
```

See `flipper_sd_map/2026-06-07_134154_flipper_sd_map/install_candidates.txt`
for the full candidate and `.fap` listing.

## Recommended install destination

Recommended destination for LAIA Stardate:

```text
/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap
```

Reason: Momentum's mounted SD layout has a root `/apps` tree with category
folders, and the existing `Tools` category already contains direct `.fap`
applications. The `/ext/apps` layout is not present on this card.

Install status: copied by direct SD card copy on 2026-06-07. Source and
destination checksums matched:

```text
2714eed4f82ab9fa4d293239d39b66cd60f4968c
```

Hardware launch/smoke test is still pending until the SD card is reinserted into
the Flipper and the app is launched from Apps -> Tools or the Momentum
equivalent.

## Momentum-built replacement

On 2026-06-07, the previous stock/uFBT SD copy was backed up and replaced with
the Momentum-built FAP.

Backup of replaced FAP:

```text
flipper_sd_backup/preinstall_replaced_laia_stardate/laia_stardate_replaced_20260607_140732.fap
```

Installed Momentum-built FAP:

```text
/Volumes/FLIPPER SD/apps/Tools/laia_stardate.fap
```

Checksum:

```text
65f2f32703415e85261575f9eb6ef84c117a7a7b
```

No firmware flash or SD erase occurred. Hardware launch test is next.
