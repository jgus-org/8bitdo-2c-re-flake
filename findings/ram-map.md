# 8BitDo Ultimate 2C controller — SRAM map (v1.09)

Goal: find a **provably-unused RAM byte** to stash the settled charge read (the two-hook design), instead of the guess (`0x847000`) that bricked the pad. Analysis is static, from the app payload (img `0x6000`); the bootloader (`0x0–0x5FFF`) is not in the image.

## Chip: genuine 16 KB B80 (this resolves the brick)

SRAM base is `0x840000`. The cstartup loads the SVC-mode stack pointer with the **top of SRAM = SRAM_SIZE**; here that constant is **`0x844000`**, so SRAM is **`0x840000–0x844000` = 16 KB** — a real **B80**, not a 32 KB TLSR8251. (Telink `SRAM_SIZE` = base+size and is exactly the SP-init value: B80=`0x844000`, B80B=`0x845000`, 8251=`0x848000`, 8253=`0x84C000`, 8258=`0x850000`. Sources: `telink-semi/tc_ble_simple_sdk` `b80_ble_sdk/boot/cstartup_flash.S` and `.../project/tlsr_tc32/B80/boot.link`.)

**Therefore the brick is explained:** `0x847000` is `0x3000` **above** the 16 KB top — it is not RAM at all. The write faulted because there was no memory there, not because the byte was "live." Any stash must stay strictly inside `0x840000–0x844000`.

## Memory map (verified from cstartup @0x60b4–0x6162)

The entry `0x6000` jumps to cstartup `0x60b4`, which sets both stacks, zeroes bss, copies data, then calls `0x10374`→`main`(`0xfed8`). Pool constants read directly from the image:

| region                           | range                 | how known                                            | status for a stash                                           |
| -------------------------------- | --------------------- | ---------------------------------------------------- | ------------------------------------------------------------ |
| `.vectors` + `.ram_code`         | `0x840000`–`0x842500` | branch targets / refs from `0x840004` up             | **reserved** (RAM-resident code + RF)                        |
| IC-tag (I-cache tag)             | `0x842500`–`0x842600` | 256 B, zeroed as a separate loop (Telink `ZERO_TAG`) | **reserved** (hardware cache)                                |
| **unreferenced gap**             | `0x842600`–`0x842e00` | not zeroed/copied; no code; no pointer               | **candidate (2 KB)** — see below                             |
| `.data`                          | `0x842e00`–`0x842fac` | copied from flash `0x18084`                          | used (packed; e.g. battery gauge `0x842e04`)                 |
| pad                              | `0x842fac`–`0x842fb0` | alignment                                            | —                                                            |
| `irq_stk` (IRQ stack, mode 0x12) | `0x842fb0`–`0x843130` | 384 B; SP(IRQ)=`0x843130`=`irq_stk+0x180`            | **reserved** (IRQ stack)                                     |
| `.bss`                           | `0x843130`–`0x843cf0` | zeroed; matches traced global top `0x843cef`         | used (dense; button word `0x84342c`, FF `0x8434ef`)          |
| main stack headroom              | `0x843cf0`–`0x844000` | SP(SVC)=`0x844000`, grows down                       | **reserved** (stack) — only ~784 B, linker guarantees ≥600 B |

Static allocation nearly fills the 16 KB; the only slack is the mid gap and dead bytes inside bss.

## How usage was mapped (`trace.py` / `analyze.py`, kept alongside)

TC32 reaches a global by loading its base from a PC-relative literal pool (`tloadr rN,[pc,#imm] ; (0xPOOL)`) then `tloadr/tstorer[b/h] rX,[rN,#off]`. The tracer follows that: read the pool word from the image; if it's `0x84xxxx`, record every subsequent constant-offset access off that register, and flag register-indexed (`[rN,rM]`) accesses as **arrays** (extent bounded conservatively by the next base). Register→base tracking resets at each function label and on overwrite.

**Limitation (important):** it captures pool-load-then-offset accesses. It undercounts arrays indexed off a non-pool-loaded base and any computed-address access — so an unreferenced run is _evidence of_, not _proof of_, being free. Hence the empirical read-back gate below.

## Candidate stash locations

1. **Mid unreferenced gap — `~0x842900`.** Strongest static case: the whole `0x842600–0x842e00` region has **no code** (0 branch/call targets), **no pointer** (the only `0x84xxxx` pool word in range is `0x842600`, which is merely cstartup's IC-tag-zero _end_ boundary), and **is not a DMA/RF buffer** (no low-16 or full pool word addresses it; the `0x2600–0x2dff` pool words are unrelated constants like `0x2710`=10000). Caveat: it is _not_ cstartup-initialized, so its nature (linker slack vs. a bootloader-owned scratch) isn't provable statically, and its boot value is undefined.

2. **Dead byte in zeroed bss — `~0x843300`** (inside the 255 B dead run `0x8432b9–0x8433b7`; the 319 B run `0x843179–0x8432b7` is the larger alternative). **Definitely app RAM** (zeroed at boot → not hardware, not bootloader, not stack — an app bss byte), starts clean at `0`, sits +393 B above the IRQ stack and ~`0xa00` below the main stack. Residual risk is only a bss array my tracer missed.

Prefer **#2** for the "definitely valid app RAM" guarantee; keep **#1** as fallback.

## Why either is safe enough for the two-hook stash

The stash only needs to survive between the LED-hook write and the scanner read — a few ms, entirely within app runtime. The LED routine runs on wake **and on every plug/unplug** (VBUS interrupt, bootloader-invoked), so the stash is **self-healing**: any clobber at boot/sleep is overwritten on the next transition. So the gate is simply "nothing writes this byte during app runtime," which a non-destructive read-back confirms directly.

## Verification plan (do before trusting a byte)

Flash a **read-back diagnostic**: scanner shim reads the candidate byte and exposes it over 2.4GHz (no writing — non-destructive). Exercise the pad hard — sticks/buttons, BT/2.4GHz traffic, plug/unplug, charging — and confirm the byte stays constant (`0` for the bss candidate). Constant ⇒ free ⇒ use it for the real stash. Recovery net (L1+R1 bootloader) remains if a later step misfires.

## Reusable learnings

- **The SVC-mode SP-init constant in cstartup = top of SRAM = the chip's SRAM size.** Read it first to pin the part and the stack base (here `0x844000` ⇒ 16 KB B80).
- **Out-of-SRAM writes fault like "live" RAM.** The `0x847000` brick was an invalid address, not a used one — always bound guesses to `[base, SP_init)`.
- **cstartup is the authoritative RAM map**: its bss-zero bounds, data-copy dst, IC-tag zero, and the two SP loads give data/bss/irq_stk/stack exactly.
- **Pool-word scan + offset tracer** gives a fast app-RAM usage map without Ghidra data-refs (which the TC32 SLEIGH module doesn't emit); treat gaps as candidates to _verify_, not conclusions.
