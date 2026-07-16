# 8BitDo Ultimate 2C — Modified-firmware flashing: decision-grade synthesis

Device: Ultimate 2C pad + 2.4 GHz dongle (USB 2dc8:310a). MCU: Telink B80 (TLSR8232/823x-class per Angle 3; brief said "825x-class" — same SWS bus + tool family, but 2-byte SWire addressing and a different analog-register map). Firmware confirmed **plaintext** (no AES). Container: 28-byte little-endian ebitdo header + raw Telink payload flashed at **0x6000**.

Synthesized from `flash-angle-1.md` … `flash-angle-4.md` in this directory.

---

## 1. Bottom line

**Yes — writing a modified image to the 2C controller is feasible, and the primary path is the vendor USB IAP protocol.** Every independent line of evidence (fwupd's `UNSIGNED_PAYLOAD` flag, the numpad USB sniff, and our own Ghidra dump of the dongle IAP handler) agrees there is **no cryptographic signature** anywhere in the update path; the only integrity gate is a **CRC** (`flash_crc`, the `"writefirmware ----> crc != header"` string). The one obstacle that stopped every prior community effort — payload *encryption* — is confirmed **absent** on the 2C. So the device will accept an arbitrary plaintext payload at 0x6000 provided the 28-byte header is well-formed and the CRC(s) match. The single remaining blocker is purely mechanical: recover the exact `flash_crc` algorithm and where its expected value rides in the packet, then replay the `0x00/0xc1/0xc3/0x04/0x03/0xc4/0x07/0x00` sequence with a corrected CRC. Confidence that the write is *possible*: **HIGH**. Confidence in the *exact CRC recipe* today: **LOW** (not yet extracted). Hardware SWS is a strong, brick-proof fallback and — more importantly — the tool that makes the whole effort safe by giving a full-flash backup.

---

## 2. Ranked flashing paths

### Path A — USB IAP (vendor 0x8105 HID protocol, bootloader mode) — PRIMARY, rank 1

- **What it requires:** Put the 2C in bootloader mode (power off, hold **L1+R1**, plug USB-C; LED by the port flashes red — re-enumerates under a distinct boot PID, reported `2dc8:3208` but unconfirmed on the 2C). Then a `pyusb`/`hidapi` client that emits 64-byte reports: `0x8105` prefix | cmd | 3B param | 1B len(0-46) | pad | 10B big-endian addr | ≤46B data, using cmds `0x00` session → `0xc1` init → `0xc3` set-block-addr(+expected block CRC) → `0x04` block-start → `0x03` data×N → `0xc4` done → `0x07` verify → `0x00`. Blocks are 4 KB (90×46 B); chunk cap 46 B matches the dongle's `"pbufferLength > 46"`.
- **Verified:** No signature; CRC-only gate; plaintext payload; command set + packet layout (from the numpad sniff, byte-identical family); 46-byte chunk cap corroborated by our own dongle handler; container header struct (version×100, dest_addr=0x6000, dest_len, 16 "reserved" bytes holding PID+per-file checksum).
- **Unknown:** Exact `flash_crc` poly/width/init and the byte range it covers; where the expected CRC sits in the `0xc3` block-address packet; whether the 28-byte header's per-file checksum is enforced on-device (fwupd never sets it); exact 2C boot-mode PID; whether the controller's resident bootloader is as permissive as the dongle's (our RE is of the *dongle* handler); any anti-rollback/version-counter.
- **Biggest risk:** Flashing a bad app to 0x6000. Mitigated by design — the IAP rewrites only 0x6000+, leaving the resident bootloader (0x0–0x5FFF) intact, so the device should re-enter update mode and re-accept a good image. SELECT+START recovery mode is the software safety net (but is itself unverified on the 2C).
- **First de-risk step:** Disassemble `flash_crc`/`writefirmware`/`saveCodeBlock` in the *already-dumped* plaintext firmware to read the CRC recipe and CRC field location (see §3), then confirm with a usbmon capture of the official tool flashing stock firmware.

### Path D — Hardware SWS single-wire (bypass the updater) — SAFETY-CRITICAL FALLBACK, rank 2

Ranked second as a *write* path but it is the **enabler for the whole effort**: it is the only route that can take a full-flash backup and un-brick a dead pad.

- **What it requires:** Physical PCB access to the chip's SWS/SWM pad + GND + 3V3 + RESET. A **non-FTDI** USB-serial adapter with **no RX LED** (CH340/CP210x/PL2303): `TX→SWS` via ~1 kΩ series, `RTS→RESET`, `GND`, `+3V3`. Tooling: pvvx `TlsrComProg`/`TlsrComSwireWriter` (bit-bang), or the sturdier Telink-hosted `TLSRPGM` / STM32 `SWireSTM32` masters. Use 2-byte SWire addressing (`-u`) for a 823x part. "Activation" (reset → CPU-**stop** within the first few ms) seizes the core before firmware can reassign the SWS pin.
- **Verified:** SWS drives the on-die flash controller directly — can dump `0x000000…flash_end` (recovering the sub-0x6000 bootloader the ebitdo image never contains) and write raw payload to any address, with no updater in the loop so header/CRC/signature are all irrelevant. Activation defeats a *firmware*-based SWS-disable.
- **Unknown:** Whether a retail 2C exposes a probe-able SWS pad (8BitDo has left debug pads unpopulated — numpad's J22) or requires probing at the chip pin; the SWS pin location on the B80/8232 package (datasheet `DS_TLSR8232-E`); whether an off-the-shelf 823x SRAM stub exists (825x stubs won't fit); whether the part is embedded flash vs OTP (field updates strongly imply rewritable flash); whether 8BitDo even disables SWS at boot.
- **Biggest risk:** Hard-brick if you erase/overwrite the bootloader (0x0–0x5FFF) or the MAC/RF-cal sectors — but only SWS itself can then recover it, and only if you took a backup first. Also mundane: wrong voltage / FTDI / RX-LED adapters silently fail or damage the part.
- **First de-risk step:** On a **sacrificial** 2C, trace SWS to a pad, wire a CH340, do a **read-only** chip-ID read, then a full `0x000000–0x080000` dump. Non-destructive; resolves "is it unlocked / rewritable / does a pad exist" in one shot.

### Path B — BLE OTA (stock Telink OTA GATT service) — SPECULATIVE, rank 3

- **What it requires:** The 2C's BLE side would have to expose the stock Telink OTA service (GATT UUID **0x1912**). If present, pvvx's `TLSR825x_OTA_Flash_Hacker` flashes over BLE with no USB tooling.
- **Verified:** Nothing 2C-specific. This is the standard Telink SDK OTA path; existence on the 2C is unconfirmed.
- **Unknown:** Whether the service exists at all on the 2C; and even if it does, stock Telink OTA writes the **SDK dual-bank layout** (bank0@0x0 / new-bin@0x40000), which does **not** match the 2C's custom single-slot-at-0x6000 arrangement — so a stock-OTA write may be rejected or land at the wrong address.
- **Biggest risk:** Writing to the SDK bank layout on a device that boots a custom bootloader → mismatched image, likely non-booting.
- **First de-risk step:** BLE-scan the 2C (`bluetoothctl`/`nRF Connect`) for service UUID 0x1912. If absent, drop this path entirely.

### Path C — Dongle relay — RULED OUT, rank 4

- **Status:** Not viable for the *controller*. Firmware travels over **wired USB only**; the 2.4 GHz dongle and BLE do not carry the controller's firmware protocol. The dongle is flashed on its own USB port with the same IAP protocol — it is not a relay. Keep it in scope only as a *second target* to flash independently, not as a route to the pad.
- **First de-risk step:** None needed — this is a verified negative.

---

## 3. Single most important experiment first (cheapest information gain)

**Statically disassemble `flash_crc` (plus `writefirmware` and `saveCodeBlock`/`savehead4K`) in the firmware you already have dumped and Ghidra'd.** Cost: zero — no hardware, no bootloader entry, no risk, data already in hand. Payoff: it directly resolves the *single blocking unknown* for Path A — the CRC poly/width/init, the exact byte range it covers (46-byte chunk? whole 4 KB block? does it include the 10-byte address?), and where the expected CRC lands in the `0xc3` packet. Cross-check the recovered polynomial against the Telink-idiomatic **CRC16 poly 0x8408** (reflected CCITT/X25, init 0xFFFF) — the strongest a-priori candidate. While in the dump, confirm the app's **TLNK marker at 0x6008** and the size/tail-check word at **0x6018**.

Immediate follow-on (first experiment that touches hardware): a **usbmon + Wireshark capture** of the official Ultimate Software V2 flashing *stock* firmware to the 2C in L1+R1 bootloader mode. That validates the disassembled CRC against real bytes for a known payload, reveals the device ACK format (host→device only was ever sniffed), confirms the 2C's boot-mode PID, and hands you a replay client. Then flip one non-functional byte, recompute the CRC(s), and reflash — the definitive signed-vs-unsigned test, with SELECT+START (or SWS) as the net.

---

## 4. Brick hazards and how to avoid them

- **No full-flash backup before writing = the cardinal risk.** The USB IAP can only *write* the app region; it cannot read the full flash back. If a write goes wrong and recovery mode fails, your only original-image source is the vendor `.dat` (app slot only — **not** the bootloader, MAC, or RF calibration). **Mitigation: take an SWS full-flash dump (`0x000000–0x080000`) of the exact unit before the first write**, or at minimum have SWS wired and proven as an escape hatch. Keep the stock vendor `.dat` archived.
- **Never full-chip-erase or write over 0x76000–0x78000 (MAC @0x76000, RF calibration/freq-offset @0x77000).** These are factory-written and RF-load-bearing; overwriting them de-tunes the radio and changes device identity, and they are **not** in the vendor `.dat`. A modified app at 0x6000 does not reach them — but an SWS `ea` (erase-all) or `chip-erase` will wipe them irreversibly unless backed up. **Mitigation: back up first; only ever sector-write the app region; never chip-erase a unit you care about.**
- **Do not erase the resident bootloader (0x0–0x5FFF) via SWS.** It carries the IAP handler that is your recovery path. Erasing it hard-bricks the pad with SWS-reflash the only way back. The USB IAP path never touches it (writes 0x6000+), which is precisely why Path A is relatively brick-resistant. **Mitigation: on the SWS path, sector-target 0x6000+; leave 0x0–0x5FFF alone.**
- **A malformed app image (bad TLNK@0x6008 or inconsistent size word @0x6018) won't boot but is recoverable.** The bootloader simply won't jump to an invalid app; re-enter update mode and reflash. **Mitigation: keep TLNK intact and the +0x18 size word consistent with the new payload length; recompute the appended 4-byte tail check.**
- **SELECT+START recovery mode is unverified on the 2C.** Treat it as a hoped-for net, not a guarantee. **Mitigation: prove recovery mode works (enter it, watch dmesg) *before* the first modified write, and have SWS as the real backstop.**
- **Possible anti-rollback / version counter (unknown).** Flashing an equal/older version may be refused. Not a brick — just a failed write — but bump the header `version` (=display×100) if you hit it.
- **SWS wiring hazards:** it's a 3.3 V part; FTDI adapters and adapters with an RX-line LED silently fail; use CH340/CP210x with a ~1 kΩ series resistor on TX→SWS. Getting this wrong wastes bench time, not the pad.
