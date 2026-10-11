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

"""The version gate's copy of ``_release_parts`` still matches the library's.

``p2ked/entry.py`` carries its own copy of that helper on purpose: a version
gate must not import the library it is checking, because a library too old to
contain the gate would raise -- which is the failure the gate exists to
prevent. The duplication is deliberate and must not be "fixed" by sharing it;
see the module docstring there for the whole of that argument.

What it needs is a check that the copies stay identical, and that is what
this module is. Without it a drift lands in *one* tool, so the symptom is
"p2ked is broken with this vinsynlib and the other nine work" -- a support
ticket about one program rather than a red build anyone can see.

p2ked has two front ends, ``p2ked`` and ``p2kcli``, sharing the one
``entry.py``; the copy the gate runs is the same for both, so one check
covers them.
"""

from __future__ import annotations

import os

from vinsynlib import devchecks

HERE = os.path.dirname(os.path.abspath(__file__))


def test_the_version_gate_copy_has_not_drifted() -> None:
    entry = os.path.join(HERE, os.pardir, "p2ked", "entry.py")
    assert os.path.exists(entry), f"{entry} is not where this test looks"
    assert not devchecks.release_parts_drift(entry), (
        f"{entry}'s copy of _release_parts no longer matches the one in the "
        f"installed vinsynlib. A project's copy must stay identical to the "
        f"library's; update this one, or the library's first and then this "
        f"one."
    )
