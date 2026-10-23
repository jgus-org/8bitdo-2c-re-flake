# 8BitDo Ultimate 2C — Flash layout & checksum angle

Angle owner goal: understand the flash/memory layout and the integrity math so a **modified controller image can be made acceptable** to the device that flashes it. Device: 8BitDo Ultimate 2C pad + 2.4 GHz dongle (USB 2dc8:310a), both on a Telink **B80 (TLSR825x-class, TC32)**. Firmware confirmed plaintext (no AES on the 2C).

Confidence legend: **[V]** verified from primary source, **[I]** inference/strong candidate, **[?]** open.

---

## 1. What is established

### 1.1 TLSR825x internal flash map (512K variant) **[V]**

From the Telink B85m/BLE SDK flash map (search-surfaced SDK layout, consistent across pvvx tooling):

| Offset    | Region                                                                            |
| --------- | --------------------------------------------------------------------------------- |
| `0x00000` | Firmware bank 0 ("old firmware bin")                                              |
| `0x34000` | NV_1 (non-volatile / user params sector)                                          |
| `0x40000` | OTA "new bin" storage area (bank 1)                                               |
| `0x76000` | **MAC address** (8 bytes)                                                         |
| `0x77000` | **C_Cfg_Info** — factory/RF calibration incl. the 1-byte **frequency-offset** cal |
| `0x78000` | U_Cfg_Info (user cfg)                                                             |
| `0x7A000` | NV_2                                                                              |
| `0x80000` | end of 512 KB flash                                                               |

- The MAC + calibration sectors near the top of flash are written at the factory and are **RF-load-bearing**: erasing/overwriting them de-tunes the radio and changes identity. A modified image **must not touch `0x76000`–`0x78000`**. **[V]/[I]**
- 128 KB variants scale the top sectors down (MAC at `0x1F000`, cfg one sector below); the 512K numbers above are the confirmed ones. **[I]**

### 1.2 The 2C does NOT use the stock SDK dual-bank layout **[V for addr, I for arrangement]**

The ebitdo container for the 2C flashes at **`destination_addr = 0x6000`** (from the CONTEXT decode). `0x6000` is neither `0x0` nor a mask-ROM multiboot address (`0x0/0x20000/0x40000/0x80000`). This means:

- **`0x0`–`0x5FFF` (24 KB) = a custom 8BitDo bootloader/IAP** (the code carrying `eraseFlash/writefirmware/boot_wirteFlash/flash_crc/saveCodeBlock/savehead4K/get_pid`).
- **`0x6000+` = the application slot** that gets rewritten.
- The mask-ROM boots the bootloader at `0x0` (its TLNK marker at `0x8`); the bootloader then validates and jumps into the app at `0x6000` (app's own TLNK marker expected at `0x6008`). **[I]**
- Implication: the stock SDK "bank0 @0x0 / new-bin @0x40000 ping-pong" is **not** how the 2C updates. There is a single app slot plus an IAP bootloader.

### 1.3 Telink boot header (per-image), from pvvx `cstartup_825x.S` **[V]**

The first 0x20 bytes of any Telink image (bootloader at `0x0`, app at `0x6000`):

| Off (rel to image base) | Directive                           | Meaning                                                                                                                          |
| ----------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `+0x00`                 | `tj __reset`                        | reset-vector jump                                                                                                                |
| `+0x08`                 | `.word 0x544c4e4b`                  | **TLNK marker** — flash bytes `4b 4e 4c 54` ("KNLT"). Mask-ROM/bootloader treats an image as valid only if this word is present. |
| `+0x0C`                 | `.word 0x00880000 + icload_size/16` | SRAM "IC load" descriptor (how many bytes the boot copies to SRAM)                                                               |
| `+0x10`                 | `tj __irq`                          | IRQ-vector jump                                                                                                                  |
| `+0x18`                 | `.word (_bin_size_ + 4)`            | **firmware length**, incl. a 4-byte check appended at the tail                                                                   |
| `+0x20`                 | code                                | `.align 4`, real code begins                                                                                                     |

- The `+4` at `0x18` and the tail word are the SDK's **appended firmware check** (written by Telink's `tl_check_fw` post-build step). The bootloader can compare a computed value against the last 4 bytes before accepting the image. **[V for layout, I for use]**
- **Invalidating an image = erasing its TLNK word at `+0x8`** (this is exactly how Telink flippers/pvvx force a bank switch: erase `run0` TLNK so boot falls through to `run1`). **[V]**

### 1.4 ebitdo 28-byte container header (fwupd `fu-ebitdo.rs`) **[V]**

```
struct FuStructEbitdoHdr {   // 28 bytes = 0x1C, little-endian
    version:          u32le, // +0x00
    destination_addr: u32le, // +0x04  (0x6000 on the 2C)
    destination_len:  u32le, // +0x08  (payload byte count)
    reserved:         [u32le; 4], // +0x0C..+0x1B (16 bytes)
}
```

- `version` is the **raw integer = display-version × 100** (retro-receiver dumps: `0x69`=105 → v1.05, `0x6c`=108 → v1.08, `0x6f`=111 → v1.11). **[V]**
- fwupd only reads `version/destination_addr/destination_len`; on build it writes those three and leaves the **16 reserved bytes = 0** and **computes no checksum**. **[V]**
- CONTEXT reports the _vendor's_ files carry **USB PID + a per-file checksum inside those 16 "reserved" bytes**. So fwupd's "reserved" == vendor's PID+checksum field. **[V vendor-use / I exact-offsets]**
- Newer `.dat` files can hold **multiple payloads**: a second 28-byte header + payload appended at an offset, targeting a second address (e.g. bootloader vs app, or pad vs dongle). **[V]**

### 1.5 The two different write protocols (do not conflate)

- **(A) fwupd "ebitdo" USB protocol** (older SF30/M30-era pads): `FuStructEbitdoPkt` framing, **32-byte** data chunks, cmds `FwUpdateHeader(0x01)/FwUpdateData(0x00)/UpdateFirmwareData(0x16)/FwUpdateOK/Ack(0x14)/Nak(0x15)`, plus a serial-derived **"encode ID"** (`serial[i] ^ app_key_index[serial[i]&0xf]`) sent via `FW_SET_ENCODE_ID`. **No per-chunk CRC and no header-checksum validation** in this path. **[V]**
- **(B) 8BitDo vendor HID protocol** (numpad + Ultimate-family, matches the 2C dongle's IAP symbols): **64-byte reports**, **46-byte** data field, per-block CRC. This is the `flash_crc` / `writefirmware` / `pbufferLength > 46` path. **[V]**

### 1.6 Vendor HID packet layout (skowronski USB-sniff) **[V]**

64-byte host→device report:

```
[0:2]   0x81 0x05           fixed prefix
[2]     command
[3:6]   param (0x000000; first pkt 0x210100)
[6]     data_len            payload bytes used, 0..46
[7]     0x00                padding
[8:18]  address             10 bytes, BIG-ENDIAN flash location
[18:64] data                46 bytes (zero-padded)
```

Command set:

| Op     | Name                  | Notes                                                 |
| ------ | --------------------- | ----------------------------------------------------- |
| `0x00` | session start/end     | 2 packets total                                       |
| `0xc1` | write start           |                                                       |
| `0xc3` | **set block address** | 12-byte data struct (addr/len/**expected block CRC**) |
| `0x04` | block write start     | follows each `0xc3`                                   |
| `0x03` | data write            | **46-byte** payloads, the bulk                        |
| `0xc4` | write finish          |                                                       |
| `0x07` | update finish         | last before session end                               |

- A block = **90 × 46 = 4140 bytes** (except the last = 12 writes); ties to the `savehead4K`/`saveCodeBlock` **4 KB sector** granularity. **[V/I]**
- `"writefirmware ----> crc != header"` = the device recomputes `flash_crc` over the received block and compares to the CRC carried in the `0xc3` "header" packet. **This is the integrity gate that a patched image must satisfy.** **[I, high]**

### 1.7 Low-level flash primitives **[V]**

pvvx `cmd_parser.c` and Telink `flash.c` expose the raw ops the IAP wraps: read (3-byte LE addr + len), page-program (SPI `0x02`), **sector-erase 4 KB (SPI `0x20`)**, read-status `0x05`, write-enable `0x06`, JEDEC-ID `0x9F`, chip-erase `0xC7/0x60`. pvvx's own BLE flash-hack cmds: `RDFB/WRFB/ERFB/CHGB(change boot)/OTAC(clear new-fw area)`.

### 1.8 Candidate CRC algorithms

- **Telink BLE-OTA whole-image CRC** = **CRC16, poly `0x8408`** (reflected CCITT/X25, init `0xFFFF`); appended per 16-byte block and reported at OTA-End as `02 ff <blocks_le> <crc_le>` (atc1441 gist example `02 ff fa14 05eb` → 0x14fa blocks, crc 0xeb05). **[V]** This is the Telink-idiomatic CRC and the **strongest candidate for the 2C's `flash_crc`**. **[I, medium]**
- **tl_check_fw appended tail check** (the `bin_size+4` word at `0x18`): SDK-version dependent — classic SDK = CRC32-style tail; Android-RCU variant swaps in RSA signing (`ref_sign_fw.py`). The 2C is **unsigned** (plaintext, no crypto handler), so a plain checksum/CRC, not a signature. **[V no-signature / ? exact-algo]**

---

## 2. How to make a modified image acceptable (synthesis)

To flash a patched app back through path (B):

1. Keep the **app TLNK marker at `0x6008`** intact and the **`+0x18` size word** consistent with the new length. **[I]**
2. Recompute the **appended tail check** (last 4 bytes of the app image, per `bin_size+4`) if the bootloader verifies it before jumping to `0x6000`. **[I]**
3. Recompute the **per-block `flash_crc`** for every 4 KB/46-byte block and place it in each `0xc3` block-address packet — this is the check that actually fires during `writefirmware`. **[I, high]**
4. Recompute the **ebitdo 28-byte header's per-file checksum** in the reserved field **only if** the device validates it. fwupd never sets it and still flashes older pads, so it is likely **not enforced** — but the 2C uses path (B), so this must be confirmed on-device, not assumed from fwupd. **[?]**
5. Do **not** modify `0x76000`–`0x78000` (MAC + RF calibration). **[V/I]**

---

## 3. Confidence summary

- Flash map offsets (512K), TLNK@0x8, size@0x18, ebitdo 28-byte struct, version×100, vendor 64-byte/46-data packet + opcodes, two-protocol split: **[V]**.
- 2C = bootloader@0x0 + app@0x6000 (from dest_addr 0x6000): addr **[V]**, bootloader/jump arrangement **[I high]**.
- `flash_crc` == Telink CRC16/0x8408: **[I medium]** — must confirm on the binary.
- Whether the ebitdo header per-file checksum is enforced by the 2C: **[?]**.
- Exact byte offsets of PID vs checksum inside the 16 reserved header bytes: **[?]**.

---

## 4. Open questions

1. Exact width/poly/init of `flash_crc` and the precise byte range it covers (whole block? 46-byte chunk? includes the 10-byte address?).
2. Where in the `0xc3` 12-byte struct the expected CRC sits, and whether length/addr are also CRC-covered.
3. Does the bootloader verify the app's appended tail check (`0x6018` size word + trailing 4 bytes) before jumping to `0x6000`? If not, only the transport `flash_crc` matters.
4. Is the ebitdo 28-byte header's reserved checksum validated by the device, and what algorithm (sum vs CRC) over which bytes?
5. B80 flash size on the 2C (128K vs 512K) — determines whether MAC/cal live at `0x1F000` or `0x76000`.
6. Does the 2C's BLE side expose the **stock Telink OTA service** (UUID 0x1912)? If so, pvvx's `TLSR825x_OTA_Flash_Hacker` is an **independent flashing path** that bypasses the vendor HID protocol entirely — but it writes the SDK bank layout, which may not match the 0x6000 app slot.

---

## 5. Single most useful next action

**Disassemble `flash_crc`, `writefirmware`, and `saveCodeBlock`/`savehead4K` in the already-dumped, Ghidra'd firmware (task #1).** The binary is plaintext, so reading these routines directly yields (a) the exact CRC width/poly/init and covered byte range, and (b) where the expected CRC arrives in the `0xc3` packet — the two facts needed to compute a valid checksum for a patched payload. Cross-check the recovered polynomial against Telink CRC16 `0x8408`. Secondarily, dump the live app region and confirm the TLNK word at `0x6008` and the tail-check word at `0x6018`.

---

## Sources

- fwupd ebitdo struct/plugin: https://raw.githubusercontent.com/fwupd/fwupd/main/plugins/ebitdo/fu-ebitdo.rs , `fu-ebitdo-device.c`, `fu-ebitdo-firmware.c`, README.md
- fwupd ebitdo issue (multi-payload, header parse): https://github.com/fwupd/fwupd/issues/9679
- 8BitDo vendor HID sniff (64-byte/46-data, opcodes): https://skowronski.tech/posts/2025-05-24-8bitdo-numpad-firmware-hackability/
- ebitdo header version dumps: https://hackaday.io/project/161458-reversing-the-8bitdo-retro-receiver
- Telink boot header (TLNK@0x8, size@0x18): https://raw.githubusercontent.com/pvvx/TLSR825x_OTA_Flash_Hacker/main/source/cstartup_825x.S
- Telink flash cmds: https://raw.githubusercontent.com/pvvx/TLSR825x_OTA_Flash_Hacker/main/source/cmd_parser.c
- TLSR825x flash map / MAC 0x76000 / cfg 0x77000: Telink B85m BLE SDK handbook + https://developer.tuya.com/en/docs/iot-device-dev/bluetooth_platform_ble_tlsr825x
- Telink secure-boot header / boot addresses 0x0/0x20000/0x40000/0x80000: https://doc.telink-semi.cn/doc/en/application_note/res/others/secure_boot/secure_boot_application_note_en/
- Telink OTA CRC16 / OTA-End frame: https://gist.github.com/atc1441/42d9ed497600a35a17e456c8125374c5
- tl_check_fw (append check / signing variant): https://android.googlesource.com/platform/hardware/telink/atv/refDesignRcu/+/refs/heads/master/tl_check_fw.sh
