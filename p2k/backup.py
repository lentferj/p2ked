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

"""The setup backup: a restore point for the one destructive write.

p2ked's only destructive write is the per-channel one, and it is destructive
because a per-channel edit is a **whole-setup write** -- a Setup Dump
"replaces" every master and channel setting the unit is playing from
(``docs/RESOLUTION_NOTES.md`` §13). Nothing on the unit keeps the setup it
had a moment before, so the only way back is a copy taken first. This module
is that copy.

It is a thin binding of :mod:`vinsynlib.backup`, the family's device-agnostic
JSON envelope, rather than a tenth copy of it. The library owns the on-disk
shape: a JSON object whose blocks are base64, a format byte a future p2ked
reads and checks, a filename that never overwrites, and a
:func:`~vinsynlib.backup.list_backups` that reports a file it cannot read
rather than dropping it. What p2ked adds is what the library cannot know:

* the application's name, so the default directory is p2ked's per-platform
  data directory and **not** the checkout a ``git clean`` empties;
* the block: one setup, the frame
  :func:`p2k.messages.encode_setup_dump` produces from the dump the unit just
  sent. That encoder is the parser's exact inverse, so the block is the
  unit's own bytes and not a re-description of them (§13);
* the filename, which is what :func:`load` and ``p2kcli backup restore``
  address. The library's :class:`~vinsynlib.backup.Backup` carries the header
  and not the path, so :class:`Backup` here pairs the two.

**Nothing here talks to MIDI.** It serialises a dump it is handed and reads
one back; the bridge and the CLI do the round trips. That keeps a backup
testable with no hardware, and keeps the rule that workers do MIDI and
nothing else does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from p2k import favorites
from p2k import messages as m
from vinsynlib import backup as _backup
from vinsynlib.backup import FORMAT

__all__ = [
    "APP_NAME",
    "BLOCK",
    "FORMAT",
    "KIND",
    "Backup",
    "default_dir",
    "list_backups",
    "load",
    "save_setup",
]

#: The directory name under the per-platform data root, the same one the
#: favourites database uses. Named here as well as in :mod:`p2k.favorites`
#: because a reader of this module should not have to follow an import to
#: learn which application's data directory a backup lands in.
APP_NAME = favorites.APP_NAME

#: The library's ``kind``: what one of these files is. A restore refuses a
#: file whose kind is anything else, so a future p2ked that backs up
#: something else cannot be mistaken for this.
KIND = "setup"

#: The block name inside the envelope. One block, because one setup is the
#: whole of what a restore sends.
BLOCK = "setup"


@dataclass(frozen=True)
class Backup(_backup.Backup):
    """The library's record, plus the filename that addresses it.

    A subclass rather than a second envelope, the way
    :class:`p2k.favorites.Favorites` subclasses the library's store: the
    fields, their meanings and the lenient listing are the library's and
    stay in one place. The one thing the library's
    :class:`~vinsynlib.backup.Backup` does not carry is *which file it is* --
    its fields are the JSON header, and a directory of those cannot name one
    to :func:`load`. ``id`` is that name (the file's basename), and it is the
    handle the CLI's ``restore`` and the app's announcement use.
    """

    id: str = ""


def default_dir() -> str:
    """Where setup backups live.

    Under the per-platform data directory the favourites database uses --
    **not** the checkout, which ``git clean`` empties and which a test must
    never write into. The name is ``backups``, beside ``favorites.db``, so a
    person looking for their restore points has one place to look and one
    directory to copy elsewhere.
    """
    return os.path.join(favorites.data_dir(), "backups")


def _record(header: _backup.Backup, id: str) -> Backup:
    """The library's header with its filename attached."""
    return Backup(
        kind=header.kind,
        slot=header.slot,
        name=header.name,
        saved=header.saved,
        device_id=header.device_id,
        source=header.source,
        blocks=header.blocks,
        error=header.error,
        id=id,
    )


def _resolve(id: str, directory: Optional[str]) -> str:
    """A backup's path: the id against a directory, or a path as given.

    An ``id`` from :func:`list_backups` is a bare filename and is looked up
    in ``directory`` (or :func:`default_dir`); a full path, or anything with
    a separator in it, is taken as itself -- so a backup copied to a USB
    stick can be restored by naming it directly.
    """
    if os.path.isabs(id) or os.sep in id:
        return id
    return os.path.join(directory or default_dir(), id)


def save_setup(
    dump: m.SetupDump,
    *,
    device_id: int,
    slot: int | str,
    source: str = "p2ked",
    directory: Optional[str] = None,
) -> Backup:
    """Write one setup to the backup directory, and return its record.

    ``dump`` is a :class:`p2k.messages.SetupDump` -- normally the live one a
    worker has just read, which is the whole point: what is stored is the
    setup as it was *before* the write that follows. It is encoded with
    :func:`p2k.messages.encode_setup_dump`, the parser's exact inverse, so
    the block is the unit's own frame rather than a re-description of it; a
    dump the encoder refuses is refused here too, rather than stored as
    something a restore could not send.

    ``slot`` is the library's slot label, a string in the filename. The live
    setup has no number, so the callers pass ``"live"``. ``source`` records
    who took it -- ``"p2ked (before edit)"`` or ``"p2ked (manual)"`` -- which
    is what makes a directory of these readable by a person deciding which
    one to restore.

    The envelope and its never-overwrite rule are the library's
    (:func:`vinsynlib.backup.save`); this chooses only the block, the name
    and the directory. Returns p2ked's :class:`Backup`, whose ``id`` is the
    file's name -- the handle :func:`load` and the CLI's ``restore`` use.
    """
    frame = m.encode_setup_dump(dump, device=device_id)
    path = _backup.save(
        directory or default_dir(),
        kind=KIND,
        slot=str(slot),
        name=dump.name,
        device_id=str(device_id),
        source=source,
        blocks={BLOCK: frame},
    )
    return _record(_backup.load(path), os.path.basename(path))


def list_backups(directory: Optional[str] = None) -> list[Backup]:
    """Every backup in a directory, newest first.

    A file that cannot be read is listed with its ``error`` rather than
    dropped -- a restore point you cannot read is exactly the thing to be
    told about. That is the library's rule
    (:func:`vinsynlib.backup.list_backups`) kept here while the filename is
    attached; the record's ``id`` is that filename.

    Newest first, by the saved time the header carries, because the backup a
    person wants after a mistake is almost always the one just taken. A
    corrupt entry sorts last: it has no saved time to sort by.
    """
    target = directory or default_dir()
    out: list[Backup] = []
    if not os.path.isdir(target):
        return out
    for name in sorted(os.listdir(target)):
        path = os.path.join(target, name)
        if not os.path.isfile(path):
            continue
        try:
            out.append(_record(_backup.load(path), name))
        except Exception as exc:
            out.append(
                Backup(
                    kind="",
                    slot="",
                    name="",
                    saved=0.0,
                    device_id="",
                    source="",
                    blocks={},
                    error=str(exc),
                    id=name,
                )
            )
    out.sort(key=lambda backup: backup.saved, reverse=True)
    return out


def load(id: str, *, directory: Optional[str] = None) -> m.SetupDump:
    """Read a backup back into the dump a restore sends.

    ``id`` is the name :func:`list_backups` reports, or a full path. The
    block is parsed with :func:`p2k.messages.parse_setup_dump`, so what comes
    back is a :class:`~p2k.messages.SetupDump` ready for
    :meth:`p2k.bridge.ProteusBridge.send_setup_dump` -- the same object the
    live read returns.

    Refuses a file that is not a setup backup, or that carries no setup
    block, rather than sending something the unit did not ask for. The
    envelope's own version check is the library's
    (:func:`vinsynlib.backup.load`).
    """
    record = _backup.load(_resolve(id, directory))
    if record.kind != KIND:
        raise ValueError(f"{id} holds {record.kind!r}, not a {KIND} backup")
    frame = record.blocks.get(BLOCK)
    if not frame:
        raise ValueError(f"{id} carries no {BLOCK} block")
    packet = m.parse(frame)
    if packet is None:
        raise ValueError(f"{id} is not a setup dump frame")
    return m.parse_setup_dump(packet)
