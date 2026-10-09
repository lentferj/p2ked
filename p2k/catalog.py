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

"""Preset names, and where each one came from.

Two sources, kept apart all the way to the screen:

* **Printed** names, from the instrument-definition files shipped for the
  Proteus family. Generated locally into ``p2k/data/catalog.json``, which is
  gitignored -- those names are E-MU's and are not redistributed here.
* **Live** names, read from a unit over System Exclusive.

A single mapping cannot keep them distinguishable, and the distinction is
the useful part: a ROM bank whose live name differs from the printed one is
a printed list E-MU got wrong, and the unit is right. That is the single
most informative thing this program can put on a screen.

A **user** bank cannot support the same comparison. Its printed "names" are
placeholders -- E-MU's own instrument-definition file ships ``usr:A0``
wherever somebody's saved work goes -- so a difference against them is
guaranteed and means nothing. See :meth:`differs` for what that costs and
why it is still the right answer.

Unlike the sibling rxved, reading live names here costs nothing but time --
a Proteus names any preset on request without selecting it. There is
therefore no reason to prefer the printed catalog once a unit is connected,
and no "this will play the instrument" warning anywhere in p2ked.
"""

from __future__ import annotations

import json
import sys
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from p2k import roms

__all__ = ["Entry", "Catalog", "load", "empty", "DEFAULT_PATH"]

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "catalog.json"
)


@dataclass(frozen=True)
class Entry:
    bank_id: str
    program_change: int
    name: str

    @property
    def key(self) -> str:
        return f"{self.bank_id}:{self.program_change:03d}"


def _writable_bank(bank_id: str) -> bool:
    """Whether ``bank_id`` is the unit's own memory.

    The four user banks, and nothing else: a bank p2ked's ROM table does
    not list is *not* user memory, so the printed name keeps its authority.
    A :class:`LookupError` must not quietly switch the check off everywhere,
    which is what returning False here does.
    """
    try:
        return roms.bank(bank_id).rom.writable
    except LookupError:
        return False


class Catalog:
    """Printed names, plus whatever has been read from a unit."""

    def __init__(
        self, entries: Iterable[Entry] = (), *, source: str = "", generated: str = ""
    ) -> None:
        self._entries: Dict[str, Entry] = {}
        for entry in entries:
            self._entries[entry.key] = entry
        self._live: Dict[str, str] = {}
        self.source = source
        self.generated = generated

    # --- printed ------------------------------------------------------------

    def entry(self, bank_id: str, program_change: int) -> Optional[Entry]:
        return self._entries.get(f"{bank_id}:{program_change:03d}")

    def name(self, bank_id: str, program_change: int) -> Optional[str]:
        found = self.entry(bank_id, program_change)
        return found.name if found is not None else None

    def has(self, bank_id: str) -> bool:
        prefix = f"{bank_id}:"
        return any(key.startswith(prefix) for key in self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    # --- live ---------------------------------------------------------------

    def set_live_name(self, bank_id: str, program_change: int, name: str) -> None:
        self._live[f"{bank_id}:{program_change:03d}"] = name

    def live_name(self, bank_id: str, program_change: int) -> Optional[str]:
        return self._live.get(f"{bank_id}:{program_change:03d}")

    def is_live(self, bank_id: str, program_change: int) -> bool:
        return f"{bank_id}:{program_change:03d}" in self._live

    def differs(self, bank_id: str, program_change: int) -> bool:
        """Whether the unit and the printed list disagree about this slot.

        **A user bank cannot disagree with its printed list, because the
        printed list has no real names in it.** E-MU's own
        instrument-definition file cannot document what a user has saved
        into user memory, so its user-bank sections hold placeholders --
        ``usr:A0``, ``usr:C0`` -- 512 of them across the four banks.
        Comparing a real preset name against one of those always "differs",
        which is what produced a screen where every slot in every user bank
        carried ``*`` and the footnote said "saved over the factory preset"
        128 times. A placeholder is an admission that the document does not
        know, not a claim to be wrong about.

        **That is not the end of the user-bank story.** What a user bank can
        disagree with is *itself, earlier in this session*: p2ked reads one
        the moment it is looked at, and a later read that finds a different
        name has found something that changed while the program was open.
        That is the useful signal -- it used to be claimed here, from a
        document that could not support it -- and it now lives in
        ``p2ked.app.P2kedApp._session_change``, which owns the baseline.
        This method is only ever asked what is true against the *printed*
        list, which is why it answers False for user memory.

        So the comparison is only made where the printed list has authority:
        a ROM. There a difference means the printed list is wrong and the
        unit is right, which is the finding this exists for.

        That is not hypothetical, and it is not only whitespace. Reading
        whole ROMs off a unit and comparing them with E-MU's own published
        patch lists leaves disagreements in two distinct kinds:

        * **X-Lead v2**, 640 presets, 2026-09-12: 11 differences, every one
          internal whitespace -- the instrument holds two spaces where the
          document prints one.
        * **Composer**, all 1024 presets, 2026-10-02: **49**, and mostly not
          whitespace at all but errors in the published list itself --
          ``TrumpetMure2`` for ``TrumpetMute2``, ``808 Synthax`` for
          ``8O8 Synthax``, ``Clean RsrB`` for ``Clean R&B``, and two rows
          carrying the wrong category prefix (one of them naming a different
          instrument entirely: ``kb3:DX Organ`` against ``kit:Kit 1``).

        **What is lost, and where it went:** a user bank cannot be flagged
        against a printed list, and it is not flagged against one any more.
        It used to be, for all 512 slots, because a placeholder is always
        "differently named". The comparison that would mean something --
        this bank against *itself* at the start of the session -- needs state
        a catalog file cannot hold, so it lives in the browser:
        ``p2ked.app.P2kedApp._session_change``. Callers that show a ``*``
        should call ``_marked_because`` there, which decides which of the
        two complaints this slot is carrying.
        """
        live = self.live_name(bank_id, program_change)
        if live is None:
            return False
        printed = self.name(bank_id, program_change)
        if printed is None or printed == live:
            return False
        return not _writable_bank(bank_id)

    def disagreement(self, bank_id: str, program_change: int) -> Optional[str]:
        """Why the unit and the printed list differ here, in words.

        ``None`` when they agree, when the slot has not been read, or when
        the bank is the unit's own memory -- where the printed name is a
        placeholder and there is nothing to disagree with.

        It used to take a ``writable`` flag and say "saved over the factory
        preset" for a user bank. That sentence could only ever be reached by
        comparing a live name against ``usr:C0``, so it was printed for
        every slot in every user bank and never once because somebody had
        actually saved over something. The parameter is gone rather than
        left to be passed and ignored.
        """
        if not self.differs(bank_id, program_change):
            return None
        return "the printed list is wrong; the unit is right"

    def display_name(self, bank_id: str, program_change: int) -> str:
        """What to show: the unit's name if known, else the printed one."""
        live = self.live_name(bank_id, program_change)
        if live is not None:
            return live
        return self.name(bank_id, program_change) or ""

    # --- search -------------------------------------------------------------

    def search(self, needle: str) -> List[Tuple[str, int, str, bool]]:
        """Case-insensitive substring search over both sources.

        Each hit carries whether the unit and the printed list disagree
        about that slot, so a caller can show the same ``*`` the browser
        does. Search is where it matters most: the browser marks a slot the
        user is already looking at, while a search result is a name from a
        bank they have not opened -- which is how a ROM bank whose printed
        list is wrong gets noticed at all. A user bank's hit never carries
        the mark; its printed name is a placeholder, so there is nothing to
        disagree with.
        """
        wanted = needle.strip().lower()
        if not wanted:
            return []
        seen: Dict[str, Tuple[str, int, str]] = {}
        for key, entry in self._entries.items():
            if wanted in entry.name.lower():
                seen[key] = (entry.bank_id, entry.program_change, entry.name)
        for key, name in self._live.items():
            if wanted in name.lower():
                bank_id, _, number = key.rpartition(":")
                seen[key] = (bank_id, int(number), name)
        return [seen[key] + (self.differs(*seen[key][:2]),) for key in sorted(seen)]


def empty() -> Catalog:
    return Catalog()


def load(path: Optional[str] = None) -> Catalog:
    """Load the generated catalog, or an empty one.

    A missing catalog is normal and not an error: p2ked works without it,
    showing numbers only, and a connected unit can supply every name itself.
    """
    target = path or DEFAULT_PATH
    if not os.path.exists(target):
        return empty()
    try:
        with open(target, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return empty()
    entries = []
    skipped = 0
    for bank_id, rows in payload.get("banks", {}).items():
        for row in rows:
            # One bad row must not cost the whole catalog. A missing one is
            # already normal here -- the program runs on numbers alone and
            # a connected unit can supply every name -- so a corrupt one
            # taking the program down with it is the odd behaviour, not
            # skipping it.
            try:
                entries.append(
                    Entry(
                        bank_id=bank_id, program_change=int(row["pc"]), name=row["name"]
                    )
                )
            except (KeyError, TypeError, ValueError):
                skipped += 1
    if skipped:
        print(
            f"warning: {target} has {skipped} unreadable row(s), skipped; "
            f"regenerate it with tools/extract_catalog.py",
            file=sys.stderr,
        )
    return Catalog(
        entries,
        source=payload.get("source", ""),
        generated=payload.get("generated", ""),
    )
