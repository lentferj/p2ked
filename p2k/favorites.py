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

"""The favourites database: SQLite, slots, ratings, tags.

Now a binding of :mod:`vinsynlib.favorites` rather than a fifth copy of it.
The schema, the migration, the locking and the per-platform path rules are
the family's and live in one place.

What is added here is the name, and it is a parameter rather than a
constant. ``APP_NAME`` used to be a module global that
:func:`vinsynlib.favorites.data_dir` read, which meant the library could
only ever know one application's name -- so a project either monkeypatched
it (global, and therefore visible to every importer) or copied the whole
module. Passing it in is the third way and the honest one.

``Favorite`` and ``Favorites`` keep the American spelling in code while every
string a user reads says "favourite". That is deliberate and it is the
family's: the flag on nine command lines is ``--favorites`` and the file it
names is ``favorites.db``, so the identifier follows the file rather than
the prose. See vinsynlib's docs/UX-SPEC.md section 1.
"""

from __future__ import annotations

from typing import Any

from vinsynlib import favorites as _favorites
from vinsynlib.favorites import SCHEMA_VERSION, Favorite

__all__ = [
    "APP_NAME",
    "DB_NAME",
    "SCHEMA_VERSION",
    "Favorite",
    "Favorites",
    "data_dir",
    "default_path",
    "rating_cell",
]

#: The directory name used under whichever per-platform data root applies.
APP_NAME = "p2ked"

#: The database's filename, in that directory.
DB_NAME = "favorites.db"


def data_dir() -> str:
    """This application's per-platform data directory."""
    return _favorites.data_dir(APP_NAME)


def default_path() -> str:
    """Where the favourites database lives unless ``--favorites`` says otherwise."""
    return _favorites.default_path(APP_NAME, DB_NAME)


def rating_cell(rating: int, *, scale: int = 5) -> str:
    """How a rating reads in a table: the filled stars, then the rest dim.

    The signature and the glyphs are now the library's too:
    :func:`vinsynlib.favorites.rating_cell` was added in vinsynlib 0.4.0
    and renders the same cell, ``scale`` included. This copy is kept for one
    release and the next phase replaces it with the library's; the reasoning
    below is why it was written here first, and is the record of that.

    Value *and* scale, because ``★★★`` is ambiguous where ``★★★··`` is not,
    and zero is blank rather than five dots -- blank for "not rated", the
    same blank-means-absent the favourite marker column uses.

    ``★`` and not ``*``, and that is this project's own decision rather than
    the family's: ``*`` already means "this name disagrees with the
    catalogue" in the preset table's name column, on the detail line under
    it, in ``p2kcli find`` and in ``p2kcli names``. One glyph meaning two
    things in one table is how the favourite marker came to be a heart --
    and here it would be worse than a collision, because the two meanings
    answer different questions: "the unit and the book disagree" is a fact
    about a slot, and a rating is the user's own opinion of one.

    Sibling rxved spells the cell the same way for the same reason. That is
    the point of it living here rather than beside either front end: both
    show a rating, and a second copy of a glyph is exactly the kind of
    thing that drifts.
    """
    if rating == 0:
        return ""
    return "★" * rating + "·" * (scale - rating)


class Favorites(_favorites.Favorites):
    """A favourites store that defaults to *this* application's directory.

    A subclass rather than a rebinding because the base class defaults
    ``app_name`` to the library's own name -- correct for a library that
    cannot know its caller, wrong here: a bare ``Favorites()`` must land in
    ``p2ked``'s data directory and not in ``vinsynlib``'s, or the user's own
    work would be written somewhere they have never heard of and
    ``--favorites`` would be the only way to find it.
    """

    def __init__(
        self, path: str | None = None, *, db_name: str = DB_NAME, **kwargs: Any
    ) -> None:
        kwargs.setdefault("app_name", APP_NAME)
        super().__init__(path, db_name=db_name, **kwargs)

    def __enter__(self) -> Favorites:
        # Narrowed from the base class's own return type, so that
        # ``with Favorites(...) as db`` type-checks as this subclass. The base
        # returns itself; this says so in a type the fixtures can use.
        return self
