# 8BitDo Ultimate 2C firmware RE

Reverse-engineering workbench and flasher for the 8BitDo Ultimate 2C wireless controller and its 2.4 GHz USB dongle. Standalone, self-contained flake (own pinned nixpkgs + tools). `nix run github:jgus-org/8bitdo-2c-re-flake#update-all` flashes every plugged-in pad with the production firmware.

**Status: shipped.** The original goal — charging pads claiming low gamepad slots on k1 ([jgus-org/tickets#120](https://github.com/jgus-org/tickets/issues/120)) — is resolved *charger-side*: `machine/k1/charge-dock.nix` unbinds a docked pad's input drivers on the designated charging hub, so it charges but claims no slot (no controller firmware involved). Bonus firmware also landed ([#123](https://github.com/jgus-org/tickets/issues/123)): unscaled 0-100 battery % + L4/R4/Square over 2.4 GHz via `patches/battery-ctrl.s` (controller) + `patches/batt-l4r4-dongle.s` (dongle) + this flake's `nixosModules.xpad-2c-charge` kernel patch (host); the controller mod also rebrands it **Ultima+e** so a flashed pad is visibly distinct in `lsusb`. Parked / won't-do: live charge-status over 2.4 GHz ([#121](https://github.com/jgus-org/tickets/issues/121) — VBUS isn't inline-readable), BT force-feedback ([#122](https://github.com/jgus-org/tickets/issues/122)), SWS rig ([#124](https://github.com/jgus-org/tickets/issues/124) — the bootloader dumps over USB instead). Follow-ups: tooling cleanup [#138](https://github.com/jgus-org/tickets/issues/138), fleet rollout [#139](https://github.com/jgus-org/tickets/issues/139).

**Results so far:** [findings/FINDINGS.md](findings/FINDINGS.md) is the vetted decision-grade synthesis (charging gate, BT/FF, extra buttons, flashing). The analysis pipeline (scripts + `symbolicate.py`) is documented in [NOTES.md](NOTES.md).

## NixOS module

`nixosModules.xpad-2c-charge` applies the host kernel patch (`patches/xpad-2c-charge.patch`) via `boot.kernelPatches` — the driver half that surfaces the FW mods' battery % (`/sys/class/power_supply/xpad-*`) and L4/R4/Square. Consume it:

```nix
inputs.bitdo-2c-re.url = "github:jgus-org/8bitdo-2c-re-flake";
# then in the host's modules:
imports = [ inputs.bitdo-2c-re.nixosModules.xpad-2c-charge ];
```

## Quick start

```bash
git clone https://github.com/jgus-org/8bitdo-2c-re-flake && cd 8bitdo-2c-re-flake
nix develop            # or: direnv allow
```

The devshell provides `ghidra` (with the Telink TC32 processor module), `rizin`, `binwalk`, `binutils`, `file`, and `refetch-firmware`.

## Provenance chain (derivations)

Firmware is pinned as fixed-output derivations off 8BitDo's live API, then reduced to the flashed image:

| Target | What it is |
|---|---|
| `nix build .#fw-ctrl-v109` | Controller firmware v1.09, raw `.dat` (ebitdo header intact) |
| `nix build .#fw-dongle-v103` | Dongle firmware v1.03, raw `.dat` |
| `nix build .#payload-ctrl-v109` | Controller payload — header stripped, ready for Ghidra |
| `nix build .#payload-dongle-v103` | Dongle payload |
| `nix build .#ghidra-tc32` | Ghidra + Telink TC32 module (SLEIGH precompiled) |

Factory versions (`ctrl-v106`, `dongle-v100`) are pinned too, for version diffing.

`refetch-firmware <type>` re-queries the API for the *current* published build (75=controller, 76=dongle, 77=wired) — use it to discover new releases, then add the URL+hash to `flake.nix`.

## Loading a payload in Ghidra

GUI:

1. Import a `payload-*.bin`, language **Telink_TC32:LE:16:default**.
2. Set the image base to **0x6000** (fall back to 0x0 if absolute pointers don't resolve).
3. Registers live at 0x00800000 (len 0x8000) for the 826x family — add via Memory Map if needed.

Headless (reproducible; the project directory must already exist):

```bash
mkdir -p proj
ghidra-analyzeHeadless proj ctrl -import result-payload \
  -processor Telink_TC32:LE:16:default \
  -loader BinaryLoader -loader-baseAddr 0x6000 \
  -scriptPath scripts -postScript ReportStats.java
```

`ReportStats.java` reports the loaded blocks + instruction/function counts (sanity check). A verified baseline for `payload-ctrl-v109` is **6086 instructions / 98 functions**. Ghidra scripts here **must be Java** — Ghidra 12 runs `.py` scripts through PyGhidra (CPython), which plain `analyzeHeadless` does not start.

See [NOTES.md](NOTES.md) for the format details, chip ID, string-analysis findings, the Ghidra-12 packaging gotcha, and the running RE log.

## Format & chip (summary)

- `.dat` = fwupd **ebitdo** container: 28-byte LE header + raw payload; `filesize − dest_len == 28`.
- Chip = **Telink B80 (TLSR825x-class), TC32 core** — a proprietary ARM9-Thumb-like ISA.
- Payload is **not encrypted** (entropy ~6.9 bits/byte). No key needed — strip 28 bytes and disassemble.

## Flashing

Modified images flash without a signature: `flasher/flash2c.py` drives the raw IAP (`0x8105` HID) and bootloader (`0x3208` address) protocols directly, generated from protocol knowledge and validated byte-for-byte against the vendor stream (`nix flake check`). `nix run .#update-all` flashes every plugged-in device with its production firmware. See [flasher/README.md](flasher/README.md).
