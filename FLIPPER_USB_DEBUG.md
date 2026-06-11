# Flipper USB Connection Troubleshooting

## Current status

macOS sees a USB serial device at `/dev/cu.usbmodemCDkbio011`, but uFBT cannot find a Flipper.

## 2026-06-07 reconnect test

- Requested physical state: Flipper unplugged/replugged on the normal home screen.
- Back button while plugging in: user was instructed to avoid holding Back; not independently verifiable from the terminal.
- Latest serial paths:

```text
/dev/cu.usbmodemCDkbio011
/dev/tty.usbmodemCDkbio011
```

- `system_profiler SPUSBDataType | egrep -i 'flipper|serial|cdc|stm|dfu|usbmodem'` returned no matching lines.
- `python -m ufbt cli` still failed:

```text
Failed to find connected Flipper
Is Flipper connected via USB and not in DFU mode?
```

- Launch was not attempted because uFBT CLI did not connect.

Recommended next actions if this still fails after another normal reconnect:

1. Install qFlipper and verify whether the official tool can detect the device.
2. Try another Mac user account, another Mac, or a different USB-C adapter/cable path.
3. Use Flipper's built-in file transfer or SD card route if available.

## Error message from uFBT

```
Failed to find connected Flipper
Is Flipper connected via USB and not in DFU mode?
```

## Physical checks to perform

1. **Check the Flipper screen**
   - Is the Flipper powered on?
   - Is the screen awake (not screensaver/blank)?
   - Press a button to wake if needed

2. **Check USB-C cable**
   - Try a known data cable (not charge-only)
   - Some cheap USB-C cables only carry power, not data
   - Try a different USB port on the Mac

3. **Check Flipper USB mode**
   - On the Flipper: Connect > USB Devices
   - Note which device is enabled (usually "Serial" or similar)
   - Try disabling and re-enabling USB

4. **Check Flipper bootloader state**
   - Hold the back button while plugging in USB (enters bootloader)
   - If this is the case, hold it and plug in normally (or press the back button on the device to exit)
   - The error message asks "not in DFU mode?" which suggests the device may be in bootloader

5. **Force Flipper to exit bootloader/DFU**
   - If the Flipper is in bootloader, hold the back button
   - Unplug the USB
   - Plug USB back in while holding back button
   - Then release back button
   - The main menu should appear

6. **Try a different USB power source**
   - Power the Flipper from battery (not relying on USB power) if possible
   - Some USB hubs or weak power supplies can cause detection issues

## If uFBT still cannot find it after physical checks

Then the issue may be:
- Firmware version mismatch with uFBT SDK
- Corrupted firmware
- Non-official Flipper hardware
- Incompatible custom firmware

At that point, the Flipper may need a firmware restore via DFU mode using the official Flipper tools.

## Manual install fallback

If the Flipper cannot be detected by uFBT but will mount as a USB storage device:

1. Look for a Flipper mount under `/Volumes`
2. Navigate to `/ext/apps/Tools/`
3. Copy `/Users/iv/LAIA/manual_install/momentum_sd/apps/Tools/laia_stardate.fap` into that folder
4. Eject the Flipper and restart it
5. The app should appear in the Tools menu

But this requires the Flipper to expose itself as USB storage, which means it must not be in DFU mode and must support file access.

Momentum firmware is installed. Since uFBT launch is blocked despite the serial
path, the recommended path is manual install via qFlipper, Flipper Lab, or SD
card. See `FLIPPER_MOMENTUM_INSTALL.md`.

## Next steps

1. Perform physical checks above
2. Check Flipper bootloader/DFU state specifically
3. If USB device is still visible, retry `python -m ufbt cli`
4. If that still fails, use the Momentum manual install path in `FLIPPER_MOMENTUM_INSTALL.md`
