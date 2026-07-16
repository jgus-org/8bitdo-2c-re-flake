# 8BitDo Ultimate 2C — firmware RE: decision-grade synthesis

Controller `ctrl-v109` (Telink B80/TC32, app payload base 0x6000, len 74752, ends 0x18400) + 2.4GHz dongle `dongle-v103` (base 0x6000). All addresses are IMAGE addresses; controller file-offset = img − 0x6000, and the vendor-distributed controller file additionally prepends a 28-byte (0x1C) ebitdo header. TC32 opcode bytes are NOT ARM-Thumb. Every claim below survived independent adversarial re-tracing; downgrades/refutations are flagged explicitly.

---

## BOTTOM LINE (6 lines)
1. **Charging sense is in the app** (`analog_read(0x88) & bit5` @FUN_00007138); the **power-OFF decision + its "am I charging" gate are NOT** — they live in the resident bootloader (0x0–0x5FFF, not in our image), so the "won't power off while charging / wakes on a dumb charger" behavior is **not fixable via the USB-flashable app**; only SWS reaches it.
2. **BT inherits the same charge/power gate** — power mgmt runs in the transport-agnostic main loop (0xa430–0xa48c); radio mode only swaps the live stack. [INFERRED, med]
3. **L4/R4 vanish over 2.4GHz at the DONGLE**: `FUN_0000733c` maps only button-word bits {0–13,17} and silently drops the upper block {16,18,25,26,27,28}; the controller packs the full word. Cleanest fix is a dongle-side OR-map — **conditional on the (unproven) assumption that the RF frame actually carries those bits.**
4. **BT force-feedback is declared-but-dead (case ii)**: the BLE HID map declares a rumble output report and a writable characteristic exists (buffer 0x84315c), but its ATT write-callback is NULL and no code ever reads the buffer. The motor back end is fully intact; the fix is one BLE→`FUN_0000fa68` hop.
5. **Flashing is feasible, CRC-only, no signature, no encryption.** The **dongle** IAP is fully reversed incl. the CRC (CRC-16/MODBUS). The **controller** gate is inferred-similar but its bootloader isn't in our dump, so the controller CRC recipe is **still un-extracted** — one usbmon capture closes it.
6. **Get an SWS single-wire rig on a sacrificial unit first.** It is the only full-flash backup, the only un-brick path, and the only route to the bootloader-resident power gate of goal 1.

---

## GOAL 1 — charging==on logic, patchability, firmware-vs-hardware power-ON split

**ANSWER.** The controller detects "charging/VBUS present" by reading analog register 0x88 and testing **bit5 (mask 0x20)** inside the charge-indicator loop **FUN_00007138 @0x7102–0x710c**: `analog_read(0x88)` (0x7102 `tmovs r0,0x88` → 0x7104 `tjl 0x6d84`), then `tnand`(BIC) with 0x20 @0x710a and `tjne 0x7154` @0x710c. **Polarity (traced both paths):** bit5 SET → fall through to the charge-LED ramp; bit5 CLEAR → 0x7154 disables the comparator (`analog_write(0x81, val&0xbf)`) and returns. This is the **only** genuine analog-0x88 read in the image (the second `tmovs r0,0x88` @0xb0e4 calls 0xfaf4 = ADC channel-select, a false positive). USB DP/DM GPIO (PA1/PA2) and ADC-VBAT are **not** used for charge sense.

**Sleep/power-off primitive.** The single sleep trigger is `*reg_pwdn_ctrl(0x80006f) = 0x81` (bit7 SLEEP + bit0) @0x6026 inside the primitive **@0x6020**, called from exactly one site (0x7234) inside the suspend routine **@0x7210** (which arms pre-sleep analog regs, sleeps, then on-wake shows the charge LED). Reboot = `*reg_pwdn_ctrl = 0x20` @0x716a. `poolregs` shows 0x80006f referenced exactly 2× (these two writes); `tjl 0x6020` appears once.

**Where the gate lives.** The suspend root 0x7210 has **zero in-image callers** (full-listing grep for a call/branch to 0x7210 = 0). `reg_wakeup_en 0x6e` is **never written in-image** (absent from `poolregs`). Best explanation: the whole PM cluster (0x6020/0x70b4/0x7160/0x7174/0x7210) is a **callback invoked from the resident bootloader**, which also arms the VBUS/LPC deep-sleep wake source. So a power-off suspend on the battery rail is immediately re-woken while VBUS is present → the pad appears not to turn off, and a dumb charger cold-wakes it.

**CONFIDENCE.**
- Charge-sense *mechanism* (reads 0x88, gates charge-LED on bit5): **VERIFIED, high**.
- **[DOWNGRADED]** The *identity* "bit5 = the low-power comparator = 5V/VBUS present" is **INFERRED, low-med** and **conflicts with register-map.md**, which documents the LPC result at **bit6 (0x40)**, not bit5. Either the pvvx-8258-sourced map has the wrong bit for the B80, or 0x88/bit5 is a different status than the documented LPC result. What is certain: the firmware branches its charge-LED loop on 0x88 bit5.
- Sleep=`0x81`@0x6026 / reboot=`0x20`@0x716a / single sleep call site: **VERIFIED, high**.
- "No direct caller of suspend root 0x7210": **VERIFIED**. "Therefore bootloader-resident / bootloader arms the wake": **INFERRED, med** (the exhaustive pointer search behind it was not independently reproducible; an indirect dispatch through a function-pointer word cannot be excluded from text artifacts alone).
- `reg_wakeup_en 0x6e` never written in-image: **VERIFIED** (strong: SDK register writes are pool-based).

**Firmware-vs-hardware split on power-ON.** Partly firmware but **not from the app image**, and a pure-hardware contribution cannot be excluded. A battery pad's "off" is suspend/deep-sleep on the battery rail, so a dumb-charger wake needs an *armed* analog (LPC/VBUS) wake source — that's firmware, but **bootloader-side**, hence not in the app payload. A board LDO/POR that cold-boots the MCU whenever VBUS appears would be pure hardware and not firmware-preventable at all. **[INFERRED, med]** Distinguishing the two needs a bench trace: does MCU VDD collapse when the pad is "off"? If yes → firmware/bootloader wake-arm; if VDD stays up → hardware.

**PATCH / NEXT STEP.**
- **Patch 1 (safe, in-app, but does NOT achieve the goal alone):** turn the charge-sense branch unconditional — `tjne 0x7154` → `B.n 0x7154`, i.e. halfword 0xC122 → 0x8722 (same target). **Payload offset 0x110d `0xc1→0x87`; on the vendor file with the 28-byte header this is on-disk offset 0x1129.** Effect: always takes the "not charging" path, killing the charge LED. VERIFIED encoding/effect/in-region. It does **not** defeat the bootloader power gate.
- **Decisive fix (goal 1 proper):** patch the power-off decision + wake-arm in the **bootloader (0x0–0x5FFF)**, reachable **only via hardware SWS**, not the USB IAP (which only writes the app region — and on the dongle is even clamped to the staging bank; see goal 5).
- **First experiment:** SWS full-flash dump of a sacrificial unit → disassemble the sub-0x6000 bootloader → locate the `reg_wakeup_en 0x6e` write and the charge-gated branch. Also do the VDD-collapse bench measurement to settle the hardware-vs-firmware question before any bootloader edit.

**UNVERIFIED.** The physical meaning of 0x88 bit5 (vs the documented LPC bit6); the bootloader-callback inference for the PM cluster; the exact bootloader branch/register that implements "stay awake while charging"; whether a hardware LDO independently cold-boots on VBUS.

**[REFUTED sub-recipe]** The originally-proposed "Patch 2" (disarm the LPC reference by NOP-ing the two `tmovs` at 0x7226/0x7228) is **defective as written** — it leaves the `tjl 0x6dc4` call at 0x722a live, which then calls `analog_write` with stale r0/r1 and writes an *unintended* analog register. To actually drop that write you must also NOP 0x722a. (Efficacy is uncertain regardless, since the true wake-enable is bootloader-side.)

---

## GOAL 2 — does Bluetooth mode have the same power gate?

**ANSWER.** Structurally **yes**. The rumble applier `FUN_0000faa0` (@0xa43c), the mode getter `FUN_0000d7c8` (@0xa44c, gating the 0xa448–0xa452 branch), and the 2.4GHz dispatcher `FUN_0000a328` (@0xa49e) all live in a **single shared main-loop body 0xa430–0xa48c** that is not duplicated per transport; the mode byte at SRAM **0x843470** only selects the rumble-intensity curve and a couple of minor branches. Power management runs in that same shared loop, so BT inherits the same charge behavior — and per goal 1 the actual gate is bootloader-side and therefore mode-independent anyway.

**CONFIDENCE.** Shared-loop structure: **VERIFIED**. "BT inherits the charge gate": **INFERRED, ~0.7** — the specific "won't power off while charging" branch was not traced from the BT path, and the 0x843470 value→mode (2.4G/BT/wired) mapping is **unresolved**.

**PATCH / NEXT STEP.** None specific to BT — fixing goal 1 (bootloader) fixes all modes at once. To close the inference, decode the 0x843470 writers (0xd5xx–0xd8xx connection/state block) to nail the value→mode map, and trace the charge-gated branch from a BT-connected state.

**UNVERIFIED.** The 0x843470→mode mapping; that the charge/stay-awake branch is literally the same instructions under BT.

---

## GOAL 3 — the four extra buttons (SQUARE/STAR/L4/R4) + remap options

**ANSWER — scan.** Buttons are a **driven-column / sampled-row keypad matrix**, not one-GPIO-per-button. Scanner **FUN_0000c7a4 @0xc7a4** drives 4 columns (`FUN_0000c288`/`FUN_0000c324`) with a settle delay, reads 5 rows each via **FUN_0000c33c @0xc33c** — rows **PA5/PA6/PA7** (`reg_gpio_pa_in 0x800500`) + **PC1/PC3** (`reg_gpio_pc_in 0x800510`) — plus **PA4 read directly @0xc8ce → word bit17**. It assembles a button word using bit set **{0–13, 16, 17, 18, 25, 26, 27, 28}** (bits 14,15 and 19–24,29–31 unused). Standard 15-button set = {0–13,17}; extra block = {16,18,25,26,27,28}. **PD0** (`reg_gpio_pd_in 0x800518` bit0) is a separate hard-wired system button (power/pair/home), outside the matrix.

**ANSWER — why L4/R4 are BT-only.** All three controller packers (0xf0b0 / 0xf158 / 0xf238) copy the **full 4-byte button word** into the report — the controller drops nothing. The loss is at the **dongle**: `FUN_0000733c @0x733c` folds only source bits **{0–13} (via shift-sign tests) plus bit17** (bit17 → autofire output 0x400 via counter at RAM 0x74e0) into the 16-bit USB button field, and **never references {14,15,16,18,25,26,27,28}**. So any button in the upper block is received-but-dropped over 2.4GHz. In BT there is no dongle, and the controller's own BLE HID map governs exposure — so those buttons can appear over BT.

**ANSWER — what SQUARE/STAR do.** Upper-block bits are consumed by **local handlers**, so they never emit as buttons in either transport: **bit18** = hold-counter handler @0xd10c (mask 0x40000, saturates ~24 ticks → fires) = hold-to-program/profile; **bit28** tested @0xcd7a/0xd152; **bit17/PA4** hold handler @0xd0b0. These are the program/turbo mechanism.

**CONFIDENCE.**
- Matrix scanner + pins + bit set: **VERIFIED, high**.
- Dongle maps only {0–13,17}, drops {16,18,25,26,27,28}: **VERIFIED, high (decisive)**.
- All three controller packers send the full word: **VERIFIED**, with a **scope caveat**: these are the **wired/USB** packers. They prove the *wired* report carries every bit; they do **not** prove the **2.4GHz RF frame** does — the RF/BLE TX packer is in the closed SDK region and was not verified.
- Bits 18 & 28 locally consumed (program/turbo): **VERIFIED referenced**; the names are **INFERRED** (stripped image).

**[REFUTED / COLLAPSED]**
- The absolute SRAM address for the button word — the report's **0x84342c is wrong**; the scanner's store pointers (pool @0xc938/0xc93c) decode to **≈0x0004942C** (mirror +0x20 = 0x0004944C). Non-load-bearing, but correct the address if you touch it.
- **Bits 25/26/27 are ALSO locally consumed** — a remap handler @0xccc4…0xcd16 tests them (`<<6/<<5/<<4`) and does key-remap stores. So the report's clean split "L4/R4 = handler-free bits {16,25,26,27}" **fails for 25/26/27**; only **bit16** had no local handler found. **⇒ The exact L4/R4 bit indices are materially uncertain and need one captured RF/BLE frame to pin down.** [INFERRED, med → downgraded]

**PATCH / NEXT STEP (remap).** For BT, L4/R4 are already governed by the controller's own HID map (should already be visible). To recover them over **2.4GHz**:
- **Option A (dongle-side, preferred IF the premise holds):** add OR-map blocks in `FUN_0000733c` routing the L4/R4 source bits to free USB button bits. The 16-bit field has spare bits (output bits 0x800/0x8000 appear unused, contra "XInput has no spare"). **Premise to verify first — UNPROVEN:** that the 2.4GHz RF frame actually *carries* bits {16,18,25–28}. The dongle only ever reads bits {0–13,17} of `param_3`; nothing proves the controller's RF TX packer transmits the upper bytes. If it sends fewer bytes, a dongle-only patch cannot recover L4/R4 and a **controller** change is also required.
- **Option C (size-neutral alias):** single OR-immediate edit in `FUN_0000733c` so L4/R4 alias an existing/rare button — trivial, XInput-safe — still gated on the same RF-carries-the-bits premise.
- **Option B (repurpose SQUARE/STAR):** NOP the local consumers and redirect their OR target to a dongle-mapped bit, then add to the dongle map. Higher risk (loses program/turbo/remap). **Note:** the report's cited NOP site **0xd0fc is a pool literal** (the mirror-global pointer 0x0004944C), not an instruction — editing there corrupts the pointer; the real bit18 consumer is **0xd10c+**.
- **First experiment:** capture one live 2.4GHz RF frame (or BLE input report) with L4/R4/SQUARE/STAR pressed to (a) confirm the RF payload carries the upper bits and (b) resolve the exact bit→button assignment. This single capture de-risks Options A/C and pins the names.

**UNVERIFIED.** Button *names* (stripped); exact L4/R4 vs 25/26/27 mapping; whether the 2.4GHz RF frame carries the upper block; the closed-SDK BLE-notify packer contents.

---

## GOAL 4 — BT force-feedback patchability

**ANSWER.** The FF back end is **fully intact and transport-neutral**: motor driver **FUN_0000f93c @0xf93c** scales strength 0–100 → PWM duty and writes **PWM4 (`reg_pwm4 0x8007a4`)** and **PWM5 (`reg_pwm5 0x8007a8`)**, period 10000 (pool `0xfa04=0x27100000`); enabled by **FUN_0000fa10** via `reg_pwm_enable 0x800780` bits 4/5 (`reg_pwm_clk 0x800782 = 0x17`); PWM0 (`0x800794`) = LED. The setter **FUN_0000fa68 @0xfa68** stashes motorA/B/duration into RAM globals **0x8434ef / 0x8434f0 / 0x8434f1**; the applier **FUN_0000faa0 @0xfaa0** drives both motors every shared-main-loop pass (@0xa43c). The complete 11-caller set of `fa68` is: notification buzzes (0xa0f8, 0xdaa8), disconnect-stop (0xa4ae), pairing/startup SM (0xcf00 block), **2.4GHz RF parser FUN_0000dc58** (0xdce6), **USB parsers FUN_0000eabc** (0xeaf4) **and FUN_0000f684** (0xf6a8). **No BLE/ATT handler is among them.**

BT mode uses a **different** HID report map @0x1734c that **does** declare a rumble OUTPUT report — **Report ID 5, PID usage page 0x0F, 4×u8 (0–100)**, bytes @0x173af `05 0f 09 70 85 05 15 00 25 64 75 08 95 04 91 02 c0` (it is the value of the 0x2A4B Report-Map attribute, attrLen 116). The BLE GATT service **does** expose a writable output-report characteristic — ATT entry @0x17754, uuid 0x2A4D, buffer RAM **0x84315c**. **But** its ATT write-callback field @0x17764 is **NULL (0x00000000)**, and the LE pointer 0x84315c occurs **exactly once** in the whole image (the table's own val* field) with **zero code xrefs**. So host rumble writes land in RAM and are **silently dropped**.

**⇒ BT FF = case (ii): declared AND a writable characteristic exists, but no handler is installed and the bytes are never consumed.** (Robust doubly: even setting aside the null-callback question, no `fa68` caller is BLE.)

**CONFIDENCE.** Motor chain (f93c/fa68/faa0/fa10 → PWM4/5): **VERIFIED, ~0.9**. All rumble funnels through fa68 with no BLE caller: **VERIFIED (airtight)**. BT map declares the rumble output report: **VERIFIED byte-for-byte**. Writable characteristic with NULL callback, buffer unread: **VERIFIED**. Case (ii): **VERIFIED**.

**[CORRECTIONS — do not change the verdict]** attrLen = **1**, not 4 (at most 1 byte lands in 0x84315c via the SDK default path, not 4); "props 0x0E" is the **characteristic-declaration** property byte @0x17330 — the value attribute's ATT permission is **0x03** (READ|WRITE). The duration byte 0x8434f1 is also written by `faa0` (decrement), so "written only in fa68" holds only for the two intensity bytes.

**PATCH / NEXT STEP.** Only the BLE→`fa68` hop is missing; everything downstream works.
- **Option A (install the missing ATT write callback):** write a shim pointer into the currently-zero, in-region word at flash **0x17764**; the shim reads `value[0]`/`value[1]` from the ATT write packet and calls `FUN_0000fa68(a, b, 0)`. Reading from the packet sidesteps the attrLen=1 buffer cap.
- **Option B (poll 0x84315c from the shared main loop):** redirect one main-loop `bl` slot to a shim that reads the buffer and calls `fa68` on change. Bypasses the callback ABI — **but attrLen=1 means a naive 4-byte poll reads stale bytes for motorB**; poll only what the SDK actually stores, or force a larger attrLen.
- **Bench-decidable, not static:** every `.w`/`.r` in the ATT table is NULL, so whether the closed Telink ATT dispatcher honors a non-null `.w` is **not shown in-image**. Validate empirically: write known BLE output-report bytes, read 0x84315c / observe the motor via SWS; and resolve the exact `value` offset in the write packet the same way.

**UNVERIFIED.** Whether the closed-SDK ATT path honors a per-attribute write callback; the exact ATT-packet value offset; free-space for a shim in the 0x18274–0x18400 tail (image ends exactly at 0x18400; content extends to at least 0x18135).

---

## GOAL 5 — flashing feasibility + CRC-recipe status

**ANSWER.** Feasible via the vendor **USB HID IAP**; the write gate is **CRC-only — no signature, no encryption, plaintext payload**. This is now **instruction-level VERIFIED for the DONGLE** and the CRC recipe (the prior blocker) is resolved.

**Dongle IAP, fully traced (`iap_dispatch @0xd998`):** 64-byte report; magic **0x81 0x05**; command @byte[2]; 16-byte header = packet[2..17] with **length @[6..7] (≤46)**, **expected CRC @[8..9]**, **u32 LE flash address @[14..17]**; ≤46-byte data @[18..63]; device replies prefixed **0x02 0x05** on USB EP3/EP4/EP8 (`FUN_0xd124`/`0xdd7c`). Command ids C1/C3/04/03/C4/07/02/05/0B match the numpad USB sniff byte-for-byte.

**CRC recipe — RESOLVED [VERIFIED, VERY HIGH]:** `FUN_0x0000d0e4` = **CRC-16/MODBUS** (poly 0xA001 reflected = 0x8005, init 0xFFFF, refin/refout, **no xorout**), over the **payload bytes only**, expected value at **packet[8..9] little-endian**. `check("123456789") = 0x4B37` (reproduced; the TC32 `tshftrs` in the loop is logical LSR, proven three ways). Recompute:
```python
def crc16_modbus(d):
    c = 0xFFFF
    for x in d:
        c ^= x
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c & 0xFFFF          # packet[8:10] = c.to_bytes(2, "little")
```
Variants (not the per-chunk path): `multi_writeFlash` (cmd 0x0B) uses an **8-bit additive sum over 59 bytes**; `saveCodeBlock`/`savehead4K` use the same MODBUS CRC over its 0x30-byte header (4-byte CRC appended at header+0x30).

**No signature / no decryption [VERIFIED, VERY HIGH]:** the only data-dependent rejection is `crc != header` (writefirmware `tcmp r2,r9`@0xd3e0 / boot_wirteFlash `tcmp r2,sl`@0xd4c2); data is written verbatim (`&packet[18]` → flash, untransformed). The AES engine (0x800700/708/710/711) is **never referenced** anywhere in the dongle image. No RF in the IAP chain.

**Self-flash, not a relay [VERIFIED]:** handlers program the dongle's **own** SPI flash (SDK `0xb220` write / `0xb1ec` erase / `0xb204` read) and answer on its own USB. Controller and dongle are each flashed independently over their **own** USB in L1+R1 bootloader mode. **Dongle-relay-to-controller is RULED OUT** — firmware travels over wired USB only.

**[REFUTED sub-claim]** "boot_wirteFlash writes raw addr, no bounds, any region" is **wrong**. The shared low-level primitive `FUN_0xcd0c` loads −0x12000 and unsigned-rejects `addr − 0x12000 > 0xD000`, so **all IAP writes are clamped to [0x12000, 0x1F000]** (the staging/upper bank). The IAP only **stages**; the resident bootloader applies staging→live on reboot. It cannot directly overwrite the live app (0x6000–0x11FFF) or bootloader (0x0–0x5FFF). This does **not** weaken "CRC-only, no signature," but it does mean even a CRC-bypass patch stages content — it doesn't reach the live regions. (Consistent with the container's `dest_addr=0x6000` being the *final* resting place, applied from staging.)

**CONTROLLER caveat — the real remaining gap [INFERRED, med]:** the entire IAP RE above is of the **dongle**. The controller's resident bootloader (0x0–0x5FFF) is **not in our dump**. So for the controller:
- "No signature / CRC-only" is **inferred** (from the dongle handler + fwupd's `UNSIGNED_PAYLOAD` flag + the byte-identical 0x8105 command family in the numpad sniff) — **PLAUSIBLE, not established**.
- The controller's **exact CRC recipe and CRC-field location are un-extracted (LOW)**. It plausibly matches CRC-16/MODBUS but that is not proven, and the controller's staging/apply addressing may differ from the dongle's [0x12000,0x1F000].

**PATCH / NEXT STEP.**
- **On-device CRC-bypass (dongle, needs SWS — circular over USB):** writefirmware `tjne 0xd3a6`@0xd3e2 (`e0 c1`) → NOP `c0 46`; or boot_wirteFlash `tjeq 0xd4e6`@0xd4c4 (`0f c0`) → uncond `tj.n` `0f 80`. Both VERIFIED encodings, both in the app region (0x6000–0xFFFF). Still confined to the staging window by `FUN_0xcd0c`.
- **Controller, the decisive experiment:** **usbmon + Wireshark capture of the official Ultimate Software V2 flashing STOCK firmware to the 2C** in L1+R1 bootloader mode. This validates the CRC on real bytes for a known payload, reveals the device ACK format and the 2C boot-mode PID, and yields a replay client. Then flip one non-functional byte, recompute the CRC(s), reflash — the definitive signed-vs-unsigned test — with SELECT+START recovery and SWS as the net.
- **SWS single-wire rig (do this first):** non-FTDI USB-serial (CH340/CP210x/PL2303, no RX LED), `TX→SWS` via ~1 kΩ, `RTS→RESET`, GND, +3V3; "activation" stops the core within the first ms. It is the only full-flash backup, the only un-brick path, and the only route to the goal-1 bootloader gate.

**Brick hazards.** Take an SWS full-flash dump (`0x000000–0x080000`) of the exact unit before any write. Never chip-erase (**MAC @0x76000**, **RF-cal @0x77000** are factory-written, RF-load-bearing, and NOT in the vendor `.dat`). Never erase the bootloader (0x0–0x5FFF) — it is the recovery path. A malformed app at the staging/app slot won't boot but is recoverable via re-flash. SELECT+START recovery is **unverified on the 2C** — treat as a hoped-for net, prove it before the first modified write.

**UNVERIFIED.** The controller's signature-absence, CRC recipe, CRC-field location, and staging/apply addressing; the 2C boot-mode PID; whether SELECT+START recovery works on the 2C; any anti-rollback/version counter; whether a retail 2C exposes a probeable SWS pad.

---

## Cross-cutting: what a modification campaign needs, in order
1. **SWS rig on a sacrificial 2C** → chip-ID read → full-flash dump (backs up bootloader + MAC + RF-cal; enables everything else). Resolves goal-1's bootloader gate and goal-5's controller-CRC gap directly.
2. **usbmon capture of the official flasher** on stock firmware → validates the (inferred) controller IAP + CRC against real bytes, reveals ACK/PID.
3. **One live 2.4GHz/BLE frame capture** with L4/R4/SQUARE/STAR pressed → confirms the RF frame carries the upper button bits and pins the exact bit→button map (goal 3).
4. **Bench BLE write test** to the output-report characteristic while watching 0x84315c/motor via SWS → decides Option A vs B for goal-4 FF.
5. **VDD-collapse measurement** when the pad is "off" → settles goal-1's firmware-vs-hardware power-ON question before any bootloader edit.

Only after 1–2 are the app-region byte patches (goal-1 Patch 1, goal-3 dongle OR-map, goal-4 ATT-callback shim) safely flashable — each is small and in-region, but all currently gate on the un-extracted controller CRC and, for goals 3–4, on premises that are bench-decidable, not statically decidable.