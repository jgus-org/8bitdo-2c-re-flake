# Flash angle 1 — the on-wire firmware-flash protocol for 8BitDo Telink pads

Scope: reconstruct how an 8BitDo controller/dongle firmware image is written over the wire, and
answer the load-bearing question: **is a write gated by any signature/authentication, or only by a
CRC?** Focus device: Ultimate 2C (Telink B80, plaintext firmware) + its 2.4G dongle (2dc8:310a).

## TL;DR (the answer that matters)

**There is NO cryptographic signature or authentication gating a firmware write on 8BitDo Telink
pads. Integrity is a CRC only.** This holds across all three independent sources below. For the 2C
specifically — where we have already confirmed the firmware payload is *plaintext* (no AES) — the
device will accept an arbitrary payload as long as (a) the 28-byte ebitdo header is well-formed and
(b) the per-chunk / header CRC matches. That makes a modified-image write **feasible in principle**;
the only real work is reproducing the CRC and confirming the exact wire layout on the 2C.

Confidence: **HIGH** that there is no signature. **MEDIUM-HIGH** that CRC is the only gate on the
2C (corroborated by the dongle IAP handler strings but the exact CRC algorithm is not yet recovered).

## Two distinct protocol generations — do not conflate them

There are **two** different 8BitDo flash protocols. The 2C uses the *newer* one.

### A) Legacy "ebitdo" protocol (fwupd `ebitdo` plugin) — NOT what the 2C uses
- Targets the older **STM32-based** pads. Bootloader re-enumerates as **VID 0x0483 (STMicro) / PID
  0x5750** (also `2dc8:5750`). Device list in `plugins/ebitdo/ebitdo.quirk`: FC30/NES30/SFC30/
  SNES30/…/M30 (5006)/SN30v2 (9012)/N30 Pro 2 (9015). **The Ultimate 2C / dongle 310a is NOT in
  this list** — fwupd's ebitdo plugin does not handle it. (VERIFIED: fetched quirk file.)
- Transport: **raw USB interrupt transfers** on dedicated endpoints (NOT HID reports, no report ID):
  bootloader EP OUT `0x01` / EP IN `0x82`; runtime EP OUT `0x02` / EP IN `0x81`; **64-byte** packets.
- Packet header (`FuStructEbitdoPkt`, little-endian): `pkt_len:u8, type:u8, subtype:u8, cmd_len:u16le,
  cmd:u8, payload_len:u16le` then up to `64-8` data bytes.
- Command enum (`fu-ebitdo.rs`, all VERIFIED verbatim): FwUpdateData=0x00, FwUpdateHeader=0x01,
  FwUpdateOk=0x02, FwUpdateError=0x03, FwGetVersion=0x04, FwSetVersion=0x05, FwSetEncodeId=0x06,
  Ack=0x14, Nak=0x15, UpdateFirmwareData=0x16, TransferAbort=0x18, VerificationId=0x19,
  GetVerificationId=0x1a, VerifyError=0x1b, VerifyOk=0x1c, TransferTimeout=0x1d, GetVersion=0x21,
  GetVersionResponse=0x22. Packet types: UserCmd=0x00, UserData=0x01, MidCmd=0x02.
- Write flow (`fu_ebitdo_device_write_image`, VERIFIED): send FW_UPDATE_HEADER(header)→ACK; loop
  **32-byte** chunks as FW_UPDATE_DATA→ACK each; send FW_SET_ENCODE_ID(serial_new); send
  FW_UPDATE_OK→ACK. Note chunk size here is **32**, not 46.
- **Auth: none.** The device explicitly carries `FWUPD_DEVICE_FLAG_UNSIGNED_PAYLOAD`. The only
  obfuscation is "encode ID": `serial_new[i] = serial[i] ^ app_key_index[serial[i] & 0x0f]` for
  i=0..2, where `app_key_index[16]` is a **hardcoded public table** in fwupd (0x186976e5, 0xcac67acd,
  0x38f27fee, 0x0a4948f1, 0xb75b7753, 0x1f8ffa5c, 0xbff8cf43, 0xc4936167, 0x92bd03f0, 0x5573c6ed,
  0x57d8845b, 0x827197ac, 0xb91901c9, 0x3917edfe, 0xbcd6344f, 0xcf9e23b5). The serial comes from the
  device's own GetVerificationId reply. fwupd's own comment: *"likely a checksum, bluetooth pairing
  or maybe just security-through-obscurity."* This is NOT a signature — the key is public and the
  input is the device's own serial. (VERIFIED from source.)

### B) New "0x8105" protocol (8BitDo Ultimate Software / web.8bitdo.com WebUSB) — THIS is the 2C's
Reconstructed primarily from Wojciech Skowronski's USB-sniff of the 8BitDo Retro 18 numpad (Telink
**TLSR8271**, same Telink family as the B80). The Ultimate 2C and its dongle are updated by the same
8BitDo Ultimate Software / web updater (WebUSB, VID **2dc8**), so this is the applicable family.

- **64-byte packet layout** (VERIFIED from the numpad sniff; big-endian address field):
  | bytes | field | notes |
  |---|---|---|
  | 0-1 | `0x8105` fixed prefix | 2-byte magic. Sniffed as the first two *payload* bytes over WebUSB — **not** confirmed to be a HID Report ID (0x81). See open Q1. |
  | 2 | command | see table below |
  | 3-5 | parameter | usually `0x000000`; non-zero only on session start/end |
  | 6 | data length | 0-46 |
  | 7 | padding `0x00` | |
  | 8-17 | address | **10 bytes, big-endian** (see open Q2 — Telink flash is 24-bit, so most of these are zero/padding) |
  | 18-63 | data | up to **46 bytes**, zero-padded |
- Command bytes (VERIFIED from numpad sniff):
  `0x00` session start / session end (bookends);
  `0xc1` write init / erase-begin;
  `0xc3` set 4KB data-block address (repeats);
  `0x04` data-block write start (per 4KB block);
  `0x03` data write — the bulk **46-byte** payload packets;
  `0xc4` write completion;
  `0x07` update finish / verify.
- Block granularity: **4 KB** (block index increments by 0x0010). Bulk unit: **46 bytes/`0x03`
  packet**. This matches the dongle IAP handler's `"pbufferLength > 46"` guard exactly.
- **CRC**: the numpad blog did not capture device replies or the CRC math. But the *dongle firmware's
  own IAP handler* (from our Ghidra dumps) confirms the gate: symbols `flash_crc`, `writefirmware`,
  `boot_wirteFlash`, `multi_writeFlash`, `eraseFlash`, `saveCodeBlock`, `savehead4K`, `get_pid`, and
  the log string **`"writefirmware ----> crc != header"`**. I.e. each chunk / the header carries a
  CRC that the device recomputes and compares; mismatch aborts the write. The user-facing *"Update
  failed: CRC error"* in the Windows tool corroborates CRC as the integrity mechanism.
- **Auth: none observed.** Numpad blog: the protocol is *"unauthenticated at the USB layer."* The
  dongle IAP handler shows **no signature/HMAC/public-key check** — only `flash_crc`. (The numpad's
  extra obstacle was that its firmware is AES-*encrypted* on-device; **our 2C firmware is confirmed
  plaintext**, so that obstacle does not apply here.)

## Firmware container format (shared by both generations — VERIFIED)
28-byte (0x1C) little-endian header, then raw payload. `FuStructEbitdoHdr`:
`version:u32le, destination_addr:u32le, destination_len:u32le, reserved:[u32le;4]`.
- fwupd parses/validates: `version` (stored ÷100 → "X.YZ"), `destination_addr`, `destination_len`
  (= payload byte count following the header). The 4 reserved u32s are where the 2C build stores
  **USB PID** and a **per-file checksum** (matches our header analysis; fwupd ignores them).
- For the 2C, `destination_addr = 0x6000` (the Telink flash IAP base). fwupd `write` re-emits the
  same header shape, so a modified image just needs the header's `destination_len` and the reserved
  checksum recomputed. Max image 16 MB (fwupd `set_size_max`).

## Bootloader entry (2C controller, from vendor/community docs — MEDIUM confidence)
- Update mode: power **off**, hold **L1+R1** while plugging USB-C. Recovery bootloader (rapid LED
  flash): hold **SELECT+START** while plugging USB. Firmware transfers over **wired USB-C to the
  controller**; the 2.4G dongle is flashed as its own USB device (2dc8:310a) — the RF link does not
  carry the flash protocol.

## Confidence summary
- No signature / auth gate on either protocol generation: **HIGH** (3 independent corroborations:
  fwupd UNSIGNED_PAYLOAD, numpad "unauthenticated", dongle IAP handler has only `flash_crc`).
- 0x8105 packet layout & command bytes: **HIGH for the numpad**, **MEDIUM-HIGH that the 2C is byte-
  identical** (same vendor tool, same Telink family, same VID). Needs a 2C-specific capture to confirm.
- CRC is the only gate on the 2C: **MEDIUM-HIGH**. Exact CRC algorithm/polynomial/coverage: **LOW /
  unknown** — not in any public source; must be recovered from `flash_crc` in our firmware dump or
  from a capture.
- 2C firmware is plaintext (so no AES obstacle like the numpad): **given as VERIFIED by the effort.**

## Open questions
1. Is `0x8105` a HID Report ID (byte0=0x81, report 0x05) delivered via SetReport, or a literal 2-byte
   payload magic over a vendor WebUSB interrupt/control transfer? (Numpad sniff suggests the latter.)
   Determines how we replay it (hidraw feature report vs libusb interrupt transfer).
2. What do the 10 address bytes actually mean for a 24-bit Telink flash — which bytes are live vs
   padding, and is the 0x6000 base already applied or added by the device?
3. Exact `flash_crc` algorithm (poly, init, reflect, coverage: per-46B chunk? per-4KB block? whole
   header?) and where the CRC sits in the packet (the layout above has no explicit CRC field — it may
   ride in the `parameter` bytes 3-5, in the header's reserved u32s, or be appended). **This is the
   one unknown blocking a replay.**
4. Device→host reply/ACK format for each command (numpad sniff only captured host→device).

## Single most useful next action
**Capture one real USB trace of the 8BitDo Ultimate Software (or web.8bitdo.com WebUSB) flashing the
actual 2C** — Linux `usbmon`+Wireshark, or Chromium DevTools instrumenting `USBDevice.transferOut`.
One capture simultaneously (a) confirms the 0x8105 layout on the 2C, (b) reveals the device ACK
format, and (c) exposes the literal CRC bytes for a known payload — which, cross-checked against the
`flash_crc` routine in our existing Ghidra dump, pins down the CRC algorithm. Since the flasher
applies the vendor file *as-is* and the firmware is plaintext, once the CRC is reproducible we can
edit the payload, recompute header `destination_len` + reserved checksum + per-chunk CRC, and replay
the exact `0x00/0xc1/0xc3/0x04/0x03/0xc4/0x07/0x00` sequence with libusb to write a modified image.
(Fallback if no capture: fully reverse `flash_crc`/`writefirmware` in the dump — the symbols are
already present — to derive the CRC statically.)

## Sources
- fwupd ebitdo plugin (VERIFIED, read verbatim): `plugins/ebitdo/fu-ebitdo-device.c`,
  `fu-ebitdo.rs`, `fu-ebitdo-firmware.c`, `ebitdo.quirk` @ github.com/fwupd/fwupd/tree/main/plugins/ebitdo
- Skowronski, "8BitDo Mechanical Numpad firmware hackability and adventures with USB sniffing"
  (0x8105 layout + command sequence): https://skowronski.tech/posts/2025-05-24-8bitdo-numpad-firmware-hackability/
- ladis.cloud "How to update the firmware of 8BitDo's gamepads without…" (firmware download API,
  fwupd install-blob flow): https://ladis.cloud/blog/posts/firmware-update-8bitdo/index.html
- franfermon/8bitdo_update (fwupd wrapper; legacy-protocol only): https://github.com/franfermon/8bitdo_update
- rdnlsmith "8BitDo's Semi-Secret Web-Based Firmware Updater" (WebUSB updater, VID 2dc8, supports
  Ultimate 2 / 8BitDo 64): https://rdnlsmith.com/posts/2026/001/8bitdo-web/
- Dongle IAP handler symbols/strings (`flash_crc`, `"crc != header"`, `"pbufferLength > 46"`): our
  own Ghidra dump of the 2C dongle firmware (effort context).
