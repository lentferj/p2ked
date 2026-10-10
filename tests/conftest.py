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

"""The ``--hardware`` option, and the unit fixture for the file that uses it.

**Nothing here runs unless you ask for it.** CLAUDE.md's hardware rule is
that only one session drives a unit at a time, so the suite that talks to a
real Proteus 2000 is opt-in twice over: the ``--hardware`` flag, and the
machine actually answering. ``make check`` -- and CI, which runs it -- never
passes the flag, so ``tests/test_hardware.py`` skips there by design rather
than by accident. The environment variable covers the case of a unit plugged
into a runner nobody meant to address.

A skip is a skip, not a pass. ``-rs`` names the reason, so "the unit was
off" and "the offsets are wrong" never look like the same green.

The layout is the sibling rxved's, which solved this first; the differences
are this unit's. A Proteus answers a request it cannot serve with silence,
so a timeout distinguishes nothing -- powered off, another port (USB
renumbers them), Rx Exclusive off, a second session already driving it -- and
the skip says every cause rather than picking one, the way CLAUDE.md's
"two protocol facts" demands.
"""

import os

import pytest

#: Why the option is spelled out rather than folded into ``-m hardware``.
HELP = (
    "run the tests that need a real Proteus 2000 on a MIDI port. They open "
    "the ports, so only one session may use them at a time. Without this "
    "flag they skip."
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("hardware", "tests against a real Proteus 2000")
    group.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help=HELP,
    )


def _asked_for_hardware(config: pytest.Config) -> bool:
    """The flag, or the environment variable that says the same thing."""
    return bool(config.getoption("hardware")) or bool(os.environ.get("P2KED_HARDWARE"))


@pytest.fixture(scope="session")
def unit(request: pytest.FixtureRequest):
    """A live :class:`p2k.bridge.ProteusBridge`, or a skip saying why not.

    Session-scoped on purpose: one connection, one set of ports, held for
    the whole run rather than opened and closed per test -- the bridge
    learns the device ID and the port once, and the tests that write put
    back what they changed, so the next one starts clean.

    A failure to connect is a skip, never a failure. The reason lists every
    cause the manual gives rather than picking one, because this unit
    answers a request it cannot serve with silence and a timeout cannot say
    which of them it was.
    """
    if not _asked_for_hardware(request.config):
        pytest.skip(
            "hardware tests need --hardware (or P2KED_HARDWARE=1); the "
            "suite that talks to a real Proteus 2000 is opt-in because only "
            "one session may drive the unit"
        )

    from p2k import bridge as b

    try:
        connection = b.ProteusBridge.connect(scan=False)
    except (
        b.MidiUnavailable,
        b.DeviceNotFound,
        b.DeviceError,
    ) as exc:
        pytest.skip(
            f"no Proteus 2000 answered ({exc}). The unit may be powered off, "
            "on another port (USB renumbers them), busy with another "
            "session, or have Rx Exclusive off -- a request it cannot serve "
            "is answered with silence, so a timeout does not say which."
        )
    try:
        yield connection
    finally:
        connection.close()
