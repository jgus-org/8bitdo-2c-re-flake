# 8BitDo Ultimate 2C — normal-mode flash read, full flash map, dual-bank, bootloader (v1.09)

Discovered 2026-07-15. All addresses are device flash addresses (the app loads at `0x6000`; app file_offset = addr − 0x6000).

## 1. The app IAP can READ flash in normal mode (no boot-mode flip)

The running controller (`2dc8:310a`, XInput; IAP on intf 2, EP 0x06 out / 0x83 in) speaks the `0x8105` protocol. Its command dispatch (handler entry `0xe15c`, cases at `0xe16c`+) includes **`cmd 0x05` = read** (`0xe3ae`): it reads a length from `report[6:8]` (≤46), a 32-bit address from `report[14:18]`, calls the flash-read routine `0xbf38`, CRCs it, and returns the bytes at `response[18:]` (response prefixed `02 05`). These are the *same* field slots the write protocol uses (the handler works on `&report[2]`).

Request: `[0]=0x81 [1]=0x05 [2]=0x05  [6:8]=len(LE ≤46)  [14:18]=addr(LE32)`. No session or request-CRC needed. Wired into the flasher:

```
flash-2c --target ctrl read <addr> <n> [--out FILE]     # hex, or tolerant file dump
flash-2c --target ctrl scan <lo> <hi> <step>            # 16B sample per step -> flash map
```

**Reads arbitrary flash** (bootloader, both app banks, config). **RAM reads are unreliable** — `0x840000` aliased back to the app image, `0x842e00` returned garbage — so this path is flash-only.

## 2. Full 512 KB flash map

| region | contents |
|---|---|
| `0x0–0x5000` | **resident bootloader** (code; end-to-end real) |
| `0x6000–0x18400` | **app bank A** — stock v1.09, byte-identical to the vendor `.dat` |
| `0x18400–0x40000` | erased (0xff) |
| `0x40000–0x52400` | **app bank B** — a second full app slot |
| `0x52400–0x73000` | erased |
| `0x73000–0x75000` | config + cal data |
| `0x76000` | **MAC** (this unit `6c:6e:31:d8:17:e4`) + flags |
| `0x77000` | small flag/config |
| `0x79000 / 0x7c000 / 0x7f000` | per-device cal/keys (data, not code) |

No third program and no hidden code — just the bootloader, two app banks, and device config/cal. (Per-device MAC/cal/keys are not committed.)

## 3. The device is DUAL-BANK

App bank A (`0x6000`) and bank B (`0x40000`) are two full app slots. **An app-mode flash writes the *inactive* bank and the bootloader swaps to it on reboot**; a boot-mode flash writes physical `0x6000` (bank A). Evidence: after app-flashing a modded image, bank A stayed stock (== vendor `.dat`) while bank B held the mod (its 54-byte diff was exactly our injected trampolines + shims). Consequence: a bad app-flash "bricks" because the crashing bank is made active — recovery is a boot-mode flash of bank A (or, once understood, flipping the active-bank marker). The bank-select logic lives in the bootloader (not yet fully traced).

## 4. The bootloader (`dumps/2c-bootloader-v109.bin`, sha256 `d64d7096…`)

Reproduce: `flash-2c --target ctrl read 0x0 0x6000 --out <file>`.

- It contains its **own** copy of the charge-LED routine at **`0x276e`** — byte-identical logic to the app's `0x70b4` — plus its own `analog_read@0x2444` and `analog_write@0x2484` (same `reg_ana` interface: addr `0x8000b8`, data `0x8000b9`, ctrl `0x8000ba`). **The app's `0x70b4` PM cluster is DEAD** — the bootloader's copy is what runs on charge events. (So hooking the app's LED routine was hooking dead code.)

## 5. Charge-read recipe (why the inline read was stuck, and the fix)

The charge routine **arms** the low-power comparator (`analog_write(0x81, v | 0x40)`), settles ~30 iterations, reads `analog_read(0x88)`, tests **bit5 (0x20)** — then **powers the LPC back off** (`analog_write(0x81, v & 0xbf)`) on exit. So at button-scan time the comparator is unpowered ⇒ a cold read is stuck. The fix, entirely inside the app scanner hook:

1. arm: `analog_write(0x81, analog_read(0x81) | 0x40)`
2. settle (≥30-iteration busy loop)
3. `analog_read(0x88)`; `& 0x20` → nonzero = **VBUS present**

The comparator **reference** `analog_write(0x82, 0x65)` (bit6 set = enabled — **not** `0x85`, which is the sleep/disabled value) and `analog_write(0x34, 0x80)` are already persistent from the app's power-on init, so they don't strictly need re-setting; `charge-inline-ctrl.s` sets them anyway (harmless, removes init-order dependence).

**`0x88` bit5 = voltage-presence** — it reports "on external supply present" and *cannot* distinguish "charging current flowing" from "plugged in, battery full." That is exactly the "on external power (VBUS)" signal wanted, despite 8BitDo labelling it "charging." **bit6 is unused.**

## Reusable learnings

- **The IAP write protocol usually has a matching read** (`cmd 0x05`) using the same header slots — worth probing before assuming a device is write-only or reaching for hardware (SWS). It read the "SWS-only" bootloader over USB.
- **A dual-bank OTA device**: app-flash targets the inactive bank; identical-looking `0x6000` writes can land physically elsewhere. Scan `0x40000` (and the whole flash) to see the real layout.
- **`analog_read(reg)` is only valid while its analog block is powered**; a routine that arms→reads→disarms leaves the value stale for anyone reading cold. Copy the arm+settle, don't just copy the read.
