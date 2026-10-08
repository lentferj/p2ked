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

"""How a launch reports what it is doing, shared by both front ends.

The probing line and the fallback line are the same two sentences whether
they are printed by the browser or by ``p2kcli``. Keeping them in one place
is not tidiness: the fallback notice is the one thing that tells a user their
launch took the slow path, and two copies drift until only one of them says
so. See :func:`vinsynlib.midi.open_remembered_or_swept`.
"""

from __future__ import annotations

import sys


def say_probing(name: str) -> None:
    """One line per port as the sweep reaches it."""
    print(f"  probing {name}...", file=sys.stderr)


def say_fallback(port: str, exc: BaseException) -> None:
    """Say that the remembered port did not answer, and why, before sweeping.

    A silent fallback is indistinguishable, from the terminal, from the fast
    path having worked -- which is how a slow launch quietly becomes the
    normal one. The reason is printed because it is the difference between
    "the unit moved" (``--scan``) and "no MIDI backend at all".
    """
    print(
        f"  {port}: remembered, but {exc}. Probing every port "
        f"(--scan does this on purpose).",
        file=sys.stderr,
    )


def say_connected(port: object) -> None:
    """Say which remembered port answered, so a fast launch is not silent."""
    print(f"  {port} (remembered)", file=sys.stderr)
