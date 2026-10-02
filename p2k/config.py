# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# Ported from the sibling rxved project's config handling in xv/bridge.py:
#   Copyright (C) 2026  rxved contributors           - GPL-2.0-or-later
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

**Disposable on purpose.** Unlike the favourites database, nothing here is
the user's own work -- it is a note of what was true last time, so that
starting the program again does not mean setting the same things again.
Deleting it costs one re-entry of each. That is why it lives in the working
directory rather than the data directory, why every failure to write it is
swallowed, and why it is gitignored.

Only OSError is swallowed, mind: a read-only directory or a full disk, where
forgetting a preference beats refusing to run. Anything else is a bug and
should be heard. rxved's first attempt at remembering a channel caught
everything, and so never noticed that it was raising NameError on every
single call and writing nothing at all.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Tuple

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None

__all__ = [
    "DEFAULT_PATH",
    "load_channel",
    "save_channel",
    "load_last_port",
    "save_last_port",
    "load_last_recv_port",
    "save_last_recv_port",
    "load_device_id",
    "save_device_id",
]

DEFAULT_PATH = "config.toml"

_warned = False


def _read(path: str) -> Tuple[dict, str]:
    if not os.path.exists(path) or tomllib is None:
        return {}, "ok"
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle), "ok"
    except (OSError, ValueError):
        return {}, "unreadable"


_TOML_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _toml_string(value: str) -> str:
    """One TOML basic string, escaped.

    Writing a value straight between quotes is fine until it contains one.
    A MIDI port name is an arbitrary string -- ALSA client names are
    whatever the device reports -- so a quote in one produces a file that
    is not TOML. ``_update`` then refuses to overwrite a file it cannot
    parse, which is the right refusal and also means the cache never heals:
    every later run reads nothing and writes nothing until somebody deletes
    it by hand.

    TOML basic strings interpret the usual backslash escapes as well, so a
    literal tab or newline is written as an escape rather than embedded.
    """
    out = ['"']
    for char in value:
        if char in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append("\\u%04X" % ord(char))
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _update(path: str, **changes) -> None:
    global _warned
    data, status = _read(path)
    if status == "unreadable":
        if not _warned:
            _warned = True
            print(
                f"p2ked: {path} could not be parsed, so settings are not "
                f"being saved. Fix or delete it; nothing has been "
                f"overwritten.",
                file=sys.stderr,
            )
        return
    data.update(changes)
    lines = ["# p2ked local config - gitignored, safe to delete."]
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, str):
            lines.append(f"{key} = {_toml_string(value)}")
        else:
            lines.append(f"{key} = {value}")
    try:
        # encoding= is not optional: without it Python uses the locale
        # codec, and TOML is UTF-8 by spec. Both ends must say so.
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError:
        pass


def load_channel(path: str = DEFAULT_PATH) -> Optional[int]:
    """The channel last sent on, zero-based, or None.

    The bool check is not decoration. `isinstance(True, int)` is True and
    `0 <= True <= 15` is true, so a hand-edited ``channel = true`` used to
    come back as ``True`` and pass every range check downstream -- and
    then `0xC0 | True` is `0xC1`, which is MIDI **channel 2**. A wrong
    channel is not an error anywhere: the instrument simply plays nothing,
    or something else does.
    """
    value = _read(path)[0].get("channel")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 15 else None


def save_channel(channel: int, path: str = DEFAULT_PATH) -> None:
    _update(path, channel=int(channel))


def load_last_port(path: str = DEFAULT_PATH) -> Optional[str]:
    value = _read(path)[0].get("port")
    return value if isinstance(value, str) and value else None


def save_last_port(port: str, path: str = DEFAULT_PATH) -> None:
    _update(path, port=str(port))


def load_last_recv_port(path: str = DEFAULT_PATH) -> Optional[str]:
    """The input port last opened, when it differed from the output one."""
    value = _read(path)[0].get("recv_port")
    return value if isinstance(value, str) and value else None


def save_last_recv_port(port: str, path: str = DEFAULT_PATH) -> None:
    _update(path, recv_port=str(port))


def load_device_id(path: str = DEFAULT_PATH) -> Optional[int]:
    value = _read(path)[0].get("device_id")
    # `isinstance(True, int)` is True, so a hand-edited `device_id = true`
    # would come back as device 1 -- a real device ID, and the wrong one.
    # A wrong device ID is answered with silence by this instrument, which
    # is the failure mode that hides behind every other.
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 127 else None


def save_device_id(device_id: int, path: str = DEFAULT_PATH) -> None:
    _update(path, device_id=int(device_id))
