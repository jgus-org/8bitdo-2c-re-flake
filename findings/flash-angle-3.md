# Flash Angle 3 — Telink SWS Hardware Flashing (bypass the vendor updater)

Direct programming of the 2C's Telink MCU over its native debug/programming bus (SWS / SWire), bypassing the USB-HID IAP updater entirely. This is the hardware fallback: it needs physical PCB access but is not gated by anything the vendor firmware does over USB.

---

## 1. What is established

### The chip

- The 2C pad + dongle both carry a **Telink B80**. **B80 is Telink's product/module name for the TLSR8232 (TLSR823x series)**: tc32 core, 16 KB SRAM (0x840000–0x844000), 512 KB flash, BLE + 2.4 GHz + USB. `B80 BLE Single Connection SDK` is the matching SDK. **Confidence: HIGH** that B80 == TLSR8232-class. (The task brief labels it "TLSR825x-class" — same SWS bus and tool family, but the addressing width and analog-register map differ from true 825x; see §4.)
- Whole TLSR82xx family (8232/823x, 825x, 826x, 8271, 8258/B85 …) is programmed over the **same SWS / SWire single-wire bus**. This is why the pad, dongle, Xiaomi thermometers, and 8BitDo numpad are all reachable with the _same_ open-source tools. **Confidence: HIGH.**

### SWS can do everything we need

- **Full-flash READ, including the bootloader below 0x6000.** SWS drives the on-die MSPI flash controller directly at the byte level; it is address-agnostic and does not care about the fwupd "ebitdo" container. A dump reads `0x000000 … flash_end`, recovering the boot/loader region that the fwupd image never contains. **This is the single biggest advantage of the hardware route.** **Confidence: HIGH.**
- **Arbitrary flash WRITE (sector-erase + program).** `we`/`wf` write a raw payload to any address. To install a modified app you write the **raw Telink payload straight to 0x6000** and leave the bootloader intact. The ebitdo 28-byte header and its per-file checksum are irrelevant on this path — there is no updater in the loop to validate them, and (per the dongle RE) no cryptographic signature check exists anyway. **Confidence: HIGH** that SWS write works on an unlocked part; **MEDIUM** on whether the retail 2C part is unlocked (see §4).

### The 8BitDo IAP corroboration (cross-check, not this angle)

- An independent teardown of the **8BitDo Retro 18 Numpad (Telink TLSR8271)** documented the USB-HID updater protocol: **2-byte prefix `0x8105`, command byte, params, length, big-endian address, 46-byte payload**; commands **session-start `0x00`, data-write `0x03`, block-write `0x04`, finish `0x07`**. This is a byte-for-byte match to the dongle IAP handler in our RE (`writefirmware`, `saveCodeBlock`, `boot_wirteFlash`, `"pbufferLength > 46"`). Strong evidence the 8BitDo IAP is a shared house protocol. **Confidence: HIGH.**
- **Discrepancy to flag:** that author _speculated_ the firmware was AES-128-CCM encrypted, based purely on the chip's advertised capability, and could not confirm it. Our 2C RE has **confirmed plaintext**. The "encrypted" claim in that blog is capability, not observed fact — do not let it contradict our finding. **Confidence: HIGH.**

---

## 2. Exact protocol, pinout, command detail

### SWS bus (from hacst.net RE + pvvx/DeepWiki)

- Single wire, half-duplex, idles HIGH via pull-up. Self-clocking, **5 time units per bit**:
  - bit **0** = 1 unit LOW + 4 units HIGH
  - bit **1** = 4 units LOW + 1 unit HIGH
- Transaction framing:
  ```
  START(0x5A) → ADDR(2–3 bytes, MSB first) → RW_ID → DATA… → END(0xFF)
  ```
  - START byte = master cmd-bit set, value `0x5A`; END byte = `0xFF`.
  - **RW_ID**: bit7 = 1 read / 0 write (`0x80` read, `0x00` write); bits6-0 = slave id.
  - Master byte = CMD-bit(1)+8 data bits+end unit; slave byte = 8 data bits+end unit (master pulses 1 unit to clock each slave byte out).
- Speed: up to ~2 Mbit/s; pvvx runs ~0.96 Mbit/s (~208 ns/unit).
- **Flash read path**: registers `0x0D` reg_mspi_ctrl (CS + read-mode), `0x0C` reg_mspi_data, `0xB3` reg_swire_id (bit7 = FIFO auto-read). Sequence: CS-low → SPI cmd `0x03` + 24-bit addr → enable FIFO auto-read → repeated reads of data reg → disable FIFO → CS-high. **Confidence: HIGH** (measured on the wire).

### "Activation" — seizing a running chip (the crucial one for a locked/booting part)

- After power/reset, the tool **immediately sends a CPU-STOP command over SWire to halt the core before its firmware runs.** This is what pvvx calls _Activation_ (`--tact`, default 600 ms window; TLSRPGM `-a`). CPU control verbs: **stop, stall, run, go, soft-reset (mrst)**.
- **Gotcha (verified):** the _stall_ command can partially wake the MCU, which then fetches its own code from the same flash being dumped and corrupts the SWire read. Use full **CPU-stop**, not stall, when dumping flash.

### Open-source programmers (all pvvx unless noted) — URLs

- **TlsrComProg825x** / **TlsrComSwireWriter** — pure **USB-serial bit-bang** SWire, no extra MCU. Loads a small **SRAM stub over SWire, then runs the stub** to do flash I/O. Wiring:
  - `TX → SWS` (series ~1 kΩ recommended by community; not stated in README)
  - `GND → −Vbat`, `+3.3 V → +Vbat`
  - `RTS → RESET` (or, on modules with no reset pin, RTS powers the module so it can be power-cycled)
  - Commands: `rf` read-flash-to-file, `wf`/`we` write (±sector-erase), `es` erase-region, `ea` erase-all, `fsr`/`fsw` flash-status-reg.
  - Baud: TlsrComSwireWriter 921600 (min 340000); TlsrComProg default 230400.
  - Example: `python TlsrComProg.py -p COM10 rf 0 0x80000 dump.bin` / `… -t 600 we 0 mod.bin`
  - **Adapter caveats (verified):** does **NOT** work on **FTDI** adapters, nor on adapters with an **LED on the RX line**. Use CH340 / PL2303 / CP210x.
  - **TlsrComProg825x README explicitly limits itself to TLSR8251/8253/8258** stubs; for a B80/8232 you either use the SWireWriter, the STM32/Telink programmers below, or a stub built for 823x. **Confidence: MEDIUM** that an off-the-shelf stub covers 8232 unmodified.
- **TLSRPGM** (https://github.com/pvvx/TLSRPGM) — a faster/robust programmer, but it **runs the SWire master on a Telink module** (TB-03F/TB-04 = TLSR8253 + USB-COM, or TLSR8269 direct-USB), **not on an ESP**. Pins on the _programmer_ side: `PD3→RESET`, `PD4(SWM)↔SWS`, `PB4→Power(≤16 mA)`. Rich CPU/reg/flash command set; supports 2-byte (826x/823x, `-u`) vs 3-byte (825x) SWire addresses. _(Correction to the task brief: pvvx's flasher is Telink-hosted, not ESP8266/ESP32; ESP-hosted SWS bit-bangers exist in the wild but are separate, less-maintained forks.)_
- **TlsrTools825x / SWireSTM32** — SWire master on an **STM32 "Blue Pill"** + Windows GUI. Good when you want a dedicated, reliable master rather than raw UART bit-bang.
- **Telink BDT (Burning & Debugging Tool) + EVK** — the _official_ vendor programmer/debugger; the ground-truth reference for SWS. Windows-only, closed, but authoritative for chip-ID and the analog-register map.

---

## 3. Read-protection / SWS-lock — how to tell if the 2C is locked

Two very different lock mechanisms exist; which applies depends on the chip generation:

- **True hardware "Secure Debug" (eFuse).** Documented for the **TLSR9-series** (952x/922x): a 32-bit _Interface functions_ eFuse with **bit15 `if_sws_disable`, bit14 `if_jtag_disable`**; re-enable requires an **AES-128-derived Debug Key** (Root Key + Debug Plaintext, burned via BDT Secure Boot Tool). If this were set, SWS is _cryptographically_ dead. **This is a 9-series feature; a B80/8232-class 2C is very unlikely to have it.** **Confidence: MEDIUM-HIGH** that it does not apply here.
- **Firmware-based SWS disable (the realistic case for 82xx).** On older TLSR82xx there is no eFuse secure-debug; "protection" is the _firmware itself reassigning/disabling the SWS GPIO early in boot_ so the pad stops responding once the app runs. **The pvvx Activation race defeats exactly this**: reset → grab the bus with CPU-stop in the first few ms, before the app's init code runs. **Confidence: MEDIUM-HIGH** that any 82xx "lock" is firmware-based and thus race-defeatable; **UNKNOWN** whether 8BitDo's firmware even bothers to disable SWS.
- **Flash-level write protection** (flash status register block-protect bits) is independent and clearable with `fsw` before writing.

**Detection procedure (non-destructive, read-only):**

1. Wire SWS + reset + power, run the tool with activation, request **chip-ID / analog registers**. A correct, stable chip-ID = SWS is alive and the part is not hard-locked.
2. Attempt a small **flash read at 0x6000**. If it returns the plausible app bytes we already know from the fwupd image → fully readable, unlocked. If SWS refuses to ACK, or flash reads back uniform `0x00`/`0xFF`, suspect a firmware SWS-disable (retry with a tighter reset-to-stop window / power-cycle activation) or, far less likely, an eFuse lock.

---

## 4. Open questions

1. **Does a retail 2C PCB expose a probe-able SWS pad?** SWS needs only ONE signal net (the chip's SWS/SWM GPIO) + GND + 3V3 + ideally RESET. 8BitDo has been seen to route debug to pads but leave them _unpopulated_ (the numpad's **unpopulated 10-pin J22** with exposed test points). General Telink consumer-board teardowns (M6 band, FocusFit smartwatch, Xiaomi thermometers) routinely find usable SWS pads and dump/flash them with pvvx tools. **Assessment: MEDIUM-HIGH likelihood** a usable SWS test point exists on the 2C, even if unlabeled — worst case it is probed directly at the chip's SWS pin.
2. **Which pin is SWS on the B80/8232 package?** Need the TLSR8232 datasheet pinout to map SWS/SWM to a physical pad/pin, then continuity-trace to a test point. (Datasheet: wiki.telink-semi.cn `DS_TLSR8232-E`.)
3. **Is a ready 823x SRAM stub available**, or must one be built (SWireWriter stub vs TlsrComProg's 825x-only stubs)? Addressing is 2-byte for 823x (`-u`).
4. **Does the 2C firmware actually disable SWS at boot?** Only bench testing (step 1 above) answers this.
5. **Embedded vs external flash** on the 2C: 8232 is "embedded flash or OTP." If OTP rather than re-writable flash, WRITE is impossible and only READ works — needs confirmation from the dump/erase test. **Confidence the 2C uses re-writable flash: MEDIUM-HIGH** (it ships with field firmware updates, which implies rewritable flash, not OTP).

---

## 5. Single most useful next action

**Bench-bring-up on one sacrificial 2C: read-only first.** Identify the B80/TLSR8232 SWS pin from the datasheet pinout, continuity-trace it to a test pad, and wire a **non-FTDI** USB-serial adapter (CH340/CP210x): `TX→SWS` (~1 kΩ series), `RTS→RESET`, `GND`, `3V3`. Run `TlsrComProg`/`TlsrComSwireWriter` with activation and attempt, in order: (a) **chip-ID read** (confirms SWS is live + not hard-locked), then (b) a **full flash dump 0x000000–0x080000**. Success delivers the two things the USB-IAP path cannot: proof the part is unlocked/writable, and the **sub-0x6000 bootloader** we currently don't have. Only after a clean read do we attempt a write of the modified image to 0x6000. This one experiment resolves open questions 1, 4, and 5 at once and gates the entire hardware angle.
