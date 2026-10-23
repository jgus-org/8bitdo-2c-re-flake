# Flash Angle 2 — Bootloader Entry & Signing (8BitDo Ultimate 2C)

Scope: how to put the 2C controller (and its dongle) into firmware-update mode, and
whether the bootloader validates a _cryptographic signature_ (vs. mere integrity CRC)
that would reject a modified-but-unsigned image.

Bottom line up front: **All evidence points to integrity-only (CRC) validation, NOT a
signature check, on the path relevant to the 2C.** The one barrier that stopped prior
community efforts (firmware _encryption_) does **not** apply here, because this project's
own RE has already confirmed the 2C/dongle firmware is _plaintext_ (no AES). That makes
the 2C a materially softer target than the encrypted models others gave up on.

---

## 1. What's established (high confidence)

### 1.1 Update transport = wired USB only; dongle/BT do NOT carry firmware

- Firmware transfer requires a wired USB-C connection to the device being flashed.
  Bluetooth and the 2.4 GHz dongle **do not** carry the firmware protocol. To flash the
  _controller_ you connect the controller's own USB-C port; to flash the _dongle_ you
  plug the dongle into USB. The dongle is **not** a relay for controller firmware.
  Confidence: HIGH (consistent across fwupd wiki, multiple community gists, vendor docs).
- Corollary: there is **no BLE OTA path** on the 2C for firmware. (The 2C variants are
  2.4 GHz+wired or "Bluetooth"; even the BT SKU updates over wired USB.) Confidence: HIGH
  for USB-only; the _absence_ of a hidden BLE OTA is INFERENCE (no source documents one,
  and the dongle IAP handler we RE'd is a USB handler).

### 1.2 The 2C is NOT handled by fwupd / libebitdo

- `plugins/ebitdo/ebitdo.quirk` (fetched raw, fwupd main) contains **no Ultimate or
  Ultimate 2C entry** and **no PID 310a / 3208 / 520a**. The whole quirk list tops out at
  legacy pads (FC30/NES30/SN30 Pro/Pro+/M30/N30 Pro 2). Bootloader entries are only
  `2DC8:5750` and `0483:5760`. Confidence: HIGH (primary file).
- Implication: the 2C uses 8BitDo's **newer proprietary protocol** delivered by "Ultimate
  Software V2" (Windows) and the experimental **WebUSB** "Ultimate Software Online" —
  _not_ the old open-sourced libebitdo protocol. Do not assume fwupd's command set applies
  to the 2C. Confidence: HIGH.

### 1.3 Two different protocols exist — use the NEW one

- **Legacy (fwupd `fu-ebitdo-device.c`)**: 64-byte USB packets, cmds
  `FW_UPDATE_HEADER` / `FW_UPDATE_DATA` / `FW_UPDATE_OK` / `ACK`, data in **32-byte**
  blocks, header parsed at 0x1C bytes (first 12 = version, dest_addr, payload size). Has
  an "encode id" = **XOR obfuscation** against a 16-entry `app_key_index` table keyed by
  serial bytes — _not_ cryptographic; no signature. Confidence: HIGH but **NOT the 2C's
  protocol**.
- **Modern (matches the 2C/numpad + our dongle RE)**: USB-HID packets with fixed 2-byte
  prefix `0x81 0x05`, 1-byte cmd, and **46-byte data chunks**. Observed cmd bytes from a
  numpad USB sniff: `0x00` session start/end, `0xC1` write-start, `0xC3` set-block-addr,
  `0x04` data-block-start, `0x03` data-write, `0x07` finish, `0x08 → 0xC4` write-finish.
  Packet layout: `2B prefix(8105) | 1B cmd | 3B param | 1B data_len | 1B pad | 10B addr
(big-endian) | 46B data`. Confidence: HIGH for the _numpad_; that this is the _same
  family_ the 2C uses is MEDIUM-HIGH inference (same 46-byte chunk size, same vendor era,
  and our dongle IAP handler's `"pbufferLength > 46"` string corroborates the 46-byte
  chunk limit exactly).

### 1.4 The gate is a CRC, not a signature (this angle's key claim)

- Our own dongle RE: IAP handler symbols `eraseFlash / writefirmware / boot_wirteFlash /
readfirmware / multi_writeFlash / flash_crc / saveCodeBlock / savehead4K / reset /
get_pid`, and log strings `"writefirmware ----> crc != header"` and `"pbufferLength >
46"`. This is a per-chunk / per-image **CRC compared against a value in the header** —
  an _integrity_ check, trivially recomputable, with **no asymmetric-signature verify**
  in the handler. Confidence: HIGH (direct from our disassembly).
- The fwupd legacy path's only "crypto-looking" step is XOR obfuscation. Confidence: HIGH.
- The numpad blog author found no signature step either; his _only_ stated blocker was
  **encryption of the payload**, which he could not obtain the key for. Confidence: HIGH.
- **The encryption blocker is voided for the 2C**: this project already confirmed the 2C
  image is plaintext. So neither of the two mechanisms anyone has documented (encryption,
  or a would-be signature) is present on the 2C path. Confidence: the _plaintext_ fact is
  HIGH (our RE); the leap to "therefore a modified image will be accepted" is the central
  hypothesis — MEDIUM until empirically tested (see §5).

---

## 2. Bootloader-mode entry (button chords) & enumeration

### 2.1 Entry chord (2C controller)

- **Primary/normal**: power the controller OFF, hold **L1 + R1**, then plug in USB-C;
  the small LED next to the USB port flashes **red**. Enters bootloader/update mode.
  Confidence: MEDIUM-HIGH (repeated across vendor-adjacent guides + community gists; the
  "flash red" LED is consistently reported).
- **Recovery / forced (after a failed flash)**: hold **SELECT + START** while plugging in
  USB-C, release after ~3 s; LED flashes rapidly and the tool detects a "recovery" device.
  Confidence: MEDIUM (widely repeated, but sourced from SEO how-to pages, not a teardown).
- A third variant ("LB+RB+START 5 s → solid blue → plug USB") appears in low-quality SEO
  content. Confidence: LOW — treat as unverified.

### 2.2 USB enumeration (VID = 2DC8 throughout)

| Mode                                      | VID:PID                         | Confidence                        |
| ----------------------------------------- | ------------------------------- | --------------------------------- |
| 2C **dongle** ("Adapter")                 | `2dc8:310a`                     | HIGH (this project's own capture) |
| 2C controller, wired runtime              | `2dc8:520a` (reported)          | MEDIUM (single search summary)    |
| 2C controller, **bootloader/update**      | `2dc8:3208` (reported)          | MEDIUM — see caveat               |
| Ultimate 2 Wireless XInput                | `2dc8:310b`                     | MEDIUM-HIGH (community gist)      |
| Ultimate 2 Wireless DInput (2.4G/BT)      | `2dc8:6012`                     | MEDIUM                            |
| Ultimate 2 Wireless, powered-off/charging | `2dc8:6013`                     | MEDIUM                            |
| Ultimate 2, Switch mode                   | `057e:2009` (spoofs Switch Pro) | MEDIUM                            |

- **Caveat on `3208`**: this boot-mode PID was reported for the _Ultimate 2_ line; some
  sources conflate 2C and Ultimate 2. The exact 2C boot-mode PID must be confirmed
  empirically by watching `dmesg`/`lsusb` while doing the L1+R1 entry on _your_ 2C. It is
  a distinct PID from runtime (the device re-enumerates on entering the bootloader).
- The dongle (310a) is itself a USB device with its own IAP handler → it is flashed on its
  own, over its own USB connection, using the same modern IAP protocol.

### 2.3 Flash memory layout (Telink B80 / TLSR825x)

- Telink boots from internal flash offset `0x0`. The fwupd/ebitdo header's `dest_addr =
0x6000` (from this project's header analysis, and matching legacy ebitdo) means the
  **bootloader occupies `0x0000–0x5FFF`** and the **application image is written at
  `0x6000`**. The bootloader is what runs the IAP handler; a normal update rewrites only
  the app region, so the signature/CRC policy lives in that resident bootloader.
  Confidence: HIGH for the 0x6000 split; the exact bootloader size is inference.

---

## 3. Does 8BitDo _sign_ its .dat, and does the device refuse unsigned images?

- **Signing**: No evidence of asymmetric signing anywhere in the update path. What exists
  is (a) a header-embedded **CRC/checksum** (integrity), (b) legacy **XOR obfuscation**
  (encode-id), and (c) on _some_ models, **payload encryption** (numpad). None of these is
  a signature; (a) and (b) are recomputable, and (c) is confirmed **absent** on the 2C.
- **Refusal of modified images**: The only documented rejection is the CRC mismatch
  (`"crc != header"`). A modified image with a corrected header CRC is expected to pass.
  No community report describes a _signature_-based rejection on any 8BitDo model.
- **Community modified-firmware successes**: **None found.** No one has published a flashed
  _modified_ 8BitDo image on any model. But — critically — the people who _tried_ (the
  numpad blog is the most serious attempt) were stopped by **encryption**, i.e. they could
  not even read/produce a valid plaintext image; they were **not** stopped by a signature
  check. That distinction is exactly why the 2C (plaintext, already dumped here) is a fresh
  and more promising target rather than a re-tread of a known dead end.

---

## 4. Open questions

1. **Controller-side bootloader == dongle-side bootloader?** Our CRC-only, no-signature
   finding is from the _dongle's_ IAP handler. The _controller's_ resident bootloader
   (`0x0–0x5FFF`) must be dumped/disassembled to confirm it is equally permissive. High
   priority — this is the actual code that will accept or reject a modified controller img.
2. **Exact 2C boot-mode PID** (confirm `3208` vs. something else on the real 2C).
3. **Exact modern command stream for the 2C**, incl. where the CRC sits in the header and
   whether it's CRC-16/CRC-32 and over-what-range. We have the numpad's `0x8105` cmd set
   as a template but need the 2C's own trace.
4. **Is the header checksum independent of the CRC?** The container has both a per-file
   checksum (28-byte header) and the IAP "crc != header" chunk CRC; both must be satisfied.
5. **Does entering bootloader wipe/downgrade-protect?** i.e. any monotonic version counter
   or anti-rollback that would refuse a re-flash of an equal/older version.

---

## 5. Single most useful next action for this angle

**Capture a `usbmon` trace of the official Ultimate Software V2 flashing the 2C
controller in L1+R1 bootloader mode, then do a null-modification round-trip.**

Concretely:

1. Put the 2C controller in bootloader mode (L1+R1 + USB-C, LED red), confirm its
   re-enumerated PID via `lsusb`/`dmesg`.
2. Record the full update with `usbmon` + Wireshark while Ultimate Software V2 (Wine or a
   Windows box) applies the _stock_ 2C firmware. This yields the exact `0x8105` command
   sequence, chunking, and the byte offset/width of the CRC and header checksum — the one
   thing we still lack for the 2C specifically (fwupd's protocol does not apply).
3. Replay that captured stream **unchanged** with a small Python `pyusb`/`hidapi` client to
   prove we can drive the bootloader ourselves.
4. Flip a single non-functional byte (e.g. a log string) in the plaintext image, recompute
   the chunk CRC and the 28-byte header checksum, and flash. **Acceptance = definitive
   proof there is no signature gate; rejection = tells us exactly which field is the true
   gate.** The SELECT+START recovery mode is the safety net for a bad flash.

This single experiment converts the whole "is it signed?" question from inference to fact,
and simultaneously hands us the working flash client for the real modified image.
