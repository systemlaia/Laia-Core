# LAIA Stardate SDK Setup

## Purpose

This document captures the current mini environment and the safe setup plan for
continuing LAIA Stardate SDK work when the MacBook is unavailable.

Do not flash a Flipper.
Do not deploy to a Pebble.
Do not use this machine for hardware deployment until the real SDK environment
and hardware are available.

## Machine info

```text
uname -a
sw_vers
```

- Darwin Pauls-Mac-mini.lan 25.3.0 arm64
- macOS 26.3.1

## Available tools

```text
which python3
python3 --version
which pip3
which git
git --version
which cc
cc --version
which make
make --version
which brew
which docker
```

- python3: /opt/homebrew/bin/python3
- Python 3.14.3
- pip3: /opt/homebrew/bin/pip3
- git: /opt/homebrew/bin/git (git version 2.53.0)
- cc: /usr/bin/cc (Apple clang 17.0.0)
- make: /usr/bin/make (GNU Make 3.81)
- brew: /opt/homebrew/bin/brew
- docker: available (Docker version 29.3.1)

## Missing tools

- uFBT is not installed globally.
- uv is not installed.
- Pebble SDK tooling is not installed on this machine.

## Current project validation

```bash
cd /Users/iv/LAIA
make test
```

- Python/C reference tests pass.
- Existing project files are intact.

## Flipper setup path

A local virtual environment has been created for uFBT at:

```text
/Users/iv/LAIA/.venv-flipper
```

Use the new Make targets for validation:

```bash
make flipper-build
make flipper-clean
make full-test
```

- `make test` remains Python + C only.
- `make flipper-build` performs the Flipper FAP build from `flipper_staging/laia_stardate/`.
- `make full-test` includes Python, C, and Flipper build validation.

Install/check commands used:

```bash
python3 -m venv .venv-flipper
. .venv-flipper/bin/activate
python -m pip install --upgrade pip
python -m pip install --upgrade ufbt
python -m ufbt --help
```

Result:

- uFBT is available in the local venv.
- No global uFBT install was required.
- The Flipper staging app now builds successfully from
  `/Users/iv/LAIA/flipper_staging/laia_stardate/` using `.venv-flipper`.
- The Flipper runtime has been updated to read RTC/local datetime for live
  stardate calculation.
- The current app uses `ViewPort` and input callbacks to support left/right
  color label cycling, up/down tag selection, and Back to exit.
- Supported notebook colors are: Orange, Purple, Yellow, Pink, Silver, White, Green.
- The app now supports an append-only SD log entry via OK.
- SD log entry path: `/apps_data/laia_stardate/log.txt`.
- Log line format: `YYYY-MM-DD HH:MM:SS | stardate XXXXX.X | Color / Tag`.
- No persistence of selected color/tag beyond the current session.
- RGB LED cue now follows the selected notebook color label with approximate LEDs only; the screen remains monochrome.

## Flipper sandbox build attempt

A safe build sandbox was created at:

```text
/Users/iv/LAIA/build_sandboxes/flipper_laia_stardate/
```

The staging package was copied into the sandbox and the following build was
run from the `.venv-flipper` environment:

```bash
cd /Users/iv/LAIA
source .venv-flipper/bin/activate
cd flipper_staging/laia_stardate
python -m ufbt
```

Result:

- The Flipper staging package now builds successfully on the mini with local
  uFBT.
- No hardware flash or deployment has been performed.
- Generated FAP path: `/Users/iv/.ufbt/build/laia_stardate.fap` and installed
  artifact path: `/Users/iv/LAIA/flipper_staging/laia_stardate/dist/laia_stardate.fap`.
- The app now uses `ViewPort` and input callbacks, not direct draw.
- No SD logging or persistence has been implemented yet.
- RGB LED cue now follows the selected notebook color label; the screen remains monochrome.

The build validates that the staging manifest and source are correct for the
current uFBT setup. The next Flipper milestone is to replace the fixed vector
with the Flipper RTC time.

## Pebble setup path

Pebble SDK tooling is not installed on this machine.

- `uv` is missing.
- Python is 3.14.3; Pebble tooling may prefer Python 3.13.
- Docker is available and may support a Rebble SDK container.

Recommended Pebble setup command when the SDK machine is available:

```bash
uv tool install pebble-tool --python 3.13
```

Alternative Docker-based route:

```bash
docker pull rebble/pebble-sdk
```

Do not install Pebble tools on this machine until Python compatibility is confirmed.

## Recommended next step

On the real Flipper SDK machine:

```bash
cd ~/Projects/LAIA-Flipper-Lab
mkdir -p apps/laia_stardate
rsync -av --exclude='.DS_Store' /Users/iv/LAIA/flipper_staging/laia_stardate/ apps/laia_stardate/
. /Users/iv/LAIA/.venv-flipper/bin/activate
cd /Users/iv/LAIA/build_sandboxes/flipper_laia_stardate
python -m ufbt
```

For Pebble SDK setup when a compatible environment is ready:

```bash
uv tool install pebble-tool --python 3.13
```

## Warning

- Do not flash a Flipper.
- Do not deploy to a Pebble.
- Do not use this machine for device deployment.

## Summary

This mini is now prepared as a reference SDK/build host for LAIA Stardate,
with a local uFBT venv available and a sandbox build attempted. The Pebble
SDK still requires a compatible toolchain.
