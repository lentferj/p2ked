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
from vinsynlib import devchecks


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

    def test_a_degenerate_width_wraps_one_block_per_line(self):
        """A width of zero must not switch wrapping off.

        The guard used to be ``if width and ...``, so a non-positive width
        made the test false on every candidate and the legend came out as
        one very long line -- the exact failure this function exists to
        prevent, reached by a different route. The only caller clamps, so
        nothing ever passed 0; a function that silently degrades on an
        argument its own docstring does not mention is the thing here.
        """
        for width in (0, -1, -100):
            assert wrap_blocks(("a hint", "b hint"), width) == "a hint\nb hint", width

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
            "p2ked",
            "app.py",
        )
        tree = ast.parse(open(source, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorated = any(
                (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "work")
                or getattr(d, "id", "") == "work"
                for d in node.decorator_list
            )
            if decorated:
                yield node

    def test_there_are_workers_to_check(self):
        """Guard against this passing because it found nothing to check."""
        assert list(self._workers())

    def test_no_worker_touches_the_catalog_directly(self):
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Attribute)
                    and inner.attr == "catalog"
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == "self"
                ):
                    offenders.append(node.name)
        assert not offenders, (
            f"worker(s) {sorted(set(offenders))} touch self.catalog; workers "
            f"do MIDI and hand off with call_from_thread"
        )

    def test_no_worker_queries_widgets(self):
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "query_one"
                ):
                    offenders.append(node.name)
        assert not offenders, (
            f"worker(s) {sorted(set(offenders))} query widgets directly; "
            f"that is the main thread's job"
        )

    def test_no_worker_writes_the_settings_cache(self):
        """TODO 11. The third check of this shape, for the same reason.

        Nothing reaches `_update` from two threads today, because nothing
        the workers do writes settings -- the rule is what keeps it safe,
        not a lock. The rule is enforced for the catalog and for widgets,
        and it was not enforced for the one call that would end badly
        *elsewhere*: `Settings.update` rewrites the whole file, so two
        concurrent writers interleave, and the user's port name can end up
        half of each.

        `test_a_worker_writing_config_is_caught` below proves this check can
        fail; a guard that passes because it matched nothing is worse than
        none.
        """
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr.startswith("save_")
                ):
                    offenders.append(f"{node.name}: {inner.func.attr}")
        assert not offenders, (
            f"worker(s) write settings: {sorted(set(offenders))}. `update` "
            f"rewrites the whole file, so two writers interleave and the "
            f"port can end up half of each. Hand it off instead."
        )

    def test_a_worker_writing_config_is_caught(self):
        """The guard above must be able to fail. Written against a source
        p2ked does not have, because the check is otherwise one refactor
        away from being vacuous -- and the refactor that turns it vacuous
        is exactly the one a future edit feature would tempt somebody into.
        """
        import textwrap

        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "p2ked",
            "app.py",
        )
        # Read, not parsed: the point is that the real source is where this
        # check lives, so a future edit that moves it cannot leave the
        # synthetic half behind testing nothing.
        assert os.path.exists(source)
        synthetic = ast.parse(
            textwrap.dedent(
                """
                from textual import work

                class Something:
                    @work(thread=True)
                    def _worker(self):
                        from p2k import config
                        config.save_channel(1)
                """
            )
        )
        offenders = []
        for node in ast.walk(synthetic):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorated = any(
                (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "work")
                or getattr(d, "id", "") == "work"
                for d in node.decorator_list
            )
            if not decorated:
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr.startswith("save_")
                ):
                    offenders.append(inner.func.attr)
        assert offenders == ["save_channel"], (
            "the check does not catch a worker writing settings; it would "
            "pass on the tree it is meant to guard"
        )


class TestConfigIsNotWrittenBehindTheSuitesBack:
    """``config.DEFAULT_PATH`` is relative, so a pathless save hits the CWD.

    That is the right default for the application -- ``config.toml`` is a
    disposable per-checkout cache, gitignored in all four sibling projects --
    and exactly the wrong thing for a test, which would drop the file into
    whatever directory pytest was started from. It is gitignored, so it never
    shows up in ``git status`` to give the game away; the only evidence is a
    file appearing next to the source. The sibling rxved had the same bug with
    backups and fixed it in ``1f5aa3a``.
    """

    def _test_sources(self):
        """Every test module, parsed. The walk is the family's.

        This was p2ked's own generator until the library grew the same one;
        ``vinsynlib.devchecks.iter_test_sources`` is ``test_*.py`` under a
        directory, parsed and yielded, which is exactly what this did, so it
        is a binding now rather than a ninth copy. What stays p2ked's is the
        *check* below, and it is deliberately stricter than the library's
        ``devchecks.config_saves_without_path``: that one looks at
        ``save_*`` only, and a pathless ``load_*`` takes its answer from
        whatever the developer's checkout happens to hold -- which is a test
        that passes for one developer and fails for the next. It did.
        """
        here = os.path.dirname(os.path.abspath(__file__))
        return devchecks.iter_test_sources(here)

    def test_every_config_access_in_the_suite_names_its_file(self):
        """Reads as well as writes.

        The guard started out covering ``save_`` only, on the reasoning that
        a write is what leaves a file behind. A *read* is just as dependent
        on the working directory: ``p2kcli select`` selects on the channel
        remembered in ``config.toml``, so a test that does not name a file
        takes its channel from whatever the developer's checkout happens to
        hold -- and that is a test that passes for one developer and fails
        for the next. It did, in fact, happen.
        """
        offenders = []
        for name, tree in self._test_sources():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (
                    isinstance(func, ast.Attribute)
                    and (func.attr.startswith("save_") or func.attr.startswith("load_"))
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "config"
                ):
                    continue
                # `load_*` takes the path as its one argument; `save_*`
                # takes the value first and the path second. Either way a
                # path is either positional or path=.
                if func.attr.startswith("load_"):
                    has_path = len(node.args) >= 1
                else:
                    has_path = len(node.args) >= 2
                has_path = has_path or any(kw.arg == "path" for kw in node.keywords)
                if not has_path:
                    offenders.append(f"{name}:{node.lineno} {func.attr}")
        assert not offenders, (
            f"{offenders} touch config.DEFAULT_PATH, which is relative to "
            f"the working directory. Pass a tmp_path."
        )

    def test_the_check_has_something_to_check(self):
        """Guard against the search passing because it matched nothing."""
        found = 0
        for _, tree in self._test_sources():
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and (
                        node.func.attr.startswith("save_")
                        or node.func.attr.startswith("load_")
                    )
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "config"
                ):
                    found += 1
        assert found, (
            "no config.save_* or config.load_* calls found; the check is vacuous"
        )
