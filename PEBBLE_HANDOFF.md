# LAIA Stardate Pebble Handoff

## Purpose

This document is for moving the staged LAIA Stardate Pebble package from the
mini/reference repo into a real Pebble SDK environment.

The goal of v0.5.1 is only:

- move the staging package into the Pebble SDK project
- build the scaffold
- fix package/SDK syntax issues
- verify the fixed display output

Do not add live time, color/tag picker, persistent storage, or hardware deployment yet.

> Note: this package is staged on the mini/reference repo and is not built here. Pebble SDK tooling is not installed on this machine; a real Pebble SDK environment is required for v0.5.1.

## Source Package

```text
/Users/iv/LAIA/pebble_staging/laia_stardate/
```

Expected files:

```text
README.md
package.json
src/laia_stardate.c
src/stardate_core.h
src/stardate_core.c
```

## Build Goal

v0.5.1 is successful when:

- the Pebble SDK accepts the package
- the app builds
- the app displays the fixed vector:

```text
Stardate 50432.6
```

## Suggested Build Steps

Do not run these on this machine unless a real Pebble SDK is installed.

```bash
cd /path/to/laia_stardate
pebble build
```

Optional emulator install later (not part of this staging task):

```bash
pebble install --emulator basalt
```

## Likely Fix Areas

Likely areas that may need tuning once the Pebble SDK is available:

- `package.json` schema details
- SDK version compatibility
- target platform support
- TextLayer sizing/fonts
- float formatting support
- localtime/time_t conversion
- app lifecycle functions

## Rules for v0.5.1

- Do not change the stardate formula
- Do not add live time until scaffold builds
- Do not add color/tag picker yet
- Do not add persistent storage yet
- Keep fixed vector display until build is proven
- Compare against Python/C test vector `50432.6`

## Next Milestones

```text
v0.5   — Pebble staging package
v0.5.1 — Build scaffold inside real Pebble SDK environment
v0.5.2 — Replace fixed vector with Pebble local time
v0.5.3 — Add color/tag quick cycling
v0.5.4 — Optional persistent recent entry
```
