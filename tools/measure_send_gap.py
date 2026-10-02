#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# Reads, but does not redistribute, the Cakewalk instrument-definition files
# distributed for the E-MU Proteus family. Its output is preset names, which
# are E-MU's, and is gitignored.
#
# p2ked is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# p2ked is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""Measure the inter-message gap the unit actually tolerates.

`bridge.SEND_GAP` has been a guess since the first commit: E-MU's
specification asks senders to keep messages under 244 data bytes and says
nothing at all about timing between them, so the sibling projects'
conservative 10 ms default was inherited. TODO.md item 4 wanted this
measured, and a name sweep of a 1024-preset ROM spends a thousand of them,
so it is worth knowing.

**Read-only, and silent.** Every request here is a Generic Name Request,
which this family answers without selecting anything -- the property the
whole program is built around. Nothing is written, and nothing sounds.

What is measured
----------------

For a given gap, read one bank's names and compare them against a
reference read taken at a gap known to work. The interesting failure is
not a timeout: it is a reply belonging to the *previous* request, which
this protocol cannot distinguish from the current one except by the object
number the reply carries (see `bridge.preset_name`). Too small a gap
produces exactly that -- every name shifted by one preset -- so the check
is a comparison against a reference, not a count of successes.

Usage::

    python3 tools/measure_send_gap.py --port "U6MIDI Pro:U6MIDI Pro MIDI 1 40:0"
    python3 tools/measure_send_gap.py --demo          # synthetic, proves nothing
    python3 tools/measure_send_gap.py --gaps 0.010,0.005,0.002,0.001
    python3 tools/measure_send_gap.py --bank XLEAD2-0 # a 128-preset bank

Exit status is 0 when every gap tried matched its reference exactly, 1
otherwise -- so it can be run as a check, though it needs hardware and so
is not part of `make check`.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from p2k import bridge as b
from p2k import messages as m
from p2k import roms

#: Gaps tried by default, longest first. 10 ms is the current default;
#: below that the sweep tightens until something breaks, so the answer is
#: "this is where it started to fail", not "this is the fastest".
DEFAULT_GAPS: Tuple[float, ...] = (0.010, 0.005, 0.002, 0.001, 0.0005)

#: A gap is only believed after this many consecutive clean reads. One
#: clean sweep is an absence of evidence on a cable: a marginal gap fails
#: intermittently, and an intermittent failure is exactly what a one-shot
#: measurement misses.
REPEATS = 3

#: ``{program change: name}``, with ``None`` for a slot that has no name.
Names = Dict[int, Optional[str]]


def read_bank(device, bank_id: str) -> Tuple[Names, float, int]:
    """Every name in a bank, plus how long it took and how many failed.

    A failed or absent slot is recorded as ``None``, so a gap that loses a
    name part-way through a sweep cannot be mistaken for one that read a
    shorter bank: the caller compares whole dicts and would notice either.
    """
    bank = roms.bank(bank_id)
    rom_id = roms.USER_ROM_ID if bank.rom is roms.USER else bank.rom.msb
    out: Names = {}
    failed = 0
    entries = roms.presets(bank_id)
    started = time.perf_counter()
    for entry in entries:
        try:
            name = device.preset_name(entry.number, rom_id)
        except TimeoutError:
            name = None
        if name is None or roms.is_absent(name):
            # Either it timed out, or the unit said the slot is not there.
            # Both leave a slot with no name, which is what the reference
            # comparison is against.
            name = None
            failed += 1
        out[entry.program_change] = name
    return out, time.perf_counter() - started, failed


def compare(
    reference: Mapping[int, Optional[str]], got: Mapping[int, Optional[str]]
) -> Tuple[int, int, int]:
    """``(missing, wrong, extra)`` against the reference read.

    "Wrong" is the number that matters: it means the unit answered with a
    name belonging to a *different* preset, which is the failure a bare
    success count cannot see and the only one that would put a name on the
    wrong row of the screen.
    """
    missing = sum(
        1
        for key, name in reference.items()
        if name is not None and got.get(key) is None
    )
    wrong = sum(
        1
        for key, name in reference.items()
        if name is not None and got.get(key) is not None and got[key] != name
    )
    extra = sum(
        1
        for key, name in got.items()
        if name is None and reference.get(key) is not None
    )
    return missing, wrong, extra


def measure(device, bank_id: str, gaps: List[float], repeats: int) -> int:
    """Sweep the gaps. Returns a process exit status."""
    original = b.SEND_GAP

    print(
        f"reference read at the current default, {original * 1000:.1f} ms "
        f"({repeats} pass(es))",
        file=sys.stderr,
    )
    reference: Dict[int, Optional[str]] = {}
    for index in range(repeats):
        b.SEND_GAP = original
        names, seconds, failed = read_bank(device, bank_id)
        if failed:
            print(
                f"  pass {index + 1}: {failed} slot(s) failed at the "
                f"default gap; the reference is not trustworthy. Is the "
                f"unit connected and is SysEx enabled?",
                file=sys.stderr,
            )
            return 1
        if not names:
            print(f"  pass {index + 1}: read nothing from {bank_id}", file=sys.stderr)
            return 1
        if reference and names != reference:
            print(
                f"  pass {index + 1}: differs from pass 1 at the *default* "
                f"gap. That is a fault to look at before changing any "
                f"timing.",
                file=sys.stderr,
            )
            return 1
        reference = names
        print(
            f"  pass {index + 1}: {len(names)} names in {seconds:.2f}s", file=sys.stderr
        )

    ok = 0.0
    print("", file=sys.stderr)
    print(
        f"{'gap':>9}  {'clean':>6}  {'miss':>5}  {'wrong':>6}  {'mean s':>7}",
        file=sys.stderr,
    )
    for gap in gaps:
        b.SEND_GAP = gap
        clean = 0
        miss = wrong = 0
        total = 0.0
        for _ in range(repeats):
            names, seconds, _failed = read_bank(device, bank_id)
            total += seconds
            mss, wrg, _extra = compare(reference, names)
            miss += mss
            wrong += wrg
            if not mss and not wrg and names == reference:
                clean += 1
        mean = total / repeats
        print(
            f"{gap * 1000:8.2f}ms  {clean:>4}/{repeats}  {miss:>5}  "
            f"{wrong:>6}  {mean:7.2f}",
            file=sys.stderr,
        )
        if clean == repeats:
            ok = gap

    b.SEND_GAP = original
    print("", file=sys.stderr)
    if ok < max(gaps):
        print(
            f"smallest gap that read {bank_id} cleanly {repeats} times: "
            f"{ok * 1000:.2f} ms",
            file=sys.stderr,
        )
    else:
        print(
            f"every gap tried, including {ok * 1000:.2f} ms, read "
            f"{bank_id} cleanly {repeats} times. Extend --gaps downwards "
            f"to find the edge.",
            file=sys.stderr,
        )
    print(
        f"bridge.SEND_GAP is {original * 1000:.1f} ms and is NOT changed "
        f"by this tool. Edit p2k/bridge.py deliberately, and record what "
        f"was measured in docs/RESOLUTION_NOTES.md.",
        file=sys.stderr,
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="measure_send_gap", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--port", help="MIDI port name")
    parser.add_argument("--recv-port", help="input port, if it differs")
    parser.add_argument("--device-id", type=int, default=None)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="synthetic device; proves nothing about timing",
    )
    parser.add_argument(
        "--bank", default=None, help="bank to read (default: the first fitted ROM's)"
    )
    parser.add_argument(
        "--gaps",
        default=None,
        help="comma-separated seconds, longest first "
        f"(default: {','.join(str(g) for g in DEFAULT_GAPS)})",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=REPEATS,
        help=f"reads per gap (default: {REPEATS})",
    )
    args = parser.parse_args(argv)

    gaps = [float(g) for g in args.gaps.split(",")] if args.gaps else list(DEFAULT_GAPS)
    if any(g <= 0 for g in gaps):
        parser.error("every gap must be positive")

    if args.demo:
        from p2ked.demo import DemoDevice

        device: Any = DemoDevice()
        print(
            "demo device: timing here is the fake's, not the unit's.", file=sys.stderr
        )
    else:
        b.install_clean_exit()
        try:
            if args.port:
                device = b.ProteusBridge.open(
                    args.port,
                    recv_port=args.recv_port,
                    device_id=(
                        args.device_id
                        if args.device_id is not None
                        else m.BROADCAST_DEVICE
                    ),
                )
                if device.learn_device_id(timeout=0.8) is None:
                    device.close()
                    print(
                        "nothing identifying itself as an E-MU device "
                        "answered on that port.",
                        file=sys.stderr,
                    )
                    return 1
            else:
                device = b.ProteusBridge.autodetect(
                    on_try=lambda name: print(f"  probing {name}...", file=sys.stderr)
                )
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    try:
        # hardware_config is cached on the bridge, so this both chooses a
        # bank and gives `rom_id_for` the SIMM list it needs.
        config = device.hardware_config()
        fitted = {simm.simm_id for simm in config.simms}
        if args.bank:
            bank_id = args.bank
        else:
            first = roms.USER if roms.USER_ROM_ID in fitted else None
            if first is None:
                first = next(
                    (
                        roms.rom_for_simm_id(s)
                        for s in sorted(fitted)
                        if roms.rom_for_simm_id(s)
                    ),
                    None,
                )
            if first is None:
                print("no fitted ROM is in p2k's table; pass --bank", file=sys.stderr)
                return 1
            bank_id = f"{first.id}-{first.lsbs[0]}"
        print(
            f"reading {bank_id} ({len(roms.presets(bank_id))} presets)", file=sys.stderr
        )
        return measure(device, bank_id, gaps, max(args.repeats, 1))
    finally:
        device.close()


if __name__ == "__main__":
    raise SystemExit(main())
