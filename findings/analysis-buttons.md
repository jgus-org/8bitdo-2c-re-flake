# Extra buttons (SQUARE/STAR/L4/R4): scan → pack → dongle map

Controller v1.09 (base 0x6000), dongle v1.03 (base 0x6000). Telink B80 / TC32.

## Decisions per question
- **Scan method:** driven-column / sampled-row **keypad matrix** (not one-GPIO-per-button). Scanner `FUN_0000c7a4` @0xc7a4; row reader `FUN_0000c33c` @0xc33c samples **PA5/PA6/PA7 (reg_gpio_pa_in 0x800500)** and **PC1/PC3 (reg_gpio_pc_in 0x800510)**; one extra row pin **PA4** read directly at 0xc8ce; columns driven by `FUN_0000c288`/`FUN_0000c324`. Result = a ~29-bit button word at SRAM **0x84342c** (mirror 0x84344c). [VERIFIED]
- **Bit→name:** the physical→bit map is recoverable (table below); the button *names* are not labelled in this stripped image → name assignments [INFERRED].
- **Why L4/R4 are BT-only:** the RF frame carries the whole word, but the **dongle translator `FUN_0000733c` @0x733c maps only word bits {0–13,17}** into USB and **drops {14,15,16,18,25,26,27,28}** — the block the extras live in. In BT the dongle is absent, so the controller's own HID map governs exposure. [VERIFIED dongle drop; INFERRED L4/R4 occupy dropped block]
- **What square/star do:** consumed by **local handlers** (hold-timers/mode state machines) at 0xc9xx–0xd9xx (program/turbo) and never emitted as buttons → invisible in both transports. [VERIFIED that word bits 18 & 28 drive local hold/mode logic; INFERRED those are square/star]

## 1. Scan (VERIFIED)
`FUN_0000c7a4`: 4× {drive column via `FUN_0000c288`; ~20-tick settle `FUN_00000fe0(0x14)`; read rows via `FUN_0000c33c` → OR the 5 row bits into 32-bit r4 at fixed positions}, then read PA4 directly (0xc8ce → bit17), then store r4 to 0x84342c/0x84344c (pool words 0xc938/0xc93c, confirmed from binary). `FUN_0000c33c` samples PA5(0x20)/PC1(0x02)/PA6(0x40)/PC3(0x08)/PA7(0x80). Ports verified: PA in/out=0x800500/503, PC in/out=0x800510/513, PD out=0x80051b.

Reconstructed word-bit map (`Cn.rk` = column n, row k of {PA5,PA6,PA7,PC1,PC3}):

| bit|src|bit|src|bit|src|
|---|---|---|---|---|---|
|0|C1.r2|8|C3.r0|18|**C4.r3**|
|1|C3.r4|9|C1.r0|25|**C1.r3**|
|2|C3.r3|10|C2.r4|26|**C1.r4**|
|3|C3.r2|11|C2.r3|27|**C4.r2**|
|4|C2.r1|12|C3.r1|28|**C4.r4**|
|5|C1.r1|13|C4.r1|||
|6|C4.r0|16|**C2.r2**|||
|7|C2.r0|17|**PA4 direct**|||

Upper/extra block = bits {16,18,25,26,27,28}; bits 14,15 unused. **PD0** (reg_gpio_pd_in 0x800518 bit0) is a separate hard-wired system button polled directly all over (0xa0c6, 0xb774, 0xd1d4, 0xd8ea, 0xda72, 0xea0c, debounce SM 0xb452–0xb59c) — not in the matrix word.

## 2. Controller report packing (VERIFIED)
Three structurally-identical packers copy the **full 4-byte button word** (byte0→report[3] … byte3→report[6]) then interleave stick axes, each emitting to a USB EP, gated by a mode byte: #1 0xf0b0→`FUN_0000ebfc`; #2 0xf158 (mode==1)→`FUN_0000ede8`; #3 0xf238 (mode==2, wraps `{02,02,66,…}`)→`FUN_0000eb04`. **None truncate the extras** — the loss happens at the dongle, not here. (BLE-notify packer is in the closed SDK region, not in our payload, but draws from the same 0x84342c.)

## 3. Local consumption of function bits (VERIFIED)
0xc9xx–0xd9xx tests specific upper bits: **bit28** = most-referenced (mode/turbo state machine, 0xcd16 area); **bit18** = hold counter saturating ~24 ticks then fires (`FUN`@0xd0fc, `tjl 0xb8bc`) = hold-to-program/profile; **bit17**(PA4) hold handler @0xd0b0; **bit12** tested 0xd628/0xd8fc. Bits 18 & 28 are outside the dongle-mapped set → their presses do device-local things and never reach USB in 2.4G.

## 4. Dongle RF→USB map `FUN_0000733c` @0x733c (VERIFIED, decisive)
Takes controller button bitmap `param_3`, ORs bits into the 16-bit USB button field, copies 4 stick axes, stamps 8BitDo header (`+0xe=0x1c,+0xf=0x30,+0x10=0x67`), sends via 0x7288. Shift-sign tests map **source bits {0,1,2,3,4,5,6,7,8,9,10,11,12,13} plus bit17** (bit17→autofire out 0x400 via counter at RAM 0x74e0). **Bits {14,15,16,18,25,26,27,28} are never referenced.** The used-and-dropped set {16,18,25,26,27,28} = exactly the six extra buttons.

## 5. Mapping table (names INFERRED)
| button | word bit | wired | 2.4G | BT | role |
|---|---|---|---|---|---|
| standard 15 | 0–13,17 | sent | **mapped** | mapped | normal |
| **L4** | one of 16/25/26/27 | sent | **dropped** | mapped→visible | plain button |
| **R4** | another of 16/25/26/27 | sent | **dropped** | mapped→visible | plain button |
| **SQUARE/program** | 18 or 28 | sent | **dropped** | not mapped | local hold/remap |
| **STAR/turbo** | 28 or 18 | sent | **dropped** | not mapped | local turbo/mode |
| power/pair | PD0 | — | — | — | system button |

Split rationale: bits 18 & 28 **provably** drive local hold/mode handlers (= program/turbo); bits 16/25/26/27 have **no** local handler (= plain buttons only a report-map can surface → live in BT, stripped in 2.4G).

## 6. Patches (CRC-only gate, no signature)
- **A (preferred, dongle-side):** RF frame already carries L4/R4; only `FUN_0000733c` drops them. Add two `lsl/tst; orr *puVar3,#sparebit` blocks routing the L4/R4 source bits to free USB button bits. No in-line space → relocate the function tail into trailing padding and append, or repurpose the guide/0x1000 slot (shift 0x12). **No controller change needed.** Needs one hardware capture to confirm the exact source bit (16 vs 25/26/27) and a free output bit (DInput has spare; XInput does not → use Patch C).
- **B (repurpose square/star):** NOP the bit18/bit28 local consumers (0xd0fc; ~0xcd16) and, in `FUN_0000c7a4`, redirect their OR target to a dongle-mapped bit (≤13 or 17); then add to the dongle map. Higher risk (loses program/turbo).
- **C (remap onto existing button):** single OR-immediate edit in `FUN_0000733c` so L4/R4 alias an existing/rare button; size-neutral, trivial CRC fix, XInput-safe.

## 7. Load-bearing claims
1. [VERIFIED,high] Matrix scan: `FUN_0000c7a4`/`FUN_0000c33c`, rows PA5/PA6/PA7(0x800500)+PC1/PC3(0x800510)+PA4-direct, word at SRAM 0x84342c.
2. [VERIFIED,high] Dongle `FUN_0000733c` @0x733c maps only word bits {0–13,17}; bits {16,18,25,26,27,28} received-but-dropped → the 2.4G loss.
3. [VERIFIED,high] All three controller packers (0xf0b0/0xf158/0xf238) send the full 4-byte word; extras lost at the dongle, not the controller.
4. [VERIFIED,med-high] Word bits 18 & 28 consumed by local hold/mode handlers (0xd0fc; 0xcd16-area) = the program/turbo mechanism.
5. [INFERRED,med] square/star = locally-consumed bits 18/28; L4/R4 = handler-free dropped bits {16,25,26,27}. Exact indices need one live frame capture.
6. [INFERRED,med] PD0 = dedicated system button (power/pair/home), outside the matrix word.

---

## ~250-word summary

The 8BitDo Ultimate 2C controller does **not** read buttons one-GPIO-each; it runs a **driven-column/sampled-row keypad matrix** (`FUN_0000c7a4` @0xc7a4, rows read by `FUN_0000c33c` @0xc33c from PA5/PA6/PA7 on reg_gpio_pa_in 0x800500 and PC1/PC3 on reg_gpio_pc_in 0x800510, plus PA4 read directly at 0xc8ce). The scan assembles a ~29-bit button word into SRAM 0x84342c (mirror 0x84344c). The low block (bits 0–13,17) is the standard gamepad set; the upper block (bits 16,18,25,26,27,28) holds the four extra buttons. PD0 (reg_gpio_pd_in 0x800518 bit0) is a separate hard-wired system button.

All three controller USB report packers (0xf0b0/0xf158/0xf238) copy the **entire 4-byte word** — the extras are never dropped on the controller side. The loss is at the dongle: `FUN_0000733c` @0x733c maps only word bits {0–13,17} into the USB button field and **never references {16,18,25,26,27,28}**, so any button there is received-but-dropped over 2.4GHz. Separately, bits 18 & 28 are consumed by local hold/mode handlers (0xd0fc hold-counter; 0xcd16 state machine) = the program/turbo functions, so they're never reported anywhere.

Cleanest fix for L4/R4 in 2.4GHz is dongle-side only (add OR-maps in `FUN_0000733c`); the RF frame already carries them.

**Most load-bearing claims (for independent verification):**
- [VERIFIED] Matrix scanner `FUN_0000c7a4`/`FUN_0000c33c`; rows PA5/6/7 (0x800500) + PC1/3 (0x800510) + PA4-direct; word at SRAM 0x84342c.
- [VERIFIED] Dongle `FUN_0000733c` @0x733c maps only button bits {0–13,17}; drops {16,18,25,26,27,28} → the 2.4G disappearance.
- [VERIFIED] All three controller packers (0xf0b0/0xf158/0xf238) transmit the full 4-byte button word; extras lost at the dongle, not the controller.
- [VERIFIED] Word bits 18 & 28 consumed by local hold/mode handlers (0xd0fc, 0xcd16-area) = program/turbo.
- [INFERRED, med] square/star = locally-consumed bits 18/28; L4/R4 = handler-free dropped bits {16,25,26,27} (exact indices need one captured RF frame).