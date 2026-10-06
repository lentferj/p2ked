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

"""p2ked keeps the contract the other eight projects in the family keep.

Every check below is the same one, run against this program rather than
written out again here. The reasons are in docs/UX-SPEC.md section 5 and in
the library: what drifted was never a bug anyone chose, it was a copy that
nobody had a second copy to compare against.
"""

from p2k.terms import TERMS
from p2ked.app import KEY_HINTS, P2kedApp, build_parser
from vinsynlib import conformance

#: The legend's own hints: `m channels` is where the family puts `m` in a
#: browser, and the two below are p2ked's.
EXTRAS = ("m channels", "C category", "a all ROMs")


def test_flags_match_the_family() -> None:
    # A tuple rather than a set: check_flags takes a Sequence, and mypy is
    # right that a set is not one. --scan is not required: this unit is on a
    # DIN cable behind an interface whose name says nothing about E-MU.
    assert not conformance.check_flags(
        build_parser(),
        required=(
            "port",
            "recv-port",
            "demo",
            "channel",
            "device-id",
            "catalog",
            "config",
            "favorites",
        ),
    )


def test_keys_match_the_family() -> None:
    # select=False, and the reason is in p2ked/app.py: a focused DataTable
    # consumes Enter for its own row selection, so it arrives as RowSelected
    # and calls action_select_preset from there. There used to be an App-level
    # `enter` binding as well, guarded by has_focus; it never fired while a
    # table had focus, and binding it meant the App could take Enter from the
    # table and every other table key with it. Removed rather than renamed, so
    # that all nine reach the key the same way. Checked from the other side
    # below, and by the two tests in test_audit_fixes.py.
    assert not conformance.check_bindings(
        P2kedApp, favourites=True, channel=True, select=False
    )


def test_the_legend_matches_the_family() -> None:
    # select=True here even though the binding check above says False: the
    # legend is a promise about which keys work, and this one does.
    assert not conformance.check_legend(KEY_HINTS, extras=EXTRAS)


def test_the_vocabulary_is_declared() -> None:
    assert not conformance.check_terms(TERMS)
