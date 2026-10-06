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

"""The local settings cache: which port answered, and which channel.

Now a binding of :class:`vinsynlib.config.Settings` rather than a sixth copy
of it. The behaviour, including the traps it is written around, is the
family's and lives in one place:

* A TOML boolean is not a channel. ``isinstance(True, int)`` is true, so a
  hand-edited ``channel = true`` used to come back as ``True``, pass every
  range check, and then ``0xC0 | True`` is MIDI channel 2 -- a wrong channel
  being not an error anywhere.
* Everything written is escaped. A port name is whatever ALSA reports, and a
  quote in one produces a file that is not TOML, which the writer then
  refuses to overwrite: a cache that never heals.
* Only :class:`OSError` is swallowed -- a read-only directory or a full disk,
  where forgetting a preference beats refusing to run.

What is added here is the name. One string decides what the one warning
message says, and it has to be right: several of these programs can be open
in one session, and a user who is told a file could not be parsed has to be
able to tell which one is unhappy.

Note that ``load_last_recv_port``/``save_last_recv_port`` are p2ked's own
names for the library's ``load_recv_port``/``save_recv_port``. The library
spells it the way the family does now; these two keep the spelling their call
sites already used.
"""

from __future__ import annotations

from vinsynlib.config import DEFAULT_PATH, Settings

__all__ = [
    "DEFAULT_PATH",
    "load_channel",
    "load_device_id",
    "load_last_port",
    "load_last_recv_port",
    "save_channel",
    "save_device_id",
    "save_last_port",
    "save_last_recv_port",
]

_settings = Settings("p2ked", DEFAULT_PATH)

#: Module-level aliases, so every existing call site reads the same as it did
#: before: ``config.load_channel(path)``. The library takes the path as an
#: optional first argument exactly as these did, so nothing here wraps.
load_channel = _settings.load_channel
save_channel = _settings.save_channel
load_last_port = _settings.load_port
save_last_port = _settings.save_port
load_last_recv_port = _settings.load_recv_port
save_last_recv_port = _settings.save_recv_port
load_device_id = _settings.load_device_id
save_device_id = _settings.save_device_id
