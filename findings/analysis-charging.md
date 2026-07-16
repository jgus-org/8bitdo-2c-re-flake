# 8BitDo Ultimate 2C controller — charge/power-gate analysis (v1.09)

**ISA note (load-bearing for all byte patches):** disasm is Telink **TC32**, a Thumb-like ISA with **remapped opcodes** — bytes do NOT match ARM Thumb. Encoding derived empirically from this image (table at end). Image = app payload at 0x6000 (74752 bytes); resident bootloader (0x0–0x5FFF) is NOT in this image.

## 1. VBUS/charging detection
**Charging = low-power comparator: `analog_read(0x88) & 0x20` (bit5); SET = present.** [VERIFIED] Only genuine LPC read in the image, at FUN_00007138:
```
7102 tmovs r0,0x88 ; 7104 tjl 0x6d84   -> analog_read(0x88)
7108 tmov r3,r8    ; r3 = 0x20 (mask set once at 0x70e4)
710a tnand r3,r0   ; r3 = 0x20 &~ r0   (tnand == BIC, confirmed via busy-wait at 0x7334)
710c tjne 0x7154   ; bit5 CLEAR -> exit (not charging); SET -> ramp charge LED
```
LPC powered/configured in the same cluster: `analog_write(0x81, v|0x40)` @0x70ce (power-on, bit6), `analog_write(0x82,0x85)` @0x7226 (reference/scale).

**Helper correction:** `analog_write` @0x6dc4 is **(addr, value)** — r0→reg_ana_addr(0x8000b8), r1→reg_ana_data(0x8000b9), then 0x60(START|RW)→0x8000ba. The brief's "(value, addr)" is backwards. `analog_read` @0x6d84 = (addr). [VERIFIED]

**Negatives:** USB DP/DM GPIO (PA1/PA2) NOT read for charge (the one reg_gpio_pa_in consumer @0xc33c packs PA5/6/7+PC1/3 into a button mask). No ADC-VBAT charge path. The apparent analog_read(0x88) at 0xb0e4 is a false positive (`func_0xfaf4(0x88<<1)`). [VERIFIED] VBUS→LPC pad via a board divider (PB1–PB7). [INFERRED, high]

## 2. Power-off / sleep path
**Sleep primitive @0x6020** (only sleep trigger in image): `tmovs r2,0x81; *reg_pwdn_ctrl(0x80006f)=0x81` (bit7 SLEEP) at 0x6024/26, then ~60 NOPs, resume. Called from exactly one site, **0x7234**. [VERIFIED]

**Suspend routine @0x7210** (sole caller of sleep): pre-sleep `analog_write(0x34,*), (0xe4,0x10), (0x82,0x85)`; quiesce reg_gpio_pe_ie(0x800521); **call 0x6020 (SLEEP)**; on-wake restore analog; call 0x7174 (reboot-check); call 0x70b4 (charge-LED). [VERIFIED]

**Reboot @0x7160:** `*reg_pwdn_ctrl=0x20` then spin; also sets analog 0x3a (DEEP_ANA_REG0) bit1 retention flag. [VERIFIED]

**KEY STRUCTURAL FINDING:** the entire PM cluster (0x6020/0x70b4/0x7160/0x7174/0x7210) has **no in-image caller and no static pointer** (exhaustive byte-search = 0 hits; cstartup→main `tjl 0x10374→0xfed8` never reaches it). It is a **PM callback invoked from the resident bootloader.** Therefore the **power-off decision and its charging gate are NOT in the flashable app payload** — the app holds only the charge *sense*, the *indicator*, and pre-sleep analog config. [VERIFIED by exhaustion]

## 3. The charging gate
No in-image `if(charging) skip power-off` branch exists. The gate is bootloader-resident. Most likely mechanism: the **LPC/VBUS is armed as a deep-sleep wake source** (reg_wakeup_en 0x80006e is never written in-image, consistent with bootloader arming), so a power-off suspend is immediately re-woken by present VBUS → on-wake handler runs → pad appears not to turn off. [INFERRED, med] Alternatively a bootloader USB-enumeration check for the specifically "wired" case. [INFERRED, low-med]

## 4. Patches (ranked by safety)
**Patch 1 — force in-image charge sense to "not charging" (SAFEST):** 0x710c `0xc122`(tjne 0x7154) → `0x8722`(unconditional B.n, same +0x22 → same target). **Byte: file offset 0x110d, `0xc1→0x87`.** Effect: charge-LED loop always takes not-charging path (disables LPC, returns); kills the charge indicator. Cannot brick; reversible. Honest efficacy: does NOT by itself power-off-while-charging (gate is bootloader), unless a bootloader gate consults a shared flag.

**Patch 2 — disarm LPC reference pre-sleep (MEDIUM):** NOP `analog_write(0x82,0x85)` at 0x7226/0x7228 (TC32 NOP = `0x06c0`). May stop VBUS waking a suspended pad (→ off while charging AND no charger-power-on), but the true wake-*enable* is bootloader-side so efficacy uncertain; test with SWS recovery wired.

**Patch 3 — patch the real gate in the bootloader (DECISIVE, needs SWS):** the decision + wake-arm live in 0x0–0x5FFF, reachable only via the SWS single-wire path, NOT the USB IAP (app-region only). Only route to the actual branch.

**Not recommended:** changing the 0x81 sleep value / mode — sleep is already unconditional once reached; problem is upstream.

## 5. "Powers ON when placed on a charger" — firmware-preventable?
Partly firmware, but not from the app image; hardware contribution not excludable. [INFERRED, med] Battery-powered pad ⇒ "off" is suspend/deep-sleep on the battery rail, so dumb-charger wake needs an armed analog (LPC/VBUS) wake — firmware, but **bootloader-side**, hence not patchable via the app payload. A load-switch/POR cold-boot route would be pure hardware, not firmware-preventable; distinguishing needs a board trace (does MCU VDD collapse when "off"?).

## TC32 encoding (derived)
`tmovs Rd,#i8`=0xA000|(Rd<<8)|i8 · `tcmp Rn,#i8`=0xA800|(Rn<<8)|i8 · Bcond=0xC000|(cond<<8)|i8 (EQ0 NE1…LS9; ARM-Thumb uses 0xD0|cond) · B.n=0x8700|i8(signed8) · `ldr Rd,[pc,#i]`=0x0800|(Rd<<8)|(i>>2) · `strb Rd,[Rn,#0]`=0x4000|(Rn<<3)|Rd · `tnand`(BIC)Rd,Rm=0x0200|(Rm<<3)|Rd. Target = (insn+4) + 2*signed_imm8.

---

## ~250-word summary

The controller senses charging via the on-die low-power comparator: the only genuine LPC read in the image is `analog_read(0x88) & 0x20` (bit5 set = VBUS/charging present) inside the charge-indicator loop FUN_00007138 @0x7102–0x710c. USB DP/DM GPIO and ADC-VBAT are not used for charge detection. The sleep trigger is a single instruction — `*reg_pwdn_ctrl(0x80006f)=0x81` (bit7) at 0x6024/26 in the primitive @0x6020, called only from the suspend routine @0x7210 (which arms LPC analog regs, sleeps, then on wake shows the charge LED); reboot is `=0x20` @0x7160. Critically, the whole power-management cluster has no in-image caller or pointer, so it is a callback invoked from the resident bootloader (0x0–0x5FFF, not in the flashable app image): the power-off decision and its "am-I-charging" gate are therefore not in the app payload. The observed "won't turn off while charging / powers on from a charger" is best explained by a bootloader-side LPC/VBUS deep-sleep wake-arm (reg_wakeup_en 0x80006e is never written in-image). The safest concrete app patch forces the in-image charge sense to "not charging" (1 byte, file offset 0x110d: 0xc1→0x87), but the decisive gate can only be changed by patching the bootloader via SWS — outside the USB-IAP-writable region. Note bytes are Telink TC32, not ARM Thumb.

Most load-bearing claims (for independent verification):
- **Charge detect = `analog_read(0x88) & 0x20` (LPC bit5 set = present), the only genuine LPC read (0x7102–0x710c); DP/DM GPIO and ADC-VBAT unused.** [VERIFIED]
- **`analog_write`@0x6dc4 arg order is (addr, value) — opposite of the brief's note** (r0→0x8000b8 addr, r1→0x8000b9 data). [VERIFIED]
- **Sleep = `*reg_pwdn_ctrl(0x80006f)=0x81`@0x6024 (primitive @0x6020, called only from 0x7234); reboot=0x20@0x7160.** [VERIFIED]
- **The entire PM cluster (0x6020/0x70b4/0x7160/0x7174/0x7210) has zero in-image callers/pointers ⇒ bootloader-invoked; the power-off charging gate is not in the app payload.** [VERIFIED by exhaustion]
- **"Powers on from charger / won't off while charging" ⇒ bootloader-side LPC/VBUS wake-arm (reg_wakeup_en 0x80006e never written in-image); fixable only via SWS/bootloader, not USB-IAP.** [INFERRED, med]
- **Patch 1: file offset 0x110d `0xc1→0x87` (tjne→B.n) forces the in-image charge sense to "not charging"; safe/reversible but doesn't alone defeat the bootloader gate.** [VERIFIED encoding/effect]