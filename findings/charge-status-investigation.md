# 8BitDo Ultimate 2C — charge/VBUS status: what's readable inline, what isn't

Goal: expose charger-connected status (+ battery level) to the host over 2.4 GHz. Battery level works; **live charge status has no software path that leaves the 2.4 GHz link intact.** This documents why, so the decision (hardware vs firmware vs infer) rests on evidence.

## Battery level — works

The app's battery byte (RAM `0x842e04`) is produced by a successive-approximation LC-comparator ADC and relays correctly over 2.4 GHz.

## `0x88` bit5 is the BATTERY comparator, not VBUS

The bootloader routine `@0x276e` (the app's copy `@0x70b4` is dead — the bootloader runs its own) is the battery ADC: arm the LC comparator (`0x81 |= 0x40`), ramp **DAC reg `0x01`** through thresholds (`0x4e`→`0x4b`), read `0x88` bit5 (comparator output vs the DAC), disarm. `reg 0x01` is a threshold DAC, **not** an input mux — no value routes VBUS to the comparator. `0x88` bits 6/7 are comparator power/settle status.

Confirmed on the bench (diagnostic `charge-diag-ctrl.s`): with the LC armed at scan time, `analog_read(0x81)` bit6 = 1 (arm took) and `analog_read(0x82)` bit6 = 1 (reference set) — so **the analog-write path works fine from the scan thread** — yet `0x88` bits 5/6/7 stay constant across a charger plug/unplug cycle. The old "`0x88` bit5 = VBUS" reading was wrong; it's the battery comparator.

## Charging is a separate bootloader measurement `@0x2A68` — live, but RF-hostile

Charger detection is a distinct SAR-style measurement (`@0x2A68`, called from `0x32BC`), separate from battery:

- **Config:** analog `0x06=0xc8`; convert pulse (`0x27fc`: `0x40` bit1 set→clear, `0x05` bit3 set→clear); `0x8c=0x02`, `0x82=0x65`, `0x34=0x80`; `0x0b` keep-bit7; `0x00` clear-bit7; `0x02=0x84`, `0x01=0x4d`; `0x25–0x29=0`.
- **Helpers:** `0x2854` = system-tick timing window; `0x2750` = the LC comparator core (same routine as battery); `0x29c0` = read the 32-bit counter `0x40–0x43` (debounced); `0x2c78` = indirect scaler via bootloader-RAM function pointer `0x843C90`.
- **Result:** status gates `analog_read(0x7e)` bit0 and `analog_read(0x44)` bits 0/2, plus the counter, feed a latch at RAM `0x843B98` that drives the charge LED. `0x800602` bit4 is a power-up/reset wake-status latch (a fast-path gate), not a live bit.
- **Decision is not a clean boolean:** a sanity/overflow gate requires the scaled value to be `0x10000000` or `0xffffffff`, else it writes `reg 0x6f = 0x20` = **chip reboot**.

Why it cannot run from the app's 2.4 GHz scan thread:

- It rewrites the **system-tick timer** (`reg 0x740` — the RF scheduler), **DMA address registers** (`0xc40–0xc4a` — RF TX/RX), and **resets/re-selects the clock tree** (`regs 0x60–0x66` — RF baseband timing).
- It dispatches through a function pointer at bootloader RAM `0x843C90` that the app context never installs (app and bootloader have separate RAM layouts) → `bx` to garbage → crash.
- It reboots the chip on out-of-range readings.

Calling `0x2A68` inherits all of the above. And the minimal "safe subset" — analog config + convert pulse + raw counter read, with **none** of the timer/DMA/clock machinery, the scaler, or the reboot check — **still crashed the controller on the bench** (`charge-diag3-ctrl.s`): the low analog regs `0x00`/`0x02`/`0x06`/`0x0b` gate the clock/core and can't be modified under the running RF app.

## Also ruled out

Read cold (basic arm/reference only, `charge-diag2-ctrl.s`): `0x7e` bit0, `0x44` bits 0/2, and SFR `0x800602` bit4 are all constant across a charger cycle — none is a pollable live VBUS bit.

## Conclusion and paths forward

No software path reads charging without disturbing the 2.4 GHz link; battery is the only power signal the app safely exposes. Options, in order of robustness:

1. **Hardware** — wire the charger STAT/VBUS to a spare GPIO the app already polls (button matrix). An RF-safe live charge bit via a tiny GPIO-read shim. Cost: opening the controller + one solder joint per unit.
2. **Firmware (hard)** — a cooperative task that saves the RF timer/DMA/clock state, runs the measurement in a gap between packets, and restores everything. Large and risky (subtle RF glitches likely); no guarantee it lands.
3. **Battery-trend inference** (software-only, host-side) — battery level rises while charging; infer "charging" from a sustained upward trend. Hacky and laggy, zero firmware/hardware change.

## Resolution — the goal was met from the charger side, not the controller

The real requirement was "treat a controller as **off** while it charges on its designated home charger" (so eight controllers on a dock don't each steal a player slot). That needs nothing from the controller firmware. On k1 (`machine/k1/charge-dock.nix`): the home charger is a dedicated USB hub; a udev rule unbinds every interface of any 8BitDo controller under that hub's topology path, so a docked controller enumerates (draws charge current) but has **no input device** — while controllers on 2.4 GHz or any other charger are untouched. The firmware charge-status work above is therefore parked as "not feasible without a hardware GPIO mod"; the product goal is solved.

## Diagnostic evidence (shims removed in #138)

Three throwaway shims established the negative result, then were removed:

- arm/reference/`0x88` readback proved writes land from the scan thread — and `0x88` is the battery comparator, not VBUS.
- a cold probe of `0x7e`/`0x44`/`0x800602` — none track VBUS.
- the RF-hostile config subset **crashed the app on the bench** (the low analog regs `0x00`/`0x02`/`0x06`/`0x0b` gate clock/core under the running RF app).
