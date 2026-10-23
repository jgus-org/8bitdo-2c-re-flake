#!/usr/bin/env python3
"""Unified 8BitDo Ultimate 2C flasher — two on-wire protocols, both plaintext (no signature).

App IAP (0x8105), on the running controller (2dc8:310a, intf 2, EP 0x06) or idle dongle (2dc8:301c, intf 0, EP 0x05): the whole command stream is GENERATED from the payload — session handshake, per-4KB-sector erase(0xc3)+begin(0x04)+data(0x03), a verify-burst re-issuing every sector's 0xc3, then finalize(0xc4)+reset(0x07). Validated byte-for-byte against captured vendor templates via `gen --template`.

Bootloader (2dc8:3208, intf 0, EP 0x05; enter with L1+R1 held), an address-based protocol reversed from 8BitDoFirmwareUpdaterTools.dll: erase/write/read by device address — recovers an app that no longer enumerates as 310a. Details in ../NOTES.md.

Data blocks in both protocols carry a CRC-16/MODBUS. The app's per-sector addresses are 0-based; the bootloader's are absolute (app base 0x6000 = payload offset 0).
"""

import argparse
import sys
import time

import usb.core
import usb.util

VID = 0x2DC8

# App profiles carry the vendor's per-device quirks: session-handshake repeat counts, the firmware version stamped into 0xc4, and (dongle only) a write_len smaller than the payload — its IAP rewrites just the 0x7000-byte app region while 0xc4 still declares the full length. Boot has no such profile.
TARGETS = {
    "ctrl": dict(
        pids=[0x310A],
        intf=2,
        ep_out=0x06,
        ep_in=0x83,
        mode="app",
        s_start=4,
        s_end=2,
        version=0x6D,
    ),
    "dongle": dict(
        pids=[0x301C],
        intf=0,
        ep_out=0x05,
        ep_in=0x84,
        mode="app",
        s_start=1,
        s_end=1,
        version=0x67,
        write_len=0x7000,
    ),
    "boot": dict(pids=[0x3208], intf=0, ep_out=0x05, ep_in=0x84, mode="boot"),
}
APP_BASE = 0x6000


def crc16(d):
    c = 0xFFFF
    for x in d:
        c ^= x
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c & 0xFFFF


# ---- app IAP (0x8105) sequence generator ----


def _app(cmd):
    r = bytearray(64)
    r[0], r[1], r[2] = 0x81, 0x05, cmd
    return r


def _app_data(cmd, data, crc=None, off=0, len10=True):
    r = _app(cmd)
    r[6:8] = len(data).to_bytes(2, "little")
    r[8:10] = (crc16(data) if crc is None else crc).to_bytes(2, "little")
    if len10:
        r[10:14] = len(data).to_bytes(4, "little")
    r[14:18] = off.to_bytes(4, "little")
    r[18 : 18 + len(data)] = data
    return bytes(r)


def _sectors(lo, hi):
    return [(a, min(0x1000, hi - a)) for a in range(lo, hi, 0x1000)]


def _r00():
    r = _app(0x00)
    r[3], r[4] = 0x21, 0x01
    return bytes(r)


def _rc1():
    return bytes(_app(0xC1))


def _rc3(addr, ln):
    return _app_data(
        0xC3,
        addr.to_bytes(4, "little") + ln.to_bytes(4, "little") + b"\xcc" * 4,
        len10=False,
    )


def _r04(sec):
    r = _app(0x04)
    r[14:18] = sec.to_bytes(4, "little")
    return bytes(r)


def app_sequence(payload, t, version=None):
    version = t["version"] if version is None else version
    total = len(payload)
    write = min(t.get("write_len", total), total)
    seq = []
    for _ in range(t["s_start"]):
        seq += [_r00(), _rc1()]
    for a, ln in _sectors(0, write):
        seq += [_rc3(a, ln), _r04(a)]
        for o in range(0, ln, 46):
            seq.append(
                _app_data(
                    0x03, payload[a + o : a + o + min(46, ln - o)], off=a + o
                )
            )
    for a, ln in _sectors(
        write, total
    ):  # tail sectors: 0xc3 without data (dongle only)
        seq.append(_rc3(a, ln))
    for a, ln in _sectors(0, total):  # verify burst
        seq.append(_rc3(a, ln))
    seq += [
        _app_data(
            0xC4, total.to_bytes(4, "little") + version.to_bytes(4, "little")
        ),
        _app_data(0x07, b"\x00" * 8, crc=0),
    ]
    for _ in range(t["s_end"]):
        seq += [_r00(), _rc1()]
    return seq


# ---- bootloader (address) protocol ----


def _boot(cmd, addr=0, param4=0, datalen=0, data=b"", crc=0):
    r = bytearray(64)
    r[0] = 0x05
    r[1:3] = cmd.to_bytes(2, "little")
    r[5:7] = datalen.to_bytes(2, "little")
    r[7:9] = crc.to_bytes(2, "little")
    r[9:13] = param4.to_bytes(4, "little")
    r[13:17] = addr.to_bytes(4, "little")
    r[17 : 17 + len(data)] = data
    return bytes(r)


def boot_xfer(dev, t, report, cmd, timeout=3000):
    dev.write(t["ep_out"], report, timeout)
    for _ in range(
        6
    ):  # a slow op (erase) may answer with a ZLP before the real response
        try:
            r = bytes(dev.read(t["ep_in"], 64, timeout))
        except usb.core.USBError:
            return False, None
        if len(r) >= 5:
            return (r[0] == 0 and r[1] == 5 and r[2] == 0 and r[4] == cmd), r
    return False, b""


def boot_read(dev, t, addr, n):
    out = bytearray()
    while len(out) < n:
        k = min(46, n - len(out))
        ok, r = boot_xfer(
            dev, t, _boot(5, addr=addr + len(out), param4=k, datalen=k), 5
        )
        if not ok:
            return None
        out += r[18 : 18 + k]
    return bytes(out[:n])


# ---- shared USB ----


def open_target(name, sel=None):
    t = TARGETS[name]
    if sel:
        bus, addr = (int(x, 0) for x in sel.split(":"))
        dev = usb.core.find(idVendor=VID, bus=bus, address=addr)
        if dev is None:
            raise SystemExit(f"no {VID:#06x} device at {sel}")
    else:
        dev = next(
            (
                d
                for pid in t["pids"]
                if (d := usb.core.find(idVendor=VID, idProduct=pid))
            ),
            None,
        )
        if dev is None:
            raise SystemExit(
                f"no {VID:#06x} device for target '{name}' (PIDs {[hex(p) for p in t['pids']]})"
            )
    for i in range(dev.get_active_configuration().bNumInterfaces):
        try:
            if dev.is_kernel_driver_active(i):
                dev.detach_kernel_driver(i)
        except (usb.core.USBError, NotImplementedError) as e:
            print(f"warn: detach interface {i}: {e}", file=sys.stderr)
    usb.util.claim_interface(dev, t["intf"])
    print(
        f"opened '{name}': {VID:#06x}:{dev.idProduct:#06x} intf {t['intf']} out {t['ep_out']:#04x} in {t['ep_in']:#04x}",
        file=sys.stderr,
    )
    return dev, t


def cmd_probe(args):
    dev, t = open_target(args.target, args.dev)
    if t["mode"] == "boot":
        ok, r = boot_xfer(dev, t, _boot(8, param4=4, datalen=4), 8)
        print(
            "boot-version response:",
            r.hex()[:36] if r else "(none)",
            "->",
            "OK type=0x%04x" % (r[16] | r[17] << 8) if ok else "no ACK",
        )
    else:
        resp = None
        for _ in range(args.retries):
            dev.write(t["ep_out"], bytes(_r00()), 800)
            try:
                resp = bytes(dev.read(t["ep_in"], 64, 800))
                break
            except usb.core.USBError:
                continue
        ack = resp and resp[0:2] in (b"\x02\x05", b"\x02\x22")
        print(
            "session-start response:",
            resp.hex() if resp else "(timeout)",
            "->",
            "ACK" if ack else "no ACK",
        )
    usb.util.release_interface(dev, t["intf"])


def app_flash(dev, t, payload, version, limit):
    seq = app_sequence(payload, t, version)
    n = limit or len(seq)
    print(
        f"app-flashing {n} generated reports — DO NOT INTERRUPT",
        file=sys.stderr,
    )
    ok = bad = i = 0
    for i, r in enumerate(seq[:n]):
        try:
            dev.write(t["ep_out"], r, 3000)
        except usb.core.USBError as e:
            print(
                f"[{i}] write ended (reset reboot on 0x07): {e}",
                file=sys.stderr,
            )
            break
        resp = None
        for _ in range(4):
            try:
                resp = bytes(dev.read(t["ep_in"], 64, 800))
                break
            except usb.core.USBError:
                continue
        if resp is not None and resp[0:2] in (b"\x02\x05", b"\x02\x22"):
            ok += 1
        else:
            bad += 1
            if bad <= 12:
                print(
                    f"[{i}] cmd {r[2]:#04x}: no/odd ACK {resp[:8].hex() if resp else '(none)'}",
                    file=sys.stderr,
                )
        if i % 200 == 0:
            print(f"  {i}/{n} ok={ok} bad={bad}")
    print(
        f"done: {i + 1}/{n}, acked {ok}, other {bad}. Pad reboots — replug + `probe` to confirm."
    )


def boot_flash(dev, t, payload, verify, addr=APP_BASE):
    n = len(payload)
    print(f"boot-flashing {n} bytes to 0x{addr:x}", file=sys.stderr)
    ok, r = boot_xfer(
        dev,
        t,
        _boot(4, addr=addr, param4=(n + 0xFFF) & ~0xFFF),
        4,
        timeout=8000,
    )
    if not ok:
        raise SystemExit(f"erase failed: {r[:8].hex() if r else 'no ack'}")
    bad = 0
    for off in range(0, n, 46):
        blk = payload[off : off + 46]
        ack, _ = boot_xfer(
            dev,
            t,
            _boot(
                3,
                addr=addr + off,
                param4=n,
                datalen=len(blk),
                data=blk,
                crc=crc16(blk),
            ),
            3,
        )
        bad += not ack
        if off % (46 * 400) == 0:
            print(f"  {off}/{n} bad={bad}")
    print(f"boot write done, {bad} rejected")
    if verify:
        rb = boot_read(dev, t, addr, n)
        print("verify:", "MATCH" if rb == payload else "MISMATCH")


# A controller's app spans past 0x10000; a dongle's app ends at 0x10000 with the rest blank. Sizes: dongle ~0xa000, controller ~0x12400.
APP_KINDS = {"dongle": (0x8000, 0xC000), "ctrl": (0x10000, 0x16000)}


def _payload_kind(payload):
    n = len(payload)
    return next(
        (k for k, (lo, hi) in APP_KINDS.items() if lo <= n <= hi), None
    )


def _wake_app(dev, t, retries=10, debug=False):
    """Open the app IAP session (0x00 + 0xc1) until it ACKs. The controller's read/write path stays inert until this handshake — the dongle answers cold, the controller does not. Non-destructive: the same session ping as `probe`, no erase/write."""
    for i in range(retries):
        try:
            dev.write(t["ep_out"], bytes(_r00()), 800)
            resp = bytes(dev.read(t["ep_in"], 64, 800))
            dev.write(t["ep_out"], bytes(_rc1()), 800)
            dev.read(t["ep_in"], 64, 800)
        except usb.core.USBError as e:
            if debug:
                print(f"    wake[{i}]: {e}", file=sys.stderr)
            continue
        if debug:
            print(f"    wake[{i}]: resp {resp[:4].hex()}", file=sys.stderr)
        if resp[0:2] in (b"\x02\x05", b"\x02\x22"):
            return True
    return False


def _device_kind(dev, t, debug=False):
    """Classify by reading flash 0x10000 (blank=dongle, code=ctrl). Wakes the app session first + retries — a cold controller ignores IAP reads until the 0x00/0xc1 handshake. Returns (kind|None, session-ACKed)."""
    woke = _wake_app(dev, t, debug=debug)
    for _ in range(8):
        time.sleep(
            0.02
        )  # a controller needs a beat after the session opens before its IAP serves reads
        probe = _read1(dev, t, 0x10000, 16, debug=debug)
        if probe is not None:
            return (
                "dongle" if all(b == 0xFF for b in probe) else "ctrl"
            ), woke
    return None, woke


def cmd_flash(args):
    payload = open(args.payload, "rb").read()
    dev, t = open_target(args.target, args.dev)
    pk = _payload_kind(payload)
    if (
        pk and not args.force
    ):  # 0x310a is a wired controller OR a dongle relaying one — confirm against the device's own flash
        dk, _ = _device_kind(dev, t)
        if dk and dk != pk:
            raise SystemExit(
                f"REFUSING: {pk} firmware into a {dk} device. Re-check the target (0x310a can be a dongle), or pass --force."
            )
        if dk is None:
            print(
                "warn: could not read device to confirm its type; proceeding",
                file=sys.stderr,
            )
    if t["mode"] == "boot":
        boot_flash(
            dev,
            t,
            payload,
            args.verify,
            args.addr if args.addr is not None else APP_BASE,
        )
    else:
        app_flash(dev, t, payload, args.version, args.limit)
    try:
        usb.util.release_interface(dev, t["intf"])
    except usb.core.USBError:
        pass


def _read1(dev, t, addr, k, debug=False):
    """One <=46-byte read chunk. Boot: address protocol cmd 5. App: 0x8105 cmd 0x05 (len@[4:6], addr@[12:16]); data in the response at [18:]."""
    if t["mode"] == "boot":
        ok, r = boot_xfer(dev, t, _boot(5, addr=addr, param4=k, datalen=k), 5)
        return r[18 : 18 + k] if (ok and len(r) >= 18 + k) else None
    req = bytearray(64)
    req[0], req[1], req[2] = 0x81, 0x05, 0x05
    req[6:8] = k.to_bytes(
        2, "little"
    )  # length (the write protocol's datalen slot)
    req[14:18] = addr.to_bytes(
        4, "little"
    )  # address (the write protocol's offset slot)
    dev.write(t["ep_out"], bytes(req), 800)
    for _ in range(4):
        try:
            r = bytes(dev.read(t["ep_in"], 64, 800))
        except usb.core.USBError:
            return None
        if debug:
            print(f"raw resp @0x{addr:x}: {r.hex()}", file=sys.stderr)
        if len(r) >= 18 + k and r[0] == 0x02:
            return r[18 : 18 + k]
    return None


def cmd_read(args):
    dev, t = open_target(args.target, args.dev)
    addr, n = int(args.addr, 0), int(args.n, 0)
    out = bytearray()
    bad = first_bad = 0
    while len(out) < n:
        k = min(46, n - len(out))
        c = _read1(dev, t, addr + len(out), k, debug=(len(out) == 0))
        if c is None:
            if not bad:
                first_bad = addr + len(out)
            out += b"\xff" * k
            bad += 1
        else:
            out += c
        if args.out and len(out) % (46 * 200) < 46:
            print(
                f"  {len(out)}/{n} @0x{addr + len(out):x} unreadable={bad}",
                file=sys.stderr,
            )
    if args.out:
        open(args.out, "wb").write(bytes(out[:n]))
        print(
            f"wrote {args.out}: {n} bytes from 0x{addr:x}; {bad} unreadable"
            + (f" (first @0x{first_bad:x})" if bad else "")
        )
    else:
        print(bytes(out[:n]).hex())
    usb.util.release_interface(dev, t["intf"])


def cmd_scan(args):
    """Sample 16 bytes at each step across [lo,hi) to map populated flash regions."""
    dev, t = open_target(args.target, args.dev)
    lo, hi, step = int(args.lo, 0), int(args.hi, 0), int(args.step, 0)
    print(f"scanning 0x{lo:x}-0x{hi:x} step 0x{step:x}", file=sys.stderr)
    a = lo
    while a < hi:
        c = _read1(dev, t, a, 16)
        if c is None:
            tag = "READERR"
        elif all(b == 0xFF for b in c):
            tag = "-- ff --"
        elif all(b == 0 for b in c):
            tag = "-- 00 --"
        else:
            tag = c.hex()
        print(f"0x{a:06x}: {tag}")
        a += step
    usb.util.release_interface(dev, t["intf"])


BRAND = (b"Ultima+e", "Ultima+e".encode("utf-16-le"))


def _already_branded(dev, t, payload):
    """The device flash already carries the modded brand at the payload's own offset. A read failure or any mismatch counts as not-branded, so update re-flashes rather than risk skipping a stock device."""
    for needle in BRAND:
        idx = payload.find(needle)
        if idx >= 0:
            return _read1(dev, t, APP_BASE + idx, len(needle)) == needle
    return False


def _update_one(sel, pid, payloads, args):
    """Classify one device by PID (+ a 0x10000 flash read to split a wired 0x310a controller from a dongle relaying one) and flash the matching production payload."""
    if pid == 0x3208:
        return "SKIP: bootloader mode — recover with `flash --target boot`"
    if pid not in (0x301C, 0x310A):
        return f"SKIP: unhandled PID {pid:#06x}"
    dev, t = open_target("dongle" if pid == 0x301C else "ctrl", sel)
    try:
        dk, woke = _device_kind(dev, t, args.debug)
        if pid == 0x310A:
            if dk == "dongle":
                return "SKIP: dongle relaying a controller — idle it (unplug the pad) to flash the dongle"
            if dk != "ctrl":
                return f"SKIP: 0x310a but 0x10000 unreadable (session {'ACKed' if woke else 'no ACK'}) — cannot confirm a wired controller"
            kind = "ctrl"
        else:
            kind = "dongle"
        payload = payloads.get(kind)
        if payload is None or _payload_kind(payload) != kind:
            return f"SKIP: no valid {kind} payload"
        if not args.force and _already_branded(dev, t, payload):
            return f"up-to-date ({kind})"
        if args.dry_run:
            return f"would flash {kind} ({len(payload)} bytes)"
        app_flash(dev, t, payload, args.version, None)
        return f"flashed {kind}"
    finally:
        try:
            usb.util.release_interface(dev, t["intf"])
        except usb.core.USBError:
            pass


def cmd_update_all(args):
    """Flash every plugged-in 2C device with its production payload: idle dongles (0x301c) + wired controllers (0x310a). A 0x310a that is really a dongle relaying a controller is skipped, never flashed as a controller."""
    payloads = {
        "ctrl": open(args.ctrl_payload, "rb").read(),
        "dongle": open(args.dongle_payload, "rb").read(),
    }
    devs = sorted(
        usb.core.find(find_all=True, idVendor=VID),
        key=lambda d: (d.bus, d.address),
    )
    if not devs:
        raise SystemExit(f"no {VID:#06x} devices found")
    print(
        f"found {len(devs)} {VID:#06x} device(s)"
        + (" — DRY RUN" if args.dry_run else ""),
        file=sys.stderr,
    )
    rows = [
        (
            f"{d.bus}:{d.address}",
            f"{d.idProduct:#06x}",
            _update_one(f"{d.bus}:{d.address}", d.idProduct, payloads, args),
        )
        for d in devs
    ]
    print("\n=== update-all summary ===")
    for sel, pid, status in rows:
        print(f"  {sel:>7}  {pid}  {status}")


def cmd_gen(args):
    """Offline: build the app sequence from a payload; with --template, diff byte-for-byte (validation, no hardware)."""
    t = TARGETS[args.target]
    if t["mode"] != "app":
        raise SystemExit("gen is app-mode only")
    seq = app_sequence(open(args.payload, "rb").read(), t, args.version)
    if args.template:
        tmpl = [bytes.fromhex(x) for x in open(args.template).read().split()]
        diffs = [
            i for i in range(min(len(seq), len(tmpl))) if seq[i] != tmpl[i]
        ]
        ok = not diffs and len(seq) == len(tmpl)
        print(
            f"generated {len(seq)} vs template {len(tmpl)}: {'MATCH' if ok else f'{len(diffs)} diffs, first at {diffs[:1]}'}"
        )
        if not ok:
            raise SystemExit(1)
    else:
        print(f"generated {len(seq)} reports; first={seq[0].hex()}")


def main():
    ap = argparse.ArgumentParser(
        description="8BitDo Ultimate 2C flasher (app 0x8105 + bootloader)"
    )
    ap.add_argument("--target", choices=list(TARGETS), default="ctrl")
    ap.add_argument(
        "--dev", help="select among same-PID devices by BUS:ADDR (e.g. 1:57)"
    )
    ap.add_argument(
        "--version",
        type=lambda s: int(s, 0),
        default=None,
        help="app: firmware version byte for 0xc4 (default per target)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="non-destructive: identify the endpoint")
    p.add_argument("--retries", type=int, default=5)
    p.set_defaults(func=cmd_probe)

    f = sub.add_parser(
        "flash",
        help="flash a raw payload (generated app IAP, or bootloader address writes)",
    )
    f.add_argument("payload")
    f.add_argument(
        "--verify",
        action="store_true",
        help="boot only: read back and compare",
    )
    f.add_argument(
        "--addr",
        type=lambda s: int(s, 0),
        help="boot only: write address (default 0x6000)",
    )
    f.add_argument(
        "--limit", type=int, help="app only: send just the first N reports"
    )
    f.add_argument(
        "--force",
        action="store_true",
        help="skip the controller/dongle firmware-vs-device safety check",
    )
    f.set_defaults(func=cmd_flash)

    r = sub.add_parser("read", help="bootloader only: read device flash")
    r.add_argument("addr")
    r.add_argument("n")
    r.add_argument(
        "--out",
        help="write raw bytes to a file (tolerant of unreadable chunks); else print hex",
    )
    r.set_defaults(func=cmd_read)

    s = sub.add_parser(
        "scan",
        help="map populated flash: sample 16B at each step across [lo,hi)",
    )
    s.add_argument("lo")
    s.add_argument("hi")
    s.add_argument("step")
    s.set_defaults(func=cmd_scan)

    g = sub.add_parser("gen", help="offline: build/validate the app sequence")
    g.add_argument("payload")
    g.add_argument(
        "--template",
        help="diff the generated sequence against a captured template",
    )
    g.set_defaults(func=cmd_gen)

    ua = sub.add_parser(
        "update-all",
        help="flash every plugged-in 2C device (idle dongles + wired controllers) with its production firmware",
    )
    ua.add_argument("--ctrl-payload", required=True)
    ua.add_argument("--dongle-payload", required=True)
    ua.add_argument(
        "--dry-run",
        action="store_true",
        help="classify and report the plan; flash nothing",
    )
    ua.add_argument(
        "--force",
        action="store_true",
        help="re-flash even a device already reading Ultima+e",
    )
    ua.add_argument(
        "--debug",
        action="store_true",
        help="print the raw session-wake + read exchanges per device",
    )
    ua.set_defaults(func=cmd_update_all)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
