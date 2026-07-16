# Dongle IAP / flash protocol — code-grounded confirmation

Target: 2C dongle v1.03, Ghidra base **0x6000**, image `/nix/store/4jpgmydgqy8pwaq2b1zich7f9hxdpw28-8bitdo-2c-dongle-v103-payload.bin` (0x6000–0x10000; file offset = addr − 0x6000). Artifacts under `analysis/dongle-v103/`.

## 0. Decisions on the three questions
- **(a) CRC only — no signature, no decryption.** Write handlers compute **CRC-16/MODBUS** (poly 0xA001 reflected = 0x8005, init 0xFFFF, refin/refout, xorout 0) over the received data and compare to a 16-bit header field. No asymmetric verify, no HMAC/SHA, no decrypt — USB bytes hit flash verbatim. The AES engine (0x800700) is **never referenced** in the whole dongle image. VERY HIGH.
- **(b) Dispatch fully traced.** 64-byte USB-HID report, first two bytes must be **0x81 0x05**, command at byte[2], 16-byte header = packet[2..17], ≤46-byte data = packet[18..63]. VERY HIGH.
- **(c) Self-flash.** Handlers call Telink SDK SPI-flash program/erase/read (`0xb220`/`0xb1ec`/`0xb204`) on the dongle's **own** flash and reply on its **own** USB endpoints; no RF anywhere. Not a controller relay. VERY HIGH.

**CRC recompute recipe resolved** (the #1 blocker) — §3.

## 1. Transport & dispatch — `iap_dispatch` @ 0x0000d998
```
d99e  packet[0] == 0x81  else return          ; magic 0x81 0x05
d9a8  packet[1] == 0x05  else return
d9ae  if packet[2]==0x0b -> multi_writeFlash @0xda10
d9be  memcpy(local_hdr, &packet[2], 0x10)     ; header = packet[2..17]
d9da  data = &packet[0x12]                     ; = packet[18]
      chained self-guarding handlers, each re-checks its own cmd id:
d9ca C1 FUN_d1bc | d9d0 04 FUN_d230 | d9d6 08 FUN_d940
d9e0 02 FUN_d424(boot_wirteFlash) | d9e8 03 FUN_d2e8(writefirmware)
d9ee 05 FUN_d508 | d9f6 C3 FUN_d6d0(flash_crc) | d9fc C2 FUN_d7e4(eraseFlash)
da02 07 FUN_d8dc(finish/reboot) | da0a C4 FUN_d838(saveCodeBlock)
```

**Packet layout (from the handlers' header field reads):**

| offset | field | width | notes |
|---|---|---|---|
| 0 | magic | u8 | **0x81** |
| 1 | magic | u8 | **0x05** |
| 2..3 | **command** | u16 LE | byte[2]=cmd, byte[3]=0 |
| 4..5 | param | u16 LE | block index / cmd_params |
| 6..7 | **data length** | u16 LE | **≤46** |
| 8..9 | **expected CRC-16** | u16 LE | MODBUS CRC compared on-device |
| 10..13 | aux | — | saveCodeBlock/flash_crc block addr/len/size |
| 14..17 | **flash address/offset** | u32 LE | |
| 18..63 | **data payload** | ≤46 B | arg to write handlers |

The 46-byte area = 64−18, exactly the `"pbufferLength > 46"` guard (cmd-0x05 clamps length to 0x2E @0xd56e). **Replies** are built by `FUN_0xd124` with prefix **0x02 0x05**, sent via `FUN_0xdd14`→`FUN_0xdd7c` which writes `reg_usb_ep3/ep4/ep8_*` (verified in decomp.sym.c) — resolving the device→host ACK format the numpad sniff never captured.

Command ids (C1/C3/04/03/C4/07/02/05) match the numpad sniff byte-for-byte.

## 2. Write path — writefirmware (cmd 0x03) @0xd2e8, boot_wirteFlash (cmd 0x02) @0xd424
Both identical:
```
len=hdr[4..5](pkt6-7,≤46); addr=hdr[12..15](pkt14-17); crcHW=hdr[6..7](pkt8-9)
crc = FUN_0xd0e4(0xFFFF, data, len)             ; CRC-16/MODBUS over payload
if (crc != crcHW){ printf("...crc != header..."); NAK; return; }
FUN_0xcd0c(addr, data, len)                      ; flash_write verbatim
ACK
```
- writefirmware biases `phys = addr + 0x13000` (0x98<<9 @0xd380), only gate `phys > 0x11FFF` (staging bank ≥0x12000); **no upper bound, no signature**.
- boot_wirteFlash writes **raw** addr, **no bias/no bounds** — can target any region, still CRC-only.
- Flash primitives: `FUN_0xcd0c` write→SDK `0xb220`; `FUN_0xccdc` erase→`0xb1ec`; `FUN_0xcd94` read→`0xb204`; `FUN_0xcc58` SPI-flash unlock/unprotect; `FUN_0xcd44` savehead4K = CRC-16 over 0x30-byte header, append 4-byte CRC @0x30, erase+write sector **0x12000**. Staging header@0x12000, code@0x13000. No RF/AES touched.

## 3. CRC routine — `FUN_0x0000d0e4` = CRC-16/MODBUS
Reflected bit-by-bit CRC-16, 2-entry table `{0, poly}`:
```
crc=0xFFFF
for b in data: crc^=b; for 8: crc=(crc>>1)^0xA001 if crc&1 else crc>>1
return crc     # no final xor
```
Raw constants: poly @0xd120 = **0xA001**; init @0xd414/d4fc/d7e0 = **0xFFFF**; no xorout. ⇒ **CRC-16/MODBUS** (poly 0x8005, init 0xFFFF, refin/refout, xorout 0). Executed the disassembled algo: `check("123456789")=0x4B37`, bit-identical to textbook MODBUS over random buffers. **Coverage = payload only** (`length` bytes), expected value at **packet[8..9]**. Recompute:
```python
def crc16_modbus(d):
    c=0xFFFF
    for x in d:
        c^=x
        for _ in range(8): c=(c>>1)^0xA001 if c&1 else c>>1
    return c & 0xFFFF   # packet[8:10] = c.to_bytes(2,'little')
```
Other variants (not the per-chunk path): `multi_writeFlash` (cmd 0x0B) uses an **8-bit additive sum over 59 bytes**; `saveCodeBlock` uses the same MODBUS CRC over its header.

## 4. No signature / no decryption (grounded)
Only rejection is `crc != header` (VERIFIED @0xd3e0-e2 / @0xd4c2-c4). Written data is the unmodified receive buffer (`&packet[0x12]`→`FUN_0xcd0c`). AES peripheral has zero refs (symreport). No RSA/ECDSA/HMAC/SHA in the chain. ⇒ gate is entirely `packet[8..9]==CRC16_MODBUS(payload)`.

## 5. Patch proposals
**Preferred (no device patch):** edit payload → set `packet[8..9]=crc16_modbus(chunk)` LE → fix `packet[6..7]` length and `packet[14..17]` address → if rewriting staging header, recompute its 0x30-byte MODBUS CRC at offset 0x30. Safe because it satisfies the device's only check.

**Optional on-device CRC-bypass** (circular for USB IAP; only useful via hardware SWS). TC32 verified: NOP=0x46C0 (`c0 46`, grounded on real `tnop`@0xd226); cond-branch `0xCc oo`, target=(addr+4)+off·2; uncond `tj.n`=0x8000|off11.
- **writefirmware @0xd3e2** `tjne.n 0xd3a6` (`e0 c1`) → NOP **`c0 46`**: drops the mismatch→NAK jump, always writes. Effect HIGH, byte HIGH.
- **boot_wirteFlash @0xd4c4** `tjeq.n 0xd4e6` (`0f c0`) → uncond **`0f 80`**: always takes write path. Effect HIGH, encoding MEDIUM-HIGH (verify assembled halfword).

## 6. Corrections to prior notes
Confirmed flash-angle inferences (CRC-only, `crc != header`, `pbufferLength > 46`, 0x8105 family). Corrections: address is **32-bit LE @packet[14..17]** (not "10-byte big-endian"); CRC is **CRC-16/MODBUS over payload**, value at **packet[8..9]**; replies carry **0x02 0x05**. The a-priori CCITT/0x8408 guess was wrong. Scope caveat: this is the dongle **app** (base 0x6000); the resident bootloaders (0x0–0x5FFF) and the **controller** image are not disassembled here — controller-updater uniformity remains INFERRED.

---

## Summary (~250 words)

I confirmed the flashing story directly against the dongle v1.03 disassembly. The dongle contains a complete USB-HID IAP updater (dispatcher `iap_dispatch` @0x0000d998) that programs its **own** SPI flash — it is a self-updater, not a relay, matching "no relay to controller." The on-wire unit is a 64-byte report beginning with the magic **0x81 0x05**; byte[2] is the command; a 16-byte header (packet[2..17]) carries length@[6..7], expected-CRC@[8..9], and a 32-bit LE flash address@[14..17]; up to 46 data bytes follow at [18..63]. Device replies use an **0x02 0x05** prefix on USB EP3/EP4. The write handlers `writefirmware` (cmd 0x03, staging bank +0x13000) and `boot_wirteFlash` (cmd 0x02, raw address) gate a write on exactly one thing: a **CRC-16/MODBUS** (poly 0x8005/0xA001, init 0xFFFF, no xorout) computed over the payload, compared to packet[8..9] — the literal `"crc != header"` string. There is **no signature, no HMAC, and no decryption**: the received bytes are written verbatim (`FUN_0xcd0c`→SDK `0xb220`), and the AES engine is never referenced anywhere in the image. The CRC routine is `FUN_0x0000d0e4`; I extracted its constants from the raw image and reproduced the standard MODBUS check value 0x4B37. This fully resolves the previously-blocking "recompute CRC" recipe.

Most load-bearing claims (for independent verification):
- **[VERIFIED, VERY HIGH]** Write gate is CRC-only; no signature/decryption exists in the IAP chain (writefirmware @0xd3e0-e2, boot_wirteFlash @0xd4c2-c4; AES 0x800700 unreferenced).
- **[VERIFIED, VERY HIGH]** CRC = CRC-16/MODBUS (`FUN_0xd0e4`, poly word @0xd120=0xA001, init @0xd414/d4fc/d7e0=0xFFFF, no xorout); covers the payload; expected value at packet[8..9]; check("123456789")=0x4B37.
- **[VERIFIED, VERY HIGH]** Dispatch: 64-byte report, magic 0x81 0x05, cmd@[2], header packet[2..17], ≤46B data@[18..63], u32 LE address@[14..17]; replies prefixed 0x02 0x05 on USB EP3/EP4/EP8 (`iap_dispatch`@0xd998, `FUN_0xd124`/`0xdd7c`).
- **[VERIFIED, HIGH]** Self-flash: writes dongle's own SPI flash via SDK 0xb220/0xb1ec/0xb204 (staging header@0x12000, code@0x13000), answers on its own USB; no RF path.
- **[INFERRED, MEDIUM-HIGH]** The controller updater and resident bootloaders (0x0–0x5FFF, not in this dump) use the same protocol/CRC — inferred from the byte-identical command set + shared vendor tooling, not yet proven on the controller image.