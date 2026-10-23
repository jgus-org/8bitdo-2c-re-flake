# RE notes & log

Running technical notes on the 8BitDo Ultimate 2C firmware. Newest log entries at the bottom.

## Firmware acquisition

8BitDo serves firmware from a live API over plain HTTP, no auth:

```
POST http://dl.8bitdo.com:8080/firmware/select
  header  Type: <n>     required — a bare POST returns an empty list
  header  Beta: 0|1     optional
```

Response JSON `.list[]` entries carry `version`, `fileSize` (exact), `filePathName` (relative), and `md5`. Download = `http://dl.8bitdo.com:8080` + `filePathName`.

- **Type 75** = Ultimate 2C controller, **76** = Ultimate 2C Adapter (dongle, USB `2dc8:310a`), **77** = Ultimate 2C Wired.
- The manifest `md5` field is **garbage** — the same value appears across three different files, and it matches none of the served bytes. Verify by `fileSize` only.
- The empty-list-without-Type behavior is why fwupd's `8bitdo-firmware.py` (sends only `Beta:1`) is broken. `refetch-firmware` and `franfermon/8bitdo_update` send a per-model `Type` header.

Pinned versions (see `flake.nix` for URLs + hashes):

| Device     | Ver           | Size  | md5 (real)                       |
| ---------- | ------------- | ----- | -------------------------------- |
| Controller | v1.09 current | 74780 | b24d58a5b394c8480a44a6858959e80a |
| Controller | v1.06 factory | 74780 | d8944c5f65a1cd1c310536d841607b79 |
| Dongle     | v1.03 current | 40988 | 594b337c3fed92bfa3c5e8e462a36fcd |
| Dongle     | v1.00 factory | 25116 | 934525490551334ab0cc904f1cf57736 |

Downloads are byte-deterministic (no per-request nonce). If the vendor URL ever rots, we have local copies to vendor into the flake.

## Container format (ebitdo)

28-byte (0x1C) little-endian header + one raw payload. Header struct = fwupd `FuStructEbitdoHdr` ([`plugins/ebitdo/fu-ebitdo.rs`](https://github.com/fwupd/fwupd/blob/main/plugins/ebitdo/fu-ebitdo.rs)):

| Offset    | Field        | ctrl v1.09 | dongle v1.03 |
| --------- | ------------ | ---------- | ------------ |
| 0x00 u32  | version ×100 | 109        | 103          |
| 0x04 u32  | dest_addr    | 0x6000     | 0x6000       |
| 0x08 u32  | dest_len     | 0x12400    | 0xA000       |
| 0x0C u16  | USB PID      | 0x301B     | 0x301C       |
| 0x10 u32  | checksum     | 0xA420DCC3 | 0x69DB5CE5   |
| 0x14–0x1B | zero         |            |              |

`filesize − dest_len == 28` exactly for every image (verified on the bytes) → single payload, no trailer. fwupd only reads version/dest_addr/dest_len.

## Chip & encryption

- **Telink B80 (TLSR825x-class), TC32 core.** Positive ID from the embedded SDK string `$$$telink_b80_ble_2.4g_dual_mode_sdk_V3.0.0$$$` plus the `TLNK` section magic (stored LE as `KNLT`) at payload offset 8. ("TLSR8271" seen elsewhere is cross-part inference from a sibling numpad teardown, not from this binary.)
- **Not encrypted.** Payload entropy 6.78–6.97 bits/byte, ~10% zero bytes, duplicate 16-byte blocks, surviving ASCII — impossible for AES. Single-byte XOR sweep best key = 0x00. The 2C shipped with Telink's HW AES secure-boot left disabled; other current 8BitDo models (numpad, Ultimate 2) are AES-encrypted.
- TC32 ≈ 16-bit ARM9 Thumb; ELF machine type 58. Ghidra has no built-in TC32 — the `trust1995/Ghidra_TELink_TC32` module supplies it (that fork has a working decompiler; `rgov`'s is disassembly-only).

## String analysis (asymmetry that matters)

- **Dongle (v1.03) is symbol-rich.** Full IAP/bootloader command handler (`eraseFlash`, `writefirmware`, `boot_wirteFlash`, `readfirmware`, `multi_writeFlash`, `flash_crc`, `saveCodeBlock`, `savehead4K`, `init.upgrade_addr`, `mcu_uuid`, `setLEDStatus`, `usb_init`, `watch dog reset`), USB-mode state machine (`init_usb_idle/xinput/dinput`, `USB_MODE_*`, `get_is_wiredGamepad`), stick cal (`CAL_JOY*`), pairing (`set_rf_address`, `enter/end pair`).
- **Controller (v1.09) is stripped.** Only ~4 real strings survive: `Telink Remote`, the SDK tag, `8BitDo Ultimate 2C Wireless`, `XUSB10`. The other ~100 length≥5 hits are code bytes that happen to be printable. **Consequence:** the charging/power-on logic lives in the controller, so that RE is a string-less TC32 disassembly with no breadcrumbs — meaningfully harder than the dongle work.

## Charging behavior (the actual target)

- Documented **intended** behavior, not a bug. The 2C manual: _"The controller will not turn off during a wired connection."_ A charge cable counts as a wired connection, so the power-off gesture is ignored while charging.
- **No Ultimate Software V2 setting controls it.** The V2 sleep toggle + 15-min idle auto-off govern only the battery-idle path.
- The pads power on from a **dumb charger** (no data lines, no enumeration), so the trigger is **raw VBUS presence**, not a USB data handshake. A data-blocker cable still passes VBUS → would not help, _unless_ the pad distinguishes a BC1.2 charger (D+/D− shorted) from bare VBUS, in which case opening D+/D− might drop it to an idle-off path. Cheap to test empirically; low confidence it helps.
- Untested alternative: does a charging pad also auto-connect in **Bluetooth** mode? If not, replacing the 2.4 GHz dongles with BT pairing sidesteps the whole slot-contention problem without any firmware work.

### RE result (2026-07-12) — full detail in [findings/FINDINGS.md](findings/FINDINGS.md)

- Charge sense is in the app: `analog_read(0x88) & 0x20` at `FUN_00007138` @0x7102 gates a charge-indicator LED loop (VERIFIED). The bit's identity (a comparator / VBUS-present flag) is inferred and conflicts with the register map's documented LPC result at bit6 — the physical meaning of analog 0x88 bit5 is unconfirmed.
- Sleep primitive: `*reg_pwdn_ctrl(0x80006f) = 0x81` at 0x6026, single call site, inside a suspend routine @0x7210 that has **zero in-image callers**; `reg_wakeup_en 0x6e` is never written in the app image. The power-off decision, the charge gate, and the deep-sleep wake-arming therefore live in the **resident bootloader (0x0–0x5FFF), which is not in our image**.
- Consequence: "won't power off while charging / wakes on a dumb charger" is **not patchable through the USB-flashable app** — only hardware SWS reaches the bootloader. Whether power-on-from-VBUS is bootloader firmware or a pure-hardware LDO cold-boot is undecided (bench test: does MCU VDD collapse when the pad is "off"?).

## Flashing (captured & verified — controller + dongle)

- fwupd `ebitdo.quirk` does not list the 2C; official flashers (`web.8bitdo.com` WebUSB, Ultimate Software V2) drive a newer proprietary protocol, not fwupd's legacy ebitdo path.
- Bootloader entry (family-wide): power off, hold **L1+R1** while connecting USB-C until the LED blinks red. Wired-USB only. The dongle does **not** relay controller firmware — each device is flashed over its own USB port.
- **Dongle IAP fully reversed** (`iap_dispatch` @0xd998): 64-byte HID report, magic `0x81 0x05`, cmd @[2], length @[6..7] (≤46), expected CRC @[8..9] LE, **u32 LE flash address @[14..17]**, ≤46-byte data @[18..63]; device replies prefixed `0x02 0x05`. (Corrects the earlier "10-byte big-endian address" from the numpad sniff.)
- **Integrity gate = CRC only, no signature, no encryption** (VERIFIED on the dongle). CRC routine `FUN_0000d0e4` = **CRC-16/MODBUS** (poly 0xA001 reflected, init 0xFFFF, refin/refout, no xorout) over the payload bytes; expected value at packet[8..9] LE. The AES engine (0x800700+) is never referenced in the IAP path.
- **Writes are clamped to the staging window [0x12000, 0x1F000]** by `FUN_0xcd0c`; the IAP only stages, and the resident bootloader applies staging→live on reboot. The IAP cannot directly overwrite the live app (0x6000–0x11FFF) or the bootloader (0x0–0x5FFF).
- **Controller — VERIFIED by capture** (2026-07-12, see below): the controller uses the same `0x8105` protocol (on EP 0x06), the same CRC-16/MODBUS, and transmits the image plaintext (exact-match reconstruction). "Controller is CRC-only / no signature" is no longer inferred. The lone residual is a possible boot-time whole-image check in the un-dumped bootloader.
- **Brick hazards & recovery**: the IAP writes only the app region — the resident bootloader (0x0–0x5FFF) is not touched by a normal flash, so it survives a bad app and is the recovery anchor. **Recovery channel CONFIRMED** (enumeration capture `2c-bootloader-plug.pcapng`, 2026-07-12): holding **L1+R1 while plugging in** enters the resident bootloader **`2dc8:3208`**, a HID interface exposing **EP 0x05 OUT + EP 0x84 IN** — an app-independent USB flash channel that survives a bricked app. That it speaks the same `0x8105` protocol is inferred (OUT endpoint present; same family/endpoint as the dongle) — confirm non-destructively via a read-probe (session-start / get-version) before relying on it for writes. The official Ultimate Software V2 flashes the 2C in _normal_ mode and ignores `3208`; the `3208` channel is ours to use. Never chip-erase (MAC @0x76000, RF-cal @0x77000 are factory-written, not in the `.dat`); never erase the bootloader.
- **No off-the-shelf flasher exists for the modern 2C**: every open-source tool (`fwupd` ebitdo, `franfermon/8bitdo_update`, `8bitdo-firmware`, ladis.cloud) implements the _legacy_ `.dat`/PID ecosystem, not the `2dc8`/`0x8105` protocol; only 8BitDo's own Ultimate Software V2 + WebUSB do, and both are update-gated with no reflash-on-demand/restore mode. A custom `0x8105` tool is the only route to on-demand reflash and to driving the `3208` recovery channel. Endpoints by mode: **normal-mode app flash = EP 0x06**, **dongle = EP 0x05**, **`3208` bootloader = EP 0x05 OUT / EP 0x84 IN**.
- **SWS single-wire** (pvvx tooling; non-FTDI USB-serial, `TX→SWS`, `RTS→RESET`, GND, 3V3) is the **guaranteed** full-flash backup + un-brick route (bypasses the vendor path entirely) and the only path to the goal-1 bootloader gate.

### On-wire flash protocol — captured & verified (2026-07-12)

Captured USB traffic of Ultimate Software V2 flashing stock firmware to a controller and a dongle (Wireshark/USBPcap; `/storage/tmp/2c-{controller,dongle}-flash.pcapng`), analyzed with tshark + the pinned payloads.

- **Transport:** 64-byte interrupt-OUT reports. **Controller flashes on EP 0x06, dongle on EP 0x05**, both while enumerated in their _normal_ mode (controller = XInput `2dc8:310a`, device stays at its running address). The tool drives the transition + post-flash reboot; **L1+R1 bootloader mode is not used by the normal update path** — no separate bootloader device appears.
- **Report layout:** `81 05 | cmd(1) | 3B | len(u16 LE @6) | crc16(u16 LE @8) | 8B | data(@18 … 18+len)`.
- **Command set:** `00` session-start (params `21 01`) · `c1` write-start · `c3` set-block-addr (12-byte desc: addr u32 LE, size u32 LE = 0x1000, 4B fill) · `04` block-start · `03` data-write (46-byte chunk) · `c4` write-finish (carries total image length, e.g. 0x12400) · `07` reset. Blocks are **4 KB at sequential offsets from the app base 0x6000** (controller wrote all of 0x0–0x12400; dongle capture wrote 7/10 blocks — a differential write skipping unchanged blocks).
- **Integrity = CRC-16/MODBUS** (poly 0xA001, init 0xFFFF) over each command's `data[18:18+len]`, stored LE at `[8:9]` — verified against **every** captured chunk (controller 1643/1643 data-writes + 38 c3 + 1 c4; dongle 630/630). `07` reset carries no CRC. Recomputable.
- **Plaintext, no encryption:** the `0x03` data-writes reconstruct **byte-for-byte to the pinned payloads** (controller 74752 B exact match; dongle's written blocks exact match). No signature anywhere in the write path.
- **⇒ A modified image is flashable:** patch payload → re-chunk (4 KB blocks → 46-byte writes) → recompute CRCs → replay `0x8105` to EP6 (controller) / EP5 (dongle). Definitive no-signature proof = a null-modification round-trip (flip one non-functional byte, fix its chunk CRC, flash, confirm boot) with recovery (verified bootloader chord or SWS) ready.

## Prior art

- [`trust1995/Ghidra_TELink_TC32`](https://github.com/trust1995/Ghidra_TELink_TC32) — the processor module this flake bundles.
- [`telink-semi`](https://github.com/telink-semi) B80 / TLSR825x SDK — RF-driver register enums + flash/OTA routines; best symbolication anchor.
- [`franfermon/8bitdo_update`](https://github.com/franfermon/8bitdo_update) — cleanest reference impl of the live API.
- [`fwupd` ebitdo plugin](https://github.com/fwupd/fwupd/tree/main/plugins/ebitdo) — header struct + USB flash protocol + `ENCODE_ID` XOR handshake.
- [ladis.cloud writeup](https://ladis.cloud/blog/posts/firmware-update-8bitdo/index.html) — human-readable API + physical flash reference.

## Analysis pipeline (scripts/)

Headless Ghidra scripts, run against an imported project with `ghidra-analyzeHeadless <proj> <name> -process -noanalysis -scriptPath scripts -postScript <Script>.java <outdir>` (project first created with `-import <payload.bin> -processor Telink_TC32:LE:16:default -loader BinaryLoader -loader-baseAddr 0x6000`):

- `ExportAll.java` — decompiled C + function table + strings + register-window references.
- `ListingExport.java` — full disassembly listing; PC-relative pool loads annotated with the `0x800xxx` value they reach.
- `PoolRegs.java` — histogram of distinct register addresses the code references (the peripheral footprint).
- `StringXrefs.java` — string → referencing-function map (semantic anchors for an otherwise-`FUN_`-named image).
- `CreateFuncs.java <lo> <hi>` — creates functions at TC32 `push {..,lr}` (byte 0xB5) prologues, recovering library routines the call-graph walk missed.
- `AggressivePre.java` — preScript enabling aggressive instruction/switch/param analysis.
- `ReportStats.java` — block + instruction/function counts (sanity check).

**Register symbolication is a text pass, not a Ghidra pass.** The bundled TC32 module does **not** emit data references for PC-relative literal-pool loads, so Ghidra renders register accesses as `*DAT_<pooladdr>` and reference-based mapping (`getReferencesTo`) returns nothing. `scripts/symbolicate.py` instead scans the flat payload for 4-aligned words holding a `0x800xxx` register (pool image-addr = base + offset = Ghidra's `DAT_<addr>` suffix), maps them via `findings/regmap.tsv`, and rewrites the matching tokens in the decompilation to `<regname>_p`:

```
symbolicate.py --payload <bin> --decomp <decomp.c> --regmap findings/regmap.tsv --base 0x6000 --out <decomp.sym.c> --report <symreport.txt>
```

The `--report` doubles as a register → pool-image-addr index. A pool image-addr below the first real function is the SDK library region, which decompiles poorly (missing caller context → garbage register vars) — read `listing.txt` there rather than the decompilation.

## Shim build toolchain (patches/)

New firmware code is authored as **TC32 assembly** (`patches/*.s`) and assembled at build time — no hand-encoded opcode bytes. `tc32-tools` packages Telink's own `tc32-elf-{as,ld,objcopy,objdump}` (GCC-4.5.1 vintage, from [`flyskywhy/tc32`](https://github.com/flyskywhy/tc32)), fetched per-binary and patchelf'd. `mkAsmMod` links each `.s` with a generated script placing its `.tramp`/`.shim` sections at their img addresses and resolving firmware `syms` (e.g. `analog_read = 0x6d84`), then `apply.py` writes each section at `imgaddr - load-base`, asserting the stock bytes it overwrites.

- **Mnemonics don't all match objdump.** The flag-setting ALU ops assemble **without** the `s` — `tand`/`tor`/`tshftl`/`tshftr` — even though `objdump` disassembles the same encodings _with_ it (`tands`/`tors`/…). `tmovs` keeps its `s`. Cross-check by round-tripping: assemble, `objcopy -O binary`, compare bytes.
- **A register move (`tmov r0, r2`) assembles to `add r0, r2, #0`** (`0xec10`, flag-setting), not the hi-reg move (`0x0610`) Ghidra's SLEIGH assembler emits — same result, and the flags are inert wherever a mov is used here. `.word sym + 1` yields a thumb function pointer (bit 0 set), used for the free-tail callback-slot install (a `.cbslot` data section placed at the slot address, `.word shim + 1`).
- **Nix has no hex literals** (`0x6000` parses as `0` then `x6000`); `place` addresses are hex **strings**, and `apply.py` (Python `int(s, 0)`) does the arithmetic.
- Register loads are img-relative pool words (`tloadr rN, [pc, #imm]` + trailing `.word symbol`); a shim's `tjl`/`tjex` targets and pool words are absolute, so the linker script's section address is load-bearing — wrong placement mis-resolves the branches.

## Process notes (for a future skill)

This flake is a reusable pattern for firmware RE. When we distill a skill, capture:

- **Vendor toolchains package cleanly via `fetchurl` + `patchelf`:** the TC32 binutils are stock x86-64 ELF needing only `libc`+`libz`; fetch the four tools individually (skip the C compiler + eclipse cruft) and `patchelf --set-interpreter`/`--set-rpath`. Authoring shims _as source_ and asserting the assembled bytes reproduce the known-good image makes each mod a reviewable diff, not an opaque hex blob.

- **Standalone flake under `flakes/`**, self-contained (own pinned nixpkgs), _not_ added to the parent flake's inputs. Enable via `.envrc` `use flake` + direnv.
- **Provenance as a derivation chain:** vendor binary → `fetchurl` FOD → header-strip `runCommand` → (next) headless-analysis derivation. Each stage is reproducible and diffable.
- **Ghidra + custom processor module in Nix (Ghidra 12, nixpkgs):** do **not** copy the ghidra tree and drop the module into `Ghidra/Processors/` — the nixpkgs launcher's wrapper hardcodes the original store path, so a copied launcher re-enters the original install and never sees the module. Instead build the module as its own root (`$out/lib/ghidra/Ghidra/Processors/<Name>/`, SLEIGH precompiled with `${pkgs.ghidra}/lib/ghidra/support/sleigh -a <dir>`), then `symlinkJoin` it and wrap `${pkgs.ghidra}/bin/{ghidra,ghidra-analyzeHeadless}` with `--set NIX_GHIDRAHOME "$out/lib/ghidra/Ghidra"`. `NIX_GHIDRAHOME` is an extra application root added by the nixpkgs `0002-Load-nix-extensions.patch`; this is exactly how `ghidra.withExtensions` works. `touch $out/lib/ghidra/Ghidra/.dbDirLock` to stop lock-file creation in the store.
- **Precompile SLEIGH:** the `.sla` must exist in-store (runtime is read-only). `support/sleigh` embeds a source hash, so Ghidra won't try to recompile a matching precompiled `.sla`.
- **Headless scripts must be Java.** Ghidra 12 dropped Jython; `.py` scripts need PyGhidra (CPython), which plain `analyzeHeadless` does not start. Java `GhidraScript`s compile and run at load with no extra setup.
- **Log findings in `NOTES.md`** as you go; keep `README.md` for orientation/usage.

## Log

### 2026-07-11

- Located, downloaded, byte-verified all four images (sizes + md5 match). Confirmed ebitdo header, TC32/B80 chip, and absence of encryption directly on the bytes.
- Stringed both current images — found the dongle symbol-rich and the controller stripped (see above).
- Scaffolded this flake: firmware FODs, payload-extraction derivations, `ghidra-tc32`, `refetch-firmware`, devshell.
- Wired the TC32 processor module into Ghidra 12 via `NIX_GHIDRAHOME` (the `Processors/` drop-in method silently fails — see process notes). Verified end-to-end: headless import of `payload-ctrl-v109` at base 0x6000 loads the Telink_TC32 language and auto-analysis yields **6086 instructions / 98 functions**.

### 2026-07-12

- Built the analysis pipeline (scripts above): exported decompilation + full listing for both current images, recovered SDK routines via prologue scanning (controller 98→104 functions incl. the power/charge routine), and symbolicated register accesses with `symbolicate.py`.
- Obtained the Telink B80 register map (268 regs, source-cited) → `findings/register-map.md` + `findings/regmap.tsv`. Identified GPIO/PWM/AES/RF/USB/analog blocks and `reg_pwdn_ctrl`, and the analog helpers `analog_read`@0x6d84 / `analog_write`@0x6dc4.
- Ran a 4-agent flashing-research fan-out and a 4-dimension analysis (each finding adversarially verified). Results in `findings/` — `FINDINGS.md` is the vetted synthesis.
- Answers to the ticket goals (see `findings/FINDINGS.md`): charge sense is in the app but the power-off gate + wake-arm are bootloader-resident (not app-patchable); BT shares the gate; L4/R4 are dropped by the dongle's RF→USB map (`FUN_0000733c`); BT force-feedback is declared-but-dead (no ATT write callback → `fa68`); flashing is CRC-16/MODBUS, no signature, staging-clamped, dongle-verified / controller-inferred.
- Next steps are hardware-bench: an SWS full-flash dump (backs up bootloader + MAC + RF-cal; reaches the goal-1 gate) and a usbmon capture of the official updater (validates the controller IAP + CRC).
- **Flash protocol captured & verified** (USBPcap of Ultimate Software V2 → controller + dongle; see "On-wire flash protocol"): controller flashes over EP 0x06 in _normal XInput mode_ (no L1+R1), data-writes reconstruct byte-for-byte to the pinned controller payload (74752 B exact), CRC-16/MODBUS matches all 1643 chunks. Dongle validated identically on EP 0x05 (630/630). **Controller flashing is now confirmed CRC-only, no signature, plaintext** — a modified image is flashable; residual = a possible boot-time whole-image check in the un-dumped bootloader.
- Host-side experiments on k1 (in ticket #120): no charge/battery telemetry over 2.4GHz or wired; BT exposes battery % only (no charge flag); charging pads are persistent XInput slot-squatters that won't idle-sleep or accept power-off. New FW direction — patch the app to _expose_ charge state to the host (BT simplest; 2.4GHz/XInput cleaner), now unblocked by the verified flash path.
- **FLASHING VALIDATED END-TO-END** (on k1, controller v1.09): built a pyusb flasher (`flasher/flash2c.py`, flake pkg `flash-2c`) that replays the captured template substituting `0x03` data + recomputed CRC-16/MODBUS. Confirmed: `probe` (session-start → `0222` version/PID ACK), stock re-flash (byte-identical → pad boots v1.09), then two _modified_ flashes — a cosmetic ASCII-string flip (booted), then flipping the UTF-16 USB iProduct `'W'→'V'` so `lsusb` reads **"Ultimate 2C Vireless Controller"**. ⇒ **modified firmware flashes, boots, and takes effect — no signature, no encryption, no boot-time gate beyond the per-chunk CRC.** Gotchas: normal-mode channel = controller EP `0x06` OUT / EP `0x83` IN (ACK `0205`, session ACK `0222`); **must detach the kernel driver from ALL interfaces** (xpad on If0 starves the IAP response); ACKs pipeline by one; the `07` reset legitimately drops the USB connection. Bootloader `3208` uses a _different_ protocol (host `0508` / device `0005`), not reversed — recovery for a booting app = normal-mode re-flash; SWS is the backstop for a non-enumerating brick.

### 2026-07-13 — BT force-feedback made to work (ticket #122)

- **BT-FF works end-to-end via bluez HoG.** A rumble Output write over BLE now drives the motor. Three firmware pieces, all in `mod-bt-ff-ctrl-v109` (`patches/bt-ff.py` + `bt-report-id.py` + `brand.py`):
  1. **Motor-routing shim** (`bt-ff.py`): installs a TC32 write callback in idx32's null `.w` field (flash `0x17764` → shim in the free tail `0x18280`). The shim reads `value[0]/value[1]` at `p+9/p+0xa` (r0 = packet — verified against the firmware's _own_ working `.w` at `0x16418`, the vendor char handle 0x30) and calls `fa68(motorA, motorB, 255)`. Assembled via `scripts/Assemble.java`; round-tripped via `scripts/DisasmRange.java`.
  2. **Report-ID fix** (`bt-report-id.py`): the report map declared the rumble Output as **Report ID 5** (`85 05` @ `0x173b4`) but the GATT Report Reference descriptor on the output characteristic says **[1, Output]** — a vendor copy-paste bug. bluez routes output reports by the Report Reference, so it had **no destination for report 5 and silently dropped every rumble write** (this is why HoG "swallowed" writes). Fix: set the report-map Output ID to 1 to match the descriptor. After this, bluez forwards `Write Request (0x12)` to **handle 0x21** = `64 64 00 00` → shim → **buzz**.
- **ABI facts (this firmware):** `.w` callback is `int(*)(void*)`, r0 = ATT packet, value bytes at **p+9** (16-bit form is `(p[0xa]<<8)|p[9]`). `.w` returning 0 → success. Attribute table: count entry (attNum=50) @ `0x1743c`, 24-byte stride, ATT handle == array index; output-report VALUE = handle **0x21** @ `0x17754` (decl handle 0x20 = bluez `char0020`). `attrLen=1` does **not** block `.w` (the working vendor char handle 0x30 also has attrLen=1).
- **Host-side gate for real use (why `ff=0`):** the kernel exposes FF only via a VID/PID driver (like `xpad` over 2.4GHz) or generic `hid-pidff` (needs a _full_ PID descriptor). The 2C's BT map has only a 4-byte rumble Output, so no FF device is created → games can't rumble it. **Option A (firmware full-PID descriptor) rejected** — ~300-450 B descriptor + a PID effect-block state machine (500-1500 B) won't fit the ~396 B free tail. **Option B = a small memless-FF kernel driver** (match 2C over BT → emit Output report → bluez → shim). Reuses the shim; firmware stays 24 B. **Not yet built.**
- **Open issue — ATT no-response / disconnect.** bluez sends the rumble as a **Write _Request_** (`0x12`, via hidraw = SET_REPORT), and the firmware **buzzes but sends no Write Response**; one unanswered request stalls bluez's ATT channel (single write survives, a burst → link drop). Rumble Output should be **Write _Without_ Response** (`0x52`, fire-and-forget) — likely how the Option-B driver's output path sends it. Couldn't isolate WWR yet (raw `btgatt-client`/`gatttool` can't grab the link — the 2C sleeps the instant bluez releases it). Candidate firmware fix if WWR isn't it: `attrLen` 1→4 (handle 0x21 @ `0x17758`) and/or shim return value. **TBD.**
- **Access:** `ssh root@k1` now works (drive BT tests directly). BT pad re-paired as **E4:17:D8:31:6E:6A** (address bumped from ...69). USB "8BitDo IDLE" (PID 301c) on k1 is a separate charging pad, not the BT one.

### 2026-07-13 (cont.) — WWR stall fix + host FF driver

- **WWR fix verified on k1.** Dropped the Write bit from the output-char declaration props (0x0E→0x06 @ flash 0x017330, `patches/bt-write-noresp.py`) so bluez sends rumble as Write Command (0x52, fire-and-forget). btmon on a burst: all Write Command, **link survives, motor buzzes** — the earlier Write-Request stall/disconnect is gone. The 4-patch mod (shim + report-id + write-noresp + brand) is flashed on the test pad (re-paired as ...6C after each pairing bumped the addr).
- **faa0 drives the motor continuously** at the last (motorA,motorB) regardless of the duration byte — both branches converge on `f93c(motorA,motorB)`; the value is inert. Motor stops only on `fa68(0,0)`. The FF driver sends (0,0) on effect-end, so normal use self-stops; disconnect-mid-rumble safety would need a watchdog (gate faa0 on the countdown) — deferred.
- **Host FF driver** `machine/k1/hid-8bitdo-2c-ff/` (wired via `machine/k1/8bitdo-ff.nix`): memless FF_RUMBLE matching the pad over BT (`hid:b0005g*v00002DC8p0000301B`), emits Output report 1 → bluez (WWR) → shim → motor. Builds green vs 6.18.38; k1 toplevel green. **Pending: deploy k1 + fftest.** Gotcha: `kernel.makeFlags` carries the kernel's in-tree flags (`O=$(buildRoot)`, `--eval=undefine`) that break an out-of-tree build (`make: empty variable name`) — filter to the toolchain flags only.

### 2026-07-13 (cont.) — FF driver works, but certain rumble values HANG the pad (OPEN)

- **Driver end-to-end confirmed working:** `hid-8bitdo-2c-ff` auto-binds after reboot, exposes FF (`ff=0x107030000`), fftest drives correct **Write Command → handle 0x21** (btmon: 2 writes/effect, not a flood), and rumble **does fire** (motorA buzzed).
- **But the controller firmware HANGS on certain rumble writes** — main loop frozen: motor stuck ON + input/DPAD dead, needs an ~8s force-off (not a BT disconnect; the pad crashes). hidraw isolation (bypassing the driver): **`64 64 00 00` [100,100] survives + buzzes; `25 01 00 00` [37,1] hangs.** So NOT "a motor == 0" (both nonzero). Trigger is low and/or asymmetric magnitudes.
- Not yet explained by static analysis of fa68→faa0→f93c (duty math is in range for these values). Candidate causes: a value-dependent firmware fault in the PWM/curve path; PWM switching noise at low duty disrupting the 2.4G BLE radio; or an intermittent race ([100,100] survived by luck). Note the ATT `.w` callback and faa0 both run in the BLE main loop (blt_sdk_main_loop), so they are the _same_ context — a naive "defer to main loop" fix likely won't help.
- **Next-session plan:** (a) map the crashing value space with hidraw (symmetric sweep 100→5, plus asymmetric pairs) to characterize the trigger; (b) fftest the SAME low/asymmetric effects over **2.4GHz** — if those don't hang, the fault is BT-path-specific; (c) if BT-specific, re-examine what the shim/ATT path touches vs the RF path; otherwise it's an inherent pad bug and the only lever is a driver-side value clamp to the known-safe region (if one exists). SWS hardware debug would catch the fault PC directly.
- **Done + permanent:** driver built, integrated (`machine/k1/8bitdo-ff.nix`), auto-loads/binds on boot. Firmware delivery (report-id + WWR-props) solid. The value-dependent hang is the sole remaining blocker for #122.

### 2026-07-13 (cont.) — CORRECTION: shim crashes the FW on EVERY rumble (contract bug, not value-dependent)

- **The prior "value-dependent" read was wrong.** User confirmed even `[100,100]` rumbles-then-crashes; the `Connected: yes` readings were false — a _hung_ pad doesn't actively disconnect, so bluez shows it connected until supervision timeout. **Every BT rumble via our shim crashes the controller**: motor fires (so the shim runs + `fa68` executes), then the main loop hangs (input/DPAD dead, PWM latched ON, ~8s force-off to recover).
- **Ruled out via static trace:** `fa68` (@0xfa68) is ABI-clean — touches only r0–r4, saves/restores r4, **preserves r5–r11**; so our minimal `push {r4,lr}` is sufficient (not a register-clobber bug). Entry contract verified (r0 = packet, value @ p+9/+10) against the _working_ vendor `.w` @0x16418. Return value 0 matches that handler. The RF (`dc58`) / USB (`eabc`) paths call the same `fa68`→`faa0`→`f93c` chain and don't crash, so the motor path itself is fine — **the fault is in how/where WE invoke it.**
- **Unverified (the gap):** the ATT-server _dispatch_ in THIS firmware — what it does _after_ `.w` returns (default `memcpy` into the `attrLen=1` buffer @0x84315c? post-write bookkeeping?). Contract was assumed from reference SDK, not read from this binary. `0x1743c` (table base) is a pool word @img 0xa324; the actual `gAttributes[h].w` call site is not yet located.
- **Decisive next test (cheap):** flash a **no-op shim** (just `movs r0,#0; return`, no `fa68` call) into the `.w` slot. Write to 0x21: if it **still crashes** → the `.w` dispatch/post-handling on a HID-report attribute is the bug (trace the dispatch / patch attrLen / SWS). If it **doesn't crash** → calling `fa68` from the ATT context is the bug (defer the apply). Then also compare `dc58`/`eabc` setup around their `fa68` calls. SWS hardware debug would catch the fault PC directly and end the guessing.

### 2026-07-13 (cont.) — BISECTION: ATT dispatch is INNOCENT; crash is the fa68 call or the motor

- **No-op `.w`** (`push{r4,lr}; movs r0,#0; pop{r4,pc}` — returns 0, no fa68), `mod-noop-ctrl-v109`, flashed: writes to handle 0x21 do **NOT** crash — 368 input notifications/2s **before AND after** the writes (pad fully alive). So the dispatch, a non-null `.w` on the attrLen=1 HID-report attribute, and the server's post-write handling are all fine. **The crash is in the shim BODY**: the value read (harmless — 2 ldrb) or the **fa68 call + downstream motor**.
- **Next cut** (`mod-callzero-ctrl-v109`, built + staged as `/storage/tmp/8bitdo/8bitdo-2c-callzero-ctrl-v109.bin`): `.w` calls `fa68(0,0,255)` — exercises the fa68 call from the ATT context but leaves the motor OFF. vs the no-op it adds only the fa68 call. **Crashes → calling fa68 from the ATT context is the fault** (fix: defer the apply — shim writes a slot, main-loop hook calls fa68). **Survives → the motor physically running kills the BT link** (EMI/power/brownout — 2.4G survives it but BLE may not; nastier).
- Liveness test recipe: write `\x01..` to the BT hidraw (HID_ID 0005:00002DC8:0000301B), then `btmon`-count `Handle Value Notification` for 2s — >0 = alive, 0 = hung. bluez `Connected:` is unreliable (stays yes on a hung pad).

### 2026-07-13 (cont.) — CONFIRMED root cause: motor energized during a live BLE connection

- **Bisection complete.** no-op `.w` (no fa68) → survives. `callzero` `.w` (fa68(0,0,255), motor OFF) → survives (356 notifs before / 357 after). Full shim (fa68(100,100), motor ON) → crashes. ⇒ **the crash is the motor physically running while BLE is connected** — not the dispatch, not the `.w` mechanism, not the fa68 call.
- **RE agent (full dispatch trace @0x138c0/0x13a10, corroborated):** on `.w != 0` the write handler does `blx .w(packet)` → check return → respond. **No default copy, no attrLen use, no pAttrValue touch.** attrLen 1→4 and return-value "fixes" are useless (dropped). Stock rejects the 0x21 write (`.w==0` → err 0x0d); our patch is the first code to accept+act on it. ATT table ptr @RAM 0x843648; `.w` load @0x13f92; blx-veneer @0x14524; outer caller @0x14aaa.
- **Conclusion:** whole BT-FF pipeline (shim/delivery/driver/dispatch/fa68) is correct. Blocker = runtime motor↔BLE-radio interaction — brownout or link-layer timing wedging the hard-real-time B80 BLE stack. 2.4G proprietary radio tolerates it; BLE doesn't.
- **Next (distinguish power vs timing):** low-duty shim `fa68(low,low)` — survives → brownout → duty cap (usable only if a feelable duty survives); crashes → RF-timing → gate faa0's f93c drive to safe windows in the BLE schedule (hard). Also: test a FULLY CHARGED pad (all-session use likely lowered battery → worse brownout). SWS = definitive fault-PC capture.

### 2026-07-13 (cont.) — Charge-exposure over 2.4GHz: injection map (agent trace)

- **Charge source:** `analog_read(0x88) & 0x20` (bit5) @ FUN_00007138 — computed transiently for the charge-LED, NOT stored in a global. Must inline-sample at the injection site. (Identity 0x88 bit5=charging is INFERRED — conflicts with the register-map's LPC-at-bit6, but the firmware drives its charge-LED loop off bit5, so bit5 is well-founded; confirm in the charger-vs-battery test, cheap to flip to bit6.)
- **Controller RF report:** button-word global @RAM 0x84342c → report[3..6] on every transport (scanner FUN_0000c7a4 @0xc7a4; packers @0xf0b0/0xf0cc...). Spare word bits {14,15,19-24,29-31} are scanned-but-unused AND dropped by the dongle → free carriers. **Bit 14 = 0x84342d bit6 = report[4] bit6 (0x40)** rides the RF frame for free.
- **Dongle RF→XInput (FUN_0000733c, ~0x730e-0x74cc, gated mode@0x843060==2):** builds a standard **WIRED Xbox-360 20-byte report** → EP4 (0x84). Spare carriers: XInput button bit 0x0800 (unused), and **reserved wire byte [18]=0x00** (written at 0x74ba) — cleanest.
- **KEY CORRECTION:** dongle enumerates as **wired Xbox360** (`2dc8:310a`, xpad `XTYPE_XBOX360`), NOT the wireless receiver. xpad's `power_supply`/battery path exists ONLY for XBOX360W/XBOXONE, and the wired parser ignores data[14..19]. So **`/sys/class/power_supply` is NOT firmware-reachable** — the clean readout needs a small host xpad quirk regardless. No zero-host-code option on 2.4G/XInput.
- **Recommended plan (~26 B firmware + ~40 lines host):** controller: inline-sample charge in FUN_0000c7a4, set word bit14 (`0x84342d |= 0x40`); dongle: at 0x74ba replace `wire[18]=0` with `wire[18] = (RF[4]>>6)&1`; k1: xpad quirk for `2dc8:310a` → register power_supply, status from data[18]. Yields `/sys/class/power_supply/xpadN/status`. Alternatives if no host change: BT HoG battery % via UPower (percentage, not a discrete charge flag) or DInput-HID (hidraw, loses XInput).
- Residual: RF-TX `rf_start_stx` call site is in the closed SDK (plan doesn't depend on it — 0x84342c is the common source); `extra_btn`@0x12bd4 not reversed (off-path).

### 2026-07-13 (cont.) — Charge + battery-level over 2.4GHz: firmware DONE, xpad quirk in progress

- **Firmware patches built + verified + staged** (charge status + 5-bit battery level):
  - Controller `mod-charge-ctrl-v109` (patches/charge-ctrl.py): trampoline @0xc8f0 (button-word finalize-store) → 40-byte shim @0x18280. analog_read(0x88)&0x20 (charging) → word bit14; battery gauge @RAM 0x842e04 (0-100) >>2 → word bits19-23 (5-bit level). Ride RF frame: bit14=report[4] bit6, bits19-23=report[5] bits3-7.
  - Dongle `mod-charge-dongle-v103` (patches/charge-dongle.py): trampoline @0x74ba (wire[0x11]=0 store) → 18-byte shim @0xff44. wire[0x11] = (RF[4]&0x40) | (RF[5]>>3): bit6=charging, bits0-4=level5.
  - Staged: /storage/tmp/8bitdo/8bitdo-2c-charge-{ctrl-v109,dongle-v103}.bin. Both round-trip disassembled; re-application reproduces byte-for-byte; sizes intact (74752/40960).
- **Host decode:** data[18] bit6 = charging (STATUS); bits0-4 = level5, CAPACITY = min(level5<<2, 100) → 4% resolution.
- **xpad quirk:** xpad 6.18.38 has NO battery code → power_supply added from scratch (~70 lines) gated on a new MAP_CHARGE_STATUS flag on the 2dc8:310a entry (xpad.c line 411), reading data[18] in xpad360_process_packet (@972), register in init_input (after input_register_device @2059) / unregister in deinit_input. Wired via boot.kernelPatches (machine/k1/xpad-2c-charge.{patch,nix}). Agent writing + kernel-build-checking.
- **To ship:** flash controller (USB normal) + flash dongle (bootloader EP0x05) + deploy k1 (kernel rebuild) → /sys/class/power_supply/<xpad>/{status,capacity}. Full-precision battery % deferred (needs scatter/gather; 4% steps chosen).

### 2026-07-14 — Both firmwares FLASHED; dongle flash logistics

- **Controller charge mod flashed** (prior session). **Dongle charge-relay mod flashed** (this session): re-enumerates 2dc8:301c, re-probes 0x0222 ACK, alive.
- **Dongle IAP writes only img [0x6000,0xd000) (file [0:0x7000], the app region); the 40960-byte payload's tail is never touched.** The shim's original home (img 0xff44) is in that untouched tail → would have bricked (trampoline flashed, shim absent). **Relocated the shim to img 0x8350** (file 0x2350) — a 176-byte 0x00 alignment pad before img 0x8400, the only free run in the flashed region (no LE32 refs into it). Trampoline re-encoded `tjl 0x8350` (`0090499f` @0x14ba); shim body is position-independent (no pool, r4=RF ptr / r6=wire ptr from caller, pop{pc}) so it moved verbatim. Both round-trip disassembled in the modded image.
- **Dongle flash template** (`flasher/dongle-v103-flash.tmpl`, 663 reports / 630 0x03 writes) extracted from `2c-dongle-flash.pcapng`: tshark field is **`usbhid.data`** (Windows sends flash reports as HID SET_REPORT; `usb.capdata` is empty). Protocol: `c3`=erase-sector (`<addr LE32><len=0x1000>cccccccc`, CRC over params only — content-independent), `04` after each erase, 46-byte `03` writes; end-burst re-issues `c3` for sectors 0–9 (non-destructive — a stock re-flash runs the same sequence and works). Reconstruction == stock[0:0x7000] exactly.
- **Flasher fixes:** `dongle` target → `pids=[0x301c], intf=0, ep_out=0x05, ep_in=0x84` (IDLE dongle, single interface). `substitute` now allows image larger than the written extent (flashes the template's span, logs the untouched tail) — the dongle payload is 40960 but only 28672 is flashed.
- **Remaining:** deploy k1 (kernel rebuild picks up the xpad quirk) → connect controller over 2.4GHz → read /sys/class/power_supply/xpad-input*/{status,capacity}.

### 2026-07-14 (cont.) — Bootloader flash protocol reversed; brick recovery

A two-hook charge diagnostic (LED-task hook stashing `analog_read(0x88)` to a _guessed_-free RAM byte `0x847000`) crashed the app **before USB enumeration** — no `2dc8:310a`, only the resident bootloader `2dc8:3208`. Neither vendor tool recovers it: the Firmware Updater refuses on a model check (our type `0x301b` vs the only-listed 2C-BT `0x301a`), and Ultimate Software V2 can't see boot mode. Recovered by reversing the bootloader's flash protocol out of `8BitDoFirmwareUpdaterTools.dll` (native x86; Ghidra decompile) and writing `flasher/bootflash.py` (flake app `flash-2c-boot`), which re-flashed stock — read-back MATCH, controller boots.

**2C bootloader protocol** (`2dc8:3208`, HID intf 0, EP 0x05 out / 0x84 in) — entirely separate from the app `0x8105` IAP. 64-byte reports:

```
[0]=0x05  [1:3]=cmd(u16le)  [3:5]=0  [5:7]=datalen(u16le)  [7:9]=crc16(u16le)  [9:13]=param4(u32le)  [13:17]=addr(u32le)  [17:]=data
```

- cmd **5** = read (datalen=len@5, param4=len@9, addr@13; read-data at response[18], <=46 bytes/report).
- cmd **4** = erase (len@9, addr@13; datalen=0).
- cmd **3** = write (datalen@5, CRC@7, addr@13, data@17; <=46 data bytes/report).
- cmd **8** = get boot version/type (type = response[16:18]).

Response `[0]=status(0=ok) [1]=0x05 [2]=0 [4]=cmd-echo`, read-data at `[18]`. **ACK = resp[0]==0 && resp[2]==0 && resp[4]==cmd.** Write data **must** carry a **CRC-16/MODBUS** (poly 0xA001, init 0xFFFF) over the block in `[7:9]` — omit it and the device replies `resp[2]=1` (rejected) but readback stays erased. Plaintext, no signature. App flash base `0x6000` = payload offset 0; erase length rounds up to 4 KB. No finalize command needed — the bootloader boots a valid app on the next power cycle. DLL entry points: `_updateGampeWithFile`→worker `FUN_1000bd20`; command builder `FUN_100091c0`; erase `FUN_10009e70`; write `FUN_1000a040`; CRC table `[0x0000,0xA001]` @`0x101aee94`.

The dongle likely has an analogous boot mode at `2dc8:3206` (the DLL's `getBootVersion` probes it alongside `3208`); the button-less entry method is unverified.

### 2026-07-14 (cont.) — Shim build toolchain: code-as-assembly

Packaged `tc32-tools` (Telink `tc32-elf` binutils via fetchurl + patchelf) and moved every code shim off hand-encoded hex into TC32 assembly source assembled by `mkAsmMod`: `charge-{ctrl,dongle}.py` → `charge-{ctrl,dongle}.s` (trampoline + shim sections) and `bt-{ff,noop,callzero}.py` → `bt-{ff,noop,callzero}.s` (shim + `.cbslot` callback-pointer section). The single-byte/string patches (`bt-report-id`, `bt-write-noresp`, `brand`) stay inline `.py`. Byte-validated: charge + bt-noop + bt-callzero reproduce the old output exactly; bt-ff matches except its two register moves, which use the assembler's canonical `add #0` encoding (see _Shim build toolchain_ above) — inert, flags unused.

### 2026-07-14 (cont.) — SRAM map for a safe charge-stash byte (full write-up: [findings/ram-map.md](findings/ram-map.md))

Static map of the app's SRAM to replace the guessed stash byte (`0x847000`) that bricked the pad in the two-hook charge diagnostic.

- **Genuine 16 KB B80**: SRAM `0x840000–0x844000`. The SVC-mode SP-init constant in cstartup = top-of-SRAM = SRAM_SIZE; here `0x844000` ⇒ 16 KB (B80), not a 32 KB 8251. **So `0x847000` was `0x3000` ABOVE SRAM — an invalid address, not "live" RAM; the write simply faulted.** Bound every stash guess to `[0x840000, 0x844000)`.
- **Layout (cstartup @0x60b4)**: vectors+ram_code `…–0x842500` (reserved); IC-tag `0x842500–0x842600` (reserved); **unreferenced gap `0x842600–0x842e00`**; `.data 0x842e00–0x842fac`; `irq_stk 0x842fb0–0x843130` (IRQ stack, reserved); `.bss 0x843130–0x843cf0`; main stack `0x844000`↓ (~784 B headroom).
- **Candidates**: (1) mid-gap `~0x842900` — the app has no code, no pointer, and no DMA buffer in the gap; (2) dead bss `~0x843300` (in the 255 B run `0x8432b9–0x8433b7`) — definitely app RAM (zeroed), unreferenced. Prefer (2). Both confirmed unreferenced.
- **Method** (`scripts/ram-map-{trace,analyze}.py`): pool-word scan + `[reg,#off]`/`[reg,rM]` access tracer over the full disassembly. Undercounts computed-address arrays, so gaps are candidates to **verify**, not proofs.
- **Next**: non-destructive read-back diagnostic to confirm the byte is constant under load (RF/play/charge), then the two-hook stash — the LED routine runs on wake _and every plug/unplug_, so the stash self-heals, and the gate is just "nothing writes it during app runtime."

### 2026-07-15 — Normal-mode flash read, bootloader dump, dual-bank; charge-read SOLVED (full write-up: [findings/flash-read-and-bootloader.md](findings/flash-read-and-bootloader.md))

- **The app IAP reads flash in normal mode** — `cmd 0x05` (`0xe3ae`): len@report[6:8], addr@report[14:18], data@response[18:]. `flash-2c --target ctrl {read,scan}`. Flash-only (RAM aliases/garbles).
- **Dumped the resident bootloader over USB** — no SWS rig, contradicting the earlier "SWS-only" conclusion. `dumps/2c-bootloader-v109.bin`.
- **512 KB flash is DUAL-BANK**: app bank A `0x6000` (== vendor `.dat`) + bank B `0x40000`; app-flash writes the _inactive_ bank and the bootloader swaps → a bad app-flash bricks by activating the crashing bank. Also: bootloader `0x0–0x5000`, config/MAC/cal `0x73000–0x7f000`. No hidden FW.
- **The app's PM/LED cluster (`0x70b4` etc.) is DEAD** — the bootloader runs its own byte-identical copy (`0x276e`, own analog fns `0x2444`/`0x2484`). Hooking `0x70b4` = hooking dead code; abandons the two-hook stash.
- **Charge-read recipe:** the read was stuck because the charge routine powers the LPC (`0x81 |= 0x40`), reads, then **powers it off** (`0x81 &= 0xbf`) on exit. Fix (inline, safe scanner hook): arm `0x81 |= 0x40`, settle ≥30, `analog_read(0x88)`, test **bit5** (= VBUS/on-external-power; bit6 unused). Reference `0x82 = 0x65` (NOT `0x85`=sleep) + `0x34 = 0x80` already persist from app init. Implemented in `patches/charge-inline-ctrl.s`.
- **Scanner timing:** the hook site `FUN_0000c7a4` is gated by `reg_system_tick 0x800740` at an 80000-tick threshold in `FUN_0000d234@0xa438` ⇒ **~5 ms / ~200 Hz** (16 MHz timer), thread context (not IRQ). The shim's arm+settle+read (~40-50 µs) is <1% of the 5 ms budget and consistent with the scanner's existing blocking column-settle delays.

### 2026-07-15 (cont.) — Dongle bricked by a mis-targeted flash, fully recovered (full write-up: [findings/dongle-recovery-and-anti-clone.md](findings/dongle-recovery-and-anti-clone.md))

- **Root cause:** `--target ctrl` selects USB `0x310a`; a controller on 2.4 GHz makes the _dongle_ enumerate as `0x310a` (relaying), so a `--target ctrl` app-flash while wireless wrote the dongle with controller FW → bricked into the bootloader (`0x3208`). Guard added (`flash2c.py` `_device_kind`/`_payload_kind`): reads the target's own flash and refuses a firmware/device mismatch; `--force` overrides.
- **Dongle is a 128 KB part** (reads alias above `0x20000`), separate from the 512 KB controller. Dual-bank: bank A `0x6000`, bank B `0x13000` (`==` A on stock), descriptor `0x12000`, cal `0x1e000`, anti-clone signature `0x1f000`.
- **Boot gate = `0x1f000`:** the bootloader reads the flash chip's HW unique ID (SPI `0x4B`), folds it → `B`, and requires the 12-byte record to equal `T[nibbles(B)]`. Blank/wrong → stuck in bootloader. `0x1e000` cal does _not_ gate boot (blank → default trim). The signature is silicon-bound, not assignable, and not a MAC.
- **`B` is exposed over USB:** `flash-2c --target boot read 0x80000002 6` (boot-read sub-command 6, magic `0x80000002`). Record = `LE32(T[n0]^T[n3]) ++ LE32(T[n4]^T[n1]) ++ LE32(T[n5]^T[n2])`, `n=B&0xF`; 16-entry `T` in the findings doc. Verified against all four sampled units.
- **Recovery:** boot-flash `dumps/2c-dongle-reference-v103.bin` (per-device sectors blank; A==B and the descriptor are version-generic — crcB `0x1e05` for v1.03, `0x3845` for v1.00), read `B`, compute + write the record at `0x1f000`, leave `0x1e000` blank. Booted (`0x301c`) and the paired controller reconnected without re-pairing.
- **Recovered dongle runs on default RF cal** — its own `0x1e000` trim was overwritten and is unrecoverable (chip-specific, not stored on the controller). Watch range/stability.

### 2026-07-15 (cont.) — Charge/VBUS status: no RF-safe inline read (full write-up: [findings/charge-status-investigation.md](findings/charge-status-investigation.md))

- **`0x88` bit5 is the BATTERY comparator, not VBUS.** The "charge" routine `@0x276e`/`@0x70b4` is a successive-approximation battery ADC (`reg 0x01` = threshold DAC ramped `0x4e→0x4b`, read `0x88` bit5). The earlier "bit5 = VBUS" recipe read the wrong signal — that's why it was stuck. Diagnostic confirmed arm (`0x81.b6`) + reference (`0x82.b6`) writes **do** land at scan time; `0x88` just carries battery.
- **Charging is a separate bootloader measurement `@0x2A68`** (SAR-style: config + `0x27fc` convert pulse + helpers `0x2854`/`0x2750`/`0x29c0`/`0x2c78`; status gates `0x7e.b0`, `0x44.b0/b2`; counter `0x40-0x43`; latched to RAM `0x843B98` for the LED). **RF-hostile:** it rewrites the system-tick timer (`0x740`), DMA regs (`0xc40-0xc4a`), and the clock tree (`0x60-0x66`), dispatches through bootloader-RAM fn-ptr `0x843C90` (app doesn't install it → crash), and reboots on out-of-range (`0x6f=0x20`).
- **Bench-confirmed dead ends:** cold reads of `0x7e`/`0x44`/`0x800602.b4` don't track the charger; the minimal analog-config-only subset (`charge-diag3`) **crashed the controller** (the low analog regs `0x00`/`0x02`/`0x06`/`0x0b` gate clock/core). Controller recovered via boot-flash of stock `ctrl-v109`.
- **Conclusion:** no software path reads charging without disturbing the 2.4 GHz link. Paths forward: (1) hardware — charger STAT/VBUS → spare GPIO the app polls (recommended); (2) firmware — cooperative measurement saving/restoring RF state (hard); (3) host-side battery-trend inference (hacky). Decision pending.
- Diagnostics: `patches/charge-diag{,2,3}-ctrl.s` (wired in the flake as `mod-charge-diag{,2,3}-ctrl-v109`).

### 2026-07-15 (cont.) — L4/R4/Square paddles + unscaled 0-100 battery over 2.4 GHz (PROVEN end-to-end)

- **Paddles are dongle-only.** Stock firmware scans L4/R4/Square into button-word bits 25/26/27 = `RF[6]` bits 1/2/3, which the stock dongle drops when building XInput. A dongle relay recovers them — **no controller shim needed for paddles**. Star (bit 28) is a hardcoded turbo the controller never broadcasts, so it's unreachable.
- **Battery needs a controller shim** (`battery-ctrl.s`) — stock never computes it into the word. Writes the raw 0-100 byte (RAM `0x842e04`) into spare bits: low-5 → word 19-23, high-2 → word 29-30.
- **Combined relay `batt-l4r4-dongle.s`:** `report[18] = (RF[5]>>3) | (RF[6] & 0x60)` = 7-bit battery; `report[19] = RF[6] & 0x0e` = R4(25)/L4(26)/Square(27). **Gotcha:** the builder writes report[18] then report[19] as consecutive stores (`0x74ba`, `0x74be`); hooking report[18]'s store leaves report[19]'s `=0x10` store to clobber ours — so hook the **report[19] store (`0x74be`)** instead. report[18]'s zero-store runs first and the shim overwrites it. One hook writes both bytes.
- **Host driver (`machine/k1/xpad-2c-charge.patch`):** `CAPACITY = report[18] & 0x7f` (unscaled 0-100); `report[19]` bit1→`BTN_GRIPR` (R4), bit2→`BTN_GRIPL` (L4), bit3→`BTN_TRIGGER_HAPPY1` (Square); capabilities under `MAP_2C_RELAY`. The dead charge-STATUS property is gone (VBUS unreadable — see [findings/charge-status-investigation.md](findings/charge-status-investigation.md)).
- **Verified:** battery 99% at `/sys/class/power_supply/xpad-*/capacity`; L4=548 (`BTN_GRIPL`), R4=549 (`BTN_GRIPR`), Square=704 (`BTN_TRIGGER_HAPPY1`) in evtest. evtest prints `(?)` for 548/549 (its label table lacks the grip codes) — cosmetic; Steam/SDL match by numeric code.
- **Pending:** fleet rollout (flash `battery-ctrl` to each controller + `batt-l4r4-dongle` to each dongle).

### 2026-07-16 — Tooling cleanup (#138)

- **Pruned the experiments.** Removed the superseded/diagnostic/dead-end shims (`charge-*`, `l4r4-{probe,dongle}`, `ramcheck`, `noop-passthrough`, `setbits`, `bt-*`), the SRAM-map scripts, and the `charge-probe` reader. The flake `mods` are now just `battery-ctrl-v109` + `batt-l4r4-dongle-v103`; the Ghidra pipeline (`scripts/*.java` + `symbolicate.py`) stays.
- **Templates → a real test.** `*-flash.tmpl` moved `flasher/` → `test/`; `gen --template` now exits non-zero on mismatch; wired as `checks.flash-template-{ctrl,dongle}`, so `nix flake check` gates the generator against the vendor stream.
- **Brand folded into production.** `brand.py` rewritten to swap `Ultimate`→`Ultima+e` across every instance (ASCII + UTF-16LE), applied by the controller mod so a flashed pad is visibly distinct. The dongle isn't branded — its product strings all sit above the `0x7000` app-IAP write window, so a brand patch there never flashes.
- **Host patch renamed.** `machine/k1/xpad-2c-charge.patch`: `MAP_CHARGE_STATUS`→`MAP_2C_RELAY` and the `charge*` power-supply symbols → battery names (behaviour unchanged; the dead charge-STATUS decode was already gone).
