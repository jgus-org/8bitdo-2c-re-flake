#!/usr/bin/env python3
"""Text-symbolicate a Ghidra TC32 decompilation by rewriting literal-pool tokens to register names.

The TC32 processor module does not emit data references for PC-relative pool loads, so Ghidra
leaves register accesses as `*DAT_<pooladdr>`. This scans the flat payload (loaded at --base) for
4-aligned words whose value is a peripheral register in [0x800000,0x808000), maps each pool
image-address to a name from regmap.tsv, and rewrites every `<prefix>_<pooladdr8hex>` token in the
decompilation to `<name>_p` (pointer-to-register). Emits the rewritten decomp plus a coverage report.
"""

import argparse
import re
import sys
from pathlib import Path

REG_LO, REG_HI = 0x800000, 0x808000


def load_regmap(path):
    m = {}
    if not path:
        return m
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            addr = int(parts[1], 16)
        except ValueError:
            continue
        m.setdefault(addr, parts[0])
    return m


def scan_pools(payload, base):
    """image-address -> register value, for 4-aligned words in the register window."""
    pools = {}
    n = len(payload) & ~3
    for i in range(0, n, 4):
        v = int.from_bytes(payload[i : i + 4], "little")
        if REG_LO <= v < REG_HI:
            pools[base + i] = v
    return pools


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    ap.add_argument("--decomp", required=True)
    ap.add_argument("--regmap", default=None)
    ap.add_argument("--base", default="0x6000")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    base = int(args.base, 16)
    payload = Path(args.payload).read_bytes()
    regmap = load_regmap(args.regmap)
    pools = scan_pools(payload, base)

    # pool image-address (as 8-hex, matching Ghidra token suffix) -> register name
    pool_name = {}
    used = {}
    for pool_addr, regval in pools.items():
        name = regmap.get(regval)
        if not name:
            continue
        pool_name[f"{pool_addr:08x}"] = name + "_p"
        used.setdefault(regval, (name, []))[1].append(pool_addr)

    text = Path(args.decomp).read_text()

    # Rewrite any Ghidra token ending in _<pooladdr8hex> for a mapped pool.
    def repl(match):
        suffix = match.group(2)
        return pool_name.get(suffix.lower(), match.group(0))

    pattern = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*_)([0-9a-fA-F]{8})\b")

    def sub(m):
        return pool_name.get(m.group(2).lower(), m.group(0))

    out_text, n = pattern.subn(
        lambda m: pool_name.get(m.group(2).lower(), m.group(0)), text
    )
    Path(args.out).write_text(out_text)

    lines = []
    lines.append(
        f"payload={args.payload} base={args.base} bytes={len(payload)}"
    )
    lines.append(f"pool words in register window: {len(pools)}")
    lines.append(f"distinct registers referenced: {len(set(pools.values()))}")
    lines.append(
        f"named (in regmap): {len(used)} registers via {len(pool_name)} pool words"
    )
    lines.append(f"token rewrites applied: {n}")
    lines.append("")
    lines.append("register\tname\tpool_image_addrs")
    for regval in sorted(used):
        name, addrs = used[regval]
        lines.append(
            f"0x{regval:08x}\t{name}\t"
            + ",".join(f"0x{a:x}" for a in sorted(addrs))
        )
    report = "\n".join(lines) + "\n"
    if args.report:
        Path(args.report).write_text(report)
    sys.stdout.write(report)


if __name__ == "__main__":
    main()
