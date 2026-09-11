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
the useful part: a user bank whose live name differs from the printed one is
a bank somebody has saved their own work into, and that is the single most
informative thing this program can put on a screen.

Unlike the sibling rxved, reading live names here costs nothing but time --
a Proteus names any preset on request without selecting it. There is
therefore no reason to prefer the printed catalog once a unit is connected,
and no "this will play the instrument" warning anywhere in p2ked.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

__all__ = ["Entry", "Catalog", "load", "empty", "DEFAULT_PATH"]

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "catalog.json")


@dataclass(frozen=True)
class Entry:
    bank_id: str
    program_change: int
    name: str

    @property
    def key(self) -> str:
        return f"{self.bank_id}:{self.program_change:03d}"


class Catalog:
    """Printed names, plus whatever has been read from a unit."""

    def __init__(self, entries: Iterable[Entry] = (), *, source: str = "",
                 generated: str = "") -> None:
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

    def set_live_name(self, bank_id: str, program_change: int,
                      name: str) -> None:
        self._live[f"{bank_id}:{program_change:03d}"] = name

    def live_name(self, bank_id: str, program_change: int) -> Optional[str]:
        return self._live.get(f"{bank_id}:{program_change:03d}")

    def is_live(self, bank_id: str, program_change: int) -> bool:
        return f"{bank_id}:{program_change:03d}" in self._live

    def differs(self, bank_id: str, program_change: int) -> bool:
        """Whether the unit and the printed list disagree about this slot."""
        live = self.live_name(bank_id, program_change)
        if live is None:
            return False
        printed = self.name(bank_id, program_change)
        return printed is not None and printed != live

    def display_name(self, bank_id: str, program_change: int) -> str:
        """What to show: the unit's name if known, else the printed one."""
        live = self.live_name(bank_id, program_change)
        if live is not None:
            return live
        return self.name(bank_id, program_change) or ""

    # --- search -------------------------------------------------------------

    def search(self, needle: str) -> List[Tuple[str, int, str]]:
        """Case-insensitive substring search over both sources."""
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
        return [seen[key] for key in sorted(seen)]


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
    for bank_id, rows in payload.get("banks", {}).items():
        for row in rows:
            entries.append(Entry(bank_id=bank_id,
                                 program_change=int(row["pc"]),
                                 name=row["name"]))
    return Catalog(entries, source=payload.get("source", ""),
                   generated=payload.get("generated", ""))
