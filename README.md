# 8BitDo Ultimate 2C firmware flake

A Nix flake for the [8BitDo Ultimate 2C Wireless Controller](https://www.8bitdo.com/ultimate-2c-wireless-controller/) and its 2.4 GHz USB dongle: the vendor firmware images pinned as fixed-output derivations, patched firmware payloads built from them, a Telink TC32 reverse-engineering workbench, a USB flasher, and a host-side `xpad` kernel patch that surfaces what the patched firmware reports. The firmware itself comes from 8BitDo's own update API (`http://dl.8bitdo.com:8080`); the Ghidra processor module from [trust1995/Ghidra_TELink_TC32](https://github.com/trust1995/Ghidra_TELink_TC32) and the TC32 binutils from [flyskywhy/tc32](https://github.com/flyskywhy/tc32).

```nix
inputs.bitdo-2c-re.url = "github:jgus-org/8bitdo-2c-re-flake";
```

## Outputs

| Output                                                                      | What you get                                                                                                                                                              |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `packages.default` (= `ghidra-tc32`)                                        | Ghidra with the Telink TC32 processor module, SLEIGH precompiled, registered through `NIX_GHIDRAHOME`.                                                                    |
| `packages.fw-ctrl-v109`, `fw-ctrl-v106`, `fw-dongle-v103`, `fw-dongle-v100` | A vendor `.dat` exactly as 8BitDo serves it (ebitdo header intact). `v109`/`v103` are the current builds; `v106`/`v100` are the factory images, kept for version diffing. |
| `packages.payload-<target>`                                                 | The same image minus its 28-byte ebitdo header — the bytes that land at flash address `0x6000`. This is what Ghidra loads and what the flasher writes.                    |
| `packages.mod-battery-ctrl-v109`                                            | Controller payload with 0–100 battery level folded into spare button-word bits and the USB product name rebranded to **Ultima+e**.                                        |
| `packages.mod-batt-l4r4-dongle-v103`                                        | Dongle payload that relays battery level into report byte 18 and L4/R4/Square into byte 19.                                                                               |
| `packages.flash-2c`                                                         | The flasher, with python + pyusb + libusb wired in: `flash-2c --target ctrl                                                                                               | dongle | boot probe | flash | read | gen`. |
| `packages.update-all`                                                       | `flash-2c` on autopilot: flashes every plugged-in `2dc8` device with the two mods above.                                                                                  |
| `packages.refetch-firmware`                                                 | Ask the vendor API for the currently published build of a device type (75 controller, 76 dongle, 77 wired).                                                               |
| `packages.tc32-tools`                                                       | Telink's `tc32-elf-{as,ld,objcopy,objdump}`, patchelf'd for nix.                                                                                                          |
| `devShells.default`                                                         | The RE workbench: `ghidra`, `rizin`, `binwalk`, `binutils`, `file`, `ripgrep`, `jq`, `curl`, `python3`, `refetch-firmware`.                                               |
| `checks.flash-template-ctrl`, `checks.flash-template-dongle`                | Regenerate the flash command stream from a stock payload and diff it byte-for-byte against a captured vendor stream.                                                      |
| `nixosModules.xpad-2c-charge`                                               | The host half of the mods, as a NixOS module.                                                                                                                             |

```bash
nix build 'github:jgus-org/8bitdo-2c-re-flake#payload-ctrl-v109'
nix run 'github:jgus-org/8bitdo-2c-re-flake#flash-2c' -- --target ctrl probe
nix develop 'github:jgus-org/8bitdo-2c-re-flake'
```

## NixOS module

`nixosModules.xpad-2c-charge` installs the `xpad` kernel patch, which registers a power supply per pad (`/sys/class/power_supply/xpad-*`, battery percentage) and decodes the relayed L4/R4/Square bits.

```nix
imports = [ inputs.bitdo-2c-re.nixosModules.xpad-2c-charge ];
```

## Platform support

Packages, checks and the devshell are published for **x86_64-linux only**. The patched payloads are assembled with Telink's prebuilt x86-64 `tc32-elf` binaries, which run on the build host; no other host can produce them. `nixosModules.xpad-2c-charge` is not per-system and carries no such restriction.

## Runtime assumptions

- The flake pins its own nixpkgs (`nixos-26.05`). Its packages are built there, not against a consuming flake's package set.
- `flash-2c` and `update-all` open the USB device directly, which needs root (or an equivalent grant on the device node). Controller in normal mode enumerates as `2dc8:310a`, an idle dongle as `2dc8:301c`, and the resident bootloader as `2dc8:3208` — entered by holding **L1+R1 while plugging in**.
- The kernel patch is a `boot.kernelPatches` source patch against `drivers/input/joystick/xpad.c`: switching it on rebuilds the host kernel, and it is written against the xpad source of the kernel this flake was developed with.

## Licences

`.dat` images are 8BitDo's own firmware: `fw-*`, `payload-*` and `mod-*` outputs contain vendor code, and the modified payloads are derivative works of it. `dumps/` holds raw flash content read off the hardware. The TC32 binutils are third-party redistributions of Telink's toolchain, fetched as binaries. Nothing here is licensed by this repository — there is no licence file for the scripts, patches and notes in it.

## Sharp edges

- `update-all` **writes firmware to every plugged-in `2dc8` device**. `--dry-run` prints the plan; controllers already reading `Ultima+e` are skipped unless `--force`, and dongles always re-flash. A bad app image is re-flashable through the `2dc8:3208` bootloader, which survives an app that no longer enumerates; single-wire debug is the last resort for a corrupt bootloader.
- Each patch site asserts the stock bytes it overwrites, and the addresses are those of the pinned images. A `mod-*` derivation fails to build against any other firmware version rather than producing a best-effort patch.
- Only the controller mod is visible over USB. The dongle's product strings sit above its `0x7000`-byte app write window, so a flashed dongle keeps its stock name.
- The kernel module's battery supply and extra buttons appear only for a pad running the modded firmware; against stock firmware the patch is inert.
- Ghidra scripts here must be **Java**. Ghidra 12 runs `.py` scripts through PyGhidra (CPython), which plain `analyzeHeadless` does not start.

## Loading a payload in Ghidra

The payload is a raw Telink B80 (TC32 core) image, unencrypted: 28-byte header stripped, image base `0x6000`, language `Telink_TC32:LE:16:default`, registers mapped at `0x800000` (length `0x8000`) if you need them in the memory map. The command below assumes a checkout of this repository, which ships the `scripts/` it points at.

```bash
mkdir -p proj
ghidra-analyzeHeadless proj ctrl -import result \
  -processor Telink_TC32:LE:16:default \
  -loader BinaryLoader -loader-baseAddr 0x6000 \
  -scriptPath scripts -postScript ReportStats.java
```

The project directory must already exist. `ReportStats.java` reports loaded blocks and instruction/function counts; `payload-ctrl-v109` yields 6086 instructions across 98 functions.

## Notes

[findings/FINDINGS.md](findings/FINDINGS.md) is the vetted synthesis of what the firmware does (charging gate, extra buttons, force feedback, flashing). [NOTES.md](NOTES.md) is the running RE log and the protocol detail behind the flasher, [flasher/README.md](flasher/README.md) its command reference, and `scripts/` the headless Ghidra analysis pipeline.
