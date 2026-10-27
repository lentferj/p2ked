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

"""The modal screens, driven headlessly against the demo device.

Six things are pinned here, and four of them were bugs:

* **`escape` and `q` close the modals.** They are bound on both the multi
  screen and the master editor, but a binding whose action method does not
  exist is not an error -- Textual logs it and presses on. Both keys did
  nothing, invisibly, until ``action_close`` was given to both screens.
* **The help names the build it is running,** in the strongest terms that
  can be proved for each of the two components -- and never in a term that
  cannot. A release knows its version and no commit; a checkout knows its
  commit. See :class:`TestTheHelpNamesItsBuild`.
* **An edit is visible where it is made.** The ``now`` cell moved, and a
  refusal is said on the modal's own status line rather than on the app's
  ``#status``, which is the dimmed backdrop behind a modal.
* **An enumeration is picked, not typed.** A parameter with named values
  opens the list of them, and the answer is the index the unit stores.
* **`+` and `-` nudge, on the same gated path a typed edit takes.**
* **A channel's detail is nine numbers, said plainly, and read-only.**

Names used here are invented, per CLAUDE.md. The async tests need no
marker: ``asyncio_mode = "auto"`` in pyproject.toml is what collects them.
"""

import pytest
from textual.widgets import DataTable, Static

from p2k import catalog as cat
from p2k import messages as m
from p2ked.app import KEY_HINTS, P2kedApp, _build_line
from p2ked.demo import DemoDevice
from p2ked.masteredit import FX_PARAMETERS, MASTER_PARAMETERS, MasterEditor
from p2ked.multi import (
    CHANNEL_EDIT_HINT,
    FX_EDIT_HINT,
    ChannelDetailScreen,
    FXEditScreen,
    MasterEditScreen,
    MultiScreen,
    ValuePickerScreen,
)
from p2ked.prompts import PromptScreen
from vinsynlib.build import Build
from vinsynlib.ui.report import ReportScreen

#: The row of a parameter with a plain integer range, so the tests that
#: drive the typed prompt are not offered a picker instead.
TRANSPOSE_ROW = [p.parameter_id for p in MASTER_PARAMETERS].index(
    m.Parameter.MASTER_TRANSPOSE
)
#: The first row, which happens to be a choice parameter.
MIDI_MODE_ROW = 0


@pytest.fixture
def app():
    return P2kedApp(DemoDevice(), catalog=cat.empty())


def _record(app):
    """Capture what the app says, and whether it said it as a refusal.

    The same helper the master-edit tests use, kept identical so a test
    can assert both halves: the sentence the modal showed, and the one the
    app's own status line still got.
    """
    said = []

    def say(message, *, refused=False):
        said.append((message, refused))

    app.notify_status = say
    return said


def _text(widget) -> str:
    """What a Static currently says."""
    return str(widget.visual)


async def _wait_for(pilot, ready, attempts=100):
    """Wait until ``ready()`` is true, or fail saying so.

    A fixed count of pauses would be a guess about how many trips through
    the message loop this machine takes, and a guess in a test is a flake.
    """
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _open_master_edit(app, pilot):
    """``m`` then ``e``: the multi screen, and the master editor over it.

    The whole way in, because that is the only way to the edit screen and
    the buttons that open it are part of what is being tested.
    """
    await pilot.press("m")
    await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
    await pilot.press("e")
    await _wait_for(pilot, lambda: isinstance(app.screen, MasterEditScreen))
    return app.screen


async def _open_multi(app, pilot):
    """``m``, and the multi screen that came up.

    ``m`` is retried while the wire is busy: the app starts by reading a
    bank of names off the unit on its own, and ``m`` is refused with "busy"
    until that is done -- a read that takes a different number of event-loop
    turns on every machine. One press and a wait made every test that opens
    this screen a race with the app's own startup: the screen either came up
    or the press was spent on the refusal, and nothing in the test could
    tell which. Repeating the press until the screen is there is what a
    reader does without thinking about it. Same fix, same reason, as
    :func:`tests.test_multi_edits._open_multi`.
    """
    for _ in range(50):
        await pilot.press("m")
        for _ in range(10):
            if isinstance(app.screen, MultiScreen):
                break
            await pilot.pause()
        if isinstance(app.screen, MultiScreen):
            break
        await _wait_for(pilot, lambda: not app._busy)
    return app.screen


class TestTheModalsClose:
    """`escape` and `q` on both modal screens.

    Both keys were already bound on both screens; neither worked, because
    a binding with no action method to serve it is not an error. Textual
    reports it to its console log -- only if ``TEXTUAL_LOG`` is set -- and
    presses on, so the keys looked dead and the reason was invisible.

    ``q`` is the one worth checking hardest: the app binds ``q`` to
    ``quit``, and a modal's binding chain stops at the modal, so a screen
    that served ``q`` from the app would quit the program where the user
    pressed it to close a dialog. It has to be the screen's own.
    """

    async def test_escape_closes_the_multi_screen(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await _open_multi(app, pilot)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, MultiScreen)

    async def test_q_closes_the_multi_screen_without_quitting(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await _open_multi(app, pilot)
            await pilot.press("q")
            await pilot.pause()
            assert not isinstance(app.screen, MultiScreen)
            assert app._running is True, "q quit the program; it is bound to quit"

    async def test_escape_closes_the_master_editor(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await _open_master_edit(app, pilot)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, MasterEditScreen)
            # And it left the multi screen underneath it alone.
            assert isinstance(app.screen, MultiScreen)

    async def test_q_closes_the_master_editor_from_on_top_of_the_multi_screen(
        self, app
    ):
        """Both screens, in order, on one key.

        The editor is pushed over the multi screen, so closing it has to
        return to that one and not to the browser -- the same ``dismiss``
        shape the app's own ``ReportScreen`` uses.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            await _open_master_edit(app, pilot)
            await pilot.press("q")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            await pilot.press("q")
            await pilot.pause()
            assert not isinstance(app.screen, MultiScreen)
            assert app._running is True

    async def test_the_screens_do_not_quit_the_program_by_any_route(self, app):
        """The whole stack, dismissed by the keys that claim to close it."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            for _ in range(2):
                await pilot.press("q")
                await pilot.pause()
            assert isinstance(app.screen, type(app.screen))
            assert app._running is True
            assert screen is not None


#: A commit that is a valid object name and nothing else, so the short sha
#: the line prints is recognisable in the output.
COMMIT = "0bad4f2" * 5
#: What a checkout knows: no distribution, and the repository it sits in.
CHECKOUT = Build(version=None, commit=COMMIT)
#: What a release knows, and all it can know: the wheel was built from an
#: sdist with no ``.git`` in it.
RELEASE = Build(version="0.4.1")
#: What a checkout that was never installed *and* is no longer reachable
#: knows. Still not an error -- the library says so, and so does the line.
NEITHER = Build(version=None)


class TestTheHelpNamesItsBuild:
    """``?`` names what is running, in the strongest terms that are true.

    A support question starts with "which version?", and the answer
    should not be a trip through a git CLI. Both components are named,
    because they are installed separately and only one of them is
    usually the bug -- one version number would send a reader down the
    wrong path.

    The tiering is the point, and it is the library's decision recorded
    in :mod:`vinsynlib.build`: a checkout can prove a commit, so it
    says one; a release cannot, so it says its version, which is the
    identity the family tags. So every case below asserts what is
    absent as firmly as what is present -- a line that invented a sha
    to fill a gap would be worse than a line that omits one.
    """

    @staticmethod
    def _line(monkeypatch, tool=CHECKOUT, library=CHECKOUT) -> str:
        """``_build_line`` with the library's facts replaced by ``tool``.

        The lookup is stubbed rather than the real one driven: the point
        of these tests is what the *words* do with each answer, and the
        real environment can only ever supply one of the three.
        """

        def fake(name, origin=None):
            return tool if name == "p2ked" else library

        monkeypatch.setattr("p2ked.app.build_of", fake)
        return _build_line()

    def test_the_line_names_both_components(self) -> None:
        """Not mocked: the environment really is both, and they differ.

        p2ked's install predates PEP 610 metadata -- its ``direct_url``
        is absent -- so the tool's commit comes out of the checkout the
        module sits in, while the library's comes out of the editable
        install's ``file:`` URL. Two different leads, one line.

        The library's half depends on how it was installed: a developer
        checkout names its commit, but CI installs the release from the
        index, which carries a version and no commit by design (a wheel is
        built from an sdist with no ``.git`` in it). So this asserts what
        is always true -- both names, and p2ked's sha -- and allows one or
        two parenthesised shas rather than demanding two.
        """
        line = _build_line()
        assert "p2ked" in line
        assert "vinsynlib" in line
        # p2ked is a checkout here, so its short sha is always present;
        # vinsynlib's is present only for an editable install.
        assert line.count("(") in (1, 2)

    def test_a_checkout_names_its_commit_and_no_version_it_cannot_prove(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        line = self._line(monkeypatch)
        assert COMMIT[:7] in line
        assert line.count("(") == 2

    def test_a_release_names_its_version_and_no_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The tier that cannot know a sha -- and does not pretend to."""
        line = self._line(monkeypatch, tool=RELEASE, library=RELEASE)
        assert line.count("0.4.1") == 2
        assert "(" not in line, "a release printed a commit it cannot know"

    def test_a_build_that_proves_nothing_still_reads_as_an_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Honest, and not a truncation: both names survive, no sha, no
        empty parenthesis, no invented version."""
        line = self._line(monkeypatch, tool=NEITHER, library=NEITHER)
        assert "p2ked" in line and "vinsynlib" in line
        assert "(" not in line
        assert COMMIT[:7] not in line
        assert line.endswith("unknown version")

    def test_the_tag_is_named_when_it_points_at_the_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """'You are on v0.4.1 exactly' beats a bare sha."""
        tagged = Build(version=None, commit=COMMIT, tag="refs/tags/v0.4.1")
        line = self._line(monkeypatch, tool=tagged, library=CHECKOUT)
        assert f"({COMMIT[:7]}, v0.4.1)" in line
        assert "refs/" not in line

    def test_an_untagged_commit_names_no_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The tag is proved, not assumed: nothing to show, nothing shown."""
        line = self._line(monkeypatch, tool=CHECKOUT, library=CHECKOUT)
        assert "v0." not in line


class TestTheHelpScreen:
    """The frame is the library's now; the words stay p2ked's own.

    Three things had to survive the swap, and two of them are the reason
    the family wrote a screen instead of a ``notify()`` at all: the keys
    that close it, and a body long enough to need scrolling. The library
    scrolls its body in a ``VerticalScroll`` where p2ked's copy put a
    ``Static`` with ``overflow-y: auto`` on it -- which does not scroll
    in Textual, so p2ked's help was clipped to the first screenful for
    as long as that copy existed.
    """

    async def test_escape_closes_the_help(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await _wait_for(pilot, lambda: isinstance(app.screen, ReportScreen))
            await pilot.press("escape")
            await _wait_for(pilot, lambda: not isinstance(app.screen, ReportScreen))
            assert app._running is True

    async def test_q_closes_the_help(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await _wait_for(pilot, lambda: isinstance(app.screen, ReportScreen))
            await pilot.press("q")
            await _wait_for(pilot, lambda: not isinstance(app.screen, ReportScreen))
            assert app._running is True

    async def test_the_help_still_carries_p2keds_own_words(self, app):
        """The build line leads; the rest of the help is still p2ked's."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await _wait_for(pilot, lambda: isinstance(app.screen, ReportScreen))
            body = _text(app.screen.query_one(".body", Static))
            assert "Program Change" in body
            assert "vinsynlib" in body

    async def test_a_long_body_scrolls_rather_than_truncating(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(
                ReportScreen("p2ked", "\n".join(f"line {n}" for n in range(200)))
            )
            await _wait_for(pilot, lambda: isinstance(app.screen, ReportScreen))
            await pilot.pause()
            scroll = app.screen.query_one("VerticalScroll")
            assert scroll.scroll_offset.y == 0
            await pilot.press("pagedown")
            await pilot.pause()
            assert scroll.scroll_offset.y > 0, "the body scrolled"


class TestAnEditIsVisibleInsideTheModal:
    """Two failures with one cause: the modal said nothing about what it
    had just done.

    ``DataTable.refresh()`` repaints the cells a table already has -- it
    never recomputes them -- so a successful edit left the ``now`` column
    reading the value from before it, which is exactly what "my edit did
    nothing" looks like. And every sentence the path produced went to the
    app's ``#status``, which is the dimmed backdrop *behind* the modal.

    The successes are drawn where they happened, so the value and the cell
    are both replaced and the note under them is redrawn; the refusals are
    said on the modal's own status line, which is where the user is
    looking. The app's own line gets the sentence either way -- it is the
    record, and it is what is left once the modal closes.
    """

    async def _edit(self, app, pilot, screen, digits):
        table = screen.query_one("#master-table", DataTable)
        table.focus()
        table.move_cursor(row=TRANSPOSE_ROW)
        await pilot.press("w")
        await pilot.pause()
        assert screen._editor.gate.armed is True
        await pilot.press("enter")
        await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
        await pilot.press(*list(digits))
        await pilot.press("enter")
        await _wait_for(pilot, lambda: not isinstance(app.screen, PromptScreen))
        await _wait_for(pilot, lambda: not app._busy)
        return table

    async def test_a_successful_edit_moves_the_now_cell(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = await self._edit(app, pilot, screen, "7")
            assert app.device.set_log == [(m.Parameter.MASTER_TRANSPOSE, 7)]
            # The screen's own record of the value, and the cell that shows
            # it: a stale cell is what made the edit look like a no-op.
            assert screen._values[m.Parameter.MASTER_TRANSPOSE] == 7
            assert table.get_row(str(m.Parameter.MASTER_TRANSPOSE))[1] == "7"

    async def test_the_note_is_redrawn_so_the_undo_count_is_current(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            note = screen.query_one(".note", Static)
            assert "0 edit(s) undoable with z." in _text(note)
            await self._edit(app, pilot, screen, "7")
            # The same redraw `w` does, because it counts what `z` could
            # undo and that count just changed.
            assert "1 edit(s) undoable with z." in _text(note)

    async def test_a_refusal_is_said_on_the_modal_s_own_status_line(self, app):
        """The sentence the user is actually looking at.

        Locked gate: the edit is refused, nothing is sent, and the screen
        says so on the line inside its own panel rather than leaving the
        reader to find the dimmed backdrop behind it.
        """
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=TRANSPOSE_ROW)
            await pilot.press("plus")
            await pilot.pause()
            assert app.device.set_log == [], "a refused nudge reached the unit"
            status = screen.query_one(".status", Static)
            assert "transpose not sent" in _text(status)
            assert "the write gate is locked" in _text(status)
            # The refusal prefix is there; `visual` is the rendered text,
            # so the markup that bolds it is already spent.
            assert _text(status).startswith("refused · ")
            # And the app's line still got it, as the record it is.
            message, refused = said[-1]
            assert "the write gate is locked" in message
            assert refused

    async def test_an_out_of_range_refusal_is_said_on_the_modal_too(self, app):
        """The other refusal :meth:`P2kedApp._apply_master_edit` makes, by
        the same route."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            await pilot.press("w")
            await pilot.pause()
            screen._editor.gate.armed = True
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 25)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == []
            status = screen.query_one(".status", Static)
            assert "transpose must be -24-24, and 25 is not" in _text(status)
            message, refused = said[-1]
            assert "must be -24-24" in message
            assert refused

    async def test_a_word_where_a_number_was_asked_for_is_said_on_the_modal(self, app):
        """The promptpath's own refusal, from inside the prompt's caller."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=TRANSPOSE_ROW)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list("loud"))
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not isinstance(app.screen, PromptScreen))
            await pilot.pause()
            assert "'loud' is not a number" in _text(
                screen.query_one(".status", Static)
            )

    async def test_a_result_is_said_on_the_modal_and_the_app_s_line(self, app):
        """Both lines, for the reason the app's is kept: it is what is left
        when the modal closes."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            screen.result(True, "transpose = 7", parameter_id=259, value=7)
            assert "transpose = 7" in _text(screen.query_one(".status", Static))
            assert said[-1] == ("transpose = 7", False)
            screen.result(False, "transpose did not take 7")
            assert "refused · transpose did not take 7" in _text(
                screen.query_one(".status", Static)
            )

    async def test_a_worker_that_finishes_after_the_screen_closed_still_reports(
        self, app
    ):
        """The screen can go away while an edit is on the wire.

        ``_edit_screen`` is kept for exactly that, and the sentence has to
        land on the app's status line rather than raise inside the
        ``call_from_thread`` hand-off -- an exception there is a crash
        on the main thread, over a screen nobody is looking at any more.
        """
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            screen.dismiss(None)
            await _wait_for(pilot, lambda: not isinstance(app.screen, MasterEditScreen))
            screen.result(
                True,
                "transpose = 7",
                parameter_id=m.Parameter.MASTER_TRANSPOSE,
                value=7,
            )
            screen.undone(
                [(m.Parameter.MASTER_TRANSPOSE, 0)],
                [(m.Parameter.MASTER_TRANSPOSE, True)],
            )
            await pilot.pause()
            # Nothing blew up, and the sentence still reached the app's
            # line, which is the one that is left when the modal is gone.
            assert said[-1] == ("transpose = 7", False)
            assert app._running is True

    async def test_a_result_for_a_value_that_could_not_be_read_stays_a_question(
        self, app
    ):
        """``None`` is said, not rounded to a zero."""
        applied = []
        screen = MasterEditScreen(
            DemoDevice().read_setup(),
            {m.Parameter.MIDI_MODE: None},
            MasterEditor(),
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value)),
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#master-table", DataTable)
            assert table.get_row(str(m.Parameter.MIDI_MODE))[1] == "?"


class TestTheNamedValuePicker:
    """`enter` on a parameter with named values opens the list of them.

    The old prompt printed ``0=omni, 1=poly, 2=multi`` and asked for a
    number -- a round trip through a vocabulary the unit does not have, on
    a screen whose own ``now`` column spells the value as a word. So an
    enumeration gets the list instead, and the answer it dismisses with is
    the **index the unit stores**: the same integer a typed ``1`` would
    have produced, so the gate, the range check and the undo log
    downstream cannot tell which door the edit came through.

    The shape is the sibling rxved's ``ChoiceScreen``, with one
    deliberate difference: the pick arrives as the DataTable's own
    ``RowSelected`` message rather than a ``priority=True`` ``enter``
    binding, which is how every other table in this tool answers one.
    """

    async def test_enter_on_a_choice_parameter_opens_the_picker_not_the_prompt(
        self, app
    ):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=MIDI_MODE_ROW)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            assert not isinstance(app.screen, PromptScreen)

    async def test_the_picker_lists_the_names_and_marks_the_current_value(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=MIDI_MODE_ROW)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            picker = app.screen
            choices = picker.query_one("#choices", DataTable)
            # The demo reads MIDI mode as MULTI (2), so that row carries the
            # mark and the cursor: the picker opens on what the unit says.
            assert choices.cursor_row == 2
            assert "now multi" in _text(picker.query_one("Label"))
            # `get_row` is the cell's own content, markup and all -- which
            # is what shows the mark is on the row the unit named.
            assert choices.get_row("0") == ["omni"]
            assert choices.get_row("2") == ["[b]multi[/b]"]

    async def test_enter_picks_the_index_under_the_cursor(self, app):
        applied = []
        screen = MasterEditScreen(
            DemoDevice().read_setup(),
            {m.Parameter.MIDI_MODE: 2},
            MasterEditor(),
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value)),
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("up")  # multi -> poly
            await pilot.press("enter")
            await pilot.pause()
            assert applied == [(m.Parameter.MIDI_MODE, 1)]

    async def test_escape_closes_the_picker_with_no_edit(self, app):
        applied = []
        screen = MasterEditScreen(
            DemoDevice().read_setup(),
            {m.Parameter.MIDI_MODE: 2},
            MasterEditor(),
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value)),
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#master-table", DataTable).focus()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("escape")
            await _wait_for(
                pilot, lambda: not isinstance(app.screen, ValuePickerScreen)
            )
            await pilot.pause()
            assert applied == []

    async def test_q_closes_the_picker_with_no_edit(self, app):
        applied = []
        screen = MasterEditScreen(
            DemoDevice().read_setup(),
            {m.Parameter.MIDI_MODE: 2},
            MasterEditor(),
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value)),
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#master-table", DataTable).focus()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("q")
            await _wait_for(
                pilot, lambda: not isinstance(app.screen, ValuePickerScreen)
            )
            await pilot.pause()
            assert applied == []
            assert app._running is True

    async def test_the_picker_opens_on_the_cursor_when_nothing_could_be_read(self, app):
        """A value that failed its read is not refused the picker: the
        cursor stays at the top rather than being sent nowhere."""
        applied = []
        screen = MasterEditScreen(
            DemoDevice().read_setup(),
            {m.Parameter.MIDI_MODE: None},
            MasterEditor(),
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value)),
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#master-table", DataTable).focus()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            assert app.screen.query_one("#choices", DataTable).cursor_row == 0
            assert "now ?" in _text(app.screen.query_one("Label"))

    async def test_a_picked_value_reaches_the_unit_and_is_drawn(self, app):
        """The whole path, from picker to wire to cell.

        The gate has to be armed for it to be sent, which is the point of
        the gate: the picker is a way *in* to the edit path, not a way
        around it.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("up")  # multi -> poly
            await pilot.press("enter")
            await _wait_for(
                pilot, lambda: not isinstance(app.screen, ValuePickerScreen)
            )
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MIDI_MODE, 1)]
            assert table.get_row(str(m.Parameter.MIDI_MODE))[1] == "poly"


class TestThePlusAndMinusNudge:
    """`+` and `-` step the value under the cursor by one.

    Not a second edit path: the clamped value goes to the same
    ``on_apply`` a typed number goes to, so the gate refuses it, the range
    check sees it, the log records it and the read-back verifies it. A
    screen that moved its own cell instead would be a screen that could
    show a value the unit never accepted.

    Clamped rather than wrapping: a key held a moment too long must not
    run a parameter up from 24 to 0.
    """

    async def _arm(self, app, pilot, screen):
        table = screen.query_one("#master-table", DataTable)
        table.focus()
        table.move_cursor(row=TRANSPOSE_ROW)
        await pilot.press("w")
        await pilot.pause()
        assert screen._editor.gate.armed is True

    async def test_plus_sends_one_more_and_draws_it(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            await self._arm(app, pilot, screen)
            await pilot.press("plus")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MASTER_TRANSPOSE, 1)]
            assert (
                screen.query_one("#master-table", DataTable).get_row(
                    str(m.Parameter.MASTER_TRANSPOSE)
                )[1]
                == "1"
            )
            assert "1 edit(s) undoable with z." in _text(
                screen.query_one(".note", Static)
            )

    async def test_minus_sends_one_less(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            await self._arm(app, pilot, screen)
            await pilot.press("minus")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MASTER_TRANSPOSE, -1)]

    async def test_two_nudges_walk_the_value_up(self, app):
        """The cell follows the wire, because it is drawn from the same
        value the edit was sent with."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            await self._arm(app, pilot, screen)
            await pilot.press("plus")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("plus")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [
                (m.Parameter.MASTER_TRANSPOSE, 1),
                (m.Parameter.MASTER_TRANSPOSE, 2),
            ]
            assert (
                screen.query_one("#master-table", DataTable).get_row(
                    str(m.Parameter.MASTER_TRANSPOSE)
                )[1]
                == "2"
            )

    async def test_the_value_is_clamped_at_the_top_of_the_range(self, app):
        """No value outside the range is ever sent -- the clamp is the
        screen's, so the range check never has to refuse a nudge."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            await self._arm(app, pilot, screen)
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 24)
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("plus")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_TRANSPOSE, 24)
            assert all(
                pid != m.Parameter.MASTER_TRANSPOSE or -24 <= value <= 24
                for pid, value in app.device.set_log
            )

    async def test_the_value_is_clamped_at_the_bottom_of_the_range(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            await self._arm(app, pilot, screen)
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, -24)
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("minus")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_TRANSPOSE, -24)

    async def test_a_locked_nudge_is_refused_and_nothing_is_sent(self, app):
        """The refusal is on the modal's own status line -- the same place
        a typed refusal goes, because it is the same refusal."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=TRANSPOSE_ROW)
            await pilot.press("plus")
            await pilot.pause()
            assert app.device.set_log == []
            assert app.device.copy_log == []
            status = screen.query_one(".status", Static)
            assert "transpose not sent" in _text(status)
            assert "the write gate is locked" in _text(status)
            _message, refused = said[-1]
            assert refused

    async def test_a_nudge_on_a_value_that_could_not_be_read_says_so(self, app):
        """Nothing to nudge from, and no invented zero to nudge from
        instead."""
        screen = MasterEditScreen(
            DemoDevice().read_setup(),
            {},
            MasterEditor(),
            on_apply=lambda parameter_id, value: None,
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            await pilot.press("plus")
            await pilot.pause()
            status = screen.query_one(".status", Static)
            assert "could not be read" in _text(status)
            assert "nothing to nudge from" in _text(status)

    async def test_a_nudge_is_undoable_with_z_like_any_other_edit(self, app):
        """Same path in, same path back: the nudge is in the log, and `z`
        sends the value it replaced."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            await self._arm(app, pilot, screen)
            await pilot.press("plus")
            await _wait_for(pilot, lambda: not app._busy)
            assert app._editor.log.pending == 1
            screen.action_undo()
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [
                (m.Parameter.MASTER_TRANSPOSE, 1),
                (m.Parameter.MASTER_TRANSPOSE, 0),
            ]
            assert (
                screen.query_one("#master-table", DataTable).get_row(
                    str(m.Parameter.MASTER_TRANSPOSE)
                )[1]
                == "0"
            )

    async def test_a_nudge_on_a_choice_parameter_steps_its_index(self, app):
        """``+`` on an enumeration is a step through the names, not a
        number typed into one."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=MIDI_MODE_ROW)
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("minus")  # multi (2) -> poly (1)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MIDI_MODE, 1)]
            assert table.get_row(str(m.Parameter.MIDI_MODE))[1] == "poly"


class TestTheFxEditScreen:
    """``x``: the master FX block, on the apparatus the general editor
    already built.

    Three doors, one key. ``x`` is bound on the app, on the multi screen and
    on the general editor, because a modal screen cuts the app's binding
    chain -- the same reason ``w`` is bound on the edit screen itself -- and
    because a legend that promised the key only in the browser would be
    contradicted by the footer of the screen the reader is standing on.

    Everything behind the door is the general editor's: one gate, one undo
    log, one read-back. The tests here are the ones that would catch the FX
    block having quietly grown a second copy of any of it -- a locked gate
    that sends, an edit that does not move the cell, an undo that sends the
    new value back instead of the old one.
    """

    #: The FX A algorithm row: an enumeration numbered from 1, which is the
    #: row whose value and whose row do not agree.
    ALGORITHM_ROW = 0
    #: FX A decay: a plain range, and the one the nudge tests step.
    DECAY_ROW = 1

    async def _open_fx(self, app, pilot, *, from_browser=False):
        if not from_browser:
            await pilot.press("m")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
        await pilot.press("x")
        await _wait_for(pilot, lambda: isinstance(app.screen, FXEditScreen))
        return app.screen

    async def test_x_opens_the_fx_editor_from_the_browser(self, app):
        """The legend promises the key in the browser, so it works there --
        and it reads the values first, because the screen shows what each
        one is now."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            assert isinstance(screen, FXEditScreen)
            # The values came off the wire, so an edit from here has
            # something to undo back to.
            assert screen._values[513] == 1
            assert screen._values[514] == 0

    async def test_x_opens_it_from_the_multi_screen(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot)
            assert isinstance(screen, FXEditScreen)
            # Pushed over the multi screen, so closing it comes back here.
            assert isinstance(screen.app.screen_stack[-2], MultiScreen)

    async def test_x_opens_it_from_the_master_editor(self, app):
        """``e`` then ``x``: the two blocks are one key apart, and the
        general editor binds ``x`` itself because a modal cuts the app's
        chain."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            await pilot.press("e")
            await _wait_for(pilot, lambda: isinstance(app.screen, MasterEditScreen))
            await pilot.press("x")
            await _wait_for(pilot, lambda: isinstance(app.screen, FXEditScreen))
            assert isinstance(app.screen.app.screen_stack[-2], MasterEditScreen)

    async def test_the_fx_screen_does_not_bind_x(self, app):
        """A key that reopened the screen it is already on is a key that
        looks live and does nothing -- the invisible kind of failure
        ``action_close``'s docstring describes from the other side."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            before = len(app.screen_stack)
            await pilot.press("x")
            await pilot.pause()
            assert isinstance(app.screen, FXEditScreen)
            assert app.screen is screen
            assert len(app.screen_stack) == before

    async def test_it_lists_every_fx_parameter_with_its_range_and_its_value(self, app):
        """All sixteen, in the dump's order, with the transcribed range
        beside each one."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            table = screen.query_one("#fx-table", DataTable)
            assert [row.key.value for row in table.rows.values()] == [
                str(parameter.parameter_id) for parameter in FX_PARAMETERS
            ]
            assert [column.key.value for column in table.columns.values()] == [
                "param",
                "now",
                "range",
            ]
            assert list(table.get_row("514")) == ["FX A decay", "0", "0 - 90"]
            assert list(table.get_row("517")) == ["FX A send 1", "0", "0 - 100"]
            # An enumeration's value is spelled as the manual spells it,
            # and its row says how many names there are rather than
            # printing forty-four of them.
            assert list(table.get_row("513")) == [
                "FX A algorithm",
                "Room 1",
                "1 - 44 (44 named)",
            ]
            assert list(table.get_row("520")) == [
                "FX B algorithm",
                "Chorus 1",
                "1 - 32 (32 named)",
            ]

    async def test_a_value_the_enumeration_does_not_hold_is_not_spelled(self, app):
        """0 is below the algorithms' range, so it is not the first name
        shifted along by one -- it is said as what it is."""
        screen = FXEditScreen(DemoDevice().read_setup(), {513: 0}, MasterEditor())
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#fx-table", DataTable)
            assert table.get_row("513")[1] == "unknown (0)"

    async def test_it_says_where_the_fx_bypass_is(self, app):
        """The bypass is in the general block, and a reader who came here to
        turn the effects off has to be told which screen that is on."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            note = _text(screen.query_one(".note", Static))
            assert FX_EDIT_HINT in note
            assert "id 258" in note
            assert "0 ms to 635 ms" in note
            # The general screen's hint is not this one's.
            assert CHANNEL_EDIT_HINT not in note

    async def test_the_gate_is_the_app_s_own_and_its_state_is_on_screen(self, app):
        """The same object the browser's ``w`` toggles, so the screen cannot
        show "armed" while the app refuses the edit."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            assert screen._editor is app._editor
            assert "write gate locked" in _text(screen.query_one(".note", Static))
            await pilot.press("w")
            await pilot.pause()
            assert app._gate.armed is True
            assert "write gate ARMED" in _text(screen.query_one(".note", Static))

    async def test_a_successful_fx_edit_moves_the_now_cell(self, app):
        """The nudge is another door into the same path, so the gate
        refuses it, the range check sees it, the log records it and the
        read-back verifies it -- and the row says what the unit now has."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            table = screen.query_one("#fx-table", DataTable)
            table.focus()
            table.move_cursor(row=self.DECAY_ROW)
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("plus")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(514, 1)]
            assert table.get_row("514")[1] == "1"
            assert screen._values[514] == 1
            assert "1 edit(s) undoable with z." in _text(
                screen.query_one(".note", Static)
            )

    async def test_a_locked_gate_refuses_in_the_fx_screen(self, app):
        """Refused on the modal's own status line, and nothing is sent."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            table = screen.query_one("#fx-table", DataTable)
            table.focus()
            table.move_cursor(row=self.DECAY_ROW)
            await pilot.press("plus")
            await pilot.pause()
            assert app.device.set_log == []
            status = _text(screen.query_one(".status", Static))
            assert "FX A decay not sent" in status
            assert "the write gate is locked" in status
            assert status.startswith("refused · ")
            _message, refused = said[-1]
            assert refused

    async def test_enter_on_an_algorithm_opens_the_picker(self, app):
        """Forty-four names in the manual's own order, with the current
        value on the cursor and marked in the list."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            table = screen.query_one("#fx-table", DataTable)
            table.focus()
            table.move_cursor(row=self.ALGORITHM_ROW)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            picker = app.screen
            choices = picker.query_one("#choices", DataTable)
            assert choices.row_count == 44
            # The demo reads the algorithm as 1, and value 1 is "Room 1" --
            # row 0, not row 1.
            assert choices.cursor_row == 0
            assert "now Room 1" in _text(picker.query_one("Label"))
            assert choices.get_row("1") == ["[b]Room 1[/b]"]
            assert choices.get_row("44") == ["DelayVerb 9"]
            assert not isinstance(app.screen, PromptScreen)

    async def test_a_picked_fx_reaches_the_unit_and_is_drawn(self, app):
        """Picker to wire to cell: the picker is a way *in* to the edit
        path, not a way around it."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            table = screen.query_one("#fx-table", DataTable)
            table.focus()
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            await _wait_for(
                pilot, lambda: not isinstance(app.screen, ValuePickerScreen)
            )
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(513, 3)]
            assert table.get_row("513")[1] == "Room 3"

    async def test_undo_of_an_fx_edit_sends_the_previous_value(self, app):
        """``z`` from the screen the edit was made on, sending back what the
        unit had before it -- and the row says so."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_fx(app, pilot, from_browser=True)
            table = screen.query_one("#fx-table", DataTable)
            table.focus()
            table.move_cursor(row=self.DECAY_ROW)
            await pilot.press("w")
            await pilot.pause()
            await pilot.press("plus")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(514, 1), (514, 0)]
            assert table.get_row("514")[1] == "0"
            assert app._editor.log.pending == 0

    async def test_escape_and_q_close_the_fx_editor(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open_fx(app, pilot, from_browser=True)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, FXEditScreen)
            assert app._running is True
            await self._open_fx(app, pilot, from_browser=True)
            await pilot.press("q")
            await _wait_for(pilot, lambda: not isinstance(app.screen, FXEditScreen))
            assert app._running is True, "q quit the program; it is bound to quit"

    async def test_the_multi_screen_footer_says_the_fx_key(self, app):
        """A key nobody is told about is a key nobody presses."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            hints = [_text(h) for h in screen.query(Static)]
            assert any("x master FX" in text for text in hints)

    def test_the_legend_promises_the_key_the_app_binds(self):
        """The legend is a promise about which keys work, so it names one
        the app actually binds -- declared to the family as an extra in
        tests/test_conformance.py, the way ``m channels`` is.

        No pilot: this is about what the app *declares*, and the three
        screens that serve the key are checked above by pressing it.
        """
        assert "x master FX" in KEY_HINTS
        assert [(b.key, b.action) for b in P2kedApp.BINDINGS if b.key == "x"] == [
            ("x", "edit_fx")
        ]


class TestTheChannelDetailScreen:
    """`enter` on a channel row opens that channel, read-only.

    Everything the dump says about a channel, in the words the manual
    uses -- and a sentence saying why none of it can be changed, pointing
    at ``docs/TODO`` item 47's read-only probe. A disabled control with
    no explanation teaches nothing; the reason is the useful part.

    The screen is read-only and it is silent: nothing here can select a
    preset or write a parameter, which is the one property the whole
    multi screen is built on.
    """

    async def _open_detail(self, app, pilot, row=8):
        await pilot.press("m")
        await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
        table = app.screen.query_one("#multi-table", DataTable)
        table.focus()
        table.move_cursor(row=row)
        await pilot.press("enter")
        await _wait_for(pilot, lambda: isinstance(app.screen, ChannelDetailScreen))
        return app.screen

    async def test_enter_on_a_channel_row_opens_its_detail(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            detail = await self._open_detail(app, pilot)
            assert isinstance(detail, ChannelDetailScreen)
            # The multi screen is still underneath, so closing the detail
            # returns to it.
            assert isinstance(detail.app.screen_stack[-2], MultiScreen)

    async def test_it_shows_all_nine_per_channel_parameters(self, app):
        """Every one of :data:`p2k.messages.CHANNEL_PARAMETERS`, named, with
        a human-readable value and the documented range beside it."""
        async with app.run_test() as pilot:
            await pilot.pause()
            detail = await self._open_detail(app, pilot)
            body = _text(detail.query_one(".body", Static))
            for name, low, high in m.CHANNEL_PARAMETERS:
                assert f"{name} " in body, name
                assert f"{low} - {high}" in body, name
            # Spelled the way the manual spells them.
            assert "on" in body  # enable
            assert "the preset's own output" in body  # mix_output -1
            assert "127 of 127" in body  # volume

    async def test_it_names_what_the_channel_plays(self, app):
        """The row's own resolution, not just the ROM-relative number: an
        off channel reads preset 0 of user memory, and that is said."""
        async with app.run_test() as pilot:
            await pilot.pause()
            detail = await self._open_detail(app, pilot, row=0)
            body = _text(detail.query_one(".body", Static))
            assert "channel 1" in body
            assert "User 0" in body

    async def test_it_resolves_the_rom_a_channel_points_at(self, app):
        """And the enabled one, aimed at a real ROM, is named as one.

        A name in the catalog is what `r` reading a bank off the unit
        supplies, so it is put in before the screen is built rather than
        asserted against a number.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            app.catalog.set_live_name("COMPOSER-0", 24, "wnd:B-Sax")
            detail = await self._open_detail(app, pilot, row=8)
            body = _text(detail.query_one(".body", Static))
            assert "channel 9" in body
            assert "Composer 24 wnd:B-Sax" in body

    async def test_it_says_why_the_channel_would_not_sound(self, app):
        """The same reasons the row and the report carry, so the screen
        cannot disagree with itself about a channel."""
        async with app.run_test() as pilot:
            await pilot.pause()
            detail = await self._open_detail(app, pilot, row=5)
            body = _text(detail.query_one(".body", Static))
            assert "why it would not sound" in body
            assert "volume is 0" in body

    async def test_it_says_when_a_channel_would_sound(self, app):
        """Channels 9 and 10 of the demo are on, at full volume, and using
        the preset's own output -- so nothing the unit reports stands
        between them and a sound."""
        async with app.run_test() as pilot:
            await pilot.pause()
            detail = await self._open_detail(app, pilot, row=8)
            body = _text(detail.query_one(".body", Static))
            assert "this channel would sound" in body
            assert "why it would not sound" not in body

    async def test_it_says_why_per_channel_editing_is_refused(self, app):
        """The hint is the whole point of the modal being read-only: the
        reason, not the missing feature."""
        async with app.run_test() as pilot:
            await pilot.pause()
            detail = await self._open_detail(app, pilot)
            hints = [_text(h) for h in detail.query(".hint")]
            assert any(CHANNEL_EDIT_HINT in text for text in hints)
            assert any("docs/TODO item 47" in text for text in hints)
            assert any("esc / q to close" in text for text in hints)

    async def test_it_sends_nothing_at_all(self, app):
        """Nothing selects, nothing writes -- the property the multi
        screen is built on, checked for the modal it opens too."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open_detail(app, pilot)
            await pilot.pause()
            assert app.device.selected_log == []
            assert app.device.set_log == []
            assert app.device.copy_log == []

    async def test_escape_closes_the_detail(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open_detail(app, pilot)
            await pilot.press("escape")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))

    async def test_q_closes_the_detail_without_quitting(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open_detail(app, pilot)
            await pilot.press("q")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            assert app._running is True

    async def test_the_multi_screen_footer_says_the_detail_key(self, app):
        """A key nobody is told about is a key nobody presses. The footer
        is the only place the multi screen has to say it."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            hints = [_text(h) for h in screen.query(Static)]
            assert any("enter channel detail" in text for text in hints)

    async def test_it_says_no_reason_is_in_effect_in_a_single_preset_mode(self, app):
        """In Omni the channel map is stored but ignored, so the reasons
        are not faults -- the same thing the multi screen's report does,
        now said in the modal too."""
        dump = DemoDevice().read_setup()
        multi = MultiScreen(dump, cat.empty(), m.MidiMode.OMNI)
        detail = multi._detail(dump.channels[8])
        async with app.run_test() as pilot:
            app.push_screen(detail)
            await pilot.pause()
            body = _text(detail.query_one(".body", Static))
            assert "NOT multitimbral" in body
            assert "No per-channel reason is in effect in this mode" in body
            assert "why it would not sound" not in body

    async def test_the_picker_does_not_spell_a_value_outside_its_enumeration(self, app):
        """A value the unit reports and the enumeration does not hold is
        said as what it is, not as the nearest name."""
        screen = ValuePickerScreen("MIDI mode", ["omni", "poly", "multi"], 9)
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            assert "now unknown (9)" in _text(screen.query_one("Label"))
            table = screen.query_one("#choices", DataTable)
            assert table.row_count == 3
            assert all(
                "[b]" not in str(cell)
                for row in range(3)
                for cell in table.get_row(str(row))
            )

    async def test_a_nudge_on_a_screen_with_no_edit_path_sends_nowhere(self, app):
        """No ``on_apply`` means nothing can be sent, so ``+`` is a no-op
        rather than a write the app never offered."""
        screen = MasterEditScreen(DemoDevice().read_setup(), {}, MasterEditor())
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            await pilot.press("plus")
            await pilot.pause()
            assert app.device.set_log == []
