# Adversarial verification: dongle IAP / flash protocol

Independently re-traced against `dongle-v103/listing.txt` + raw image `/nix/store/4jpgmydgqy8pwaq2b1zich7f9hxdpw28-8bitdo-2c-dongle-v103-payload.bin` (base 0x6000, file off = addr-0x6000), cross-checked registers vs `refs/register-map.md`. The key IAP functions are NOT in `decomp.sym.c`; all traced from raw disasm + binary bytes.

## Per-claim verdict

### Claim 1 — Write gate is CRC-only, no signature/decryption. **CONFIRMED (VERY HIGH).**
- writefirmware @0xd2e8: cmd==3 guard @0xd302; the ONLY data-dependent branch before the flash write is `tcmp r2,r9`@0xd3e0 / `tjne.n 0xd3a6`@0xd3e2 (r2=expected CRC=packet[8..9], r9=computed CRC). Mismatch → reply path, no write. Match → falls to `tjl 0xcd0c`@0xd3ea with r0=phys, r1=r5=&packet[18] (unmodified receive buffer), r2=len.
- boot_wirteFlash @0xd424: cmd==2 guard @0xd43e; only gate is `tcmp r2,sl`@0xd4c2 / `tjeq.n 0xd4e6`@0xd4c4 → write `tjl 0xcd0c`@0xd4ec with raw addr.
- Data written verbatim (data ptr r5 is never transformed). No RSA/SHA/HMAC/decrypt in either chain.
- AES engine unreferenced: `symreport.txt` names 62 regs, none AES; raw grep of listing for 0x800700/708/710/711 pool words = 0 hits; register-map.md confirms those are the AES addresses. No RF (0x800f00) touched in the IAP handler range.

### Claim 2 — CRC = CRC-16/MODBUS over payload, value @packet[8..9]. **CONFIRMED (VERY HIGH) — grounding corrected.**
- Routine FUN_d0e4. poly: `tloadr r3,pc,0x2c`@0xd0f0 → literal @0xd120; raw bytes `01 a0` = halfword 0xA001, stored to table[1] via `tstorerh`@0xd0f2. init literals: writefirmware @0xd414 = 0x0000FFFF, boot @0xd4fc = 0x0000FFFF (raw words).
- CRITICAL nuance the original report glossed: correctness depends on `tshftrs` being LOGICAL. TC32 has THREE distinct shift mnemonics here: `tshftls`=LSL (prefix 0xF000), `tshftrs`=LSR logical (prefix 0xF800), `tasrs`=ASR arithmetic (prefix 0xE000, e.g. `tasrs r7,r2,0x1f` sign-spread). The trailing "s" = "sets flags" (as in tadds/tmovs), NOT "signed". CRC uses `tshftrs` (LSR).
- Emulating the EXACT traced algorithm: with LSR → check("123456789")=0x4B37 and matches a standard MODBUS reference on random buffers. (Had tshftrs been ASR, init 0xFFFF sign-extends to 0xFFFFFFFF and result low16 = 0x34C6 ≠ MODBUS.) tshftrs=LSR is proven three independent ways: (a) the distinct `tasrs` mnemonic; (b) the on-device compare `tcmp r2,r9` only ever matches if r9 is a clean 16-bit value (which requires logical shift) — else flashing could never succeed; (c) 0x4B37 reproduces.
- Coverage = `length` payload bytes; recompute `crc16_modbus(payload).to_bytes(2,'little')` → packet[8..9]. Correct.

### Claim 3 — Dispatch: 64B report, magic 0x81 0x05, cmd@[2], header packet[2..17], data@[18..63], u32 LE addr@[14..17]; replies 0x02 0x05 on USB EP3/4/8. **CONFIRMED (VERY HIGH).**
- iap_dispatch @0xd998: packet[0]==0x81 @0xd9a0, packet[1]==0x05 @0xd9aa, packet[2]==0x0b→multi_write @0xd9b2; else `memcpy(sp,&packet[2],0x10)`@0xd9c4 (header=packet[2..17]); `r4=packet+0x12`@0xd9da = data ptr = &packet[18]. Self-guarding handlers chained (each re-checks its cmd id: verified d1bc==0xC1, d424==0x02, d2e8==0x03).
- Field offsets (from handler byte-reads, header index → packet offset): command=header[0..1]=packet[2..3]; length=header[4..5]=packet[6..7]; expected-CRC=header[6..7]=packet[8..9]; address u32 LE=header[12..15]=packet[14..17]. Matches report's packet table.
- Reply builder FUN_d124: reply[0]=0x02 @0xd146, reply[1]=0x05 @0xd14a, then 16B header + ≤46B data (clamp at 0x2e, "pbufferLength > 46" @0xd164). Wrapper FUN_d1a8 calls it with len 0x40. Send 0xdd14→0xdd7c writes reg_usb_ep8_ptr/dat/ctrl (0x110/0x118/0x120), reg_usb_ep3_ctrl (0x123), reg_usb_ep4_ctrl (0x124) per symreport; register-map.md confirms the EP3/EP4 HID layout. USB only, no RF.

### Claim 4 — Self-flash of own SPI flash via SDK 0xb220/0xb1ec/0xb204; staging header@0x12000, code@0x13000. **CONFIRMED (HIGH) — with a REFUTATION of the "any region" sub-claim.**
- FUN_cd0c (write) → unlock `tjl 0xcc58`@0xcd20 then `tjl 0xb220`@0xcd2a. FUN_ccdc (erase) → 0xcc58 then `tjl 0xb1ec`@0xccf2. writefirmware biases phys=addr+0x13000 (0x98<<9 @0xd380). multi_writeFlash (cmd 0x0B, FUN_d5d4) uses ×59-byte block stride @0xd62e-d636 + 8-bit additive sum @0xd65c-d662 (NOT MODBUS) — matches report.
- **REFUTED: "boot_wirteFlash writes raw addr, no bounds, can target any region."** FUN_cd0c (and FUN_ccdc) load literal 0xFFFEE000 = −0x12000 (@0xcd3c / @0xcd04), compute `r2 = addr − 0x12000`, and `tjhi` (unsigned) error if r2 > 0xD000. So the physical writable window is **[0x12000, 0x1F000]** only — the staging/upper bank. Any addr < 0x12000 underflows to a huge unsigned value and is rejected. boot_wirteFlash calls this same 0xcd0c, so despite using a raw address it CANNOT write the live app (0x6000–0x11FFF) or bootloader (0x0–0x5FFF). The IAP handlers only stage; the resident bootloader (not in this image) is what applies staging→live on reboot. This is a real correction to the report's security framing (the "no bounds" claim), though it does not affect the "CRC-only, no signature" conclusion.

### Claim 5 — Controller updater + resident bootloaders use same protocol/CRC. **UNPROVEN.**
- Correctly flagged INFERRED by the report. The dongle bootloaders (0x0–0x5FFF) and the controller image are not in this dump; nothing here proves it. Cannot confirm or refute.

## Patch-proposal verification
Both patch sites are in the flashed app region (0x6000–0xFFFF). Both correctly noted as only applicable via hardware SWS (circular via the CRC-gated USB IAP).
- **Patch 1** writefirmware @0xd3e2 `tjne.n 0xd3a6` → NOP: raw bytes `e0 c1` = cond NE (0xC1) offset −0x40→0xd3a6 (CONFIRMED). NOP 0x46C0 (`c0 46`) confirmed against real tnop@0xd226 (`c0 46`). NOP → fall-through to write @0xd3e4 regardless of CRC. Effect + encoding CONFIRMED.
- **Patch 2** boot_wirteFlash @0xd4c4 `tjeq.n 0xd4e6` → uncond: raw bytes `0f c0` = cond EQ (0xC0) offset +15→0xd4e6 (CONFIRMED). Desired `tj.n 0xd4e6` = 0x8000|off11; off=(0xd4e6−0xd4c8)/2=0x0f → 0x800f → bytes `0f 80`. TC32 `tj.n`=0x8000|off11 verified against 5 real instructions. CONFIRMED (report under-rated encoding as MEDIUM-HIGH; it is correct/HIGH).
- Caveat on BOTH patches: even with the CRC compare defeated, the shared FUN_cd0c bound still confines writes to [0x12000, 0x1F000]. The bypass lets you stage arbitrary CONTENT without a matching CRC, not write outside the staging window.

## Net
Every load-bearing structural/crypto claim CONFIRMED. Strengthened the CRC grounding (TC32 tshftrs=LSR proof). One sub-claim collapsed: boot_wirteFlash is NOT unbounded — FUN_cd0c clamps all IAP writes to the [0x12000,0x1F000] staging bank. Claim 5 remains genuinely unproven (out of scope of this image).
