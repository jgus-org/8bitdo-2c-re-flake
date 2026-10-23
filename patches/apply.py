#!/usr/bin/env python3
"""Apply byte patches to a firmware payload: assembled shim placements, then python patch modules.

Usage: apply.py <base.bin> <out.bin> [--load-base ADDR] [--place IMGADDR:OLDHEX:BIN]... [patch.py]...
Each --place writes the bytes of BIN at file offset IMGADDR - load-base, asserting the slot
currently equals OLDHEX (same length). Each patch module exposes `patch(data: bytearray)` and
mutates in place. Total length is preserved (the flash templates substitute at fixed offsets),
enforced below.
"""

import argparse
import importlib.util
import sys

ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("out")
ap.add_argument(
    "--load-base", default="0x0", help="img address of payload offset 0"
)
ap.add_argument(
    "--place", action="append", default=[], metavar="IMGADDR:OLD:BIN"
)
ap.add_argument("patches", nargs="*")
args = ap.parse_args()

load_base = int(args.load_base, 0)
data = bytearray(open(args.base, "rb").read())
n0 = len(data)

for spec in args.place:
    off_s, old_h, binpath = spec.split(":")
    off = int(off_s, 0) - load_base
    old = bytes.fromhex(old_h)
    new = open(binpath, "rb").read()
    assert data[off : off + len(old)] == old, (
        f"place @0x{off:x}: expected {old.hex()}, found {data[off : off + len(old)].hex()}"
    )
    assert len(new) == len(old), (
        f"place @0x{off:x}: assembled {len(new)} bytes != slot {len(old)}"
    )
    data[off : off + len(new)] = new
    print(f"placed {len(new)}B @0x{off:x} from {binpath}", file=sys.stderr)

for pf in args.patches:
    spec = importlib.util.spec_from_file_location("patch", pf)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.patch(data)
    print(f"applied {pf}", file=sys.stderr)

assert len(data) == n0, f"patch changed image length {n0} -> {len(data)}"
open(args.out, "wb").write(data)
