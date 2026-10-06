# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.

"""The console-script entry points, and the message for a missing library."""

from __future__ import annotations

import builtins
from typing import Any

from p2ked import entry

REQUIRED_BITS = (
    "error:",
    "vinsynlib",
    "pip install",
    "git+https://github.com/lentferj/vinsynlib",
)


def _hide_vinsynlib(monkeypatch: Any) -> None:
    """Make ``import vinsynlib`` raise ModuleNotFoundError, as it would."""
    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "vinsynlib" or name.startswith("vinsynlib."):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_a_missing_library_is_diagnosed(monkeypatch: Any) -> None:
    _hide_vinsynlib(monkeypatch)
    problem = entry._diagnose("p2ked")
    assert problem is not None
    for bit in REQUIRED_BITS:
        assert bit in problem, bit


def test_the_message_goes_to_stderr_and_returns_one(
    monkeypatch: Any, capsys: Any
) -> None:
    _hide_vinsynlib(monkeypatch)
    assert entry.app() == 1
    captured = capsys.readouterr()
    assert "error: p2ked cannot start" in captured.err


def test_the_cli_entry_point_says_the_same_thing(monkeypatch: Any, capsys: Any) -> None:
    _hide_vinsynlib(monkeypatch)
    assert entry.cli() == 1
    assert "error: p2kcli cannot start" in capsys.readouterr().err


def test_an_installed_library_is_reported_healthy() -> None:
    assert entry._diagnose("p2ked") is None


def test_an_older_library_is_named_rather_than_ignored(
    monkeypatch: Any,
) -> None:
    import vinsynlib

    monkeypatch.setattr(vinsynlib, "__version__", "0.0.9")
    problem = entry._diagnose("p2ked")
    assert problem is not None
    assert "0.1.0" in problem
    assert "0.0.9" in problem
