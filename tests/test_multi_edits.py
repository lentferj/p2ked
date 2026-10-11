# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026 p2ked contributors
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

"""The multi screen's editing surface, driven against the demo device.

``tests/test_channel_edits.py`` pins the *mechanism* -- one field's bytes
move, the gate refuses, the read-back verifies, ``z`` sends the dump back.
This file pins the *surface* over it: which gesture does what, where the
sentence lands, and what the row says afterwards. The two are deliberately
separate, because the mechanism is what a unit has to agree with and the
surface is what a person has to.

Every edit here goes through the app's own
:meth:`P2kedApp.action_edit_channel`, so what these tests establish is that
the screen offers an edit and never sends one -- the gate, the range check,
the worker and the read-back are the ones the master edit path uses.

Nothing has been written to a Proteus from here. ``DemoDevice`` is written
from the same document as the code it answers, so a green suite establishes
internal consistency and nothing more; the first unit contact is ``make
test-hardware``'s unmodified-dump round trip.
"""

import threading

import pytest
from textual.widgets import DataTable, Static

from p2k import catalog as cat
from p2k import messages as m
from p2k import roms
from p2ked.app import P2kedApp
from p2ked.demo import DemoDevice
from p2ked.masteredit import ChannelChange
from p2ked.multi import (
    ARP_NAMES,
    ChannelDetailScreen,
    MultiScreen,
    SoundPickerScreen,
    ValuePickerScreen,
)
from p2ked.prompts import PromptScreen

#: An enabled channel, so an edit moves one that is actually doing
#: something. The demo deliberately leaves channel 1 off and channel 6 on at
#: volume 0, so neither of those would say much.
LIVE = 8
#: A disabled channel: its fields are every bit as writable, and this is the
#: row a "would not sound" channel still gets edited from.
QUIET = 3
#: An enabled channel at volume 0, the demo's second kind of silent.
MUTED = 5

#: The columns, in the order the table draws them: ch, plays, vol, pan, out,
#: on, rxpc, arp, rom, why. Pinned here as well as in the screen's own
#: ``CELLS`` so a column added without a kind is a failure in this file
#: rather than a key that silently does nothing.
VOLUME_COLUMN = 2
PAN_COLUMN = 3
MIX_COLUMN = 4
ENABLE_COLUMN = 5
RXPC_COLUMN = 6
ARP_COLUMN = 7
PLAYS_COLUMN = 1


@pytest.fixture
def app():
    return P2kedApp(DemoDevice(), catalog=cat.empty())


def _record(app):
    """Capture what the app says, and whether it said it as a refusal.

    The same helper the other suites use, kept identical so a test can assert
    both halves: the sentence the modal showed, and the one the app's own
    status line still got.
    """
    said = []

    def say(message, *, refused=False):
        said.append((message, refused))

    app.notify_status = say
    return said


def _text(widget) -> str:
    """What a Static currently says."""
    return str(widget.visual)


async def _wait_for(pilot, ready, attempts=200):
    """Wait until ``ready()`` is true, or fail saying so.

    The same helper the master-edit tests use: every operation here finishes
    on a worker thread and is handed back with ``call_from_thread``, so how
    many trips through the message loop it takes is a property of the machine
    rather than of the code.
    """
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _open_multi(app, pilot, *, armed: bool = True):
    """``m``, then ``w`` to arm the gate, and the screen that came up.

    ``w`` is pressed *on the multi screen*, because that is where it has to
    work: a modal cuts the app's binding chain, so the app's own ``w`` is
    dead the moment this screen is open -- the whole reason the screen binds
    it for itself.

    ``m`` is retried while the wire is busy, because the app starts by
    reading a bank of names off the unit on its own and ``m`` is refused
    with "busy" until that is done -- a read that takes a different
    number of event-loop turns on every machine. One press and a wait
    made every test in this file a race with the app's own startup: the
    screen either came up or the press was spent on the refusal, and
    nothing in the test could tell which. So the press is repeated until
    the screen is there, which is what a reader does without thinking
    about it.
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
    screen = app.screen
    if armed:
        await pilot.press("w")
        await pilot.pause()
    return screen


def _table(screen) -> DataTable:
    table = screen.query_one("#multi-table", DataTable)
    table.focus()
    return table


def _cells(table, row) -> list:
    """One row's cells, as the strings the table was given."""
    return [str(cell) for cell in table.get_row(str(row))]


def _status(screen) -> str:
    """What the screen's own status line says."""
    return _text(screen.query_one(".status", Static))


class TestTheTableMovesBetweenCells:
    """The cursor is a cell cursor, because nine of these columns are values.

    A row-wide cursor could say nothing about which of a row's nine values a
    keystroke was aimed at, so the arrows move between cells and Enter comes
    back as the cell it was pressed on.
    """

    async def test_the_cursor_is_a_cell_cursor(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            assert screen.query_one("#multi-table", DataTable).cursor_type == "cell"

    async def test_the_arrows_move_between_cells(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=0)
            # ch -> plays -> vol -> pan. Three rights land on pan.
            await pilot.press("right", "right", "right")
            await pilot.pause()
            assert tuple(table.cursor_coordinate) == (LIVE, PAN_COLUMN)
            await pilot.press("right")
            await pilot.pause()
            assert tuple(table.cursor_coordinate) == (LIVE, MIX_COLUMN)
            await pilot.press("left")
            await pilot.pause()
            assert tuple(table.cursor_coordinate) == (LIVE, PAN_COLUMN)
            # Down and up move between channels, and down past the last row
            # stays on it rather than wrapping into somebody else's.
            await pilot.press("down", "down")
            await pilot.pause()
            assert tuple(table.cursor_coordinate) == (LIVE + 2, PAN_COLUMN)
            await pilot.press("up")
            await pilot.pause()
            assert tuple(table.cursor_coordinate) == (LIVE + 1, PAN_COLUMN)
            # And the cursor moves without sending anything: the one
            # property the whole program is built on, now with a keyboard
            # that walks over nine writable values.
            assert app.device.dump_log == []

    async def test_every_column_has_a_kind_of_its_own(self, app):
        """A column added without one is a key that looks live and is dead."""
        from p2ked.multi import CELLS

        kinds = {cell.kind for cell in CELLS}
        assert kinds == {"read", "number", "named", "switch", "sound"}
        assert [cell.key for cell in CELLS] == [
            "ch",
            "plays",
            "vol",
            "pan",
            "out",
            "on",
            "rxpc",
            "arp",
            "rom",
            "why",
        ]
        # The nine the dump carries, and the two that are not fields.
        editable = [cell.field for cell in CELLS if cell.editable]
        assert sorted(editable) == sorted(
            m.CHANNEL_PARAMETERS[i][0] for i in (1, 2, 3, 4, 5, 7)
        )

    async def test_the_enable_column_is_there_to_be_toggled(self, app):
        """It was a reason and nothing else, which made it the one of the
        nine a reader could see but not act on."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            keys = [column.key.value for column in table.columns.values()]
            assert "on" in keys
            assert _cells(table, LIVE)[keys.index("on")] == "on"
            assert _cells(table, 0)[keys.index("on")] == "OFF"

    async def test_enter_on_a_read_only_column_still_opens_the_detail(self, app):
        """A reader who presses Enter on ``ch`` is asking about the channel,
        not fumbling."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=0)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ChannelDetailScreen))
            assert "channel 9" in _text(app.screen.query_one(".body", Static))


class TestEnterOnANumericCell:
    """A number to type, with the range and the current value on the prompt.

    The question names the range because the specification *clips* an
    out-of-range value rather than refusing it (spec p. 41) -- a typo would
    otherwise land as a plausible, silent change.
    """

    async def test_enter_opens_the_entry_with_the_range_and_the_value(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            assert app.screen._prompt == "channel 9 volume (0-127), now 127"

    async def test_the_answer_reaches_the_unit(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list("90"))
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            # One whole-dump write, and no parameter edit: the per-channel
            # route is not the master one with different numbers.
            assert app.device.set_log == []
            assert len(app.device.dump_log) == 1
            assert app.device.read_setup().channel(LIVE).volume == 90
            # And the row says what the read-back reported.
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "90"

    async def test_a_word_where_a_number_was_asked_for_is_refused(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list("loud"))
            await pilot.press("enter")
            await pilot.pause()
            assert app.device.dump_log == []
            assert said[-1] == ("'loud' is not a number", True)

    async def test_an_empty_answer_offers_no_edit(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press("enter")
            await pilot.pause()
            assert app.device.dump_log == []

    async def test_escape_cancels_the_entry_and_leaves_the_screen_open(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list("40"))
            await pilot.press("escape")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            assert app.device.dump_log == []
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "127"

    async def test_a_value_outside_the_range_is_refused_with_the_range(self, app):
        """The range check is the app's, on the main thread, before anything
        is spawned -- and its sentence lands in the modal."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list("200"))
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            await pilot.pause()
            assert app.device.dump_log == []
            message, refused = said[-1]
            assert "must be 0-127, and 200 is not" in message
            assert refused
            assert _status(screen).startswith("refused · ")

    async def test_a_locked_gate_refuses_inside_the_modal(self, app):
        """The sentence is on the screen's own line, not on the app's
        ``#status`` behind it -- which is where a refusal used to land, where
        nobody could read it."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot, armed=False)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list("90"))
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            await pilot.pause()
            # Nothing was sent: a whole-setup write is a large thing to send
            # by accident.
            assert app.device.dump_log == []
            assert app.device.set_log == []
            status = _status(screen)
            assert "volume not sent" in status
            assert "the write gate is locked" in status
            assert "Press w to arm it" in status
            assert status.startswith("refused · ")
            message, refused = said[-1]
            assert refused
            assert message == status[len("refused · ") :]


class TestEnterOnANamedCell:
    """A field whose values a document names is a list to pick from.

    ``use preset`` is what the screen prints and what the front panel shows,
    so asking for ``-1`` and then spelling it back as words on the next
    render is a round trip through a vocabulary the unit does not use.
    """

    async def test_mix_output_opens_the_four_names(self, app):
        """Four, against a field whose documented range is four values.

        spec p. 41 gives the range -1 to 2 and the parameter tree prints
        "use preset or send 1-4" -- five names. See
        :data:`p2ked.multi.MIX_OUTPUT_NAMES` for which of the two the code
        shows and why.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=MIX_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            picker = app.screen
            assert "channel 9 mix_output" in _text(picker.query_one("Label"))
            choices = picker.query_one("#choices", DataTable)
            assert [str(choices.get_row(key)[0]) for key in ("-1", "0", "1", "2")] == [
                "[b]use preset[/b]",
                "send 1",
                "send 2",
                "send 3",
            ]
            assert str(choices.get_row("-1")[0]).count("[b]") == 1

    async def test_the_picked_name_sends_the_value_it_is_numbered_by(self, app):
        """The answer is the integer a typed -1 would have produced, so the
        gate, the range check and the undo log cannot tell which door the
        edit came through."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=MIX_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("down", "down", "down")
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            # "send 3" is the value 2, and the dump holds 2.
            assert app.device.read_setup().channel(LIVE).mix_output == 2
            assert _cells(table, LIVE)[MIX_COLUMN] == "send 3"
            assert app._changes[-1] == ChannelChange(LIVE, "mix_output", -1, 2)

    async def test_the_arpeggiator_names_are_the_specifications_own(self, app):
        """spec p. 41's "documented values" column, and nothing beyond it.

        What nobody has published is what "P" switches, so the list stops
        there rather than naming it.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=ARP_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            choices = app.screen.query_one("#choices", DataTable)
            assert [str(choices.get_row(key)[0]) for key in ("-2", "-1", "0", "1")] == [
                name if key != "0" else f"[b]{name}[/b]"
                for key, name in zip(("-2", "-1", "0", "1"), ARP_NAMES, strict=True)
            ]
            # The demo reads 0, which is "P (preset arp)" -- row 2, not row
            # 0, because the field's values start at -2.
            assert choices.cursor_row == 2

    async def test_picking_a_negative_value_writes_the_negative_value(self, app):
        """A signed field: -2 is not 16383, which is what an unsigned
        reading of the wire would make it."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=ARP_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("up", "up")
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert app.device.read_setup().channel(LIVE).arp == -2
            assert _cells(table, LIVE)[ARP_COLUMN] == "-2"

    async def test_cancelling_the_picker_writes_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=MIX_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("down")
            await pilot.press("escape")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            assert app.device.dump_log == []
            assert _cells(table, LIVE)[MIX_COLUMN] == "use preset"


class TestTheGestures:
    """``+`` / ``-``, ``space``, and a digit typed in place.

    None of them is a shortcut around the edit path: each calls the same
    ``on_edit_channel`` a typed number does, so the gate refuses it, the
    range check sees it, the log records it and the read-back verifies it.
    """

    async def test_plus_and_minus_step_the_focused_value(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("minus")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "126"
            assert app.device.read_setup().channel(LIVE).volume == 126
            # One dump write and no parameter edit: the gesture is another
            # door into the same path, not a second one.
            assert app.device.set_log == []
            assert len(app.device.dump_log) == 1

    async def test_equals_sign_steps_too(self, app):
        """``+`` is a shift on most layouts, and a nudge is a one-handed
        gesture.

        Driven on the volume of a channel that is not at the top of its
        range, because ``=`` is bound to the same ``bump(1)`` and the value
        under the cursor is the thing that makes it observable.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            # Channel 10 is at volume 127 like the others, so step the
            # pan -- 64 on the wire, and a field with room above it.
            table.move_cursor(row=LIVE + 1, column=PAN_COLUMN)
            await pilot.press("equals_sign")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert _cells(table, LIVE + 1)[PAN_COLUMN] == "1"
            assert app.device.read_setup().channel(LIVE + 1).pan == 65

    async def test_a_nudge_is_clamped_at_the_low_end(self, app):
        """No wrap, and no write: a per-channel edit is a whole-dump write,
        and re-sending a value the unit already holds would put an entry on
        the undo timeline that restores something that was never changed."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            # Channel 6 is the demo's volume-0 channel, still enabled.
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "0"
            table.move_cursor(row=MUTED, column=VOLUME_COLUMN)
            before = len(app.device.dump_log)
            await pilot.press("minus")
            await pilot.pause()
            assert app.device.dump_log[before:] == []
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "0"
            status = _status(screen)
            assert "channel 6 volume is already 0" in status
            assert "the range is 0-127" in status
            assert status.startswith("refused · ")
            assert app._changes == []

    async def test_a_nudge_is_clamped_at_the_high_end(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "127"
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("plus")
            await pilot.pause()
            assert app.device.dump_log == []
            assert "is already 127" in _status(screen)
            assert app._changes == []

    async def test_a_nudge_on_a_field_that_is_not_a_number_says_so(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=MIX_COLUMN)
            await pilot.press("plus")
            await pilot.pause()
            assert app.device.dump_log == []
            assert "+ / - step a number" in _status(screen)
            assert "mix_output" in _status(screen)

    async def test_space_toggles_a_switch_both_ways(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=RXPC_COLUMN)
            assert _cells(table, LIVE)[RXPC_COLUMN] == "on"
            await pilot.press("space")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert _cells(table, LIVE)[RXPC_COLUMN] == "OFF"
            assert app.device.read_setup().channel(LIVE).receive_program_change == 0
            await pilot.press("space")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert _cells(table, LIVE)[RXPC_COLUMN] == "on"
            assert app.device.read_setup().channel(LIVE).receive_program_change == 1
            assert app._changes[-1] == ChannelChange(
                LIVE, "receive_program_change", 0, 1
            )

    async def test_space_toggles_the_enable_column(self, app):
        """The one of the nine that used to be a reason and nothing else."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=ENABLE_COLUMN)
            await pilot.press("space")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert _cells(table, LIVE)[ENABLE_COLUMN] == "OFF"
            assert app.device.read_setup().channel(LIVE).enable == 0
            # And the reason column agrees with the switch, because both are
            # read from the same entry.
            keys = [column.key.value for column in table.columns.values()]
            assert "channel is disabled" in _cells(table, LIVE)[keys.index("why")]

    async def test_space_on_a_field_that_is_not_a_switch_says_so(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("space")
            await pilot.pause()
            assert app.device.dump_log == []
            status = _status(screen)
            assert "space toggles a switch" in status
            assert "volume is not one" in status

    async def test_a_digit_types_a_number_in_place(self, app):
        """The spreadsheet gesture: a three-keystroke value should not cost a
        dialog, so the digits go on the screen's own status line."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press(*list("90"))
            await pilot.pause()
            status = _status(screen)
            assert "channel 9 volume: 90 (0-127)" in status
            assert "writes" in status and "cancels" in status
            assert not status.startswith("refused")
            await pilot.press("escape")
            await pilot.pause()
            # Escape cancels the number and leaves the screen open -- a key
            # that both cancels an entry and closes the screen would close
            # the screen the first time.
            assert isinstance(app.screen, MultiScreen)
            assert _status(screen) == ""
            assert app.device.dump_log == []
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "127"

    async def test_the_digits_accumulate_and_enter_writes_them(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press("7", "7")
            await pilot.pause()
            assert "volume: 77" in _status(screen)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "77"
            assert app.device.read_setup().channel(LIVE).volume == 77
            # The prompt is gone, and the sentence that replaced it is the
            # app's own about the edit -- not the half-typed number.
            assert "volume: 77" not in _status(screen)
            assert _status(screen) == "channel 9 volume = 77"

    async def test_a_number_typed_over_the_range_is_refused_by_the_range(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press(*list("999"))
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            await pilot.pause()
            assert app.device.dump_log == []
            assert "must be 0-127" in _status(screen)
            assert _status(screen).startswith("refused · ")

    async def test_moving_the_cursor_abandons_a_half_typed_number(self, app):
        """A buffer that outlived the cursor would make the next digit append
        to a value meant for the cell the cursor has left."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            await pilot.press(*list("44"))
            await pilot.pause()
            assert "volume: 44" in _status(screen)
            await pilot.press("down")
            await pilot.pause()
            assert _status(screen) == ""
            await pilot.press(*list("12"))
            await pilot.pause()
            # The buffer belongs to channel 10 now, not channel 9.
            assert "channel 10 volume: 12" in _status(screen)

    async def test_a_digit_on_a_switch_names_the_key_that_toggles(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=RXPC_COLUMN)
            await pilot.press("1")
            await pilot.pause()
            assert app.device.dump_log == []
            assert "receive_program_change is on or off" in _status(screen)
            assert "space toggles it" in _status(screen)

    async def test_a_locked_gate_refuses_every_gesture(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot, armed=False)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=VOLUME_COLUMN)
            # Every gesture from the top of the range: `-` steps (and is
            # refused by the gate), `+` cannot move at all and says so
            # rather than pretending, and space toggles a switch.
            # `-` steps a value that can move, and is refused by the gate.
            await pilot.press("minus")
            await pilot.pause()
            assert "the write gate is locked" in _status(screen)
            # `space` on a switch, which is a gesture that needs no number.
            table.move_cursor(row=LIVE, column=RXPC_COLUMN)
            await pilot.press("space")
            await pilot.pause()
            assert "the write gate is locked" in _status(screen)
            await pilot.press(*list("90"))
            await pilot.press("enter")
            await pilot.pause()
            assert "the write gate is locked" in _status(screen)
            assert app.device.dump_log == []
            assert app.device.set_log == []


class _Held(DemoDevice):
    """A fake whose dump write stops on the wire until the test lets it go.

    The coalescing is about a press that arrives *while a write is in
    flight*, and a pilot cannot produce that deterministically:
    ``pilot.press`` awaits an idle app, so with a fast fake the write is
    over before the next key lands and with a slow one "idle" is one
    round trip away -- neither is a burst. This fake stops the write
    where a test can wait for it, so the keys are dispatched with the
    unit holding the frame, which is the case the complaint was about.
    The write then goes through the real path, so the read-back verifies
    exactly what it always did.
    """

    def __init__(self) -> None:
        super().__init__()
        #: Set on the worker's thread when a dump write has reached the
        #: wire, so the test waits for "in flight" rather than sleeping.
        self.held = threading.Event()
        #: Set by the test to let that write finish. Waited on with a
        #: timeout, so a test that forgets fails slowly instead of
        #: hanging the suite.
        self.released = threading.Event()
        self.inflight = 0
        self.most_at_once = 0

    def send_setup_dump(self, dump, *, timeout=None):
        self.held.set()
        self.released.wait(timeout=10)
        self.inflight += 1
        self.most_at_once = max(self.most_at_once, self.inflight)
        try:
            self.take(dump, timeout=timeout)
        finally:
            self.inflight -= 1

    def take(self, dump, *, timeout=None) -> None:
        """What the unit does with the frame once the test lets it go.

        The real fake's, so a write lands and is read back; a subclass
        overrides this to be the unit that disregards it.
        """
        super().send_setup_dump(dump, timeout=timeout)


class TestABurstOfNudgesOnOneCell:
    """``+`` five times in the time one whole-dump write takes.

    The surface half of what ``tests/test_channel_edits.py`` pins on the
    app, and the half the complaint was actually about: the row has to
    move with the keys, and no press may arrive as a refusal. A
    per-channel edit is a whole-setup write, so one nudge is a round
    trip -- that is the "incredibly slow", and ``_busy`` refusing the
    next key while it was in flight was the "often lost".
    """

    async def test_five_plus_presses_land_on_the_last_value(self, app):
        """Channel 6 is at volume 0, so there is room above it.

        The write is held on the wire while the other four keys are
        pressed -- a real round trip is longer still, so the window is
        wider on hardware than it is here.
        """
        device = _Held()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=MUTED, column=VOLUME_COLUMN)
            said = _record(app)
            device.held.clear()
            await pilot.press("plus")
            await _wait_for(pilot, device.held.is_set)
            # The row moved with the key, and it is the only one that
            # moved a unit: the rest land while the first is in flight.
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "1"
            await pilot.press("plus", "plus", "plus", "plus")
            # While the burst is in flight the row already says where it
            # is going -- the "incredibly slow" half of the complaint.
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "5"
            device.released.set()
            await _wait_for(pilot, lambda: not app._busy)
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "5"
            assert app.device.read_setup().channel(MUTED).volume == 5
            assert device.most_at_once == 1, "two writes were in flight at once"
            # Two writes, not five and not one: the first value and the
            # last. The three in between cost a redraw and no frame.
            assert len(device.dump_log) == 2
            assert app._changes == [
                ChannelChange(MUTED, "volume", 0, 1),
                ChannelChange(MUTED, "volume", 1, 5),
            ]
            # No press produced a refusal, and none produced a "busy" --
            # the sentence that used to answer the second key.
            assert not any(refused for _message, refused in said)
            assert "busy" not in [message for message, _refused in said]
            assert said[-1] == ("channel 6 volume = 5", False)

    async def test_a_minus_after_a_plus_lands_on_the_net_value(self, app):
        """The pan has room either side of centre, and this burst nets
        nothing: ``+`` then ``-`` is two writes, and the unit ends where
        it started with the ``-`` not swallowed by the ``+``."""
        device = _Held()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PAN_COLUMN)
            assert _cells(table, LIVE)[PAN_COLUMN] == "0"  # 64 on the wire
            said = _record(app)
            device.held.clear()
            await pilot.press("plus")
            await _wait_for(pilot, device.held.is_set)
            await pilot.press("minus")
            assert _cells(table, LIVE)[PAN_COLUMN] == "0"
            device.released.set()
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(LIVE).pan == 64
            assert len(device.dump_log) == 2
            assert app._changes == [
                ChannelChange(LIVE, "pan", 64, 65),
                ChannelChange(LIVE, "pan", 65, 64),
            ]
            assert not any(refused for _message, refused in said)

    async def test_a_locked_gate_refuses_every_press_of_a_burst(self, app):
        """The gate is checked at the press, so a locked one refuses the
        first key -- and nothing is queued behind the lock for the later
        ones either."""
        device = _Held()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot, armed=False)
            table = _table(screen)
            table.move_cursor(row=MUTED, column=VOLUME_COLUMN)
            await pilot.press("plus", "plus", "plus")
            await pilot.pause()
            assert app.device.dump_log == []
            assert app.device.set_log == []
            # Not even the row moved: a refused nudge draws nothing.
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "0"
            status = _status(screen)
            assert "the write gate is locked" in status
            assert status.startswith("refused · ")

    async def test_a_nudge_on_another_cell_during_a_write_is_busy(self, app):
        """``_busy`` still guards everything but the cell being written.
        One slot holds one cell, and a second cell is the old refusal."""
        device = _Held()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=MUTED, column=VOLUME_COLUMN)
            device.held.clear()
            await pilot.press("plus")
            await _wait_for(pilot, device.held.is_set)
            # Channel 9's pan, while channel 6's volume is on the wire.
            table.move_cursor(row=LIVE, column=PAN_COLUMN)
            await pilot.press("plus")
            await pilot.pause()
            assert _status(screen) == "refused · busy"
            # And the row that was refused is the one that did not move.
            assert _cells(table, LIVE)[PAN_COLUMN] == "0"
            device.released.set()
            await _wait_for(pilot, lambda: not app._busy)
            assert len(device.dump_log) == 1
            assert app.device.read_setup().channel(MUTED).volume == 1
            assert app.device.read_setup().channel(LIVE).pan == 64

    async def test_a_write_the_unit_ignores_puts_the_row_back(self, app):
        """The optimistic row is an offer, and a unit that takes the
        frame and disregards it -- what a Proteus does with a request it
        cannot serve -- is exactly why. The row ends up saying what the
        unit reports, not what was sent."""

        class Ignoring(_Held):
            """Stops on the wire as the held one does, then disregards
            the frame it was handed."""

            def take(self, dump, *, timeout=None) -> None:
                self.handle(m.parameter_edit(1, 1, device=self.device_id))

        app.device = Ignoring()
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=MUTED, column=VOLUME_COLUMN)
            device = app.device
            device.held.clear()
            await pilot.press("plus")
            await _wait_for(pilot, device.held.is_set)
            # The row moved with the key, before anything was verified.
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "1"
            device.released.set()
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == []
            assert _cells(table, MUTED)[VOLUME_COLUMN] == "0"
            assert app._changes == []
            assert "did not take 1" in _status(screen)


class TestPickASoundForTheChannel:
    """``s``: the one gesture that writes three fields, because the unit
    takes ``rom_id``, ``preset`` and ``bank_map`` together.

    The shape is the sibling rxved's ``PatchPickerScreen``, and what p2ked
    can be given of it is the bank pane, the favourites cycle and the name
    filter -- see :class:`p2ked.multi.SoundPickerScreen` for which of the
    three rxved does not have.
    """

    async def test_s_opens_the_picker_with_a_bank_pane_and_a_slot_pane(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("s")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            picker = app.screen
            banks = picker.query_one("#sound-banks", DataTable)
            slots = picker.query_one("#sound-slots", DataTable)
            # Every bank in the table, and the first bank's presets.
            assert banks.row_count == len(roms.bank_ids())
            assert slots.row_count == roms.PRESETS_PER_BANK
            # The slot's row carries the three numbers that select it, in
            # the order a sequencer's MIDI track asks for them.
            first = [str(cell) for cell in slots.get_row(next(iter(slots.rows)))]
            assert first[0] == ""
            assert first[1].startswith("USER-0 ")
            assert first[3:] == ["0", "0", "0"]

    async def test_enter_on_the_plays_column_opens_the_same_picker(self, app):
        """The gesture a reader will try first, on the column that names what
        the channel plays."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            await pilot.press("escape")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            assert app.device.dump_log == []

    async def test_the_rom_id_is_labelled_as_what_it_is(self, app):
        """The sentence ``p2kcli hardware`` prints, reused rather than
        reworded -- and it names the three ROMs that were confirmed without
        claiming twenty."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("s")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            notes = " ".join(_text(note) for note in app.screen.query(".note"))
            assert "Bank Select MSB" in notes
            assert "No E-MU document to hand" in notes
            assert "three ROMs on 2026-09-12" in notes
            assert "not all twenty" in notes

    async def test_picking_a_sound_writes_three_fields_as_one_change(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("s")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            picker = app.screen
            slots = picker.query_one("#sound-slots", DataTable)
            slots.focus()
            await pilot.pause()
            await pilot.press("down", "down", "down")
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            entry = app.device.read_setup().channel(LIVE)
            # Composer preset 24 becomes user preset 3, and the ROM with it.
            assert (entry.rom_id, entry.preset) == (roms.USER_ROM_ID, 3)
            # One entry on the undo timeline for the whole sound, not three
            # entries that could each restore a third of one.
            assert app._changes[-1] == ChannelChange(
                LIVE, "sound", (24, 0, 4), (3, 0, 0)
            )
            assert len(app.device.dump_log) == 1
            # And the row says what the read-back reported.
            assert _cells(table, LIVE)[PLAYS_COLUMN] == "User 3 Quiet Pad"
            keys = [column.key.value for column in table.columns.values()]
            assert _cells(table, LIVE)[keys.index("rom")] == "User (0)"

    async def test_the_bank_map_is_carried_over_not_invented(self, app):
        """No document to hand says what the Multimode Bank Map maps between
        (RESOLUTION_NOTES §12), so the picker changes the sound and leaves
        the channel's own mapping alone."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            app.action_edit_channel(LIVE, "bank_map", 6)
            await _wait_for(pilot, lambda: not app._busy)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("s")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            slots = app.screen.query_one("#sound-slots", DataTable)
            slots.focus()
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            assert app.device.read_setup().channel(LIVE).bank_map == 6

    async def test_the_name_filter_searches_every_bank(self, app):
        """The filter rxved's multi picker does not have: its ``/`` search is
        on the browser, and the picker scrolls. p2ked's catalog can search,
        and a 128-preset bank is a long scroll."""
        app.catalog.set_live_name("XLEAD-0", 12, "Velvet Wash")
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("s")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            picker = app.screen
            slots = picker.query_one("#sound-slots", DataTable)
            assert slots.row_count == roms.PRESETS_PER_BANK
            picker.query_one("#filter").focus()
            await pilot.pause()
            await pilot.press(*list("velvet"))
            await pilot.pause()
            # Nine, and every one of them in this bank: the demo's invented
            # names come from a sixteen-word adjective pool, so a filter
            # over a whole bank still matches a handful. What the filter
            # proves is that the pane went from 128 to the matches.
            assert 0 < slots.row_count < roms.PRESETS_PER_BANK
            assert "Velvet Wash" in str(slots.get_row(next(iter(slots.rows)))[2])
            assert "matching" in _text(picker.query_one("#picker-title", Static))
            # Enter in the filter box goes to the match, and Enter there
            # picks it.
            await pilot.press("enter")
            await pilot.pause()
            assert picker.focused is slots
            await pilot.press("enter")
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.pause()
            entry = app.device.read_setup().channel(LIVE)
            # The preset number is ROM-relative, which is what the dump
            # carries and what System Exclusive asks for.
            assert entry.preset == 12
            assert entry.rom_id == 0 or entry.rom_id == roms.rom("XLEAD").msb

    async def test_the_favourites_view_needs_a_store_to_read(self, app):
        """``None`` when the app was started without ``--favorites``: the
        cycle says so rather than showing an empty list and calling it a
        view."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("s")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            await pilot.press("v")
            await pilot.pause()
            title = _text(app.screen.query_one("#picker-title", Static))
            assert "no favourites store" in title
            assert "--favorites" in title
            # Still the bank's own presets, not an empty pane.
            assert app.screen.query_one("#sound-slots", DataTable).row_count == (
                roms.PRESETS_PER_BANK
            )

    async def test_the_favourites_view_cycles_when_there_is_a_store(
        self, app, tmp_path
    ):
        """Three views, the browser's own: all presets in this bank, this
        bank's favourites, every favourite across banks."""
        from p2k import favorites

        # A real store in a tmp_path, rather than a stub with the shape of
        # one: the view reads the same tables the browser does.
        db = str(tmp_path / "f.db")
        store = favorites.Favorites(db)
        store.add("USER-0", 5)
        store.add("XLEAD-0", 9)
        app.favorites = store
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                screen = await _open_multi(app, pilot)
                table = _table(screen)
                table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
                await pilot.press("s")
                await _wait_for(
                    pilot, lambda: isinstance(app.screen, SoundPickerScreen)
                )
                picker = app.screen
                slots = picker.query_one("#sound-slots", DataTable)
                assert slots.row_count == roms.PRESETS_PER_BANK
                await pilot.press("v")
                await pilot.pause()
                assert slots.row_count == 1
                assert "this bank's favourites" in _text(
                    picker.query_one("#picker-title")
                )
                await pilot.press("v")
                await pilot.pause()
                assert slots.row_count == 2
                assert "every favourite" in _text(picker.query_one("#picker-title"))
        finally:
            store.close()

    async def test_cancelling_the_picker_writes_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            table.move_cursor(row=LIVE, column=PLAYS_COLUMN)
            await pilot.press("s")
            await _wait_for(pilot, lambda: isinstance(app.screen, SoundPickerScreen))
            await pilot.press("q")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            assert app.device.dump_log == []
            assert app.device.read_setup().channel(LIVE).preset == 24

    async def test_a_screen_with_no_sound_path_says_so(self, app):
        """A keystroke that reaches nothing is worse than a refusal."""
        screen = MultiScreen(app.device.read_setup(), app.catalog, None)
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.action_pick_sound()
            await pilot.pause()
            assert "no sound picker path" in _status(screen)
            assert _status(screen).startswith("refused · ")


class TestWhatTheScreenSaysAndShows:
    """The seams the app looks for, and the row's honesty afterwards.

    ``say`` puts a sentence on this screen's own status line rather than on
    the app's ``#status``, which is the dimmed backdrop behind the modal --
    a refusal written there is written where nobody is looking.
    """

    async def test_a_refusal_is_said_inside_the_modal(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            screen.say("refused because of the gate", refused=True)
            assert _status(screen) == "refused · refused because of the gate"
            screen.say("it landed")
            assert _status(screen) == "it landed"

    async def test_a_verified_write_is_drawn_where_it_happened(self, app):
        """``channel_result`` redraws the row from the values the read-back
        verified -- not from the values that were sent, which is the
        difference between an edit that landed and one that did not."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "127"
            screen.channel_result(
                True,
                "channel 9 volume = 90",
                ChannelChange(LIVE, "volume", 127, 90),
            )
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "90"
            # The screen's own copy of the dump is updated too, so a detail
            # opened afterwards says the same thing the row does.
            assert screen._dump.channel(LIVE).volume == 90
            assert (
                screen.query_one("#multi-table", DataTable).get_row("8")[VOLUME_COLUMN]
                == "90"
            )

    async def test_a_failed_write_leaves_the_row_alone(self, app):
        """Nothing was put in the channel, so the row still says what the
        unit has."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            screen.channel_result(
                False,
                "channel 9 volume did not take 90",
                ChannelChange(LIVE, "volume", 127, 90),
            )
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "127"

    async def test_an_undo_tells_the_screen_what_came_back(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            screen.channel_result(
                True, "channel 9 volume = 90", ChannelChange(LIVE, "volume", 127, 90)
            )
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "90"
            screen.channel_undone([(ChannelChange(LIVE, "volume", 127, 90), True)])
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "127"
            # A ``z`` whose send failed leaves the row alone.
            screen.channel_undone([(ChannelChange(LIVE, "volume", 127, 90), False)])
            assert _cells(table, LIVE)[VOLUME_COLUMN] == "127"

    async def test_a_sound_edit_redraws_all_three_columns(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            table = _table(screen)
            keys = [column.key.value for column in table.columns.values()]
            assert "Composer" in _cells(table, LIVE)[keys.index("rom")]
            screen.channel_result(
                True,
                "channel 9 sound = preset 3, bank_map 0, rom_id 0",
                ChannelChange(LIVE, "sound", (24, 0, 4), (3, 0, 0)),
            )
            assert _cells(table, LIVE)[keys.index("rom")] == "User (0)"
            assert _cells(table, LIVE)[PLAYS_COLUMN] == "User 3 Quiet Pad"

    async def test_a_master_edit_answer_is_said_from_this_screen(self, app):
        """The master editor's own seams, because the app hands them to any
        screen that answers ``say`` -- and this is the screen ``z`` is
        pressed on, so this is where the sentence belongs."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            screen.result(True, "transpose = 5")
            assert _status(screen) == "transpose = 5"
            screen.result(False, "transpose did not take 5")
            assert _status(screen) == "refused · transpose did not take 5"
            # And `undone` draws nothing, because there are no master rows
            # here to draw -- it must not be a missing method either.
            screen.undone([(m.Parameter.MASTER_TRANSPOSE, 0)], [(259, True)])

    async def test_the_screen_has_no_master_rows_to_redraw(self, app):
        """The two seams exist, which is the whole of the claim: a screen
        that grew a ``say`` and not these would be a screen the app calls a
        missing method on."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            assert callable(screen.say)
            assert callable(screen.result)
            assert callable(screen.undone)
            assert callable(screen.channel_result)
            assert callable(screen.channel_undone)


class TestWhatTheScreenDeclares:
    """The footer, the report and the legend -- the three places a key or a
    consequence has to be written down.
    """

    async def test_the_footer_names_the_editing_keys(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            hints = " ".join(_text(widget) for widget in screen.query(Static))
            for phrase in (
                "enter channel detail",
                "+ / - nudge",
                "space",
                "toggles",
                "s picks a sound",
                "a digit types a number",
                "z undo",
            ):
                assert phrase in hints, phrase

    async def test_the_report_says_what_an_edit_does(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot, armed=False)
            report = screen._report()
            # The gate's own state, which is a fact about right now rather
            # than a key -- and it moves when `w` is pressed.
            assert "Write gate locked" in report
            assert "editing a cell" in report
            assert "whole setup dump" in report
            assert "spec p. 29" in report
            assert "read back to verify it" in report
            assert "puts the previous value back" in report
            # Armed is a different sentence, and the note is redrawn when
            # `w` is pressed rather than left describing the old state.
            await pilot.press("w")
            await pilot.pause()
            note = _text(screen.query_one(".note", Static))
            assert "Write gate ARMED" in note
            assert "editing a cell" in screen._report()

    async def test_the_rom_column_is_labelled_as_what_it_is(self, app):
        """The SIMM-ID caveat, on the screen whose ROM column names ROMs from
        it -- the rule that a guess is labelled in the interface, not only
        in a comment."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            report = screen._report()
            assert "reads the SIMM ID as that ROM's Bank Select MSB" in report
            assert "confirmed against hardware for three ROMs" in report
            assert "2026-09-12" in report

    async def test_the_legend_declares_the_new_keys(self):
        """Declared to the family, the way ``x master FX`` is: each of these
        changes the unit, and a key that changes the unit and is documented
        nowhere is a key that gets pressed by accident."""
        from p2ked.app import KEY_HINTS

        for hint in ("+ - nudge", "space toggle", "s pick sound"):
            assert hint in KEY_HINTS, hint

    async def test_the_screen_binds_the_keys_the_legend_promises(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_multi(app, pilot)
            bound = {binding.key for binding in screen.BINDINGS}
            for key in ("w", "s", "space", "plus", "equals_sign", "minus", "z", "Z"):
                assert key in bound, key
            for digit in range(10):
                assert str(digit) in bound, digit
