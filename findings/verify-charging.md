# Adversarial verification — charging/power-gate analysis (ctrl v1.09)

Independent re-read of the SAME artifacts (listing.txt, poolregs.txt, register-map.md). Verdicts per load-bearing claim. Addresses are image addresses (payload base 0x6000).

Artifact limitation up front: the raw firmware **binary is NOT in the artifact set** (only Ghidra `.rep` projects + derived text). So (a) I cannot rerun the "exhaustive byte-search = 0 pointer hits", and (b) I cannot read raw opcode bytes — opcode/encoding checks below are by control-flow + target arithmetic, not byte inspection. `functions.txt` is a **curated subset** (it omits 0x6020/0x70b4/0x7160/0x7174/0x7210 even though the listing shows them called), so absence-from-functions.txt proves nothing.

---

## Claim 1 — Charge detect = `analog_read(0x88) & 0x20` (bit5 set = present), only genuine LPC read; DP/DM & ADC-VBAT unused
**Verdict: mechanism CONFIRMED; the "bit5 = LPC comparator = VBUS/charging present" *identification* is UNPROVEN and CONFLICTS with the cited register map.**

Traced at 0x7102-0x710c:
- 0x7102 `tmovs r0,0x88`; 0x7104 `tjl 0x6d84` → analog_read(0x88). [CONFIRMED]
- mask set once: 0x70e4 `tmovs r3,0x20`; 0x70e6 `tmov r8,r3` (r8=0x20). 0x7108 `tmov r3,r8`; 0x710a `tnand r3,r0` (BIC: r3 = 0x20 & ~r0); 0x710c `tjne.n 0x7154`. Mask is **0x20 = BIT(5)**, not 0x40. [CONFIRMED by listing]
- Polarity: bit5 SET → BIC result 0 → tjne NOT taken → fall through to 0x710e (LED-ramp / write analog 0x01 = 0x4e/0x4b, the charge-indicator path). bit5 CLEAR → tjne taken → 0x7154 (analog_write(0x81, sl) disables, returns). So SET drives the charge LED, CLEAR disables it. Functional polarity **CONFIRMED** by tracing both paths.
- Only genuine LPC read: the two `tmovs r0,0x88` sites are 0x7102 (→0x6d84 analog_read) and 0x0b0e4 (→0x0faf4). I read 0xfaf4: it decodes a packed pin descriptor (shifts) and writes areg **0xeb** (ADC input-channel select) via 0xdc4 — it is **ADC channel setup**, not analog_read of reg 0x88. So the 0xb0e4 hit is a genuine false positive. **CONFIRMED** — exactly one analog_read(0x88) in the image.

**REFUTATION on the semantic label:** register-map.md line 134 documents the low-power-comparator result as `analog_read(0x88) & BIT(6)` (**bit6/0x40**, `lpc_get_result`). The firmware tests **bit5/0x20**. The report asserts "LPC bit5 set = present [VERIFIED]" — but the cited authority puts the LPC result at bit6, so either (a) the pvvx-8258-sourced map has the wrong bit for the B80, or (b) reg 0x88 bit5 is a different status than the LPC result. Bottom line: *that the code reads 0x88 and branches on bit5* is VERIFIED; *that bit5 = the LPC comparator = "5 V/VBUS present"* is **INFERRED and not backed by (indeed contradicts) register-map.md**. Confidence 0x88/bit5 is the charge-state gate: high (it gates the charge-LED loop). Confidence it is specifically the documented LPC result bit: low-med (bit conflict). The report's `[VERIFIED]` on the physical meaning overstates.

DP/DM-and-ADC-VBAT-unused: supported — reg_gpio_pa_in (0x800500, DP=PA2/DM=PA1) has only 2 pool refs and the charge loop never reads it; charge sense goes through analog 0x88. [CONFIRMED, negative]

## Claim 2 — `analog_write`@0x6dc4 arg order = (addr, value), opposite the brief
**Verdict: CONFIRMED. The report is right; the original brief was wrong.**
0x6dc4 body: 0x6dd6 `tloadr r3,pc` (→reg_ana_addr 0x8000b8); 0x6dd8 `tstorerb r0,r3` → **r0 (1st arg) → reg_ana_addr = the address**; 0x6dda `tadds r3,0x1`; 0x6ddc `tstorerb r1,r3` → **r1 (2nd arg) → 0x8000b9 = reg_ana_data = the value**; then 0x60 (START|RW) → 0x8000ba. So `analog_write(addr, value)`. analog_read@0x6d84 = `(addr)` single arg (r0→0x8000b8). poolregs confirms 0xb8/0xb9/0xba are the only analog-port words. The brief's "(value, addr)" is backwards.

## Claim 3 — Sleep = `*reg_pwdn_ctrl(0x80006f)=0x81` @0x6026 (primitive @0x6020, called only from 0x7234); reboot=0x20 @0x716a
**Verdict: CONFIRMED (one nit).**
- 0x6020: 0x6022 `tmovs r2,0x81`; 0x6024 `tloadr r3,pc`; 0x6026 `tstorerb r2,r3` → write 0x81; then ~60 `tmov r8,r8` NOPs; 0x60a8 pop; return. [CONFIRMED]
- reboot 0x7160: 0x7166 `tmovs r2,0x20`; 0x716a `tstorerb r2,r3`; 0x716c self-spin. [CONFIRMED]
- poolregs.txt shows `0x0080006f` referenced **exactly 2×** — the sleep write and the reboot write are the only two reg_pwdn_ctrl accesses in the image. [CONFIRMED]
- Full-listing grep: `tjl 0x6020` appears once, at 0x7234. Single sleep call site. [CONFIRMED]
- Nit: value is **0x81** (bit7 SLEEP + bit0), not the canonical 0x80; report states 0x81 so no error, but "bit7 SLEEP" omits the unexplained bit0.

## Claim 4 — Entire PM cluster has zero in-image callers/pointers ⇒ bootloader callback
**Verdict: "no DIRECT caller of the root" CONFIRMED; "no pointer anywhere / bootloader-invoked" UNPROVEN (plausible, not reproducible from these artifacts).**
- The cluster is one root function **0x7210** (suspend: tpush@0x7210 … tpop@0x72c0) that internally calls 0x6020 (sleep, @0x7234), 0x7174 (@0x72b6), 0x70b4 (@0x72ba); 0x7174 calls 0x7160 (@0x7202). Full-listing grep for a call/branch to **0x7210 returns ZERO**. So no *direct* in-image caller of the root exists. [CONFIRMED]
- The "no static pointer / exhaustive byte-search = 0 hits" step I **cannot reproduce** — the raw binary is absent, and functions.txt is a curated subset. An indirect dispatch via a function-pointer word cannot be excluded from the artifacts I have. So the leap to "bootloader-resident PM callback" is a reasonable **INFERENCE**, not something I independently verified. Not refuted; not independently confirmed.

## Claim 5 — "Powers on from charger / won't off while charging" ⇒ bootloader-side wake-arm; reg_wakeup_en 0x6e never written in-image
**Verdict: the sub-fact CONFIRMED; the conclusion INFERRED (med), not refuted.**
- poolregs.txt has **no `0x0080006e`** entry → reg_wakeup_en is never pool-referenced → never written in-image. [CONFIRMED]  (Caveat: excludes only pool-constant writes; the SDK register pattern is pool-based, so this is strong.)
- "Therefore the wake source is armed by the bootloader" and "the power-off charging gate is bootloader-resident" follow from Claim 4's inference; they inherit its UNPROVEN status. Consistent with the evidence, not proven by it.

## Claim 6 — Patch 1: payload offset 0x110d `0xc1→0x87` (tjne→B.n) forces not-charging; safe/reversible; doesn't defeat the bootloader gate
**Verdict: encoding + effect CONFIRMED by control-flow/arithmetic; in-app-region CONFIRMED; several caveats the report understates.**
- Target arithmetic: tjne.n@0x710c→0x7154 ⇒ imm8 = (0x7154-(0x710c+4))/2 = 0x22, so the halfword is 0xC122 (Bcond NE). B.n with the same imm8 = 0x8722 → (0x710c+4)+2·0x22 = 0x7154, the **same** target. Cross-checked against real `tj.n` sites (0x7140→0x70e8, 0x715c→0x7126, 0x716c self-loop) — all resolve consistently under B.n = 0x87xx|i8 with an 8-bit signed immediate. So flipping the high byte 0xC1→0x87 turns the conditional into an unconditional branch to 0x7154. [CONFIRMED by arithmetic; raw bytes not read — binary absent]
- Effect: always takes the 0x7154 path (disable LPC via analog_write(0x81, val&0xbf), return) ⇒ the charge-LED ramp is never executed. "Forces in-image sense to not-charging / kills the charge indicator." [CONFIRMED]
- In-app-region: 0x710c ∈ [0x6000, 0x6000+0x12400) = [0x6000,0x183ff]. Yes, in the flashable app payload. [CONFIRMED]
- **Caveat A (offset frame):** "file offset 0x110d" is relative to the **0x6000-based payload image** (0x710c-0x6000 = 0x110c, high byte +1 = 0x110d). The vendor-distributed file has a **28-byte (0x1C) ebitdo header** prepended (per flashing-options.md), so the on-disk offset in that file is **0x1C + 0x110D = 0x1129**. The report never reconciles the two frames — a real foot-gun.
- **Caveat B (flashability):** "reversible/safe" is true as a control-flow edit but glosses that any reflash must satisfy the CRC gate, whose recipe flashing-options.md rates **LOW/unknown**. Not currently flashable in practice.
- **Caveat C (contingency):** the patched function only executes if the bootloader actually invokes the suspend/charge callback (Claim 4). If it never calls in, even the "kills charge LED" effect does not manifest. The report's own honesty note ("does NOT by itself power-off-while-charging") is correct and important — Patch 1 does not achieve the user's goal.

---

## Extra defect found — Patch 2 recipe is buggy
Report proposes NOP-ing `analog_write(0x82,0x85)` by NOP-ing **0x7226/0x7228** (the two `tmovs`). But the call is at **0x722a** (`tjl 0x6dc4`), left intact. With the two movs NOP'd, 0x722a still fires with **stale r0/r1** — after the preceding `analog_write(0xe4,0x10)` returns, r0/r1 hold return-clobbered values, not 0x82/0x85 — so it writes an *unintended* analog register rather than cleanly dropping the write. To actually remove that write you must also NOP the `tjl` at 0x722a (three halfwords: 0x7226/0x7228/0x722a). As written the recipe is incomplete/unsafe. (Report already rated Patch 2 "MEDIUM, efficacy uncertain," but the byte recipe itself is defective.)

## Net
- Solidly CONFIRMED: analog_write arg order (Claim 2); sleep/reboot writes to reg_pwdn_ctrl and single sleep call site (Claim 3); only one analog_read(0x88) and the 0xb0e4 false positive (Claim 1 mechanism); reg_wakeup_en 0x6e never written (Claim 5 sub-fact); no direct caller of suspend root 0x7210 (Claim 4 direct part); Patch 1 encoding/effect/region (Claim 6).
- COLLAPSED / DOWNGRADED: Claim 1's `[VERIFIED]` semantic label "bit5 = LPC = charging present" — the bit read is bit5 but register-map.md assigns the LPC result to bit6; the physical meaning is INFERRED, not verified, and conflicts with the cited authority.
- UNPROVEN from these artifacts (raw binary absent): the full pointer-exhaustion behind Claim 4, hence the bootloader-callback conclusion (Claim 4) and the bootloader-wake-arm conclusion (Claim 5) — plausible, not independently reproducible.
- Patch caveats the report understates: Patch-1 header-offset frame (on-disk 0x1129 vs payload 0x110d), CRC-gate flashability, callback contingency; Patch-2 byte recipe is defective.
