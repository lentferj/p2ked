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

Five things are pinned here, and four of them were bugs:

* **`escape` and `q` close the modals.** They are bound on both the multi
  screen and the master editor, but a binding whose action method does not
  exist is not an error -- Textual logs it and presses on. Both keys did
  nothing, invisibly, until ``action_close`` was given to both screens.
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
from p2ked.app import P2kedApp
from p2ked.demo import DemoDevice
from p2ked.masteredit import MASTER_PARAMETERS, MasterEditor
from p2ked.multi import (
    CHANNEL_EDIT_HINT,
    ChannelDetailScreen,
    MasterEditScreen,
    MultiScreen,
    ValuePickerScreen,
)
from p2ked.prompts import PromptScreen

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
    await pilot.press("m")
    await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
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
