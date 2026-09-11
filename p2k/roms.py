# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# The ROM names and their Bank Select MSB/LSB allocation are transcribed as
# data from the Cakewalk instrument-definition files distributed for the
# Proteus family, cross-read against the Proteus 2000 Operation Manual.
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

"""Which ROM is which, and what selects a preset in it.

A Proteus 2000 has four user banks and up to four ROM SIMMs. Selection is
Bank Select MSB and LSB followed by a Program Change:

* **MSB identifies the ROM.** Each ROM has one, fixed, and unique across the
  family -- the Composer ROM is always MSB 4 whichever slot it sits in.
* **LSB is the bank within that ROM**, each holding up to 128 presets.
* **Program Change picks one of those 128.**

That is a far kinder arrangement than the sibling rxved has to cope with on
an XV-2020, where the expansion boards share one MSB and are allocated a
*running* range of LSBs -- a list with a hole in it that has to be
transcribed and cannot be derived.

**The trap here is a different one, and it is not resolved.** Two distinct
numbers identify a ROM and this module keeps them apart:

* :attr:`Rom.msb` -- the Bank Select MSB, used when *selecting* a preset.
  Well sourced.
* the **SIMM ID**, which the unit reports in its Configuration response and
  which System Exclusive uses as the "ROM ID" when *asking about* a preset.

Nothing in E-MU's System Exclusive specification maps SIMM IDs to ROM names,
and there is no hardware here to ask. It is entirely plausible that the SIMM
ID simply *is* the Bank Select MSB -- that would be the sensible design --
but plausible is not known, and a wrong ROM ID in a name request is answered
with silence, which looks like every other failure. See
:func:`rom_for_simm_id` and TODO.md.

The one ROM ID that **is** documented is ``0``, which means the user banks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "PRESETS_PER_BANK",
    "USER_MSB",
    "USER_ROM_ID",
    "Rom",
    "Bank",
    "Preset",
    "ROMS",
    "USER",
    "rom",
    "rom_ids",
    "banks",
    "bank",
    "bank_ids",
    "presets",
    "preset",
    "lookup",
    "rom_for_simm_id",
]

#: Every bank on this family is 128 presets, which is what a Program Change
#: can address. A ROM's last bank may be partly empty; the count in
#: :class:`Rom` says how many presets it really has.
PRESETS_PER_BANK = 128

#: Bank Select MSB of the user banks.
USER_MSB = 0

#: The System Exclusive ROM ID of user memory. **This one is documented**
#: ("0 for User"), unlike every other ROM ID.
USER_ROM_ID = 0


@dataclass(frozen=True)
class Rom:
    """One ROM SIMM, or the user memory.

    ``count`` is how many presets it actually holds, which is not always
    ``len(lsbs) * 128``: a ROM whose last bank is partly full still occupies
    the whole LSB.
    """

    id: str                  #: Short key used everywhere: "XLEAD", "USER".
    name: str                #: What E-MU calls it.
    msb: int                 #: Bank Select MSB. Identifies the ROM.
    lsbs: Tuple[int, ...]    #: Bank Select LSBs it answers on.
    count: int               #: Presets it holds.
    writable: bool = False   #: Only the user banks.

    @property
    def bank_count(self) -> int:
        return len(self.lsbs)


@dataclass(frozen=True)
class Bank:
    """One LSB within a ROM: up to 128 presets."""

    rom: Rom
    lsb: int
    #: Presets in this bank. The last bank of a ROM may hold fewer than 128.
    count: int

    @property
    def id(self) -> str:
        return f"{self.rom.id}-{self.lsb}"

    @property
    def label(self) -> str:
        return f"{self.rom.name} bank {self.lsb}"

    @property
    def msb(self) -> int:
        return self.rom.msb


@dataclass(frozen=True)
class Preset:
    """One selectable preset.

    :attr:`number` is the preset's number **within its ROM**, which is what
    the unit's own display shows and what System Exclusive asks for.
    :attr:`program_change` is the byte on the wire, 0-127 within the bank.
    They are separate attributes and nothing converts between them silently
    -- the same rule the sibling rxved applies to Roland's 1-based display
    numbers, for the same reason.
    """

    bank: Bank
    number: int             #: Within the ROM, 0-based, as SysEx counts them.
    program_change: int     #: Within the bank, 0-127.

    @property
    def rom(self) -> Rom:
        return self.bank.rom

    @property
    def bank_id(self) -> str:
        return self.bank.id

    @property
    def msb(self) -> int:
        return self.bank.msb

    @property
    def lsb(self) -> int:
        return self.bank.lsb

    @property
    def key(self) -> str:
        return f"{self.bank.id}:{self.number:04d}"

    def __str__(self) -> str:
        return f"{self.bank.label} {self.program_change:03d}"


def _rom(id: str, name: str, msb: int, lsbs: Tuple[int, ...], count: int,
         writable: bool = False) -> Rom:
    return Rom(id=id, name=name, msb=msb, lsbs=lsbs, count=count,
               writable=writable)


#: The ROM table, transcribed from the Cakewalk instrument-definition files
#: for the Proteus family.
#:
#: Preset counts are ``len(lsbs) * 128`` here because that is what those
#: files describe -- they list banks, not populated presets. A ROM whose
#: last bank is partly empty will therefore show slots that name nothing
#: until a real unit is asked. That is preferred to inventing a count: an
#: over-long bank shows empty rows, while a short one *hides* presets, and a
#: hidden preset is not discoverable by the person looking for it.
ROMS: Tuple[Rom, ...] = (
    _rom("USER", "User", 0, (0, 1, 2, 3), 512, writable=True),
    _rom("XTREME", "Extreme", 2, (0, 1), 256),
    _rom("AUDITY", "Audity", 3, (0, 1, 2, 3, 4), 640),
    _rom("COMPOSER", "Composer", 4, tuple(range(8)), 1024),
    _rom("PROTOZOA", "Protozoa", 5, (0, 1, 2, 3), 512),
    _rom("B3", "Definitive B-3", 6, (0, 1, 2), 384),
    _rom("XLEAD", "Xtreme Lead", 7, (0, 1, 2, 3), 512),
    _rom("ZR", "Sounds of the ZR", 8, (0, 1, 2, 3), 512),
    _rom("WORLD", "World Expedition", 9, (0, 1, 2, 3), 512),
    # Three banks, not the two the instrument-definition file's Patch[]
    # index implies: its third bank is indexed as 1281 while labelling
    # itself 1282. See tools/extract_catalog.py and RESOLUTION_NOTES.
    _rom("ORCH1", "Orchestral Sessions Vol. 1", 10, (0, 1, 2), 384),
    _rom("ORCH2", "Orchestral Sessions Vol. 2", 11, (0,), 128),
    _rom("PHATT", "Pure Phatt", 13, (0, 1, 2, 3), 512),
    _rom("ENSONIQ", "Ensoniq Project", 16, (0, 1, 2, 3), 512),
    _rom("P2500", "Proteus 2500", 17, (0, 1, 2, 3), 512),
    _rom("VINTAGE", "Vintage Collection", 18, (0, 1, 2, 3), 512),
    _rom("HOLYGRAIL", "Holy Grail", 64, (0,), 128),
    _rom("TECHNO", "Techno Synth", 65, (0, 1, 2, 3), 512),
    _rom("ADVORCH", "Advanced Orchestra", 66, (0, 1), 256),
    _rom("BEATGARDEN", "Beat Garden", 67, (0, 1, 2, 3), 512),
)

USER = ROMS[0]

_BY_ID: Dict[str, Rom] = {entry.id: entry for entry in ROMS}
_BY_MSB: Dict[int, Rom] = {entry.msb: entry for entry in ROMS}


def rom(rom_id: str) -> Rom:
    try:
        return _BY_ID[rom_id]
    except KeyError:
        raise LookupError(
            f"no ROM {rom_id!r}; have {', '.join(sorted(_BY_ID))}") from None


def rom_ids() -> List[str]:
    return [entry.id for entry in ROMS]


def rom_for_msb(msb: int) -> Optional[Rom]:
    """The ROM a Bank Select MSB identifies, if p2ked's table claims it."""
    return _BY_MSB.get(msb)


def rom_for_simm_id(simm_id: int) -> Optional[Rom]:
    """The ROM a *reported SIMM ID* names -- **a guess, and labelled one.**

    Returns the ROM whose Bank Select MSB equals ``simm_id``, on the
    hypothesis that E-MU used one number for both. That hypothesis is
    untested: no document here states the SIMM IDs, and there is no hardware
    to ask.

    Callers must present the result as a guess. A browser that quietly
    labels a SIMM "Composer" on this basis, and is wrong, has invented a
    fact the user cannot check and will not think to doubt.
    """
    return _BY_MSB.get(simm_id)


def banks(rom_id: Optional[str] = None) -> List[Bank]:
    """Every bank, or every bank of one ROM."""
    out: List[Bank] = []
    for entry in (ROMS if rom_id is None else (rom(rom_id),)):
        remaining = entry.count
        for lsb in entry.lsbs:
            size = min(PRESETS_PER_BANK, remaining)
            out.append(Bank(rom=entry, lsb=lsb, count=max(size, 0)))
            remaining -= size
    return out


_BANKS: Dict[str, Bank] = {entry.id: entry for entry in banks()}


def bank(bank_id: str) -> Bank:
    try:
        return _BANKS[bank_id]
    except KeyError:
        raise LookupError(
            f"no bank {bank_id!r}; have {', '.join(_BANKS)}") from None


def bank_ids(rom_id: Optional[str] = None) -> List[str]:
    return [entry.id for entry in banks(rom_id)]


def presets(bank_id: str) -> List[Preset]:
    """Every preset in a bank.

    ``number`` counts from the start of the **ROM** and ``program_change``
    from the start of the bank, so bank 1 preset 0 is ROM preset 128 and
    program change 0. Both are carried; neither is derived at the point of
    use.
    """
    entry = bank(bank_id)
    base = 0
    for lsb in entry.rom.lsbs:
        if lsb == entry.lsb:
            break
        base += PRESETS_PER_BANK
    return [
        Preset(bank=entry, number=base + index, program_change=index)
        for index in range(entry.count)
    ]


def preset(bank_id: str, program_change: int) -> Preset:
    entry = bank(bank_id)
    if not 0 <= program_change < entry.count:
        raise LookupError(
            f"{bank_id} holds {entry.count} presets; {program_change} is "
            f"outside 0-{entry.count - 1}")
    return presets(bank_id)[program_change]


def lookup(msb: int, lsb: int, program_change: int) -> Optional[Preset]:
    """What does this MSB/LSB/PC triple select? The inverse of everything.

    ``None`` when no ROM in p2ked's table claims the MSB, or the ROM does
    not answer on that LSB. That is a real answer and not a failure: a ROM
    this table does not know about is a ROM somebody has plugged in.
    """
    found = rom_for_msb(msb)
    if found is None or lsb not in found.lsbs:
        return None
    try:
        return preset(f"{found.id}-{lsb}", program_change)
    except LookupError:
        return None
