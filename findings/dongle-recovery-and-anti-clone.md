# 8BitDo Ultimate 2C dongle — flash layout, anti-clone boot gate, brick recovery

Discovered 2026-07-15 while recovering a dongle bricked by a mis-targeted flash. Addresses are device flash addresses.

## How the dongle got bricked (and the guard against it)

`flash-2c --target ctrl` selects USB PID `0x310a`. A controller connected over 2.4 GHz makes the **dongle** enumerate as `0x310a` (it relays the controller), so a `--target ctrl` app-flash issued while the controller is wireless writes the **dongle**, not the controller. The controller image (`0x12400` bytes) overran the dongle's `0xA000` app into its descriptor/cal/link-ID sectors and set a pending-OTA descriptor pointing at a truncated staged image → dongle stuck in its bootloader (`0x3208`).

Guard: `flash2c.py` now reads the target's own flash before a full-app flash and refuses a firmware/device-kind mismatch (`_device_kind` reads `0x10000` — blank on a dongle, app code on a controller; `_payload_kind` classifies by size). Override with `--force`.

## Flash layout (128 KB part; the controller is a separate 512 KB part)

Reads above `0x20000` alias (128 KB chip).

| region | contents |
|---|---|
| `0x0–0x6000` | resident bootloader |
| `0x6000–0x10000` | bank A — active app (`0xA000`) |
| `0x10000–0x12000` | erased |
| `0x12000` | OTA descriptor |
| `0x13000–0x1d000` | bank B — app copy (`== bank A` on stock) |
| `0x1e000` | `CFG_ADR_CALIBRATION` — per-chip RF/ADC trim |
| `0x1f000` | anti-clone link-identity signature — per-chip |

Dual-bank OTA: an app-mode flash writes the *inactive* bank and updates the descriptor; a boot-mode flash writes physical addresses. `bank A == bank B` on stock, so bank B is rebuildable from bank A (or from a matching-version reference).

## OTA descriptor `@0x12000`

52-byte record: `[0x0c]` version, `[0x18]` crcA, `[0x1c]` staging address (`0x13000`), `[0x20]` pending-update length, `[0x30]` crcB. Stock has **len=0** ("no pending update → boot bank A"). A nonzero len makes the bootloader try to activate the image staged at `0x13000`; a bad/truncated staged image traps it in the bootloader. crcB is over bank A, so it is **version-keyed**: `0x1e05` for v1.03, `0x3845` for v1.00 — identical across same-version units, differs across versions. Restore from a same-version reference.

## Boot gate: `0x1f000` is a silicon-bound anti-clone signature

The **bootloader** (not the app) gates boot on `0x1f000`. At boot it reads the flash chip's 16-byte hardware unique ID (SPI cmd `0x4B`), folds it into a 6-byte value `B`, and requires the 12-byte record at `0x1f000` to equal a table function of `B`. Blank or wrong `0x1f000` → stays in the bootloader (`0x3208`). `0x1e000` does **not** gate boot — a blank cal sector just makes the app fall back to default trim (minor RF-margin loss), so a lost/erased `0x1e000` is survivable and must **not** be copied from another unit (it is that die's trim).

The record is neither a MAC nor freely assignable — it is fixed by the silicon:

```
T = [0xd4284deb,0xf14aa66c,0x8c2571d4,0x8f67dfc9, 0xd0859ae1,0xe5457a30,0x217c1783,0xb61ddfa9,
     0xe65ad00d,0x6620b8a3,0x52176f92,0x80a2dd5b, 0x8f861560,0x0b728b0f,0xaecc9b4d,0x3c9ba353]
n = [b & 0x0F for b in B]                          # only the low nibbles matter
record = LE32(T[n0]^T[n3]) ++ LE32(T[n4]^T[n1]) ++ LE32(T[n5]^T[n2])
```

Fold (needed only if deriving from the raw unique ID rather than reading `B` directly):

```
B[0..3] = uid[0..3] ^ uid[8..11]
B[4] = ((uid[4]^uid[12]) + (uid[6]^uid[14])) & 0xFF
B[5] = ((uid[5]^uid[13]) + (uid[7]^uid[15])) & 0xFF
```

The record is low-entropy (each word is one of ≤256 `T[i]^T[j]` values) and can collide across units, so it is not a unique identifier — the uniqueness lives in the silicon unique ID.

## Reading `B` over USB (no SWS/hardware needed)

The bootloader exposes `B` via a sub-command of the boot read: `cmd=5`, `sub-command=6`, `magic=0x80000002`. Through the flasher framing that is:

```
flash-2c --target boot read 0x80000002 6
```

(the sub-command lands in the length field, the magic in the address field). `B` = the 6 returned bytes. Sanity: a v1.03 golden unit's `B` low-nibbles are `[0, 0xb, 0x9, 0x2, 0x8, 0x2]`. Note `read` aliases `0x84xxxx` to flash — it cannot reach SRAM; this sub-command is the only way to get `B`/the unique ID over USB.

## Recovery recipe (all over the bootloader USB protocol)

1. **Boot structure**: boot-flash `dumps/2c-dongle-reference-v103.bin` (per-device sectors blank), or — if bank A already holds correct stock — write just descriptor+bank B (`ref[0x12000:0x1d000]` then `ff` to `0x20000`) at `0x12000`.
2. **Read `B`**: `flash-2c --target boot read 0x80000002 6`.
3. **Compute** the 12-byte record (table + formula above).
4. **Write**: `flash-2c --target boot flash <rec.bin> --addr 0x1f000 --verify`.
5. Leave `0x1e000` blank. Power-cycle → boots (`0x301c`). The already-paired controller reconnects without re-pairing.

## Reusable learnings

- **A relaying dongle is indistinguishable from a wired controller by USB PID** (`0x310a`). Confirm device type by reading its flash before flashing, never by PID alone.
- **Anti-clone/HW-bound boot gates are recoverable in software if the bootloader exposes the derived key** — look for an undocumented sub-command before assuming a hardware attack is required.
- **Per-chip data classifies by diffing several stock units**: bytes that vary across units are identity/cal (unrecoverable by transplant); bytes constant across a firmware version are safe to restore from any same-version reference.
