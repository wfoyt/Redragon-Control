# K686 hardware support and protocol provenance

The user identified the underside label as **K686WBG-RGB-MAX**. The Amazon
[ASIN B0DBHTJ8ZP](https://www.amazon.com/dp/B0DBHTJ8ZP/) identifies the K686 PRO.
The manufacturer's [EISA MAX K686 download page](https://redragonshop.com/blogs/product-download/eisa-max-k686)
links the [official K686 manual](https://cdn.shopify.com/s/files/1/0012/4957/4961/files/K686_user_manual.pdf?v=1723515517)
and [K686-RGB-PRO v2.0 Windows software](https://cdn.shopify.com/s/files/1/0012/4957/4961/files/Redragon_K686-RGB-PRO_Setup_v2.0_20240110.exe?v=1709019093).
The installer was extracted for inspection; it was never executed.

Its `Dev/kb/KB.ini` declares wired USB **258a:010c**, wireless receiver
**3554:fa09**, and `Name=K686-RGB-PRO Keyboard`. Many manufacturers share these
chipset IDs. A matching VID/PID alone is insufficient authorization for RGB
commands. The implementation verifies the firmware model each time the device
is opened, and retains that same file descriptor for subsequent daemon frames.

## Wired direct RGB

The implementation independently encodes protocol facts from OpenRGB revision
[`deeecd3ba6e8a4b085870766e312699425f8806b`](https://github.com/CalcProgrammer1/OpenRGB/tree/deeecd3ba6e8a4b085870766e312699425f8806b).
Relevant original source files:

- [Detection and model query](https://github.com/CalcProgrammer1/OpenRGB/blob/deeecd3ba6e8a4b085870766e312699425f8806b/Controllers/SinowealthController/SinowealthControllerDetect.cpp)
- [K686 model identifiers and LED layout](https://github.com/CalcProgrammer1/OpenRGB/blob/deeecd3ba6e8a4b085870766e312699425f8806b/Controllers/SinowealthController/SinowealthKeyboard10cController/SinowealthKeyboard10cDevices.cpp)
- [Direct RGB report format](https://github.com/CalcProgrammer1/OpenRGB/blob/deeecd3ba6e8a4b085870766e312699425f8806b/Controllers/SinowealthController/SinowealthKeyboard10cController/SinowealthKeyboard10cController.cpp)
- [Keepalive requirement](https://github.com/CalcProgrammer1/OpenRGB/blob/deeecd3ba6e8a4b085870766e312699425f8806b/Controllers/SinowealthController/SinowealthKeyboard10cController/RGBController_SinowealthKeyboard10c.cpp)

Select a HID interface with Feature Report ID `06` and total report length
520 bytes. Before sending a query, read USB identity and physical connection
with HIDIOCGRAWINFO/HIDIOCGRAWPHYS on the opened descriptor. Reject an interface
whose device family differs from the explicitly selected keyboard, including
an unrelated device that has reused the old `/dev/hidrawN` path.
Send a zero-padded 520-byte model query starting
`06 82 01 00 01 00 06`; retrieve Feature Report `06`. Response byte 13 must be
`05` or `20`, the two model IDs mapped to Redragon K686 Eisa Pro by OpenRGB.
Other models are rejected before any lighting command.

Direct RGB is a zero-padded 520-byte feature report starting
`06 08 00 00 01 00 7a 01`. RGB triplets start at byte 8. The K686 LED indices
run through 112, so this app fills 113 triplets with the requested uniform
colour, scaled to the requested brightness. Off uses black triplets.

This mode is **volatile and needs a keepalive**. OpenRGB refreshes it after
one second. The local daemon must continue sending frames while active.
Stopping the daemon lets the keyboard return to its onboard lighting.
This direct path is used only for Static color and Off. The former
software-generated animations have been removed from device control.

The user's wired K686 MAX was observed read-only as `258a:010c`, with physical
connection `usb-0000:02:00.0-4`. Its keyboard interface has no Feature Report 6;
the other HID interface has a 519-byte Feature Report 6 payload, matching the
expected 520-byte total. That descriptor is covered by a regression test.

The code has packet-format and rejection-path tests with simulated HID
responses. On 2026-10-09, this specific K686WBG-RGB-MAX was connected by USB-C,
reported firmware model `20` (hex), and accepted direct RGB commands. The user
confirmed a steady teal (`#00ccbb`, 65% brightness) test. The actual descriptor
exposed Feature Report 6 with the expected 520-byte total length on hidraw8.
The RGB service successfully maintained direct mode. The input remapping
service also started and stopped against the real composite event interfaces.
Bluetooth RGB, on-device remapping, and a software factory reset remain
unsupported until their commands are verified for this model.

## 2.4 GHz direct RGB

The receiver uses a different protocol: 20-byte Output Report `13`, rather
than the wired 520-byte Feature Report. Protocol facts were independently
encoded from the [wireless streaming reference](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/web/src/lib/wireless-mode.ts)
and [model query documentation](https://github.com/dnviti/aula-x99-pro-driver-linux/blob/7ec12ad1f2bb642a46ae91b0c3bce327de96f4ce/PROTOCOL.md).
These references concern shared chipsets; their device names alone do not
establish K686 compatibility. No reference driver or Windows executable was run.

The app first checks the opened interface's USB identity and physical family,
and its Output Report `13` descriptor must have total length 20. It sends a
read-only `13 05` product query with a checksum in byte 19 (the low byte of the
sum of bytes 0–18). The reply must have a valid checksum, header
`13 05 01 00 0a`, and product signature `03 00 00 00 01 20` in bytes 5–10.
That signature matches the official driver's K686 `PSD` value and was observed
on the user's paired receiver. Unknown paired models are rejected before RGB.

Direct frames use command `88`. A uniform color is encoded as
`R G B 71` followed by LED indices `00` through `70` (113 LEDs). The resulting
117 bytes are split into nine fragments of at most 14 bytes. Each report starts
`13 88 fragment-count sequence length`, where length is `10` hex plus the
fragment's byte count; data starts at byte 5 and the checksum is byte 19.
Black/off uses the documented single idle frame starting `13 88 01 00 23`.
Static/off refresh at 20 Hz. The earlier software animation stream was replaced
with native effects after the user observed visible stepping. Direct streaming issues no persistent
configuration, flash, reset, or firmware-write commands.

On 2026-10-09, the user's receiver `3554:fa09`, at physical connection
`usb-0000:0d:00.3-3`, answered the exact model query above and accepted the
stream. With the USB cable removed, the user confirmed steady teal
(`#00ccbb`, 65% brightness). Remapping also started against the receiver's
actual composite event interfaces. Explicitly linked physical endpoints let
the tray restart services on the available cable or receiver connection;
there is no VID/PID-wide fallback to an unrelated receiver.

## Native wireless effects and recovery

All 17 native animation modes run on the keyboard, avoiding the
receiver's animation-stream bandwidth limit. Configuration framing was
independently encoded from the [wireless configuration reference](https://github.com/harshvats17/f75-linux-manager/blob/ea1a954d95b2a844c06ce191cce15c9f120bca66/aula_f75/protocol.py),
with K686-specific preservation and exact-model verification. The official
K686 `KB.ini` and `Text/en/text.xml` define the effect catalog encoded in
`redragon/effects.py`. Configuration selections 2–18 map respectively to
hardware effects 3, 2, 19, 15, 13, 20, 16, 18, 5, 7, 17, 12, 8, 28, 30, 14, 29.
Selection 2 remains labeled Smooth breathing. Static color and Off retain
their existing direct implementations. Custom per-key mode is not included.

Read command `44` returns ten checked fragments: sequences 0–8 contain
14 bytes after their length byte; sequence 9 contains the `5a a5` trailer.
Reads retry at 0.5-second intervals to recover lost wireless fragments.
The app validates this complete layout and writes a durable, device-bound
backup before changing any hardware setting.

Only three payload positions change: frame 0 byte 15 selects the effect;
the effect's parameter pair holds brightness 0–4 and speed 0–4 in its high
nibble. For selections 1–6, the pair is in frame 4 at `7 + 2*(id-1)`;
for 7–13, frame 5 at `5 + 2*(id-7)`; for 14–18, frame 6 at `5 + 2*(id-14)`.
The speed byte's low nibble preserves the original onboard color/variant flags,
except Smooth breathing explicitly selects preset color 0–6. All other
payload bytes are preserved. The write reports change command `44` to `04`
and recompute each checksum. Each configuration fragment must be echoed;
idempotent fragments retry up to three times on lost echoes.
The apply/save request is `13 0a 01 00 04 07`, padded and checksummed; its
response can carry status rather than an exact echo. Complete read-back is
mandatory regardless of the apply acknowledgment.

These modes write saved lighting settings but do not write the RGB palette,
key mappings, reset commands, or firmware. Restoring the backup uses the same
transaction, followed by byte-for-byte verification before removing the
backup. A failed restore retains the backup for the next verified connection.
Changes are sent once per setting change, not once per animation frame.
The cache includes effect selection and quantized hardware levels, so changing
effects with otherwise identical settings works and redundant saves are avoided.

The user explicitly approved the native test on 2026-10-09 and confirmed
smooth cyan breathing at brightness 3/4 and speed 2/4. The initial generic
chipset transaction was rejected by validation and its original configuration
was restored. Restricting changes to the three lighting positions above,
with read retries, passed complete read-back. Both the diagnostic and the
managed service subsequently restored the original configuration byte for
byte. The managed service was restarted successfully and made zero output
writes during an idle sample. The native preview and preset selector were
also exercised in a real GTK window.

All 17 selections subsequently passed actual wireless configuration read-back.
Three initially lost fragment echoes and passed after bounded retries were
added. The user confirmed the native Rainbow moving smoothly across the keys.

## Wired native write investigation

A read-only feature query `06 84 00 00 01 00 80 00` returned the matching
128-byte lighting region (payload starts at byte 8). A documented shared-chipset
`04` configuration write could not be verified on this K686 and subsequent
USB control requests returned protocol errors. The user disconnected USB and
returned to 2.4G; the retained original backup was then restored and verified
through the receiver. The production driver does **not** include this wired
native write path. Its capability and backend guards allow only Static color
and Off over USB; native writes are rejected before opening the wired device.
No software animation fallback is used. Original input mapping remains managed
separately through evdev and follows the available explicitly linked endpoint.

## Manufacturer recovery instructions

The official manual's printed page 6 says to **hold Fn + Esc for 3 seconds**
to restore factory settings. Fn is processed inside the keyboard and cannot
be reliably synthesized with Linux input events, so a USB reset command is
not fabricated.

The knob controls volume by default and pressing it mutes. Fn + knob press
switches to backlight adjustment; pressing the knob in that mode toggles the
backlight. Other documented shortcuts: Fn + Ins cycles effects; Fn + left/right
changes speed; Fn + up/down changes brightness; Fn + PgUp changes colour.
Fn + Backspace enters the keyboard's onboard per-key lighting editor.
