# 8BitDo Ultimate 2C flasher

`flash2c.py` drives two plaintext flash protocols (no signature), both **generated from protocol knowledge** — no captured-sequence replay. Protocol byte layouts are in [../NOTES.md](../NOTES.md).

- **App IAP (`0x8105`)** on the running controller (`2dc8:310a`, intf 2, EP 0x06) or idle dongle (`2dc8:301c`, intf 0, EP 0x05). The full command stream — session handshake, per-4 KB-sector `0xc3` erase + `0x04` begin + `0x03` data, a verify-burst re-issuing every sector's `0xc3`, then `0xc4` finalize + `0x07` reset — is built from the payload. Validated **byte-for-byte** against the captured vendor templates (see *Validation* below).
- **Bootloader (`0x3208`)** address protocol, reversed from `8BitDoFirmwareUpdaterTools.dll`: erase/write/read by device address. Recovers a controller whose app crashes before USB enumeration (no `310a`). Enter by holding **L1+R1** while plugging in.

Data blocks in both protocols carry a **CRC-16/MODBUS**. App per-sector addresses are 0-based; the bootloader's are absolute (app base `0x6000` = payload offset 0).

## Commands

- `--target X probe` — **non-destructive**. App: session-start → `0x0222`/`0x0205` ACK. Boot: get-boot-version. (First app probe after a reboot may need a few `--retries`.)
- `--target X flash <payload.bin>` — flash a raw (stripped) payload. App: generated `0x8105` stream. Boot: erase + address writes, `--verify` reads back and compares. `--version V` overrides the version byte stamped into `0xc4` (default per target). `--limit N` (app) sends only the first N reports.
- `--target boot read <addr> <n>` — read device flash (bootloader only).
- `--target X gen <payload.bin> [--template T]` — **offline**, no hardware: build the app sequence, and with `--template` diff it byte-for-byte against a captured template.

## Mass flashing (`nix run .#update-all`)

Enumerates every plugged-in `2dc8` device and flashes each with its production payload (both mods baked into the app): idle dongles (`0x301c`) get the dongle relay, wired controllers (`0x310a`) get the controller shim. A `0x310a` that a `0x10000` read shows to be a **dongle relaying a controller** is skipped — flash a dongle by idling it (unplug the pad), a controller by wiring it directly. Controllers already reading `Ultima+e` are skipped unless `--force` (dongles carry no in-window brand, so they always re-flash); `--dry-run` reports the plan without flashing. Needs root for USB.

## Targets (`--target`)

| target | device | mode | intf | OUT | IN | when |
|---|---|---|---|---|---|---|
| `ctrl` | `2dc8:310a` controller, XInput | app | 2 | 0x06 | 0x83 | pad running on USB |
| `dongle` | `2dc8:301c` dongle, IDLE | app | 0 | 0x05 | 0x84 | dongle on USB |
| `boot` | `2dc8:3208` bootloader | boot | 0 | 0x05 | 0x84 | pad in L1+R1 mode |

The `dongle` app profile writes only its `0x7000`-byte app region while `0xc4` declares the full payload length — a vendor quirk baked into `TARGETS`.

## Validation (`../test/*.tmpl` fixtures)

`../test/ctrl-v109-flash.tmpl` / `../test/dongle-v103-flash.tmpl` are the captured vendor command streams (from Ultimate Software V2), the oracle for `gen --template`, which proves the generator reproduces the official byte stream exactly. The flake's `checks.flash-template-{ctrl,dongle}` run this diff against the stock payloads, so `nix flake check` fails on any generator regression.

## Running it (Linux, needs root for USB)

The flake output `flash-2c` bundles `flash2c.py` in a python+pyusb+libusb env — it *is* the tool:

```
nix shell 'github:jgus-org/8bitdo-2c-re-flake#flash-2c' --command flash-2c --target ctrl probe
```

To iterate on the script itself, run it from a checkout in the same env: `nix shell .#flash-2c --command python3 ./flash2c.py …`.

## Safe sequence

1. `--target ctrl probe` — flasher talks to the running pad (`0x0222` ACK).
2. `--target ctrl gen stock.bin --template ../test/ctrl-v109-flash.tmpl` — offline sanity: generator matches the oracle (also run by `nix flake check`).
3. `flash stock.bin` (app) — re-flash stock; validates the write path with an unmodified image.
4. A real patch.

Recovery net: a bad app is re-flashable via the bootloader (`--target boot`, `2dc8:3208`), which survives a dead app that no longer enumerates as `310a`; hardware SWS is the last resort for a corrupt bootloader.
