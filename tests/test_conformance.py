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
written out again here. The reasons are in vinsynlib's docs/UX-SPEC.md
section 5 and in the library itself: what drifted was never a bug anyone
chose, it was a copy that nobody had a second copy to compare against.
"""

from p2k.terms import TERMS
from p2ked import cli
from p2ked.app import KEY_HINTS, P2kedApp, build_parser
from vinsynlib import conformance

#: The legend's own hints. `m channels` is where the family puts `m` in a
#: browser, the two after it are p2ked's, and `v favourites view` is
#: rxved's key borrowed for the reason given below. The last three are the
#: family's own ``EDITOR_KEYS`` for the write path, declared here because
#: p2ked binds them and a legend is a promise about which keys work.
#:
#: `x master FX` is in that set for the same reason: it is p2ked's own key
#: (the family has no FX block to edit), it is bound at App level *and* on
#: both edit screens, and a legend that promised it only in the browser
#: would be a legend the multi screen's footer contradicts.
#:
#: `+ - nudge`, `space toggle` and `s pick sound` are the multi screen's
#: per-channel editing gestures. They are *screen* bindings rather than App
#: ones, because a modal cuts the app's binding chain -- which is why the
#: multi screen's own footer names them as well. They are declared here for
#: the reason `x` is: each of them changes the unit.
EXTRAS = (
    "m channels",
    "v favourites view",
    "C category",
    "a all ROMs",
    "x master FX",
    "w write gate",
    "+ - nudge",
    "space toggle",
    "s pick sound",
    "z undo",
    "Z undo all",
)


def test_flags_match_the_family() -> None:
    # A tuple rather than a set: check_flags takes a Sequence, and mypy is
    # right that a set is not one. --scan IS required: this unit is on a DIN
    # cable behind an interface whose name says nothing about E-MU, which is
    # an argument that the sweep is a poor *default* -- not that the escape
    # hatch should not exist. The port remembered last time is the default.
    assert not conformance.check_flags(
        build_parser(),
        required=(
            "port",
            "scan",
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
    problems = conformance.check_bindings(
        P2kedApp, favourites=True, channel=True, select=False
    )
    # One deliberate divergence, and it is the whole of it: the favourites
    # view is on `v` rather than the family's `F`. `f` writes the favourites
    # database and cycling the view only reads it, so the shift-pair left a
    # write one slip away from a read; `v` has no such twin. rxved moved off
    # `F` for the same reason. The family asks a tool that renames a shared
    # key to say why in its own test -- anything else appearing here is a
    # real drift and must be fixed rather than added to the set.
    assert set(problems) == {
        "F is not bound; the family binds it to cycle_favorites",
        "cycle_favorites is not reachable from F; it is bound to v",
    }, "\n".join(problems)


def test_the_legend_matches_the_family() -> None:
    # select=True here even though the binding check above says False: the
    # legend is a promise about which keys work, and this one does.
    problems = conformance.check_legend(KEY_HINTS, extras=EXTRAS)
    # The same single divergence, from the legend side, because `v favourites
    # view` is declared as an extra and therefore legitimate here -- the only
    # complaint left is the family's own `F` block going unfilled. Two tools
    # now promise `v` where the family promises `F`, which is exactly why
    # the family asks a tool to say why rather than to stay quiet.
    assert set(problems) == {
        "the legend is missing 'F favourites view'",
    }, "\n".join(problems)


def test_the_vocabulary_is_declared() -> None:
    assert not conformance.check_terms(TERMS)


def test_the_pipe_front_end_matches_the_family() -> None:
    # The parser checks used to run only against the browser. p2kcli is the
    # other front door, and it had drifted: it did not offer --config while
    # it read and wrote the settings cache, and --channel claimed a
    # remembered default it never read. Both are fixed, and this keeps them
    # fixed. --favorites is forbidden: nothing there reads the store, and a
    # flag accepted and then ignored teaches the user that a flag can lie.
    assert not conformance.check_flags(
        cli.build_parser(),
        required=(
            "port",
            "scan",
            "recv-port",
            "demo",
            "channel",
            "device-id",
            "catalog",
            "config",
        ),
        forbidden=("favorites",),
    )
