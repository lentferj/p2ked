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

"""Build p2ked's preset-name catalog from a Cakewalk ``.ins`` file.

The ``.ins`` format is a Windows INI file in two halves. ``.Patch Names``
declares sections of ``<program change>=<name>``; ``.Instrument
Definitions`` declares, per instrument, ``Patch[<bank>]=<section name>``
where ``<bank>`` is ``MSB * 128 + LSB``.

That bank arithmetic is the whole reason this tool is careful. A bank number
carries both halves of the Bank Select in one integer, and splitting it the
wrong way round -- ``bank % 128`` for the MSB -- yields small, plausible
numbers for every ROM. The split happens once, in :func:`split_bank`, with a
test.

Usage::

    python3 tools/extract_catalog.py --ins ~/path/to/P2k_All.ins
    python3 tools/extract_catalog.py --ins a.ins --ins b.ins
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from p2k import catalog as cat
from p2k import roms  # noqa: E402

DEFAULT_INS = os.path.expanduser("~/Dokumente/SYNTHS/Proteus 2000/P2k_All.ins")
DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "p2k",
    "data",
    "catalog.json",
)

_SECTION = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
_ENTRY = re.compile(r"^(?P<pc>\d+)\s*=\s*(?P<name>.*)$")
_PATCH_REF = re.compile(r"^Patch\[(?P<bank>\d+)\]\s*=\s*(?P<section>.+?)\s*$")

#: Section headings label themselves with their own bank number in
#: parentheses -- "... Bank 2 (1282)". That label is the authority here, not
#: the Patch[] index, and the reason is a real defect in the file shipped for
#: this family: one ROM's third bank is indexed as Patch[1281] while calling
#: itself (1282). Taken at face value that silently replaces bank 1's 128
#: names with bank 2's and loses bank 2 entirely -- wrong names under right
#: numbers, which nothing downstream can detect.
#:
#: The labels are checkable and were checked: 69 of the 70 sections carry
#: one, no two agree, and the Patch[] index disagrees with exactly one of
#: them. The label sits next to the 128 names it describes; the index is a
#: separate hand-maintained list at the other end of the file.
_SECTION_BANK = re.compile(r"\((?P<bank>\d+)\)\s*$")


def split_bank(bank: int) -> Tuple[int, int]:
    """A Cakewalk bank number to ``(msb, lsb)``.

    ``bank = msb * 128 + lsb``. Doing it the other way round gives an MSB of
    0-127 and an LSB of 0-1 for every ROM in the file, which looks like data
    rather than like a mistake.
    """
    if not 0 <= bank <= 128 * 128 - 1:
        raise ValueError(f"bank {bank} is outside 0-16383")
    return (bank // 128, bank % 128)


def read_sections(path: str) -> Dict[str, Dict[int, str]]:
    """``{section name: {program change: preset name}}``.

    Read as latin-1 rather than utf-8: these files are old, Windows-authored
    and contain bytes that are not valid utf-8. Decoding strictly would
    abort on one stray character in one name and lose the whole file.
    """
    sections: Dict[str, Dict[int, str]] = {}
    current: Optional[Dict[int, str]] = None
    with open(path, encoding="latin-1") as handle:
        for line in handle:
            line = line.rstrip("\r\n")
            if not line or line.startswith(";"):
                continue
            found = _SECTION.match(line)
            if found:
                current = sections.setdefault(found.group("name"), {})
                continue
            if current is None:
                continue
            entry = _ENTRY.match(line)
            if entry:
                current[int(entry.group("pc"))] = entry.group("name").strip()
    return sections


def read_bank_refs(path: str) -> Dict[int, str]:
    """``{bank number: section name}``, merged across every instrument.

    The same bank is declared by several instruments -- every Proteus-family
    model lists the user banks -- and they agree, so the last one wins
    silently. A *disagreement* would be worth knowing about, and is reported.
    """
    refs: Dict[int, str] = {}
    corrected: Dict[str, Tuple[int, int]] = {}
    with open(path, encoding="latin-1") as handle:
        in_defs = False
        for line in handle:
            line = line.strip()
            if line.startswith(".Instrument Definitions"):
                in_defs = True
                continue
            if not in_defs:
                continue
            found = _PATCH_REF.match(line)
            if not found:
                continue
            indexed = int(found.group("bank"))
            section = found.group("section")
            labelled = _SECTION_BANK.search(section)
            bank = int(labelled.group("bank")) if labelled else indexed
            if labelled and bank != indexed:
                corrected[section] = (indexed, bank)
            refs[bank] = section
    for section, (indexed, bank) in sorted(corrected.items()):
        print(
            f"note: {os.path.basename(path)} indexes {section!r} as bank "
            f"{indexed}; using {bank} from its own label. Trusting the "
            f"index would put this bank's names under bank {indexed}'s "
            f"numbers.",
            file=sys.stderr,
        )
    return refs


#: Typographic characters a word processor substitutes, mapped back to the
#: ASCII the instrument actually holds. A preset name on this machine is 16
#: bytes of ASCII 32-126; a curly apostrophe cannot be in one. Left alone,
#: two names per ROM read as differing from the unit forever -- p2ked would
#: mark them with its "the unit disagrees with the book" flag, which is
#: reserved for somebody having saved over a preset.
_TYPOGRAPHIC = {
    "\u2018": "'",
    "\u2019": "'",  # single quotes
    "\u201c": '"',
    "\u201d": '"',  # double quotes
    "\u2013": "-",
    "\u2014": "-",  # en and em dashes
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",  # non-breaking space
}


def to_ascii(text: str) -> str:
    """Undo a word processor's substitutions, then drop anything left.

    Dropping rather than transliterating: a character the instrument cannot
    store is not a character the name has, and guessing at it would invent
    a difference between the catalog and the unit.
    """
    for fancy, plain in _TYPOGRAPHIC.items():
        text = text.replace(fancy, plain)
    return "".join(char for char in text if 32 <= ord(char) <= 126)


_ODT_BANK = re.compile(r"^Presets\s*-\s*Bank\s*(?P<bank>\d+)\s*$")
#: The name is taken verbatim after one separating space. Not ``\s*``:
#: some names carry two spaces on the instrument, and a greedy separator
#: eats the one that belongs to the name.
_ODT_PRESET = re.compile(r"^(?P<pc>\d{1,3})\.\s(?P<name>.+)$")


def read_odt(path: str) -> Dict[int, Dict[int, str]]:
    """``{bank: {program change: name}}`` from an OpenDocument patch list.

    E-MU published patch lists as documents as well as instrument
    definitions, and for at least one ROM -- X-Lead v2, Bank Select MSB 14
    -- the document is the *only* source to hand. The instrument-definition
    files do not cover it at all.

    An ``.odt`` is a zip holding ``content.xml``, and the text is recovered
    by stripping tags rather than by parsing the document model. Two things
    that costs, both found by comparing the result against a real unit and
    both silent until then:

    * **Runs of spaces are elements**, ``<text:s text:c="2"/>``, not
      characters. Stripped as tags, "K-1  HPF" becomes "K-1 HPF" -- a name
      that differs from the instrument's by one space, which is enough for
      p2ked to flag the preset as edited forever.
    * **Text is XML-escaped**, so a name containing ``&`` arrives as
      ``&amp;``.

    Both are handled below. If a future list nests its numbers in tables,
    this will need the real parser.
    """
    import html
    import zipfile

    with zipfile.ZipFile(path) as archive:
        xml = archive.read("content.xml").decode("utf-8", "replace")

    # Spaces first, while the elements still exist.
    xml = re.sub(r'<text:s\s+text:c="(\d+)"\s*/>', lambda m: " " * int(m.group(1)), xml)
    xml = re.sub(r"<text:s\s*/>", " ", xml)
    xml = re.sub(r"<text:tab\s*/>", " ", xml)

    lines = [
        html.unescape(line).strip()
        for line in re.sub(r"<[^>]+>", "\n", xml).split("\n")
        if line.strip()
    ]

    out: Dict[int, Dict[int, str]] = {}
    bank: Optional[int] = None
    for line in lines:
        heading = _ODT_BANK.match(line)
        if heading:
            bank = int(heading.group("bank"))
            out.setdefault(bank, {})
            continue
        if bank is None:
            continue
        entry = _ODT_PRESET.match(line)
        if entry:
            program_change = int(entry.group("pc"))
            if 0 <= program_change < roms.PRESETS_PER_BANK:
                out[bank][program_change] = to_ascii(entry.group("name"))
    return {bank: rows for bank, rows in out.items() if rows}


def build(paths: List[str]) -> Tuple[Dict[str, List[dict]], List[str]]:
    """Names keyed by p2ked's own bank ids, plus notes about what was left out."""
    out: Dict[str, List[dict]] = {}
    notes: List[str] = []
    known = {(entry.msb, entry.lsb): entry.id for entry in roms.banks()}

    for path in paths:
        sections = read_sections(path)
        refs = read_bank_refs(path)
        unclaimed: Dict[int, int] = {}
        for bank_number, section in sorted(refs.items()):
            msb, lsb = split_bank(bank_number)
            bank_id = known.get((msb, lsb))
            if bank_id is None:
                # A ROM p2ked's table has no row for. Counted and reported
                # rather than dropped: it means the table is incomplete, and
                # that is worth knowing.
                unclaimed[msb] = unclaimed.get(msb, 0) + 1
                continue
            rows = sections.get(section)
            if not rows:
                continue
            out.setdefault(bank_id, [])
            have = {row["pc"] for row in out[bank_id]}
            for program_change, name in sorted(rows.items()):
                if program_change in have or not name:
                    continue
                out[bank_id].append({"pc": program_change, "name": name})
        for msb, count in sorted(unclaimed.items()):
            notes.append(
                f"{os.path.basename(path)}: MSB {msb} has {count} bank(s) "
                f"that p2k/roms.py does not list"
            )

    for rows in out.values():
        rows.sort(key=lambda row: row["pc"])
    return out, notes


def merge_existing(banks_out: Dict[str, List[dict]], existing: cat.Catalog) -> bool:
    """Re-add printed banks this run did not produce, in place.

    The reason this exists: a ROM whose names came off the unit (because no
    ``.ins`` file covers it, or because it was only ever in the machine) must
    not be dropped by regenerating the file from instrument definitions
    alone. Returns whether the existing catalog had anything to merge.
    """
    if not existing:
        return False
    for bank_id, rows in existing.rows().items():
        banks_out.setdefault(bank_id, [dict(row) for row in rows])
        banks_out[bank_id].sort(key=lambda row: int(row["pc"]))
    return True


def preserve_existing(
    banks_out: Dict[str, List[dict]], payload: Dict[str, Any], output: str
) -> None:
    """Fold the existing file's kept content into what this run will write.

    Printed banks the extractor did not cover, and every name the unit
    reported, are carried forward. That is how a ROM read off the machine
    survives regenerating the file from instrument definitions alone -- it
    may not be in the machine at all.
    """
    existing = cat.load(output)
    if merge_existing(banks_out, existing):
        payload["note"] += (
            " Also carries names read off a unit by p2ked (banks the "
            "instrument-definition files do not cover)."
        )
    if existing.read_rows():
        payload["read"] = existing.read_rows()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ins", action="append", default=None, help="a Cakewalk .ins file (repeatable)"
    )
    parser.add_argument(
        "--odt",
        action="append",
        default=None,
        metavar="ROM=FILE",
        help="an OpenDocument patch list for one ROM, as "
        "ROMID=FILE (repeatable). The only source for "
        "ROMs the .ins files do not cover.",
    )
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    paths = args.ins or [DEFAULT_INS]
    missing = [path for path in paths if not os.path.exists(path)]
    if missing:
        raise SystemExit(
            f"error: no such file: {', '.join(missing)}\n"
            f"       These ship with the Proteus family's Cakewalk "
            f"instrument definitions. p2ked works without them, showing "
            f"numbers only."
        )

    banks_out, notes = build(paths)
    for note in notes:
        print(f"note: {note}", file=sys.stderr)

    for item in args.odt or []:
        rom_id, _, path = item.partition("=")
        if not path:
            raise SystemExit(f"error: --odt wants ROM=FILE, got {item!r}")
        entry = roms.rom(rom_id)  # fail now on an unknown ROM
        if not os.path.exists(path):
            raise SystemExit(f"error: no such file: {path}")
        found = read_odt(path)
        for bank, rows in sorted(found.items()):
            if bank >= len(entry.lsbs):
                print(
                    f"note: {os.path.basename(path)} has a bank {bank} "
                    f"that {rom_id} does not answer on; skipped",
                    file=sys.stderr,
                )
                continue
            bank_id = f"{rom_id}-{entry.lsbs[bank]}"
            have = {row["pc"] for row in banks_out.get(bank_id, [])}
            banks_out.setdefault(bank_id, []).extend(
                {"pc": pc, "name": name}
                for pc, name in sorted(rows.items())
                if pc not in have
            )
            banks_out[bank_id].sort(key=lambda row: row["pc"])

    payload: Dict[str, Any] = {
        "source": "; ".join(os.path.basename(path) for path in paths),
        "generated": datetime.date.today().isoformat(),
        "note": (
            "Generated locally by tools/extract_catalog.py from the "
            "user's own instrument-definition files. Not distributed "
            "with p2ked."
        ),
        "banks": banks_out,
    }
    # Keep any bank this run did not produce, and any names the unit
    # reported. That is how a ROM read off the machine survives regenerating
    # the file: p2ked writes what the ROM said, and this tool must not throw
    # that away just because the ROM is not in the .ins files (it may not be
    # in the machine at all).
    preserve_existing(banks_out, payload, args.output)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)
        handle.write("\n")

    total = sum(len(rows) for rows in banks_out.values())
    print(f"wrote {args.output}: {total} names across {len(banks_out)} banks")
    for bank_id in sorted(banks_out):
        print(f"  {bank_id:<14} {len(banks_out[bank_id]):>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
