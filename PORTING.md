# LAIA Stardate Porting Notes

This utility generates personal notebook stardates using a DS9-era timeline
mapping. It is intended for personal notes, not formal LAIA reports. Reports and
system logs should continue using real-world dates, commit hashes, version
numbers, and normal timestamps.

## Portable Core Contract

The portable core is a small function that takes real-world date/time
components and returns a floating-point stardate.

```text
calculate_stardate(
    year,
    month,
    day,
    hour,
    minute,
    second,
    offset_years = 347
) -> floating-point stardate
```

- Inputs are real-world date/time components.
- The default offset maps real year 2026 to in-universe year 2373.
- The offset is applied to the year only.
- The function calculates the fraction of the adjusted in-universe year that has elapsed.

Stardate formula:

```text
adjusted_year = year + offset_years
fraction_of_year = elapsed_seconds_in_adjusted_year / total_seconds_in_adjusted_year
stardate = ((adjusted_year - 2323) * 1000) + (fraction_of_year * 1000)
```

Notes:

- The current Python implementation uses the real calendar year length of the
  adjusted year to compute the fraction.
- The formula is intentionally simple so it can be ported to small embedded
  devices.
- The output is a floating-point stardate value, rounded later when formatting.

## Formatting Contract

The notebook output format is compact and personal:

```text
(stardate: 50123.4)
(stardate: 50123.4) [Purple]
(stardate: 50123.4) [Project]
(stardate: 50123.4) [Purple / Project]
```

Formatting rules:

- Default precision is 1 decimal place.
- Color and tag are optional.
- If both color and tag are present, use `[Color / Tag]`.
- If only one is present, use `[Value]`.
- The compact personal reference is the default user-facing output.
- Formal reports should not use stardates as primary timestamps.

## Known Test Vectors

These values come from the current Python implementation and are rounded to 1 decimal place.

Real datetime | Offset years | Adjusted year | Expected stardate | Notes
---|---|---|---|---
2026-01-01 00:00:00 | 347 | 2373 | 50000.0 | start of mapped year
2026-06-07 21:14:00 | 347 | 2373 | 50432.6 | mid-year notebook entry
2026-12-31 23:59:00 | 347 | 2373 | 51000.0 | end of mapped year
2026-06-07 21:14:00 | 0 | 2026 | -296567.4 | no offset, not in DS9-era range

## Embedded Port Notes

When porting to Flipper Zero, Pebble, or other field tools:

- Avoid dynamic allocation if possible.
- Keep the calculation independent from UI code.
- Use integer date/time fields as input.
- Use double or fixed-point math depending on platform support.
- Formatting should be separate from the calculation core.
- Color/tag picker should be UI-specific, not part of the core formula.

## Planned Ports

```text
v0.1 — Python CLI reference implementation
v0.2 — Portable core contract
v0.3 — Plain C core
v0.4 — Flipper Zero app scaffold
v0.4.1 — Flipper scaffold build pass on mini
v0.4.2 — Replace fixed vector with Flipper RTC time
v0.4.3 — Text-based color/tag selector complete
v0.4.3a — RGB LED cue for selected notebook color
v0.4.4 — Add optional SD logging
v0.5 — Pebble app scaffold
```

## C Build Instructions

Compile and run the plain C core test harness:

```text
cc -std=c99 -Wall -Wextra -pedantic c_core/stardate_core.c c_core/test_stardate_core.c -o c_core/test_stardate_core -lm
./c_core/test_stardate_core
```

## Flipper Staging Package

A staging package has been created at `flipper_staging/laia_stardate/`.

- Purpose: copy into a real Flipper apps folder later.
- Location: `flipper_staging/laia_stardate/`
- Status: scaffold only, not hardware-tested.
- Current runtime reads Flipper RTC/local datetime for live stardate calculation.
- The app supports a text-based color/tag selector using `ViewPort` and input callbacks.
- Supported notebook colors are: Orange, Purple, Yellow, Pink, Silver, White, Green.
- The app now supports `OK` to append the current entry to `/apps_data/laia_stardate/log.txt`.
- Log line format: `YYYY-MM-DD HH:MM:SS | stardate XXXXX.X | Color / Tag`.
- The fixed test vector remains canonical for documentation and Python/C tests.
- Builds successfully on the mini with local uFBT.
- No persistence of selected color/tag beyond the current session.
- No hardware flash or deployment has been performed.
- RGB LED cue now follows the selected notebook color label with approximate LEDs only.

## Pebble Staging Package

A staging package has been created at `pebble_staging/laia_stardate/`.

- Purpose: copy into a real Pebble SDK project later.
- Location: `pebble_staging/laia_stardate/`
- Status: scaffold only, not SDK-tested.
- Current app displays a fixed test vector only.
- See `PEBBLE_HANDOFF.md` for handoff/checklist details.

## SDK Machine Note

The mini is being prepared as the SDK/build machine for LAIA Stardate while the MacBook is unavailable. See `SDK_SETUP.md` for environment details, local uFBT setup, and Pebble toolchain recommendations.

## Flipper Handoff

See `FLIPPER_HANDOFF.md` for the handoff checklist and transfer/build steps.
