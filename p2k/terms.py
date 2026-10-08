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

"""What the Proteus calls things, declared once.

**The instrument's word is the instrument's.** The Proteus 2000's display
says PRESET for one stored sound, and the thing it lives in is a bank, so
those are the words every string a user reads uses here -- the list view,
the pane headings, the help, the README.

**A ROM is not a bank, and p2ked says which is which.** The four SIMM
sockets each hold a ROM, and each ROM holds several banks. ``container`` is
therefore ``bank``, not ``ROM``: the user's browser lists one ROM's banks,
and the CLI's canonical command for the whole table is ``banks`` with
``roms`` still accepted. ``rom`` and ``simm`` are recorded below as this
tool's own concepts, since the family has no opinion about how a
sample-based instrument is expanded.

The wire's word stays in the code that builds wire messages: on the wire a
preset is a Program Change, and Bank Select MSB chooses the ROM. That
translation lives in :mod:`p2k.roms` where it is visible.

**This module is a declaration, not yet a source of strings.** No
user-facing text is built from :data:`TERMS` today; its one consumer is
``tests/test_conformance.py``, which checks the vocabulary against the
family. When a screen or a help block starts saying "bank" or "preset",
it should read the word from here rather than spell it out again.
"""

from __future__ import annotations

from vinsynlib.terms import Terminology, register

__all__ = ["TERMS"]

TERMS = Terminology(
    app_name="p2ked",
    sound="preset",
    container="bank",
    device="E-MU Proteus 2000",
    own={
        # A SIMM holds a ROM; a ROM holds several banks. The family says
        # "bank" for the area a preset lives in, and so does p2ked.
        "rom": "ROM",
        "simm": "SIMM",
        # E-MU prefixes preset names with a short category, as in
        # "bas: Deep Bass". p2ked's `C` key filters on it.
        "category": "category",
    },
)

#: Registered at import so the family's registry knows what this tool calls
#: its concepts. Registration rather than a monkeypatched module global: a
#: library cannot know the name of the program using it, and passing it in is
#: honest where patching is global.
register(TERMS)
