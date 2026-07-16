# Adversarial verification: extra buttons (SQUARE/STAR/L4/R4)

Independent re-trace of ctrl-v109 + dongle-v103 (both base 0x6000, Telink B80/TC32). Verdicts per the report's five numbered load-bearing claims, plus the patch/CRC claims the brief flagged.

## Claim 1 — Matrix scanner + pins + word location — **CONFIRMED** (one sub-detail REFUTED, non-load-bearing)

VERIFIED by tracing `FUN_0000c7a4` @0xc7a4 and `FUN_0000c33c` @0xc33c:
- Scanner drives 4 columns via `FUN_0000c288(col,val)` (calls at 0xc7ae/0xc7f2, 0xc832/0xc83a, 0xc878/0xc880) bracketed by `FUN_0000c324` (0xc7a8/0xc8c2), each column followed by `FUN_00000fe0(0x14)` settle then a 5-row read `FUN_0000c33c`. This is unambiguously a **driven-column / sampled-row matrix**.
- `FUN_0000c33c` (0xc33c–0xc378) reads exactly 5 pins: **PA5** (mask 0x20), **PA6** (bit6 via `<<0x19`), **PA7** (0x80), **PC1** (0x02), **PC3** (0x08). Pin set matches the report. (Port identities reg_gpio_pa_in 0x800500 / reg_gpio_pc_in 0x800510 rest on register-map.md; the mask pattern — high three PA bits + PC1/PC3 — is consistent with it.)
- **PA4** read directly at 0xc8ce (`<<0x1b` = bit4), feeding word **bit17** through a debounce counter (saturates 0x19).
- I reconstructed the *entire* column×row→bit assignment from 0xc7bc–0xc8b8. Used word-bit set = **{0-13, 16, 17, 18, 25, 26, 27, 28}**; bits 14,15,19-24,29-31 unused. This is bit-for-bit identical to the report's "standard {0-13,17}" + "extra {16,18,25,26,27,28}". High confidence.

**REFUTED sub-detail (not load-bearing):** the absolute address "SRAM **0x84342c**". The scanner's two store targets are pool pointers at 0xc938/0xc93c, both decoding to **≈0x0004942C** (mirror at +0x20 = 0x0004944C). The report's 0x84342c/0x84344c is a mislabel of that same global pair — the +0x20 mirror delta is right, the base is wrong. Does not affect any downstream claim.

## Claim 2 — Dongle maps only {0-13,17}, drops {16,18,25,26,27,28} — **CONFIRMED** (decisive, instruction-level)

`FUN_0000733c` @0x733c, verified against listing 0x733c–0x7412. Sign-tests of `param_3 << {0x12…0x1f}` fold source bits **{13,12,4,5,10,11,1,2,9,8,7,6,3,0}** into the 16-bit USB button field at `[r5+0x26]`; then `param_3 & 0x20000` (**bit17**) drives an autofire counter at `pRAM000074e0` → output 0x400. Bits **14,15,16,18,19-31 (incl. 25,26,27,28) are never referenced.** So {16,18,25,26,27,28} are received-but-dropped over 2.4G. Solid. (Nuance: bit17/PA4 survives only as an *autofire* output, not a discrete button. Also, output bits 0x800/0x8000 appear unused in this 16-bit field — there IS spare room, contra the report's "XInput has no spare".)

## Claim 3 — All three packers send the full 4-byte word — **CONFIRMED, with a scope caveat**

`FUN` @0xf0b0, 0xf158, 0xf238 each load the button-word global and store byte0→report[3], then `word>>8` into report[4..6] = all four bytes (extras included). All three read the **same** global 0x0004942C (pool at 0xf13c / 0xf2b8, byte-identical to the scanner's store pointer at 0xc938) — so the scan→pack chain is intact.
**CAVEAT the report understates:** these three are **USB-endpoint (wired) packers**. They prove the *wired* report carries all bits; they do **not** establish that the 2.4G RF frame does. The RF/BLE TX packer is in the closed SDK region and was not verified.

## Claim 4 — Bits 18 & 28 locally consumed (program/turbo) — **CONFIRMED, with corrections**

- **bit18**: hold-counter handler at **0xd10c** (loads global, masks `0x80<<0xb = 0x40000 = bit18`, counter saturates 0x18≈24 then fires). CONFIRMED. But the report's cited "0xd0fc" is a **pool literal** (the mirror-global pointer 0x0004944C), not the function — entry is 0xd10c.
- **bit17**: separate hold handler at **0xd0b0** (mask 0x20000, counter saturates 0x19). CONFIRMED (matches report).
- **bit28**: tested at 0xcd7a and 0xd152 via `<<3`. CONFIRMED referenced.
- **New finding that undercuts the report:** bits **25/26/27 are ALSO locally consumed** — the handler at 0xccc4…0xcd16 tests `r0<<6/<<5/<<4` (= bits 25/26/27) and performs key-**remap** stores (offsets 0x86/0x88/0x8d and 0x93/0x94/0x9a). Local consumption is broader than "18 & 28." The "program/turbo" naming itself stays INFERRED.

## Claim 5 — INFERRED square/star=18/28; L4/R4=handler-free {16,25,26,27} — **PARTIALLY REFUTED**

The "handler-free plain button" rationale **fails for 25/26/27** — they drive the remap handler at 0xccc4. Only **bit16** has no local handler I could find (its status is otherwise unverified). So the clean argument collapses to at most bit16, and the specific L4/R4 bit indices are materially more uncertain than the report implies. (The report does mark this med-confidence and "needs a captured RF frame," so this weakens rather than demolishes it.)

## Claim 6 — PD0 = system button outside the matrix — **CONFIRMED (partial)**

Verified PD0 is **not** in the scanner word (the scan touches only PA/PC). "Power/pair/home" role and the specific polling sites are INFERRED (not exhaustively traced).

## Patch / CRC claims (brief asked for harshness) — **two real problems**

- **App-region:** 0x733c, 0xc7a4, 0xc33c, 0xd0b0, 0xd10c, 0xf0b0 are all ≥0x6000 → in the flashable app image. CONFIRMED. **But Patch B is mis-targeted**: it says "NOP the bit18 consumer at 0xd0fc" — 0xd0fc is a 32-bit **pool pointer** (0x0004944C), not an instruction; editing there corrupts the mirror-global pointer. The real consumer is 0xd10c+.
- **Patch A premise "RF frame already carries L4/R4 → dongle-only, no controller change"** is **UNPROVEN and likely the weakest link.** Nothing in the dongle proves the RF payload contains bits 16/18/25-28 — `FUN_0000733c` reads only bits 0-13,17 of param_3. The only verified full-word packers are USB/wired. If the controller's 2.4G RF TX packer (closed SDK) transmits fewer button bytes, a dongle-only patch cannot recover L4/R4. Treat "no controller change needed" as an assumption to test with a live capture, not a fact.
- **"No signature / trivial CRC fix":** "no signature" is inherited from flashing-options.md (strongest for the dongle IAP handler, HIGH confidence there) and I did not re-derive it from the button disasm. **"Trivial CRC fix" is overstated** — flashing-options.md explicitly rates the exact `flash_crc` recipe as NOT-yet-extracted (LOW confidence). You cannot trivially recompute an un-reversed CRC.

## Bottom line
The report's **core hardware conclusion is solid and independently reproduced**: the controller scans a 4×5 matrix (+PA4) into a word using bits {0-13,16,17,18,25-28}; the wired packers emit all of it; the dongle `FUN_0000733c` maps only {0-13,17} and silently drops {16,18,25,26,27,28} — so L4/R4 vanish over 2.4G but appear over BT. Claims 1, 2, 3 CONFIRMED. Claim 4 CONFIRMED with the 0xd0fc→0xd10c address correction and the finding that 25/26/27 are also locally handled. Claim 5's specific bit assignment PARTIALLY REFUTED (25/26/27 are not handler-free). Two things that **collapsed**: the absolute SRAM address 0x84342c (actually ≈0x0004942C), and the confidence behind Patch A/B (RF-frame-carries-the-bits is unverified; Patch B's 0xd0fc is a pool literal; "trivial CRC" contradicts the flashing doc's own LOW-confidence rating).