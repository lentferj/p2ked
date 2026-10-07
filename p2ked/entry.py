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

"""Console-script entry points, which check the shared library is installed.

``p2ked`` and its sibling tools share one library, ``vinsynlib``. It is an
ordinary installation dependency, and the ordinary way for a dependency to
be missing is that somebody pulled the source without reinstalling.

Without this module the failure is a bare ``ModuleNotFoundError`` raised
from inside a module-level ``import`` -- a traceback naming a package the
user never asked for, with no hint of what to do about it. Worse on Windows,
where a console script exits before the traceback can be read.

This is the one place that can say something useful, because it runs before
any module that imports the library. It is deliberately tiny, and it must
keep importing nothing but the standard library.
"""

from __future__ import annotations

import sys

#: The minimum that has the API this project was written against.
MINIMUM = (0, 1, 0)

#: Where to get it while it is not on an index.
SOURCE = "vinsynlib @ git+https://github.com/lentferj/vinsynlib"


def _diagnose(command: str) -> str | None:
    """``None`` if the shared library is usable, else what to tell the user."""
    try:
        import vinsynlib
    except ModuleNotFoundError as exc:
        if exc.name and not exc.name.startswith("vinsynlib"):
            raise
        return _missing(command)
    version = getattr(vinsynlib, "__version__", None)
    if not isinstance(version, str):
        return _missing(command)
    if not vinsynlib.is_compatible_version(version, MINIMUM):
        return _too_old(command, version)
    return None


def _how_to_install() -> str:
    return (
        "Install it from source (it is not on PyPI yet):\n"
        "\n"
        f'    pip install "{SOURCE}"\n'
        "\n"
        "Installing this project itself brings it in too, which is the usual\n"
        "way in from a clone:\n"
        "\n"
        "    pip install -e .        # or: uv sync\n"
    )


def _missing(command: str) -> str:
    return (
        f"error: {command} cannot start: the shared library "
        '"vinsynlib" is not installed.\n'
        "\n"
        f"{command} is one of the sibling tools that share this library for\n"
        "the settings cache, the keymap, the command line and the port\n"
        "listing, so it cannot run without it.\n"
        "\n" + _how_to_install()
    )


def _too_old(command: str, found: str) -> str:
    wanted = ".".join(str(part) for part in MINIMUM)
    return (
        f"error: {command} needs vinsynlib {wanted} or newer, and {found} is "
        "installed.\n"
        "\n"
        "Something installed an older copy, most likely as a dependency of\n"
        "an older release of one of the sibling tools. Upgrade it:\n"
        "\n"
        f'    pip install --upgrade "{SOURCE}"\n'
    )


def _run(command: str, target: str) -> int:
    """Check the library, then hand over to the real entry point."""
    problem = _diagnose(command)
    if problem is not None:
        sys.stderr.write(problem)
        return 1

    from importlib import import_module

    module, _, attribute = target.partition(":")
    entry = getattr(import_module(module), attribute)
    return int(entry() or 0)


def app() -> int:
    return _run("p2ked", "p2ked.app:main")


def cli() -> int:
    return _run("p2kcli", "p2ked.cli:main")
