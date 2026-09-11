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

"""The legend, and the rule that workers only do MIDI.

Neither needs an event loop, so they live outside the asyncio-marked module.
"""

import ast
import os

from p2ked.app import KEY_HINTS, wrap_blocks


class TestLegend:
    def test_it_wraps_rather_than_truncating(self):
        """A footer that drops its last keys teaches they do not exist.

        Textual's own Footer is one line and truncates. The sibling rxved
        hit exactly that: in a 132-column window its legend wanted 251, and
        the keys that fell off were the newest ones.
        """
        packed = wrap_blocks(KEY_HINTS, 40)
        for hint in KEY_HINTS:
            assert hint in packed

    def test_no_line_exceeds_the_width_unless_one_block_does(self):
        for line in wrap_blocks(KEY_HINTS, 40).splitlines():
            assert len(line) <= 40 or "·" not in line

    def test_a_narrow_window_still_shows_everything(self):
        packed = wrap_blocks(KEY_HINTS, 12)
        for hint in KEY_HINTS:
            assert hint in packed

    def test_a_wide_window_uses_one_line(self):
        assert "\n" not in wrap_blocks(KEY_HINTS, 500)

    def test_the_legend_method_is_not_named_render(self):
        """``Widget._render`` is Textual's own.

        Shadowing it made every layout pass ask a ``None`` for its height,
        and the resulting AttributeError surfaced deep inside the framework
        with nothing in the traceback pointing at p2ked. One line to
        prevent; the whole test suite red until found.
        """
        from p2ked.app import KeyHints

        assert "_render" not in vars(KeyHints)
        assert "_render_hints" in vars(KeyHints)


class TestWorkersOnlyDoMidi:
    """Workers talk to the device and hand off. Nothing else.

    An AST check rather than a convention, because the sibling rxved learned
    this the expensive way: a worker that touched a SQLite connection raised
    out of the worker and ended the application. p2ked has no database yet,
    and this is the guard that keeps the rule while it is still cheap.
    """

    def _workers(self):
        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "p2ked", "app.py")
        tree = ast.parse(open(source, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorated = any(
                (isinstance(d, ast.Call)
                 and getattr(d.func, "id", "") == "work")
                or getattr(d, "id", "") == "work"
                for d in node.decorator_list)
            if decorated:
                yield node

    def test_there_are_workers_to_check(self):
        """Guard against this passing because it found nothing to check."""
        assert list(self._workers())

    def test_no_worker_touches_the_catalog_directly(self):
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Attribute)
                        and inner.attr == "catalog"
                        and isinstance(inner.value, ast.Name)
                        and inner.value.id == "self"):
                    offenders.append(node.name)
        assert not offenders, (
            f"worker(s) {sorted(set(offenders))} touch self.catalog; workers "
            f"do MIDI and hand off with call_from_thread")

    def test_no_worker_queries_widgets(self):
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "query_one"):
                    offenders.append(node.name)
        assert not offenders, (
            f"worker(s) {sorted(set(offenders))} query widgets directly; "
            f"that is the main thread's job")
