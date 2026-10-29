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

"""The write path: the gate, the range, the log, and what is not offered.

p2ked was read-only until the maintainer decided editing was in. What makes
that safe is five things, and this file is the one that pins them:

* **The gate is locked by default.** ``w`` arms it. An edit aimed at a
  locked gate is refused *and nothing is sent* -- a refusal that still
  wrote to the unit would be worse than no gate at all, so the app-level
  tests assert on the fake's ``set_log`` rather than on the sentence.
* **A value outside the parameter's range is refused**, for the same
  reason: the sentence is not the point, the absence of a write is.
* **An edit is logged only when the read-back agreed.** A Proteus ignores
  a request it cannot serve rather than refusing it, so "sent" and "taken"
  are different facts, and only the second is undoable -- undoing the
  first would send back a value nobody saw the unit accept.
* **Undo sends the previous value back**, the one recorded *before* the
  new one went out. A write that failed to land has nothing to read
  afterwards, so the old value cannot be recovered later.
* **What p2ked cannot name a parameter ID for is not written at all.**
  ``probe_channel_ids`` is the read-only way to establish the per-channel
  IDs on a real unit, and it is checked here for sending nothing but
  requests.

Two levels, on purpose. :class:`p2ked.masteredit.MasterEditor` is pure and
is tested directly; the app's workers are driven headlessly against
:class:`p2ked.demo.DemoDevice`, which records every ``set_parameter`` and
``copy_master_setup`` it was handed -- so "nothing was sent" is an
assertion about the wire rather than about a message.

The async tests need no marker: ``asyncio_mode = "auto"`` in
pyproject.toml is what collects them.
"""

import pytest
from textual.widgets import DataTable, Static

from p2k import catalog as cat
from p2k import messages as m
from p2ked.app import P2kedApp, build_parser
from p2ked.demo import DemoDevice
from p2ked.masteredit import (
    CHANNEL_EDIT_IDS,
    FX_PARAMETERS,
    MASTER_BY_ID,
    MASTER_PARAMETERS,
    EditGate,
    MasterEditor,
    probe_channel_ids,
)
from p2ked.multi import (
    CHANNEL_EDIT_HINT,
    FXEditScreen,
    MasterEditScreen,
    MultiScreen,
    ValuePickerScreen,
)
from p2ked.prompts import PromptScreen

#: A parameter whose range runs either side of zero, so a sign error in the
#: check shows up here rather than on one of the 0-127 ones.
TRANSPOSE = MASTER_BY_ID[m.Parameter.MASTER_TRANSPOSE]
#: One with a plain unsigned range, and a value the demo does not start at.
CLOCK_TEMPO = MASTER_BY_ID[m.Parameter.MASTER_CLOCK_TEMPO]
#: One with choices, where the range is an enumeration rather than a span.
MIDI_MODE = MASTER_BY_ID[m.Parameter.MIDI_MODE]
#: The row a parameter with a plain integer range sits on.
#:
#: The typed prompt is what a numeric parameter still gets. A parameter
#: with ``choices`` now opens its own picker instead -- ``enter`` on "MIDI
#: mode" used to answer ``0=omni, 1=poly, 2=multi`` and ask for the number,
#: which is a vocabulary the unit does not have. Row 0 happens to be a
#: choice, so the tests that exercise the prompt move the cursor off it.
TRANSPOSE_ROW = [p.parameter_id for p in MASTER_PARAMETERS].index(
    m.Parameter.MASTER_TRANSPOSE
)


@pytest.fixture
def app():
    return P2kedApp(DemoDevice(), catalog=cat.empty())


@pytest.fixture
def favouriting(tmp_path):
    """An app with a favourites store, and the store to look at.

    ``tmp_path`` because a test must not write into the user's real
    database -- rxved learned that one the hard way, by leaving two files
    in it. A catalog with two names, because `f` records the name with the
    row and a store full of blanks tests nothing about the labels.
    """
    from p2k.favorites import Favorites

    store = Favorites(str(tmp_path / "favourites.db"))
    catalog = cat.Catalog(
        [
            cat.Entry("USER-0", 0, "Velvet Bell"),
            cat.Entry("USER-0", 1, "Rusted Pad"),
        ]
    )
    return P2kedApp(DemoDevice(), catalog=catalog, favorites=store), store


def _record(app):
    """Capture what the app says, and whether it said it as a refusal.

    The refusal flag is kept rather than discarded: ``notify_status``
    prefixes it on the status line, and a refusal that was announced
    without it would look like news rather than a "no".
    """
    said = []

    def say(message, *, refused=False):
        said.append((message, refused))

    app.notify_status = say
    return said


async def _wait_for(pilot, ready, attempts=100):
    """Wait until ``ready()`` is true, or fail saying so.

    Every app-level operation here finishes on a worker thread and is
    handed back with ``call_from_thread``, so how many trips through the
    message loop it takes is a property of the machine. A fixed count of
    pauses is a guess, and a guess in a test is a flake.
    """
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _open_master_edit(app, pilot):
    """``m`` then ``e``: the multi screen, and the master editor over it.

    The whole way in, because the edit screen is only reachable from there
    and the button that opens it is part of what is being tested.

    Settled first, for the reason the modal tests' ``_open_multi``
    retries: the launch's own name auto-read refuses a press landing in
    it, and on a slow runner that outlasts a fixed handful of pauses.
    """
    await _wait_for(pilot, lambda: not app._busy)
    await pilot.press("m")
    await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
    await pilot.press("e")
    await _wait_for(pilot, lambda: isinstance(app.screen, MasterEditScreen))
    return app.screen


class TestTheGateIsLockedByDefault:
    """A write needs an explicit act.

    This is the family's ``w write gate`` -- vinsynlib's ``EDITOR_KEYS``,
    so it is the same key in rxved and here -- and the legend shows which
    state it is in. "Why did my edit not send?" has to be answerable from
    where the question is asked.
    """

    def test_a_new_gate_is_locked(self):
        gate = EditGate()
        assert gate.armed is False
        assert gate.describe() == "write gate locked"

    def test_the_editor_does_not_come_up_armed(self):
        """``MasterEditor()`` with no arguments must not be the armed one:
        the default is what a caller gets by forgetting."""
        editor = MasterEditor()
        assert isinstance(editor.gate, EditGate)
        assert editor.gate.armed is False

    def test_the_app_starts_locked(self, app):
        assert app._gate.armed is False
        # One gate and one log per app, and the editor is built on them:
        # the state the screen shows has to be the one the edits go through.
        assert app._editor.gate is app._gate
        assert app._editor.log.pending == 0

    def test_the_refusal_names_the_key(self):
        refusal = EditGate().refuse("transpose")
        assert "transpose not sent" in refusal
        assert "the write gate is locked" in refusal
        assert "Press w to arm it" in refusal

    async def test_w_arms_the_gate_and_says_which_state_it_is_in(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first: the launch's auto-read announces its own
            # completion on the status line, and arriving mid-test it
            # overwrites the sentence this asserts on.
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("w")
            assert app._gate.armed is True
            assert said[-1] == ("write gate ARMED", False)
            await pilot.press("w")
            assert app._gate.armed is False
            assert said[-1] == ("write gate locked", False)


class TestAllowWriteArmsTheGateAtStartup:
    """``--allow-write`` is the family's flag, and p2ked now takes it.

    The docstrings in :mod:`p2ked.masteredit` and :mod:`p2ked.multi` have
    always said it starts the gate armed, so what is pinned here is both
    halves of the promise: the parser accepts it, and an app built with it
    can write with no ``w`` pressed at all.
    """

    def test_the_parser_accepts_it_and_defaults_to_locked(self):
        locked = build_parser().parse_args([])
        assert locked.allow_write is False
        armed = build_parser().parse_args(["--allow-write"])
        assert armed.allow_write is True

    def test_it_arms_the_one_gate_the_app_creates(self):
        app = P2kedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        # The same one gate and one editor the locked app has: the flag is
        # the state it starts in, not a second object to keep in step.
        assert app._gate.armed is True
        assert app._editor.gate is app._gate
        assert app._editor.log.pending == 0

    async def test_an_edit_reaches_the_unit_with_no_key_pressed(self):
        app = P2kedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first: an edit refused as "busy" is never sent, and
            # the log the test asserts on stays empty for the wrong reason.
            await _wait_for(pilot, lambda: not app._busy)
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MASTER_TRANSPOSE, 5)]

    async def test_the_same_run_without_the_flag_is_refused(self):
        """The default is still locked: the flag is what makes the
        difference, not the presence of a test that says otherwise."""
        app = P2kedApp(DemoDevice(), catalog=cat.empty())
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first: an edit refused as "busy" is never sent, and
            # the log the test asserts on stays empty for the wrong reason.
            await _wait_for(pilot, lambda: not app._busy)
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == []
            message, refused = said[-1]
            assert "the write gate is locked" in message
            assert refused


class TestALockedEditIsRefused:
    """Refused, and nothing on the wire.

    The sentence is the half of this that is easy to get right. The
    load-bearing half is that a refused edit leaves the unit alone, which
    is why these assert on the fake's ``set_log``.
    """

    def test_the_gate_alone_refuses_an_otherwise_legal_edit(self):
        refusal = MasterEditor().allow(TRANSPOSE, 5)
        assert refusal is not None
        assert "transpose" in refusal
        assert "the write gate is locked" in refusal

    def test_an_armed_gate_allows_the_same_edit(self):
        editor = MasterEditor(EditGate(armed=True))
        assert editor.allow(TRANSPOSE, 5) is None

    def test_the_gate_is_answered_before_the_range_is(self):
        """A locked gate is the answer even when the value is also wrong:
        arming it must not turn a silent refusal into a sent edit."""
        refusal = MasterEditor().allow(TRANSPOSE, 999)
        assert "the write gate is locked" in refusal
        assert "must be" not in refusal

    async def test_the_app_refuses_a_locked_edit_and_sends_nothing(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            assert screen._editor.gate.armed is False
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [], "a locked edit still reached the unit"
            assert app.device.copy_log == []
            assert app._editor.log.pending == 0
            message, refused = said[-1]
            assert "transpose not sent" in message
            assert "the write gate is locked" in message
            assert refused

    async def test_an_armed_edit_does_reach_the_unit(self, app):
        """The other side of the same check: with the gate armed the very
        edit the previous test refused goes out, so the refusal above is
        about the gate rather than about the parameter."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await _open_master_edit(app, pilot)
            await pilot.press("w")
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MASTER_TRANSPOSE, 5)]


class TestAnOutOfRangeEditIsRefused:
    """The ranges are transcribed, so they are asserted rather than
    assumed -- and an edit outside one is refused before it is sent."""

    def test_below_the_low_end_is_refused(self):
        refusal = MasterEditor(EditGate(armed=True)).allow(TRANSPOSE, -25)
        assert refusal == "transpose must be -24-24, and -25 is not"

    def test_above_the_high_end_is_refused(self):
        refusal = MasterEditor(EditGate(armed=True)).allow(TRANSPOSE, 25)
        assert refusal == "transpose must be -24-24, and 25 is not"

    def test_both_ends_are_allowed(self):
        """An inclusive range, checked at both edges: a comparison wrong by
        one is the mistake this pins."""
        editor = MasterEditor(EditGate(armed=True))
        assert editor.allow(TRANSPOSE, -24) is None
        assert editor.allow(TRANSPOSE, 24) is None

    def test_a_choice_parameter_takes_only_its_choices(self):
        editor = MasterEditor(EditGate(armed=True))
        assert editor.allow(MIDI_MODE, 3) == "MIDI mode must be 0-2, and 3 is not"
        for value in range(3):
            assert editor.allow(MIDI_MODE, value) is None

    async def test_the_app_refuses_an_out_of_range_edit_and_sends_nothing(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _open_master_edit(app, pilot)
            await pilot.press("w")  # arm the gate: only the range is in the way
            assert app._gate.armed is True
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 25)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [], "an out-of-range edit reached the unit"
            assert app._editor.log.pending == 0
            message, refused = said[-1]
            assert message == "transpose must be -24-24, and 25 is not"
            assert refused


class TestAReadBackThatDisagreesIsNotLogged:
    """Sent is not taken.

    A Proteus ignores a request it cannot serve rather than refusing it,
    so a write that left no trace looks exactly like a success. The
    read-back is what separates them, and an edit that cannot be verified
    must not become undoable.
    """

    def test_a_read_that_failed_is_said_and_logs_nothing(self):
        editor = MasterEditor(EditGate(armed=True))
        ok, message = editor.finish(TRANSPOSE, 5, before=0, after=None)
        assert ok is False
        assert "read-back failed" in message
        assert "nothing is logged" in message
        assert editor.log.changes == []

    def test_a_read_back_that_disagrees_is_said_and_logs_nothing(self):
        editor = MasterEditor(EditGate(armed=True))
        ok, message = editor.finish(TRANSPOSE, 5, before=0, after=0)
        assert ok is False
        assert "did not take 5" in message
        assert "still reports 0" in message
        assert editor.log.changes == []
        assert editor.log.pending == 0

    def test_a_read_back_that_agreed_is_logged_with_the_old_value(self):
        editor = MasterEditor(EditGate(armed=True))
        ok, message = editor.finish(CLOCK_TEMPO, 300, before=120, after=300)
        assert ok is True
        assert message == "clock tempo = 300"
        assert editor.log.changes == [(m.Parameter.MASTER_CLOCK_TEMPO, 120, 300)]

    def test_a_value_that_could_not_be_read_first_is_not_invented(self):
        """``before`` is ``None`` when the read before the write failed.
        The log then carries the value sent, because that is the only one
        anybody knows -- it does not guess a zero."""
        editor = MasterEditor(EditGate(armed=True))
        editor.finish(TRANSPOSE, 5, before=None, after=5)
        assert editor.log.changes == [(m.Parameter.MASTER_TRANSPOSE, 5, 5)]

    async def test_an_edit_a_broken_wire_interrupted_is_not_logged(self):
        class Broken(DemoDevice):
            def read_parameter(self, parameter_id, *, timeout=None):
                raise TimeoutError("no reply")

        app = P2kedApp(Broken(), catalog=cat.empty())
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [], "the edit was sent after the read failed"
            assert app._editor.log.pending == 0
            message, refused = said[-1]
            assert "transpose" in message
            assert "no reply" in message
            assert refused

    async def test_an_edit_the_unit_ignores_is_not_logged_and_cannot_be_undone(self):
        """The case the read-back exists for, against a unit that takes the
        frame and disregards it.

        This is not a perverse fake: the real thing has no "refused" reply
        on the cable either, which is exactly why silence cannot be
        distinguished from success without reading the value back.
        """

        class Deaf(DemoDevice):
            def set_parameter(self, parameter_id, value, *, timeout=None):
                self.handle(
                    m.parameter_edit(parameter_id, value, device=self.device_id)
                )

        app = P2kedApp(Deaf(), catalog=cat.empty())
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_CLOCK_TEMPO, 300)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.received, "the edit was never sent; the check is vacuous"
            assert app._editor.log.pending == 0
            message, refused = said[-1]
            assert "did not take 300" in message
            assert "still reports 120" in message
            assert refused
            # And so there is nothing to undo: `z` says so rather than
            # sending a value the unit never accepted.
            app._undo_master_edits(1)
            await _wait_for(pilot, lambda: not app._busy)
            assert said[-1] == ("nothing to undo", False)


class TestUndoSendsThePreviousValue:
    """``z`` reverses the last edit and ``Z`` all of them, by sending back
    the value that was there before.

    That is why the log records it *before* the new value goes out: a
    write that failed to land has nothing to read back afterwards, so the
    only recoverable old value is the one kept at the time.
    """

    def _editor(self):
        editor = MasterEditor(EditGate(armed=True))
        editor.finish(TRANSPOSE, 5, before=0, after=5)
        editor.finish(CLOCK_TEMPO, 300, before=120, after=300)
        return editor

    def test_the_log_holds_the_old_value_first(self):
        assert self._editor().log.changes == [
            (m.Parameter.MASTER_TRANSPOSE, 0, 5),
            (m.Parameter.MASTER_CLOCK_TEMPO, 120, 300),
        ]

    def test_the_undo_plan_is_the_old_value_newest_first(self):
        assert self._editor().undo_plan(1) == [(m.Parameter.MASTER_CLOCK_TEMPO, 120)]

    def test_a_plan_is_taken_off_the_log_as_it_is_made(self):
        """An undo that fails halfway must not be replayed twice on the
        next press: the entry leaves the log the moment it is planned."""
        editor = self._editor()
        assert editor.undo_plan(1) == [(m.Parameter.MASTER_CLOCK_TEMPO, 120)]
        assert editor.log.pending == 1
        assert editor.undo_plan(9) == [(m.Parameter.MASTER_TRANSPOSE, 0)]
        assert editor.log.pending == 0
        assert editor.undo_plan(1) == []

    def test_undoing_nothing_plans_nothing(self):
        editor = MasterEditor()
        assert editor.undo_plan(0) == []
        assert editor.undo_plan(3) == []

    def test_a_cleared_log_has_nothing_left_to_undo(self):
        editor = self._editor()
        editor.log.clear()
        assert editor.log.pending == 0
        assert editor.undo_plan(1) == []

    def test_the_report_names_what_happened(self):
        editor = MasterEditor()
        assert editor.undo_report([]) == "nothing to undo"
        assert editor.undo_report([(m.Parameter.MASTER_TRANSPOSE, True)]) == (
            "undid 1 edit"
        )
        assert editor.undo_report([(257, True), (259, True)]) == "undid 2 edits"
        assert editor.undo_report([(259, False), (257, True)]) == (
            "undid 1; the unit rejected 1 (parameters 259)"
        )

    async def test_the_app_sends_the_previous_value_back(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_CLOCK_TEMPO, 300)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MASTER_CLOCK_TEMPO, 300)]
            assert app.device.parameters[m.Parameter.MASTER_CLOCK_TEMPO] == 300
            # `z`, pressed on the screen the edit was offered on.
            screen.action_undo()
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [
                (m.Parameter.MASTER_CLOCK_TEMPO, 300),
                (m.Parameter.MASTER_CLOCK_TEMPO, 120),
            ]
            assert app.device.parameters[m.Parameter.MASTER_CLOCK_TEMPO] == 120
            assert app._editor.log.pending == 0
            assert said[-1] == ("undid 1 edit", False)

    async def test_z_and_Z_are_the_browser_s_keys_too(self, app):
        """The same two keys, with no edit screen open.

        An edit is offered on the master edit screen and undone after it is
        closed, so the keys cannot belong to the screen alone: the legend
        promises ``z undo`` and ``Z undo all`` in the browser, and the app
        is what owns the worker and the log they are applied to.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            app._apply_master_edit(m.Parameter.MASTER_CLOCK_TEMPO, 300)
            await _wait_for(pilot, lambda: not app._busy)
            assert app._editor.log.pending == 2
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_CLOCK_TEMPO, 120)
            assert app._editor.log.pending == 1
            await pilot.press("Z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_TRANSPOSE, 0)
            assert app._editor.log.pending == 0
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 0

    async def test_z_with_an_empty_log_says_so_and_sends_nothing(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first: `z` refused as "busy" says the wrong sentence.
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("z")
            await pilot.pause()
            assert app.device.set_log == []
            assert app.device.copy_log == []
            assert said[-1] == ("nothing to undo", False)

    async def test_undo_all_sends_every_previous_value_back_newest_first(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            app._apply_master_edit(m.Parameter.MASTER_CLOCK_TEMPO, 300)
            await _wait_for(pilot, lambda: not app._busy)
            assert app._editor.log.pending == 2
            screen.action_undo_all()
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [
                (m.Parameter.MASTER_TRANSPOSE, 5),
                (m.Parameter.MASTER_CLOCK_TEMPO, 300),
                # newest first, each one the value it replaced
                (m.Parameter.MASTER_CLOCK_TEMPO, 120),
                (m.Parameter.MASTER_TRANSPOSE, 0),
            ]
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 0
            assert app.device.parameters[m.Parameter.MASTER_CLOCK_TEMPO] == 120
            assert app._editor.log.pending == 0


class TestThePerChannelProbeWritesNothing:
    """The per-channel multimode parameter IDs are not established, and
    p2ked refuses to guess them: a wrong ID is a write to a number nobody
    knows. ``probe_channel_ids`` is the read-only way to find them on a
    real unit, so what it must not do is write.
    """

    def test_it_reads_the_range_and_reports_what_answered(self):
        asked = []
        answers = {700: 3, 900: 8}

        def read(parameter_id):
            asked.append(parameter_id)
            return answers.get(parameter_id)

        found = probe_channel_ids(read)
        assert found["low"] == 662
        assert found["high"] == 1024
        assert found["answered"] == [700, 900]
        assert asked == list(range(662, 1024))

    def test_the_range_is_a_hint_the_caller_can_narrow(self):
        asked = []

        def note(parameter_id):
            asked.append(parameter_id)

        found = probe_channel_ids(note, low=662, high=666)
        assert asked == [662, 663, 664, 665]
        assert found == {"low": 662, "high": 666, "answered": []}

    def test_the_per_channel_ids_are_absent_rather_than_guessed(self):
        """``None``, not a table of plausible numbers. The refusal is the
        honest answer until a hardware session establishes them."""
        assert CHANNEL_EDIT_IDS is None

    def test_every_frame_the_probe_sends_is_a_request(self):
        """The strongest form of "writes nothing" available without a unit.

        The fake's ``read_parameter`` answers from its own memory and puts
        nothing on the wire, so a probe through it would leave ``received``
        empty and the check below would be vacuous. This device asks over
        the wire instead: the probe really does emit 362 frames, and every
        one of them is a Parameter Value *request*.
        """

        class WireReading(DemoDevice):
            """The fake, with its reads on the wire so they can be seen.

            Two changes, both of them things a real unit does. The request
            goes out as a frame, so what the probe emits is inspectable
            rather than assumed; and an ID the unit has no parameter for is
            **silent** rather than answered with a default, because that is
            what makes "which ones answer" a question with an answer --
            the fake's own ``read_parameter`` returns 0 for everything,
            which would make every ID in the range look present.
            """

            def read_parameter(self, parameter_id, *, timeout=None):
                self.handle(m.parameter_request(parameter_id, device=self.device_id))
                if parameter_id not in self.parameters:
                    return None
                return super().read_parameter(parameter_id, timeout=timeout)

        device = WireReading()
        # An answer inside the range, so `answered` is not vacuous either.
        device.parameters[700] = 3
        found = probe_channel_ids(device.read_parameter)
        assert found["answered"] == [700]
        assert len(device.received) == 1024 - 662
        assert {m.parse(frame).command for frame in device.received} == {
            m.Command.PARAMETER_REQUEST
        }
        assert device.set_log == [], "the probe set a parameter"
        assert device.copy_log == [], "the probe copied a setup"
        # And the check above can actually see a write -- without this it
        # would also pass on a probe that sent nothing at all.
        device.set_parameter(m.Parameter.MASTER_CLOCK_TEMPO, 120)
        assert any(
            m.parse(frame).command == m.Command.PARAMETER_EDIT
            for frame in device.received
        )


class TestTheMasterEditScreen:
    """What the editor shows before anything is sent: the gate's state, the
    undo count, every parameter p2ked can name an ID for, and why the
    per-channel ones are not on offer."""

    def _screen(self, editor=None, values=None, on_apply=None):
        return MasterEditScreen(
            DemoDevice().read_setup(),
            {} if values is None else values,
            MasterEditor() if editor is None else editor,
            on_apply=on_apply,
        )

    def test_it_shows_the_gate_and_says_what_that_means(self):
        report = self._screen()._report()
        assert "write gate locked" in report
        assert "edits are refused until it is armed" in report
        armed = self._screen(MasterEditor(EditGate(armed=True)))._report()
        assert "write gate ARMED" in armed
        assert "every edit below will be sent" in armed

    def test_it_counts_what_z_would_undo(self):
        editor = MasterEditor(EditGate(armed=True))
        editor.finish(TRANSPOSE, 5, before=0, after=5)
        assert "1 edit(s) undoable with z." in self._screen(editor)._report()

    def test_it_says_why_per_channel_edits_are_not_offered(self):
        assert CHANNEL_EDIT_HINT in self._screen()._report()
        assert "docs/TODO item 47" in CHANNEL_EDIT_HINT

    def test_every_parameter_offered_is_one_p2ked_already_reads(self):
        """The IDs in ``MASTER_PARAMETERS`` were established by reading them
        back off a unit and comparing them with the dump
        (RESOLUTION_NOTES §10) -- so each one is in the Setup Dump, and the
        dump's value for it is inside the range the editor accepts. A range
        narrower than the unit's own value would refuse an edit the unit
        was already in."""
        dump = DemoDevice().read_setup()
        for parameter in MASTER_PARAMETERS:
            assert parameter.parameter_id in dump.master
            value = dump.parameter(parameter.parameter_id)
            assert parameter.low <= value <= parameter.high, parameter.label

    def test_the_fake_agrees_with_itself_about_the_values_the_editor_shows(self):
        """The demo's read-back and its own dump have to be one unit.

        An edit is verified by reading the parameter, and the screen shows
        a value read the same way; a fake whose two answers disagreed would
        let a write look verified against one and displayed from the other.
        """
        device = DemoDevice()
        dump = device.read_setup()
        for parameter in MASTER_PARAMETERS:
            assert device.read_parameter(parameter.parameter_id) == dump.parameter(
                parameter.parameter_id
            ), parameter.label

    async def test_it_lists_every_parameter_with_its_range_and_its_value(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await _open_master_edit(app, pilot)
            table = screen.query_one("#master-table", DataTable)
            assert [row.key.value for row in table.rows.values()] == [
                str(parameter.parameter_id) for parameter in MASTER_PARAMETERS
            ]
            assert [column.key.value for column in table.columns.values()] == [
                "param",
                "now",
                "range",
            ]
            # A list, not a tuple: DataTable.get_row answers a list, and what
            # is being pinned here is the cells and their order rather than
            # the container Textual happened to choose for them.
            assert list(table.get_row(str(m.Parameter.MASTER_TRANSPOSE))) == [
                "transpose",
                "0",
                "-24 - 24",
            ]
            # A choice parameter is spelled with its choices, and the value
            # the unit reported is shown as the name rather than the number.
            assert list(table.get_row(str(m.Parameter.MIDI_MODE))) == [
                "MIDI mode",
                "multi",
                "omni / poly / multi",
            ]
            assert screen._values[m.Parameter.MASTER_CLOCK_TEMPO] == 120

    async def test_a_parameter_that_could_not_be_read_shows_a_question_mark(self, app):
        """A read that failed is said, not rounded to zero -- and a choice
        value outside its own enumeration is not spelled as one."""
        screen = self._screen(
            values={
                m.Parameter.MIDI_MODE: None,
                m.Parameter.MASTER_FX_BYPASS: 9,
            }
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#master-table", DataTable)
            assert table.get_row(str(m.Parameter.MIDI_MODE))[1] == "?"
            assert table.get_row(str(m.Parameter.MASTER_FX_BYPASS))[1] == "unknown (9)"

    async def test_enter_on_a_row_offers_that_edit_and_the_answer_reaches_on_apply(
        self, app
    ):
        applied = []
        screen = self._screen(
            values={m.Parameter.MIDI_MODE: 2},
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value)),
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#master-table", DataTable).focus()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            await pilot.press("enter")
            await pilot.pause()
            assert applied == [(m.Parameter.MIDI_MODE, 2)]

    async def test_a_word_where_a_number_was_asked_for_is_refused(self, app):
        said = _record(app)
        applied = []
        screen = self._screen(
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value))
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=TRANSPOSE_ROW)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list("loud"))
            await pilot.press("enter")
            await pilot.pause()
            assert applied == []
            message, refused = said[-1]
            assert message == "'loud' is not a number"
            assert refused

    async def test_an_empty_answer_offers_no_edit(self, app):
        applied = []
        screen = self._screen(
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value))
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#master-table", DataTable)
            table.focus()
            table.move_cursor(row=TRANSPOSE_ROW)
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press("enter")
            await pilot.pause()
            assert applied == []

    async def test_the_result_of_an_edit_is_said_from_the_screen(self, app):
        said = _record(app)
        screen = self._screen()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.result(True, "clock tempo = 300")
            assert said[-1] == ("clock tempo = 300", False)
            screen.result(False, "transpose did not take 5")
            assert said[-1] == ("transpose did not take 5", True)


class TestTheMasterFxBlock:
    """The sixteen FX parameters, on the same path as the eleven general
    ones -- and what is transcribed rather than read.

    Two claims are pinned here and they are different kinds of claim. The
    **IDs** are unit-agreed: 513-528 is the dump's own master effects block,
    which RESOLUTION_NOTES §10 established by reading each value back from a
    unit and agreeing it with the dump. The **labels, ranges and names** are
    not: they are transcribed from the manuals with a page cite on each one
    (RESOLUTION_NOTES §12), and the two algorithms' named values are the
    operation manual's own numbering. A suite passing here says the
    transcription is internally consistent, which is a different thing from
    saying it is what a unit stores.

    What is also pinned is the one thing the FX block does *not* do: FX B
    delay (523) keeps no named values, because the two documents disagree
    about what they would be and guessing would put a plausible-looking
    list in front of somebody who then sends it.
    """

    def _screen(self, values=None):
        return MasterEditScreen(
            DemoDevice().read_setup(),
            {} if values is None else values,
            MasterEditor(),
        )

    def test_the_table_is_the_dump_s_own_effects_block(self):
        """Sixteen parameters, in the dump's order, and nothing invented.

        The block is the unit's, not the document's, so the test reads it
        out of :data:`p2k.messages.MASTER_BLOCKS` rather than out of a list
        of numbers written here -- a second list could agree with itself.
        """
        block = dict(m.MASTER_BLOCKS)["master effects"]
        assert len(block) == 16
        assert tuple(p.parameter_id for p in FX_PARAMETERS) == block
        assert [p.parameter_id for p in FX_PARAMETERS] == list(range(513, 529))

    def test_every_fx_parameter_is_one_the_dump_carries(self):
        """The same check the general table gets, for the same reason: a
        range narrower than the unit's own value would refuse an edit the
        unit was already in."""
        dump = DemoDevice().read_setup()
        for parameter in FX_PARAMETERS:
            assert parameter.parameter_id in dump.master, parameter.label
            value = dump.parameter(parameter.parameter_id)
            assert parameter.low <= value <= parameter.high, parameter.label

    def test_the_fake_agrees_with_itself_about_the_fx_values(self):
        """An edit is verified against a read-back and displayed from one;
        a fake whose two answers disagreed would hide a failure in the
        difference between them."""
        device = DemoDevice()
        dump = device.read_setup()
        for parameter in FX_PARAMETERS:
            assert device.read_parameter(parameter.parameter_id) == dump.parameter(
                parameter.parameter_id
            ), parameter.label

    def test_the_two_algorithms_are_enumerations_numbered_from_one(self):
        """``base`` is 1 for both, and that is the whole of the off-by-one.

        The specification gives each a min of 1 (spec p. 49) and the manual
        numbers its effect types from 1 -- the A list on OM p. 41, the B list
        on OM p. 43 -- so the first name is the value at ``low``. A picker
        that assumed names start at zero would offer a blank row and then
        send one too few.
        """
        a = MASTER_BY_ID[513]
        b = MASTER_BY_ID[520]
        assert (a.base, b.base) == (1, 1)
        assert (a.low, len(a.choices)) == (1, 44)
        assert (b.low, len(b.choices)) == (1, 32)
        assert a.choices[0] == "Room 1"
        assert a.choices[-1] == "DelayVerb 9"
        assert b.choices[0] == "Chorus 1"
        assert b.choices[-1] == "Distorted Double"

    def test_every_other_fx_parameter_is_a_plain_range(self):
        """Fourteen plain ranges and two enumerations, and the enumerations
        are the algorithms -- a named value appearing on a parameter the
        documents give only min/max for would be a guess with a list."""
        named = [p for p in FX_PARAMETERS if p.choices]
        assert [p.parameter_id for p in named] == [513, 520]
        assert [p.label for p in named] == ["FX A algorithm", "FX B algorithm"]

    def test_fx_b_delay_keeps_no_named_values(self):
        """The disagreement, refused rather than smoothed over.

        The parameter tree lists note values ahead of "0ms - 635ms in 5ms
        increments" (paramtree, MASTER BUTTON 11); the operation manual says
        only "The Delay value range is from 0ms to 635ms" (OM p. 146) and
        its screens show a plain number of milliseconds. Two documents, two
        answers, and a picker built on the wrong one would send a time
        nobody asked for. So the range is transcribed and the raw value is
        sent.
        """
        delay = MASTER_BY_ID[523]
        assert delay.choices == ()
        assert (delay.low, delay.high) == (0, 127)
        assert "paramtree" in delay.note
        assert "635" in delay.note

    def test_the_fx_block_is_on_the_one_lookup_the_app_checks(self):
        """``MASTER_BY_ID`` holds both tables, which is what puts the FX
        parameters on the edit path: the app refuses an ID absent from it,
        so a screen cannot offer what the app will not send."""
        for parameter in FX_PARAMETERS:
            assert MASTER_BY_ID[parameter.parameter_id] is parameter
        for parameter in MASTER_PARAMETERS:
            assert MASTER_BY_ID[parameter.parameter_id] is parameter
        # And one that is in neither -- the arpeggiator block, which p2ked
        # reads and does not edit -- is still refused.
        assert m.Parameter.MASTER_ARP_STATUS not in MASTER_BY_ID

    async def test_an_fx_edit_reaches_the_unit_and_is_read_back(self, app):
        """The whole path, on an FX parameter: the write goes out, the value
        comes back, and the log records it -- so ``z`` has something to
        reverse."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(514, 60)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(514, 60)]
            assert app._editor.log.pending == 1
            assert said[-1] == ("FX A decay = 60", False)

    async def test_a_locked_gate_refuses_an_fx_edit(self, app):
        """Nothing is sent, and the sentence names the parameter rather
        than the bare number."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first: an edit refused as "busy" is never sent, and
            # the log the test asserts on stays empty for the wrong reason.
            await _wait_for(pilot, lambda: not app._busy)
            app._apply_master_edit(521, 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == []
            message, refused = said[-1]
            assert "FX B feedback not sent" in message
            assert "the write gate is locked" in message
            assert refused

    async def test_a_value_outside_an_fx_range_is_refused_and_nothing_is_sent(
        self, app
    ):
        """The range check is the client-side half of a documented rule:
        "Values recieved that are outside the min/max range will be clipped
        to within that range" (spec p. 41). An algorithm of 45 is not
        refused by the unit -- it arrives as 44, which is a write that
        looks like it worked."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(513, 45)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == []
            message, refused = said[-1]
            assert "FX A algorithm must be 1-44, and 45 is not" in message
            assert refused

    async def test_a_read_back_that_disagrees_is_not_logged_for_an_fx_edit(self, app):
        """The unit that ignores what it cannot serve is exactly this case,
        and it is indistinguishable from a success until something reads the
        value again -- which is why an FX edit goes through the same
        read-back a general one does, and why one that did not take is not
        undoable.
        """
        said = _record(app)

        class Deaf(DemoDevice):
            def set_parameter(self, parameter_id, value, *, timeout=None):
                self.handle(
                    m.parameter_edit(parameter_id, value, device=self.device_id)
                )

        app.device = Deaf()
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(514, 60)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.received, "the edit was never sent; the check is vacuous"
            assert app._editor.log.pending == 0
            message, refused = said[-1]
            assert "FX A decay did not take 60" in message
            assert "still reports 0" in message
            assert refused

    async def test_undo_sends_the_previous_fx_value(self, app):
        """The value the unit had before the edit, read back off the log --
        not the one after it, because a write that failed to land has
        nothing to read."""
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(514, 60)
            await _wait_for(pilot, lambda: not app._busy)
            app._undo_master_edits(1)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(514, 60), (514, 0)]
            assert app._editor.log.pending == 0

    async def test_an_fx_enumeration_picks_by_index_not_by_name(self, app):
        """``Room 3`` is the value 3, not the third row of the list -- the
        arithmetic the ``base`` field exists for, checked on the picker
        that draws it."""
        applied = []
        screen = FXEditScreen(
            DemoDevice().read_setup(),
            {513: 1},
            MasterEditor(),
            on_apply=lambda parameter_id, value: applied.append((parameter_id, value)),
        )
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            table = screen.query_one("#fx-table", DataTable)
            assert table.cursor_row == 0
            table.focus()
            await pilot.press("enter")
            await _wait_for(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
            picker = app.screen
            choices = picker.query_one("#choices", DataTable)
            assert choices.row_count == 44
            # The current value, 1, is under the cursor and marked.
            assert choices.cursor_row == 0
            assert choices.get_row("1") == ["[b]Room 1[/b]"]
            await pilot.press("down")
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert applied == [(513, 3)]


class TestUndoCoversBothKindsOfChange:
    """``z`` reverses the last change of either kind, and ``Z`` all of them.

    ``f`` writes the local favourites database; an edit writes to the unit.
    Neither was undoable before this: ``z`` only ever looked at the
    master-edit log, so a favourite made with one keystroke could not be
    put back with one more, while an edit could be -- a difference in
    undo-ability that had nothing to do with how easy either is to make.

    One timeline, because ``z`` has to reverse whichever came *last*, and
    a favourite toggle can land between two edits. See
    :class:`p2ked.app.EditChange` for why it is one list rather than two.

    The favourite half sends nothing: it is a write to SQLite and a
    redraw, and there is no frame and no device call in it anywhere.
    """

    async def _press_f(self, app, pilot, times=1):
        for _ in range(times):
            await pilot.press("f")
            await pilot.pause()

    async def test_f_then_z_puts_the_favourite_back(self, favouriting):
        """With an *empty* edit log, which is what used to swallow it.

        ``z`` asked the edit log first and found nothing there, so it said
        "nothing to undo" -- while a favourite the user had just made sat
        in the store with the keystroke that could undo it. The favourite
        is a change like any other now.
        """
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            assert store.get("USER-0", number) is None
            assert app._editor.log.pending == 0
            await self._press_f(app, pilot)
            assert store.get("USER-0", number) is not None
            await pilot.press("z")
            await pilot.pause()
            assert store.get("USER-0", number) is None

    async def test_the_previous_state_is_what_comes_back_not_the_complement(
        self, favouriting
    ):
        """``f`` twice is a favourite that was undone by pressing ``f``
        again, and ``z`` has to restore the *favourite* -- the state the
        keypress replaced -- not simply flip whatever the store says."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            await self._press_f(app, pilot)  # favourited
            await self._press_f(app, pilot)  # and un-favourited again
            assert store.get("USER-0", number) is None
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert store.get("USER-0", number) is not None
            # ... and it flipped the *toggle*, it did not re-run `f`.
            assert len(app._changes) == 1

    async def test_z_after_a_master_edit_still_reverses_the_edit(self, favouriting):
        """The half that has always worked, unchanged: the previous value
        goes back over the wire, and the log loses the entry."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_CLOCK_TEMPO, 300)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log == [(m.Parameter.MASTER_CLOCK_TEMPO, 300)]
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_CLOCK_TEMPO, 120)
            assert app._editor.log.pending == 0
            assert store.get("USER-0", 0) is None

    async def test_the_newest_of_the_two_kinds_is_undone_first(self, favouriting):
        """``f``, then an edit: ``z`` takes the edit, because it came last,
        and the next ``z`` takes the favourite. One timeline, not two."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            await self._press_f(app, pilot)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert app._editor.log.pending == 1
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            # The edit, newest first -- and the favourite is untouched.
            assert app.device.set_log[-1] == (m.Parameter.MASTER_TRANSPOSE, 0)
            assert app._editor.log.pending == 0
            assert store.get("USER-0", number) is not None
            await pilot.press("z")
            await pilot.pause()
            assert store.get("USER-0", number) is None

    async def test_the_edit_can_come_first_and_the_favourite_second(self, favouriting):
        """The other order, so "newest first" is not passing by the
        accident of which kind the test happened to make first."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first: the edit below is refused while the launch's
            # auto-read owns the wire, and then there is nothing to undo.
            await _wait_for(pilot, lambda: not app._busy)
            number = app._cursor_entry().program_change
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            await self._press_f(app, pilot)
            await pilot.press("z")
            await pilot.pause()
            # The favourite, because it came second.
            assert store.get("USER-0", number) is None
            assert app._editor.log.pending == 1
            assert app.device.set_log == [(m.Parameter.MASTER_TRANSPOSE, 5)]

    async def test_Z_undoes_both_kinds_newest_first(self, favouriting):
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            await self._press_f(app, pilot)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("Z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_TRANSPOSE, 0)
            assert app._editor.log.pending == 0
            assert store.get("USER-0", number) is None
            assert app._changes == []

    async def test_a_favourite_undo_never_touches_the_device(self, favouriting):
        """No frame, no device call: it is a write to the local store."""
        app, _store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._press_f(app, pilot)
            app.device.received.clear()
            await pilot.press("z")
            await pilot.pause()
            assert app.device.received == []
            assert app.device.set_log == []
            assert app.device.copy_log == []
            assert app.device.selected_log == []

    async def test_nothing_to_undo_when_neither_kind_changed(self, favouriting):
        app, _store = favouriting
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first: `z` refused as "busy" says the wrong sentence.
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("z")
            await pilot.pause()
            assert said[-1] == ("nothing to undo", False)
            assert app._changes == []

    async def test_a_favourite_survives_a_FavouriteChange_of_a_different_slot(
        self, favouriting
    ):
        """Two slots, one ``z``: only the one under the cursor went back."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._press_f(app, pilot)  # slot 0
            app.query_one("#preset-table").focus()
            await pilot.press("down")
            await pilot.pause()
            await self._press_f(app, pilot)  # slot 1
            assert store.get("USER-0", 0) is not None
            assert store.get("USER-0", 1) is not None
            await pilot.press("z")
            await pilot.pause()
            assert store.get("USER-0", 0) is not None
            assert store.get("USER-0", 1) is None

    async def test_the_browser_s_keys_cover_both_kinds(self, favouriting):
        """``z`` and ``Z`` are the legend's own words, and neither says
        "edit" -- the family spells them that way and this is now true of
        them."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("Z")
            await pilot.pause()
            assert store.get("USER-0", number) is None
            assert app._changes == []

    async def test_the_entry_is_off_the_timeline_before_the_worker_finishes(self):
        """Consume-on-take, and why it earns a test of its own.

        The plan leaves the library's log on the main thread, so for as
        long as the worker runs the timeline is already empty -- a
        cannot lie about an entry that is being undone right now. It is
        read at the one moment it must not: inside the send the undo is
        making.
        """
        seen: list[int] = []

        class Watcher(DemoDevice):
            """A unit that reads the timeline as it is asked to undo."""

            def set_parameter(self, parameter_id, value):
                seen.append(len(app._changes))
                super().set_parameter(parameter_id, value)

        app = P2kedApp(Watcher(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            # Settled first, for the reason the direct-edit tests above are.
            await _wait_for(pilot, lambda: not app._busy)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app._changes) == 1
            seen.clear()  # the edit is done; watch the undo
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert seen == [0], "the timeline was empty as the undo ran"
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 0
            assert app._changes == []

    async def test_an_undo_while_busy_is_refused_not_queued(self, favouriting):
        """The busy gate, in the library's voice.

        The log consults it before it hands out a plan, so an undo
        never starts behind a write that owns the wire -- and the
        timeline is left standing for the press that comes after.
        """
        app, store = favouriting
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            await self._press_f(app, pilot)
            app._busy = True
            await pilot.press("z")
            await pilot.pause()
            assert said[-1] == ("busy", True)
            assert len(app._changes) == 1, "the gate refused, the log kept"
            app._busy = False
            await pilot.press("z")
            await pilot.pause()
            assert store.get("USER-0", number) is None


class TestUndoFromTheMultiScreen:
    """``z`` pressed on the multi screen, which is where an edit returns.

    ``escape`` on the master editor does not close the multi screen -- it
    dismisses the editor over it -- so this is the screen a user is looking
    at when they decide the edit was a mistake. It used to swallow the key:
    a modal screen cuts the app's binding chain, which is the whole reason
    the master editor binds ``w`` and ``z`` for itself, and the multi
    screen bound neither. The app's own ``z`` was dead here, invisibly,
    for a key the legend advertises.

    The screen now serves the keys itself, against the app's own timeline
    -- handed in the way ``on_edit`` is, because a screen owns no worker
    and ``z`` reverses on one.
    """

    async def _open_multi(self, app, pilot):
        # Settled first: the launch's own name auto-read refuses a press
        # landing in it, and on a slow runner that outlasts a fixed
        # handful of pauses.
        await _wait_for(pilot, lambda: not app._busy)
        await pilot.press("m")
        await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
        return app.screen

    async def test_z_on_the_multi_screen_reverses_the_edit(self, favouriting):
        """The whole way round: ``m``, ``e``, an edit, ``escape``, ``z``.

        The key that failed used to reach nothing at all -- not even
        "nothing to undo" -- because the app-level binding never arrived.
        """
        app, _store = favouriting
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _open_master_edit(app, pilot)
            await pilot.press("w")
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("escape")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            assert app._editor.log.pending == 1
            assert app._changes != []
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_TRANSPOSE, 0)
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 0
            assert app._editor.log.pending == 0
            assert app._changes == []
            assert said[-1] == ("undid 1 edit", False)

    async def test_z_on_the_multi_screen_puts_a_favourite_back(self, favouriting):
        """The other kind, from the same screen: no wire, no worker."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            await pilot.press("f")
            await pilot.pause()
            assert store.get("USER-0", number) is not None
            await self._open_multi(app, pilot)
            await pilot.press("z")
            await pilot.pause()
            assert store.get("USER-0", number) is None
            assert app._changes == []

    async def test_Z_on_the_multi_screen_takes_both_kinds(self, favouriting):
        """Both binds, one screen: ``Z`` leaves nothing behind."""
        app, store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            number = app._cursor_entry().program_change
            await pilot.press("f")
            await pilot.pause()
            await self._open_multi(app, pilot)
            app._gate.toggle()
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("Z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.set_log[-1] == (m.Parameter.MASTER_TRANSPOSE, 0)
            assert store.get("USER-0", number) is None
            assert app._changes == []

    async def test_the_multi_screen_says_the_key_is_there(self, favouriting):
        """A key nobody is told about is a key nobody presses, and this one
        was invisible twice over: not bound, and not in the footer."""
        app, _store = favouriting
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open_multi(app, pilot)
            hints = [str(h.visual) for h in screen.query(Static)]
            assert any("z undo" in text for text in hints)
