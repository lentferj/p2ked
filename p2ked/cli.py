# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
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

"""``p2kcli`` -- the same information as the TUI, in a pipe.

Most commands need no unit and no MIDI stack: the ROM table, the bank
arithmetic and the name catalog are p2ked's own data. Those are listed in
:data:`_OFFLINE` and never open a port, so they work on a headless box and
while somebody else is using the hardware.

``select`` is the only command that makes a sound.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict, List, Optional

from vinsynlib import cli, midi
from p2k import catalog as cat
from p2k import roms

__all__ = ["main", "build_parser"]


def _table(rows: List[List[str]], headers: List[str]) -> str:
    if not rows:
        return ""
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    out = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip(),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row in rows:
        out.append(
            "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
        )
    return "\n".join(out)


def _catalog(args) -> cat.Catalog:
    return cat.load(getattr(args, "catalog", None))


# --- offline -----------------------------------------------------------------


def _cmd_roms(_device, args) -> None:
    catalog = _catalog(args)
    rows = []
    for entry in roms.ROMS:
        named = sum(1 for bank in roms.banks(entry.id) if catalog.has(bank.id))
        rows.append(
            [
                entry.id,
                entry.name,
                str(entry.msb),
                f"{min(entry.lsbs)}-{max(entry.lsbs)}"
                if len(entry.lsbs) > 1
                else str(entry.lsbs[0]),
                str(entry.count),
                f"{named}/{entry.bank_count}",
                "user" if entry.writable else "",
            ]
        )
    print(_table(rows, ["id", "name", "MSB", "LSB", "presets", "named", "note"]))


def _cmd_list(_device, args) -> None:
    catalog = _catalog(args)
    rows = []
    for entry in roms.presets(args.bank):
        rows.append(
            [
                f"{entry.program_change:03d}",
                catalog.display_name(args.bank, entry.program_change),
                str(entry.msb),
                str(entry.lsb),
                str(entry.program_change),
                str(entry.number),
            ]
        )
    print(_table(rows, ["#", "name", "MSB", "LSB", "PC", "ROM#"]))


def _cmd_find(_device, args) -> None:
    catalog = _catalog(args)
    hits = catalog.search(args.name)
    if not hits:
        print(f"nothing matching {args.name!r}", file=sys.stderr)
        return
    rows = []
    # Four names, not three: `Catalog.search` returns
    # `(bank_id, program_change, name, differs)` -- the flag was added so
    # this command could mark a disagreement, and the loop below is what
    # marks it. It unpacked three and used a fourth name that was never
    # bound, so every non-empty search raised before reaching the marker.
    # See TODO.md item 40.
    for bank_id, program_change, name, differs in hits:
        try:
            entry = roms.preset(bank_id, program_change)
        except LookupError:
            continue
        rows.append(
            [
                bank_id,
                f"{program_change:03d}",
                name + (" *" if differs else ""),
                str(entry.msb),
                str(entry.lsb),
                str(entry.program_change),
            ]
        )
    print(_table(rows, ["bank", "#", "name", "MSB", "LSB", "PC"]))
    if any(hit[3] for hit in hits):
        print(
            "\n* the unit and the printed catalog disagree about this "
            "slot; the unit's name is shown"
        )


def _cmd_resolve(_device, args) -> None:
    found = roms.lookup(args.msb, args.lsb, args.pc)
    if found is None:
        raise SystemExit(
            f"error: no ROM in p2ked's table answers on MSB {args.msb} / "
            f"LSB {args.lsb}. That is not necessarily wrong -- it may be a "
            f"ROM this table has no row for."
        )
    catalog = _catalog(args)
    print(
        f"{found.bank.label} {found.program_change:03d}  "
        f"{catalog.display_name(found.bank_id, found.program_change)}"
    )
    print(
        f"ROM {found.rom.name} ({found.rom.id}), preset {found.number} within the ROM"
    )


# --- device ------------------------------------------------------------------


def _cmd_status(device, _args) -> None:
    fields = device.identify()
    if fields is None:
        raise SystemExit("error: nothing answered an Identity Request.")
    print(
        f"manufacturer   {fields['manufacturer']:#04x}"
        f"{'  (E-MU)' if fields['is_emu'] else ''}"
    )
    print(f"family         {fields['family']}")
    print(f"member         {fields['member']}")
    print(f"device ID      {fields['device']}")


def _cmd_hardware(device, _args) -> None:
    """What ROMs are fitted. Read-only, makes no sound.

    Named ``hardware``, with ``config`` kept as an alias: ``config`` next to
    the ``--config`` flag meant two different things in one screen, one of
    them the settings file and the other the hardware in the unit.
    """
    config = device.hardware_config()
    print(f"user presets   {config.user_presets}")
    print(f"SIMMs fitted   {len(config.simms)}")
    rows = []
    for simm in config.simms:
        guess = roms.rom_for_simm_id(simm.simm_id)
        rows.append(
            [
                str(simm.simm_id),
                str(simm.presets),
                str(simm.instruments),
                guess.name if guess else "not in p2ked's table",
            ]
        )
    print()
    print(_table(rows, ["SIMM id", "presets", "instruments", "ROM"]))
    print("\nThe ROM column reads the SIMM ID as that ROM's Bank Select MSB.")
    print("No E-MU document to hand says they are the same number; it was")
    print("confirmed against hardware for three ROMs on 2026-09-12, which is")
    print('not all twenty. A row saying "not in p2ked\'s table" means the')
    print("instrument-definition files do not cover that MSB -- the presets")
    print("are still readable, only the ROM's name is unknown.")


def _cmd_channels(device, args) -> None:
    """Every MIDI channel. Read-only, makes no sound."""
    from p2k import messages as msg

    dump = device.read_setup()
    try:
        mode = device.midi_mode()
    except Exception:
        mode = None
    catalog = _catalog(args)
    print(f"setup {dump.name!r}   {dump.channel_count} channels")
    if mode is None:
        print("MIDI mode      could not be read")
    else:
        print(
            f"MIDI mode      {msg.MidiMode.name(mode)}"
            + (
                ""
                if msg.MidiMode.is_multitimbral(mode)
                else "   -- NOT multitimbral; the settings below are "
                "stored but not in effect"
            )
        )
    print()
    rows = []
    for entry in dump.channels:
        rom = (
            roms.USER
            if entry.rom_id == roms.USER_ROM_ID
            else roms.rom_for_simm_id(entry.rom_id)
        )
        plays = f"ROM {entry.rom_id} preset {entry.preset}"
        if rom is not None:
            index, pc = divmod(entry.preset, roms.PRESETS_PER_BANK)
            if index < len(rom.lsbs):
                bank_id = f"{rom.id}-{rom.lsbs[index]}"
                plays = (
                    f"{rom.name} {entry.preset} {catalog.display_name(bank_id, pc)}"
                ).rstrip()
        rows.append(
            [
                str(entry.channel_display),
                plays,
                str(entry.volume),
                str(entry.pan - 64),
                str(entry.mix_output),
                "on" if entry.receive_program_change else "OFF",
                entry.silent_because or "",
            ]
        )
    print(_table(rows, ["ch", "plays", "vol", "pan", "out", "rxPC", ""]))
    audible = [c.channel_display for c in dump.channels if c.silent_because is None]
    print()
    print(
        "Channels that would sound: "
        + (", ".join(map(str, audible)) if audible else "none")
    )
    print("Channels 17-32 are this family's second MIDI interface.")


def _cmd_names(device, args) -> None:
    """Read a bank's names off the unit. Read-only, **makes no sound**."""

    def progress(done: int, total: int) -> None:
        print(f"\r  {done}/{total}", end="", file=sys.stderr)

    names = device.read_bank_names(args.bank, on_progress=progress)
    print("", file=sys.stderr)
    catalog = _catalog(args)
    rows = []
    for program_change in sorted(names):
        printed = catalog.name(args.bank, program_change) or ""
        live = names[program_change]
        rows.append(
            [
                f"{program_change:03d}",
                live,
                printed,
                "*" if printed and printed != live else "",
            ]
        )
    print(_table(rows, ["#", "on the unit", "in the catalog", ""]))


def _cmd_select(device, args) -> None:
    """Select a preset. **This changes what the unit is playing.**"""
    entry = roms.preset(args.bank, args.pc)
    device.select(entry, channel=(args.channel or 1) - 1)
    print(
        f"selected {entry} on MIDI channel {args.channel or 1} "
        f"(MSB {entry.msb}, LSB {entry.lsb}, PC {entry.program_change})"
    )


_COMMANDS: Dict[str, Callable] = {
    # `banks` is the family's name for the table and `roms` still works, as
    # an alias on the subparser and as a key here. p2ked's own browser has
    # always called them banks; the CLI was the odd one out.
    "banks": _cmd_roms,
    "roms": _cmd_roms,
    "list": _cmd_list,
    "find": _cmd_find,
    "resolve": _cmd_resolve,
    "ports": None,  # filled in below; needs the MIDI import
    "status": _cmd_status,
    # `hardware` with `config` still accepted, for the same reason: one word,
    # two meanings, in one line of help output.
    "hardware": _cmd_hardware,
    "config": _cmd_hardware,
    "channels": _cmd_channels,
    "names": _cmd_names,
    "select": _cmd_select,
}

#: Commands that open no port at all. Both spellings of `banks`, because both
#: dispatch and neither may fall through to the device path.
_OFFLINE = {"banks", "roms", "list", "find", "resolve"}


def _cmd_ports(_device, _args) -> None:
    from p2k.bridge import likely_proteus_ports

    try:
        ins, outs = midi.list_ports()
        likely = sorted(likely_proteus_ports())
    except midi.MidiUnavailable as exc:
        raise SystemExit(f"error: {exc}") from exc
    # The rendering is the family's, so all nine listings look alike; only the
    # "looks like an E-MU" mark and the trailing note are p2ked's.
    print(
        midi.render_ports(
            ins,
            outs,
            likely=likely,
            likely_label="looks like an E-MU",
            note=(
                "A name hint cannot decide anything. A Proteus on a DIN cable\n"
                "is behind an interface whose name says nothing about E-MU;\n"
                "`p2kcli status` asks every port and the identity reply decides."
            ),
        )
    )


_COMMANDS["ports"] = _cmd_ports
_OFFLINE.add("ports")


def build_parser() -> argparse.ArgumentParser:
    parser = cli.make_parser(
        prog="p2kcli", description="Browse an E-MU Proteus 2000's presets."
    )
    # config=False and favorites=False: nothing in p2kcli *offers* either, and a
    # flag that is accepted and then ignored teaches the user that a flag can
    # lie -- worse than no flag (docs/UX-SPEC.md section 2). The settings
    # file is still read and written, at the browser's default -- see
    # _build_device.
    cli.add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        channel=True,
        device_id=True,
        catalog=True,
        config=False,
        favorites=False,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Canonical name first, older spellings as aliases. `roms` was this CLI's
    # own word for the bank table and the family's is `banks`; p2ked's own
    # browser already said banks. `config` meant "which ROMs are fitted" while
    # the --config flag beside it meant the settings file, so the command is
    # `hardware` now and the old word still works.
    sub.add_parser("banks", aliases=["roms"], help="the bank table (no unit needed)")
    sp = sub.add_parser("list", help="one bank's presets (no unit needed)")
    sp.add_argument("bank")
    sp = sub.add_parser("find", help="search names (no unit needed)")
    sp.add_argument("name")
    sp = sub.add_parser("resolve", help="what does this MSB/LSB/PC select?")
    sp.add_argument("msb", type=int)
    sp.add_argument("lsb", type=int)
    sp.add_argument("pc", type=int)
    sub.add_parser("ports", help="MIDI ports on this host")
    sub.add_parser("status", help="ask the unit who it is")
    sub.add_parser(
        "hardware",
        aliases=["config"],
        help="what the unit reports about itself: which ROMs are fitted",
    )
    sub.add_parser(
        "channels",
        help="every MIDI channel: what it plays, and why it might not (makes no sound)",
    )
    sp = sub.add_parser("names", help="read a bank's names (makes no sound)")
    sp.add_argument("bank")
    sp = sub.add_parser("select", help="select a preset ON THE UNIT")
    sp.add_argument("bank")
    sp.add_argument("pc", type=int)
    return parser


def _build_device(args):
    if args.demo:
        from p2ked.demo import DemoDevice

        return DemoDevice()
    from p2k import bridge as b
    from p2k import config as cfg
    from p2k import messages as msg

    b.install_clean_exit()
    if args.port:
        device = b.ProteusBridge.open(
            args.port,
            recv_port=args.recv_port,
            device_id=(
                args.device_id if args.device_id is not None else msg.BROADCAST_DEVICE
            ),
        )
        if args.device_id is None:
            # Broadcast is not a safe default -- this Proteus ignores it,
            # so identity answers and every read then times out.
            device.learn_device_id(timeout=0.8)
        return device
    # No --config flag on this parser, so the settings file is the browser's
    # default: ./config.toml, gitignored, safe to delete. One Identity Request
    # to the remembered port; the sweep only when there is nothing
    # remembered, when the remembered port no longer answers, or on --scan.
    return b.ProteusBridge.connect(
        config_path=cfg.DEFAULT_PATH,
        scan=args.scan,
        on_try=lambda name: print(f"  probing {name}...", file=sys.stderr),
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handler = _COMMANDS[args.command]
    # --channel and --device-id, both checked and both named the family's way.
    cli.validate_common(args)

    if args.command in _OFFLINE:
        try:
            handler(None, args)
        except (LookupError, ValueError) as exc:
            sys.exit(f"error: {exc}")
        return 0

    try:
        device = _build_device(args)
    except Exception as exc:
        sys.exit(f"error: {exc}")
    try:
        handler(device, args)
    except (LookupError, TimeoutError, ValueError, RuntimeError) as exc:
        sys.exit(f"error: {exc}")
    finally:
        device.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
