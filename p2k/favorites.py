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

"""The local favourites database.

The one piece of state in p2ked that is genuinely the **user's** rather than
the device's or E-MU's, which is why it gets a real database rather than
another key in ``config.toml``. Three things follow from that:

**It is keyed on the slot, not on the name.** A row records ``XLEAD2-1``
number 63, never "led:Fat S12" -- so a favourite survives the user renaming
a USER preset, and so a favourite of a ROM slot means the slot, permanently.
The name is stored too, but only as a label to show when the catalog is
missing; it is never the identity.

**The bank id carries the ROM, and that is deliberate.** ``XLEAD2-1`` is
X-Lead v2's second bank: the ROM's SIMM id is the Bank Select MSB and the
bank within it is the LSB, so the pair is what a sequencer actually sends.
Storing an MSB/LSB pair instead would make a favourite meaningless the day a
ROM is moved to another slot, and storing the ROM name alone would not say
which of its banks. The catalog key says both and survives both.

**It is SQLite, and that is not over-engineering for a list of favourites.**
A JSON file rewritten on every toggle loses the whole file to a crash or a
full disk mid-write, and the natural next features -- ratings, tags, notes,
"when did I last use this" -- are all things a flat file grows badly. SQLite
gives atomic writes for free. The schema is versioned from the first commit
so the second version does not have to guess what the first one wrote.

**It lives outside the project directory by default**, in the per-platform
application-*data* directory -- see :func:`data_dir` for where that is on
each and why. Unlike ``config.toml``, which is a disposable cache of which
MIDI port answered last and lives in the working directory, favourites are
the user's own work: the one thing here worth backing up, and the one thing
that must not be lost to a ``git clean`` in a checkout. The sibling projects
keep their bench data in-tree and explicitly note the risk that creates;
this does not repeat it.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "Favorite",
    "Favorites",
    "default_path",
    "data_dir",
    "APP_NAME",
    "DB_NAME",
    "SCHEMA_VERSION",
]

#: Bumped whenever the schema changes; :meth:`Favorites._migrate` reads it.
SCHEMA_VERSION = 1


#: The directory name used under whichever per-platform data root applies.
APP_NAME = "p2ked"

#: The database's filename, in that directory.
DB_NAME = "favorites.db"


def data_dir() -> str:
    """The per-platform directory for this application's **data**.

    Data, not configuration: the distinction is real on every platform and
    matters here, because favourites are the user's own work — the one thing
    in this project worth backing up — while ``config.toml`` is a cache of
    which MIDI port answered last and is disposable.

    * **Windows** — ``%LOCALAPPDATA%\\p2ked`` (typically
      ``C:\\Users\\<user>\\AppData\\Local\\p2ked``).

      Local rather than Roaming deliberately. ``%APPDATA%`` roams, and a
      roaming profile copies files wholesale at logon and logoff; a SQLite
      database caught mid-write by that copy, or opened on two machines at
      once against one synced file, is a known way to corrupt one. SQLite's
      own documentation warns against network filesystems for the same
      reason. Roaming would be the right answer for a small settings file
      and is the wrong one for a database.

    * **macOS** — ``~/Library/Application Support/p2ked``, which is where
      Apple's File System Programming Guide puts application data that is
      not a cache and not a user document.

    * **Linux, BSD, everything else** — the XDG Base Directory
      Specification: ``$XDG_DATA_HOME/p2ked``, falling back to
      ``~/.local/share/p2ked``. Note that XDG requires ``XDG_DATA_HOME`` to
      be an **absolute** path and says a relative one must be ignored, so a
      stray relative value falls back rather than creating a directory
      wherever the process happens to have been started.

    Every branch falls back to the XDG layout if the platform's own
    environment variable is missing, which is what happens on a stripped
    Windows service account or a macOS process with no HOME. A wrong-looking
    but writable path beats raising on startup, since the alternative is a
    browser that will not open because it cannot decide where to put a file
    the user may never use.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return os.path.join(base, APP_NAME)
    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        if home != "~":
            return os.path.join(home, "Library", "Application Support",
                                APP_NAME)

    base = os.environ.get("XDG_DATA_HOME")
    # XDG: "If $XDG_DATA_HOME is either not set or empty, a default equal to
    # $HOME/.local/share should be used." and paths in it must be absolute.
    if not base or not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, APP_NAME)


def default_path() -> str:
    """Where the favourites database lives, per platform.

    Overridable everywhere it is used — ``--favorites`` on both front ends —
    so a user who wants it beside a project, on a stick, or in a synced
    folder can say so.
    """
    return os.path.join(data_dir(), DB_NAME)


class _Result:
    """The rows of one statement, already fetched.

    :class:`_LockedConnection` hands this back instead of a live cursor,
    because a cursor iterated *after* the lock is released is exactly the
    interleaving the lock exists to prevent. Everything is read inside the
    lock; what comes out is an ordinary list.
    """

    __slots__ = ("rows", "rowcount")

    def __init__(self, rows, rowcount: int) -> None:
        self.rows = rows
        self.rowcount = rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _LockedConnection:
    """A SQLite connection usable from more than one thread.

    SQLite refuses cross-thread use of a connection by default, and that
    default is a silent mine in a Textual application: the store is opened on
    the main thread, and any background worker that so much as asks for
    ``len()`` raises ``ProgrammingError`` *out of the worker*, which takes the
    whole application down. That is not hypothetical -- it is what pressing
    `i` did, the first time anybody pressed it, because the device-info
    worker built its report on the wrong thread.

    The structural fix was to move that work back to the main thread. This is
    the belt to that's braces: one lock, held across each statement and its
    fetch, so the next worker to reach for the database finds it safe rather
    than fatal. SQLite is content with a connection shared between threads as
    long as the calls do not overlap, and serialising operations this small
    costs nothing at this size.
    """

    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row

    def execute(self, sql: str, parameters=()) -> _Result:
        with self._lock:
            cursor = self._db.execute(sql, parameters)
            rows = cursor.fetchall()
            return _Result(rows, cursor.rowcount)

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._db.executescript(sql)

    def commit(self) -> None:
        with self._lock:
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


@dataclass(frozen=True)
class Favorite:
    """One favourited slot."""

    bank_id: str
    number: int
    #: The name at the time of favouriting, as a label of last resort. Not
    #: the identity: see the module docstring.
    name: str = ""
    rating: int = 0
    tags: str = ""
    note: str = ""
    added: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.bank_id}:{self.number:03d}"

    @property
    def tag_list(self) -> List[str]:
        return [t for t in (part.strip() for part in self.tags.split(",")) if t]


class Favorites:
    """A SQLite-backed set of favourited slots.

    Usable as a context manager. Safe to construct against a path whose
    directory does not exist yet -- it is created.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)),
                        exist_ok=True)
        # Shared across threads on purpose; see _LockedConnection.
        self._db = _LockedConnection(self.path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    # --- schema -------------------------------------------------------------

    def _migrate(self) -> None:
        """Create or upgrade the schema.

        ``user_version`` rather than a table of our own: it is a single
        integer in the database header, costs no row, and cannot itself be
        the thing that is missing when we go looking for the version.
        """
        current = self._db.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"{self.path} was written by a newer p2ked (schema "
                f"{current}, this build understands {SCHEMA_VERSION}). "
                f"Refusing to touch it rather than risk dropping columns it "
                f"has and this does not."
            )
        if current < 1:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS favorites (
                    bank_id TEXT    NOT NULL,
                    number  INTEGER NOT NULL,
                    name    TEXT    NOT NULL DEFAULT '',
                    rating  INTEGER NOT NULL DEFAULT 0,
                    tags    TEXT    NOT NULL DEFAULT '',
                    note    TEXT    NOT NULL DEFAULT '',
                    added   REAL    NOT NULL DEFAULT 0,
                    PRIMARY KEY (bank_id, number)
                );
                CREATE INDEX IF NOT EXISTS favorites_rating
                    ON favorites (rating DESC);
                """
            )
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.commit()

    # --- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        try:
            self._db.commit()
        finally:
            self._db.close()

    def __enter__(self) -> "Favorites":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # --- reading ------------------------------------------------------------

    def __contains__(self, key) -> bool:
        bank_id, number = _split(key)
        row = self._db.execute(
            "SELECT 1 FROM favorites WHERE bank_id = ? AND number = ?",
            (bank_id, number),
        ).fetchone()
        return row is not None

    def __len__(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]

    def get(self, bank_id: str, number: int) -> Optional[Favorite]:
        row = self._db.execute(
            "SELECT * FROM favorites WHERE bank_id = ? AND number = ?",
            (bank_id, int(number)),
        ).fetchone()
        return _to_favorite(row) if row is not None else None

    def keys(self) -> set:
        """Every favourited slot, as ``BANK:NNN`` strings.

        One query for the whole set rather than a ``__contains__`` per row:
        the browser needs to mark every visible line, and a bank is up to 128
        lines redrawn on every cursor move.
        """
        return {
            f"{row['bank_id']}:{row['number']:03d}"
            for row in self._db.execute(
                "SELECT bank_id, number FROM favorites")
        }

    def keys_for_bank(self, bank_id: str) -> set:
        return {
            row["number"] for row in self._db.execute(
                "SELECT number FROM favorites WHERE bank_id = ?", (bank_id,))
        }

    def all(self, *, order: str = "added") -> List[Favorite]:
        """Every favourite, newest first by default.

        ``order`` is validated against a fixed set rather than interpolated:
        it reaches here from a command-line argument, and an ORDER BY is the
        one clause a parameter placeholder cannot carry.
        """
        clauses = {
            "added": "added DESC",
            "rating": "rating DESC, added DESC",
            "bank": "bank_id, number",
            "name": "name COLLATE NOCASE, bank_id, number",
        }
        if order not in clauses:
            raise ValueError(
                f"unknown order {order!r}; have {', '.join(sorted(clauses))}"
            )
        return [
            _to_favorite(row) for row in self._db.execute(
                f"SELECT * FROM favorites ORDER BY {clauses[order]}")
        ]

    def search(self, needle: str) -> List[Favorite]:
        """Favourites whose name, tags or note contain ``needle``."""
        pattern = f"%{needle}%"
        return [
            _to_favorite(row) for row in self._db.execute(
                "SELECT * FROM favorites WHERE name LIKE ? OR tags LIKE ? "
                "OR note LIKE ? ORDER BY bank_id, number",
                (pattern, pattern, pattern),
            )
        ]

    def with_tag(self, tag: str) -> List[Favorite]:
        """Favourites carrying ``tag``.

        Matched against the parsed list rather than with a ``LIKE '%tag%'``,
        which would make "pad" match "padded" and "lead" match "misleading".
        Tags are a short comma-separated string; filtering them in Python
        costs nothing at this size and is correct.
        """
        wanted = tag.strip().lower()
        return [
            fav for fav in self.all(order="bank")
            if wanted in {t.lower() for t in fav.tag_list}
        ]

    def tags(self) -> Dict[str, int]:
        """Every tag in use, with how many favourites carry it."""
        counts: Dict[str, int] = {}
        for fav in self.all(order="bank"):
            for tag in fav.tag_list:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    # --- writing ------------------------------------------------------------

    def add(self, bank_id: str, number: int, *, name: str = "",
            rating: int = 0, tags: str = "", note: str = "") -> Favorite:
        """Favourite a slot, or update the one that is already there.

        An upsert that **preserves ``added``** on an existing row: re-adding
        a favourite is an edit, not a re-acquisition, and quietly resetting
        the date would corrupt the one ordering the user cannot reconstruct.
        """
        existing = self.get(bank_id, number)
        added = existing.added if existing is not None else time.time()
        self._db.execute(
            "INSERT INTO favorites (bank_id, number, name, rating, tags, "
            "note, added) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (bank_id, number) DO UPDATE SET "
            "name = excluded.name, rating = excluded.rating, "
            "tags = excluded.tags, note = excluded.note",
            (bank_id, int(number), name, int(rating), tags, note, added),
        )
        self._db.commit()
        return Favorite(bank_id, int(number), name, int(rating), tags, note,
                        added)

    def remove(self, bank_id: str, number: int) -> bool:
        """Un-favourite a slot. ``True`` if there was one."""
        cursor = self._db.execute(
            "DELETE FROM favorites WHERE bank_id = ? AND number = ?",
            (bank_id, int(number)),
        )
        self._db.commit()
        return cursor.rowcount > 0

    def toggle(self, bank_id: str, number: int, *, name: str = ""
               ) -> bool:
        """Flip a slot's favourite state. ``True`` if it is now a favourite."""
        if self.remove(bank_id, number):
            return False
        self.add(bank_id, number, name=name)
        return True

    def set_rating(self, bank_id: str, number: int, rating: int) -> None:
        if not 0 <= rating <= 5:
            raise ValueError(f"rating {rating} is outside 0-5")
        self.add(bank_id, number, **_merge(self.get(bank_id, number),
                                           rating=rating))

    def set_tags(self, bank_id: str, number: int, tags: str) -> None:
        self.add(bank_id, number, **_merge(self.get(bank_id, number),
                                           tags=_clean_tags(tags)))

    def set_note(self, bank_id: str, number: int, note: str) -> None:
        self.add(bank_id, number, **_merge(self.get(bank_id, number),
                                           note=note))

    def refresh_names(self, lookup) -> int:
        """Re-label favourites from a name source. Returns how many changed.

        Used after a catalog is generated or a bank is read from the device,
        so that favourites made before there were any names stop showing
        "--". ``lookup(bank_id, number)`` returns a name or ``None``.
        """
        changed = 0
        for fav in self.all(order="bank"):
            fresh = lookup(fav.bank_id, fav.number)
            if fresh and fresh != fav.name:
                self._db.execute(
                    "UPDATE favorites SET name = ? WHERE bank_id = ? "
                    "AND number = ?", (fresh, fav.bank_id, fav.number),
                )
                changed += 1
        if changed:
            self._db.commit()
        return changed


# --- helpers ----------------------------------------------------------------


def _split(key) -> Tuple[str, int]:
    """Accept either ``("XLEAD2-1", 63)`` or ``"XLEAD2-1:063"``."""
    if isinstance(key, tuple):
        return key[0], int(key[1])
    bank_id, _, number = str(key).partition(":")
    return bank_id, int(number)


def _to_favorite(row: sqlite3.Row) -> Favorite:
    return Favorite(
        bank_id=row["bank_id"], number=row["number"], name=row["name"],
        rating=row["rating"], tags=row["tags"], note=row["note"],
        added=row["added"],
    )


def _merge(existing: Optional[Favorite], **changes) -> dict:
    """Fields for :meth:`Favorites.add` that change one thing and keep the rest.

    Without this, setting a rating on a favourite would blank its tags and
    note, because ``add`` takes every field and defaults the ones it is not
    given.
    """
    base = {
        "name": existing.name if existing else "",
        "rating": existing.rating if existing else 0,
        "tags": existing.tags if existing else "",
        "note": existing.note if existing else "",
    }
    base.update(changes)
    return base


def _clean_tags(tags: str) -> str:
    """Normalise a comma-separated tag string: trimmed, de-duplicated."""
    seen = []
    for part in tags.split(","):
        tag = part.strip()
        if tag and tag.lower() not in {t.lower() for t in seen}:
            seen.append(tag)
    return ", ".join(seen)
