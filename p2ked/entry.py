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

**It does not call into the library to check the library.** An earlier
version asked ``vinsynlib.is_compatible_version`` whether vinsynlib was new
enough -- so a library too old to have that function raised
``AttributeError`` here, a traceback naming the package the user never asked
for, which is the exact failure this module exists to prevent. The version
comparison is a dozen lines of standard library, and it stays here.
"""

from __future__ import annotations

import sys

#: The minimum that has the API this project was written against.
#:
#: ``0.2.0`` is the version that added ``midi.open_remembered_or_swept``'s
#: ``on_fallback`` hook, the per-file ownership guard in the settings cache,
#: and the ``__version__`` whose absence used to be undetectable.
MINIMUM = (0, 2, 0)

#: Where to get it while it is not on an index. Pinned to the tag, not the
#: branch: a branch can move to something older, which is how p2ked came to
#: require an API that existed only in one checkout.
SOURCE = "vinsynlib @ git+https://github.com/lentferj/vinsynlib@v0.2.0"


def _release_parts(version: str, width: int) -> tuple[int, ...] | None:
    """The leading numeric components of ``version``, or ``None``.

    A component must begin with a digit; anything after the digits is a
    pre-release or build marker and is ignored, so ``"0.2rc1"`` compares as
    ``0.2``. A component that does not begin with a digit at all
    (``"0.1.x"``) makes the whole string unusable rather than being guessed
    at. Standard library only, on purpose -- see the module docstring.
    """
    parts: list[int] = []
    for piece in version.split(".")[:width]:
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            return None
        parts.append(int(digits))
    if not parts:
        return None
    return tuple(parts + [0] * (width - len(parts)))


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
    parts = _release_parts(version, len(MINIMUM))
    if parts is None or parts < MINIMUM:
        return _too_old(command, version)
    return None


def _how_to_install() -> str:
    """The steps that work, rather than the ones that read as if they might.

    Plain ``pip install -e .`` cannot install ``vinsynlib``: it is not on an
    index, and pip ignores the ``[tool.uv.sources]`` path that ``uv`` reads.
    Following it produces ``ERROR: Could not find a version that satisfies
    the requirement vinsynlib`` -- which is the failure this module then
    explains.
    """
    return (
        "Install it from source. Plain `pip install -e .` cannot do it: the\n"
        "library is not on an index, so pip never sees it. Clone it beside\n"
        "this checkout and install it first:\n"
        "\n"
        "    git clone https://github.com/lentferj/vinsynlib.git ../vinsynlib\n"
        "    pip install --no-deps -e ../vinsynlib\n"
        "    pip install -e .\n"
        "\n"
        "Or install it directly:\n"
        "\n"
        f'    pip install "{SOURCE}"\n'
        "\n"
        "With uv, `uv sync` reads the sibling path from pyproject.toml, so\n"
        "the checkout only has to exist.\n"
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
