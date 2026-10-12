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

"""The per-channel write path: the gate, the range, the bytes, the undo.

A per-channel edit is a whole-setup write, and the specification is what
licenses it: a command station "receive[s] and understand[s] the old setup
dump" (spec p. 29). So the operation is *read the live dump, change the one
field, re-encode the dump, send it, read it back, verify the field*. What
makes that safe is that every other byte is the one the unit sent a moment
earlier, which is the first thing this file pins -- by encoding the dump
before and after the mutation and comparing them byte for byte.

Four properties, and they are the same four the master edit path has:

* **A locked gate refuses and sends nothing**, and a value outside the
  field's transcribed range does too. Both are asserted against the fake's
  ``dump_log`` rather than against the sentence -- a whole-setup write is a
  large thing to send by accident.
* **Only the edited field's bytes move.** :func:`mutate_channel` builds a
  new :class:`p2k.messages.SetupDump` with one channel replaced, so the
  frame carries the unit's own bytes everywhere else.
* **The read-back is what gets logged.** A fake that takes the dump and
  disregards it -- which is what a Proteus 2000 does with a request it
  cannot serve -- leaves the edit unlogged and therefore un-undoable.
* **``z`` puts the previous value back**, newest first, across both kinds:
  a master edit and a channel edit share one timeline, and this file is
  where the channel half of that is pinned.

What none of this can establish is whether the unit takes the dump at all.
That is a hardware session's to answer, and ``make test-hardware``'s
unmodified round trip is the first thing it should do; see
``docs/RESOLUTION_NOTES.md`` §12, "The dump is a writable message too".
"""

import threading

import pytest
from textual.widgets import Static

from p2k import catalog as cat
from p2k import messages as m
from p2k.bridge import ProteusBridge
from p2ked.app import P2kedApp
from p2ked.demo import DEMO_DEVICE_ID, DemoDevice
from p2ked.masteredit import (
    CHANNEL_FIELDS,
    SOUND_FIELD,
    ChannelChange,
    ChannelLog,
    EditGate,
    MasterEditor,
    channel_values,
    fields_of,
    mutate_channel,
)
from p2ked.multi import MultiScreen

#: An enabled channel, so an edit moves one that is actually doing
#: something. The demo deliberately leaves channel 1 off and channel 6 on at
#: volume 0, so neither of those would say much.
LIVE = 8
#: A disabled channel: its fields are every bit as writable, and this is the
#: row a "would not sound" channel still gets edited from.
QUIET = 3
#: An enabled channel at volume 0, the demo's second kind of silent -- and
#: the one a burst of ``+`` presses has room to climb from.
MUTED = 5


@pytest.fixture
def app():
    return P2kedApp(DemoDevice(), catalog=cat.empty())


def _record(app):
    """Capture what the app says, and whether it said it as a refusal.

    The refusal flag is kept rather than discarded: ``notify_status``
    prefixes it on the status line, and a refusal that was announced without
    it would look like news rather than a "no".
    """
    said = []

    def say(message, *, refused=False):
        said.append((message, refused))

    app.notify_status = say
    return said


async def _wait_for(pilot, ready, attempts=100):
    """Wait until ``ready()`` is true, or fail saying so.

    The same helper the master-edit tests use: every operation here finishes
    on a worker thread and is handed back with ``call_from_thread``, so how
    many trips through the message loop it takes is a property of the
    machine rather than of the code.
    """
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


def _frame_offset(dump, channel: int, field: str) -> int:
    """Where ``field``'s two bytes sit in the encoded frame.

    Worked out from the dump's own header rather than hard-coded, so a change
    to the layout would move this assertion with it instead of making it
    quietly check the wrong byte: seven counts, the sixteen-byte name, the
    master blocks, then the channel block -- the order
    :func:`p2k.messages._setup_dump_payload` writes them in.
    """
    names = [name for name, _low, _high in m.CHANNEL_PARAMETERS]
    counts = tuple(len(ids) for _label, ids in m.MASTER_BLOCKS)
    payload = 2 * (len(counts) + 2)  # the seven header counts
    payload += m.NAME_LEN  # the setup name
    payload += 2 * sum(counts)  # the master blocks, two bytes each
    payload += channel * dump.parameters_per_channel * 2
    payload += names.index(field) * 2
    return payload + 6  # F0, manufacturer, family, device, model, command


def _moved_bytes(before: bytes, after: bytes):
    """The offsets at which two encodings of one setup differ."""
    assert len(before) == len(after), "a whole-setup write changed the length"
    return [i for i in range(len(before)) if before[i] != after[i]]


def _other_channels_unchanged(before, after, channel: int) -> None:
    """Every field of every other channel, compared value by value.

    ``ChannelState`` has no ``__eq__``, so "the other channels are
    unchanged" is a statement about the nine values and not about identity
    -- there is nothing else it could honestly be.
    """
    assert len(before.channels) == len(after.channels)
    for old, new in zip(before.channels, after.channels, strict=True):
        assert old.channel == new.channel
        for name, _low, _high in m.CHANNEL_PARAMETERS:
            assert old.channel == channel or getattr(old, name) == getattr(new, name), (
                f"channel {old.channel} {name} moved: "
                f"{getattr(old, name)} -> {getattr(new, name)}"
            )


class TestTheMutationIsTheOnlyThingThatMoves:
    """The mechanism, pinned to bytes.

    A per-channel edit writes the whole setup dump, which means the frame
    carries the unit's own bytes for everything but the one field.
    """

    def test_one_field_moves_only_that_fields_bytes(self):
        dump = DemoDevice().read_setup()
        edited = mutate_channel(dump, LIVE, {"volume": 90})
        before = m.encode_setup_dump(dump, device=DEMO_DEVICE_ID)
        after = m.encode_setup_dump(edited, device=DEMO_DEVICE_ID)
        moved = _moved_bytes(before, after)
        assert moved == [_frame_offset(dump, LIVE, "volume")], (
            f"{len(moved)} bytes moved, and 90 fits in seven bits so the "
            f"low byte is the only one that should have"
        )

    def test_a_value_past_a_hundred_and_twenty_seven_moves_both_bytes(self):
        """``preset`` runs to 895, so a value there does not fit in seven
        bits and both bytes move -- an encoder that only moved the low one
        would pass the previous test and be wrong here."""
        dump = DemoDevice().read_setup()
        edited = mutate_channel(dump, LIVE, {"preset": 200})
        before = m.encode_setup_dump(dump, device=DEMO_DEVICE_ID)
        after = m.encode_setup_dump(edited, device=DEMO_DEVICE_ID)
        assert _moved_bytes(before, after) == [
            _frame_offset(dump, LIVE, "preset"),
            _frame_offset(dump, LIVE, "preset") + 1,
        ]

    def test_every_other_field_of_that_channel_is_what_it_was(self):
        dump = DemoDevice().read_setup()
        entry = mutate_channel(dump, LIVE, {"pan": 90}).channel(LIVE)
        for name, _low, _high in m.CHANNEL_PARAMETERS:
            if name != "pan":
                assert getattr(entry, name) == getattr(dump.channel(LIVE), name)

    def test_every_other_channel_is_untouched(self):
        dump = DemoDevice().read_setup()
        _other_channels_unchanged(
            dump, mutate_channel(dump, QUIET, {"volume": 42}), QUIET
        )

    def test_the_dump_it_was_given_is_not_modified(self):
        """A caller that mutated the dump in place would have to re-read it to
        know what the channel used to hold -- which is the whole value of the
        operation, and the reason a new dump is built."""
        dump = DemoDevice().read_setup()
        was = channel_values(dump, LIVE, ("volume",))
        mutate_channel(dump, LIVE, {"volume": 90})
        assert channel_values(dump, LIVE, ("volume",)) == was

    def test_an_unmodified_dump_round_trips_byte_for_byte(self):
        """The write this project has never made, pinned to the encoder's own
        guarantee: what goes in is what comes out, so an unmodified round trip
        is the least that can be written and still exercise the path."""
        device = DemoDevice()
        dump = device.read_setup()
        assert m.encode_setup_dump(dump, device=DEMO_DEVICE_ID) == device._setup_reply()

    def test_a_write_lands_in_the_fake_as_the_dump_it_was_sent(self):
        """And the read-back is that dump, so the verify step has something
        real to verify against: a fake that recorded a write and went on
        answering its original dump would make every read-back agree."""
        device = DemoDevice()
        written = mutate_channel(device.read_setup(), LIVE, {"volume": 90})
        device.send_setup_dump(written)
        assert device.dump_log == [written]
        assert device.received[-1] == m.encode_setup_dump(
            written, device=DEMO_DEVICE_ID
        )
        assert m.parse(device.received[-1]).command == m.Command.SETUP_DUMP
        assert channel_values(device.read_setup(), LIVE, ("volume",)) == (90,)

    def test_a_channel_the_dump_does_not_have_is_refused_not_guessed(self):
        dump = DemoDevice().read_setup()
        assert dump.channel(32) is None
        assert channel_values(dump, 32, ("volume",)) is None
        with pytest.raises(m.ProtocolError) as found:
            mutate_channel(dump, 32, {"volume": 90})
        assert "not one of them" in str(found.value)

    def test_a_field_that_is_not_one_of_the_nine_is_refused(self):
        with pytest.raises(m.ProtocolError) as found:
            mutate_channel(DemoDevice().read_setup(), LIVE, {"tempo": 90})
        assert "not one of them" in str(found.value)

    def test_a_sound_is_three_fields_in_the_dumps_own_order(self):
        assert fields_of(SOUND_FIELD) == ("preset", "bank_map", "rom_id")
        assert fields_of("volume") == ("volume",)


class TestTheRangeCheck:
    """The nine fields' transcribed ranges, and the same style of refusal a
    master parameter gets."""

    def test_the_table_agrees_with_the_wires_own(self):
        assert sorted(CHANNEL_FIELDS) == sorted(
            name for name, _low, _high in m.CHANNEL_PARAMETERS
        )
        for name, low, high in m.CHANNEL_PARAMETERS:
            assert (CHANNEL_FIELDS[name].low, CHANNEL_FIELDS[name].high) == (low, high)

    def test_both_ends_of_every_field_are_allowed(self):
        editor = MasterEditor(EditGate(armed=True))
        for entry in CHANNEL_FIELDS.values():
            assert editor.allow_channel_field(LIVE, entry.name, entry.low) is None, (
                entry
            )
            assert editor.allow_channel_field(LIVE, entry.name, entry.high) is None, (
                entry
            )

    def test_outside_the_range_is_refused_with_the_range_in_the_sentence(self):
        editor = MasterEditor(EditGate(armed=True))
        refusal = editor.allow_channel_field(LIVE, "volume", 200)
        assert refusal == f"channel {LIVE + 1} volume must be 0-127, and 200 is not"

    def test_the_negative_end_of_a_signed_field_is_refused_not_wrapped(self):
        """``mix_output`` runs -1 to 2 and ``arp`` -2 to 1. A range check
        that read them unsigned would refuse every value the unit has."""
        editor = MasterEditor(EditGate(armed=True))
        assert editor.allow_channel_field(LIVE, "mix_output", -1) is None
        assert "must be -1-2" in editor.allow_channel_field(LIVE, "mix_output", -2)
        assert editor.allow_channel_field(LIVE, "arp", -2) is None
        assert "must be -2-1" in editor.allow_channel_field(LIVE, "arp", -3)

    def test_a_field_that_is_not_one_of_the_nine_is_refused(self):
        editor = MasterEditor(EditGate(armed=True))
        assert "not one of the nine" in editor.allow_channel_field(LIVE, "tempo", 90)

    def test_the_gate_is_answered_before_the_range_is(self):
        """A locked gate is the answer even when the value is also wrong:
        arming it must not turn a silent refusal into a sent write."""
        refusal = MasterEditor().allow_channel_field(LIVE, "volume", 200)
        assert "the write gate is locked" in refusal
        assert "must be" not in refusal

    def test_a_sound_is_refused_at_the_first_field_that_is_out_of_range(self):
        editor = MasterEditor(EditGate(armed=True))
        assert editor.allow_channel_sound(LIVE, rom_id=3, preset=10, bank_map=2) is None
        refusal = editor.allow_channel_sound(LIVE, rom_id=3, preset=1000, bank_map=2)
        assert "preset must be 0-895" in refusal
        assert "bank map" not in refusal

    def test_a_read_back_that_agreed_is_logged_with_the_old_value(self):
        editor = MasterEditor(EditGate(armed=True))
        change = ChannelChange(LIVE, "volume", 127, 90)
        ok, message = editor.finish_channel(change, (90,))
        assert ok is True
        assert message == f"channel {LIVE + 1} volume = 90"
        assert editor.channel_log.changes == [change]

    def test_a_read_back_that_disagreed_is_not_logged(self):
        """The read-back is a tuple because a dump write answers with the
        fields, not one number -- so a disagreement is a tuple that holds
        something else."""
        editor = MasterEditor(EditGate(armed=True))
        ok, message = editor.finish_channel(
            ChannelChange(LIVE, "volume", 127, 90), (127,)
        )
        assert ok is False
        assert "did not take 90" in message
        assert "still reports volume 127" in message
        assert editor.channel_log.pending == 0

    def test_a_read_that_failed_is_said_and_logs_nothing(self):
        editor = MasterEditor(EditGate(armed=True))
        ok, message = editor.finish_channel(
            ChannelChange(LIVE, "volume", 127, 90), None
        )
        assert ok is False
        assert "read-back failed" in message
        assert "nothing is logged" in message
        assert editor.channel_log.pending == 0

    def test_the_undo_plan_is_the_previous_value_newest_first(self):
        editor = MasterEditor(EditGate(armed=True))
        editor.finish_channel(ChannelChange(LIVE, "volume", 127, 90), (90,))
        editor.finish_channel(ChannelChange(QUIET, "pan", 64, 10), (10,))
        plan = editor.channel_undo_plan(1)
        assert plan == [ChannelChange(QUIET, "pan", 64, 10)]
        assert editor.channel_pending == 1
        assert editor.channel_undo_plan(9) == [ChannelChange(LIVE, "volume", 127, 90)]
        assert editor.channel_pending == 0

    def test_the_undo_report_names_the_channel_and_the_field(self):
        editor = MasterEditor(EditGate(armed=True))
        assert editor.channel_undo_report([]) == ""
        assert (
            editor.channel_undo_report([(ChannelChange(LIVE, "volume", 127, 90), True)])
            == f"undid channel {LIVE + 1} volume"
        )
        assert "the unit rejected 1" in editor.channel_undo_report(
            [(ChannelChange(LIVE, "volume", 127, 90), False)]
        )

    def test_a_cleared_channel_log_has_nothing_left_to_undo(self):
        """``Z`` emptied it, so the next ``z`` says so rather than sending a
        dump that restores nothing."""
        editor = MasterEditor(EditGate(armed=True))
        editor.finish_channel(ChannelChange(LIVE, "volume", 127, 90), (90,))
        assert editor.channel_pending == 1
        assert editor.channel_undo_plan(0) == []
        editor.channel_log.clear()
        assert editor.channel_pending == 0
        assert editor.channel_undo_plan(1) == []


class TestTheRecord:
    """One entry on the undo timeline for one dump write, and the fields an
    undo reads off it."""

    def test_one_field_carries_a_bare_value(self):
        change = ChannelChange(LIVE, "volume", 64, 90)
        assert change.channel == LIVE
        assert change.field == "volume"
        assert change.before == 64
        assert change.after == 90
        assert change.fields == ("volume",)
        assert change.restore == {"volume": 64}
        assert change.restore_values == (64,)

    def test_a_sound_carries_three_values_and_restores_all_three(self):
        change = ChannelChange(LIVE, SOUND_FIELD, (3, 10, 1), (4, 20, 2))
        assert change.fields == ("preset", "bank_map", "rom_id")
        assert change.restore == {"preset": 3, "bank_map": 10, "rom_id": 1}
        assert "preset 4" in change.spelled
        assert "rom_id 2" in change.spelled

    def test_the_channel_is_named_the_way_the_unit_shows_it(self):
        """1-based on screen, 0-based on the wire -- the same number
        :attr:`p2k.messages.ChannelState.channel_display` adds one to."""
        assert ChannelChange(0, "volume", 0, 1).label == "channel 1 volume"

    def test_a_read_that_could_not_find_the_channel_answers_none_not_zeros(self):
        """``None`` and a tuple of zeros are different answers: a dump that
        does not carry the channel says so, because a read-back of zeros
        would look like a write that landed on an empty slot."""
        dump = DemoDevice().read_setup()
        assert channel_values(dump, 32, ("volume",)) is None

    def test_declining_a_dump_that_cannot_be_written_back(self):
        """A setup p2ked could not fully decode is refused rather than
        rebuilt with the unread parts as zeros."""
        dump = DemoDevice().read_setup()
        broken = mutate_channel(dump, LIVE, {})
        broken.undecoded = ("the eightieth value is unreadable",)
        editor = MasterEditor(EditGate(armed=True))
        refusal = editor.decline_channel(broken, LIVE, {"volume": 90})
        assert "not fully decoded" in refusal
        assert "writing it back would drop" in refusal

    def test_the_channel_log_answers_nothing_for_nothing(self):
        log = ChannelLog()
        log.record(ChannelChange(LIVE, "volume", 127, 90))
        assert log.take(0) == []
        assert log.pending == 1
        log.clear()
        assert log.pending == 0
        assert log.take(9) == []


class TestALockedChannelEditIsRefused:
    """Refused, and nothing on the wire.

    The sentence is the easy half. The load-bearing half is that a refusal
    left the unit alone, which is why these assert on the fake's ``dump_log``
    rather than on the words -- a whole-setup write is a large thing to send
    by accident.
    """

    async def test_a_locked_gate_refuses_and_sends_no_dump(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.device.dump_log.clear()
            app.device.received.clear()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == [], "a locked edit reached the unit"
            assert app.device.received == [], "a locked edit sent a frame"
            assert app._editor.channel_pending == 0
            message, refused = said[-1]
            assert f"channel {LIVE + 1} volume not sent" in message
            assert "the write gate is locked" in message
            assert refused

    async def test_the_allow_write_flag_arms_it_from_the_command_line(self):
        app = P2kedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app.device.dump_log) == 1
            assert app.device.read_setup().channel(LIVE).volume == 90

    async def test_an_out_of_range_value_refuses_and_sends_no_dump(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")  # arm the gate: only the range is in the way
            app.device.dump_log.clear()
            app.action_edit_channel(LIVE, "volume", 200)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == [], "an out-of-range edit reached the unit"
            assert app._editor.channel_pending == 0
            message, refused = said[-1]
            assert message == f"channel {LIVE + 1} volume must be 0-127, and 200 is not"
            assert refused

    async def test_a_channel_the_setup_does_not_have_is_refused(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.device.dump_log.clear()
            app.action_edit_channel(32, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == [], (
                "an edit went to a channel that is not there"
            )
            message, refused = said[-1]
            assert "channel 33 is not one of the 32" in message
            assert refused

    async def test_a_dump_that_did_not_fully_decode_is_refused(self, app):
        """Writing it back would drop what p2ked could not read and put
        zeros in its place, which is the silent change this write path is
        built to refuse -- a whole-setup write is the largest shape a
        mistake could take."""

        class HalfRead(DemoDevice):
            def read_setup(self, *, timeout=None):
                dump = super().read_setup(timeout=timeout)
                dump.undecoded = ("2 bytes at 770 are not a self-describing block",)
                return dump

        app.device = HalfRead()
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.device.dump_log.clear()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == [], "an undecodable setup was written back"
            message, refused = said[-1]
            assert "not fully decoded" in message
            assert refused

    async def test_a_write_while_busy_is_refused_rather_than_queued(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = True
            app.action_edit_channel(LIVE, "volume", 90)
            await pilot.pause()
            assert app.device.dump_log == []
            app._busy = False


class TestAChannelEditIsWrittenAndReadBack:
    """The whole operation, against a unit that answers from its own state.

    Read, mutate, send, read again -- and the read-back is what says whether
    the field took, which is the only verification available on a unit that
    ignores a request it cannot serve rather than refusing it.
    """

    async def test_the_edit_reaches_the_unit_as_one_dump(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.device.received.clear()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app.device.dump_log) == 1
            assert app.device.read_setup().channel(LIVE).volume == 90
            message, refused = said[-1]
            assert message == f"channel {LIVE + 1} volume = 90"
            assert not refused
            assert app._editor.channel_pending == 1
            # One frame out, then the read-back request: the write is not a
            # stream of small ones.
            writes = [
                frame
                for frame in app.device.received
                if m.parse(frame).command == m.Command.SETUP_DUMP
            ]
            assert len(writes) == 1

    async def test_the_read_back_is_the_unit_s_report_of_the_field(self, app):
        """The field is read out of the dump the unit sent *after* the write,
        not out of what p2ked believes it sent."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            before = channel_values(app.device.read_setup(), LIVE, ("volume",))
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            after = channel_values(app.device.read_setup(), LIVE, ("volume",))
            assert after == (90,)
            assert after != before
            assert app._changes == [ChannelChange(LIVE, "volume", before[0], after[0])]

    async def test_an_edit_the_unit_ignores_is_not_logged_and_cannot_be_undone(
        self, app
    ):
        """The case the read-back exists for: a unit that takes the frame and
        disregards it, which is what a Proteus does with a request it cannot
        serve rather than refusing it."""

        class Deaf(DemoDevice):
            def send_setup_dump(self, dump, *, timeout=None):
                self.handle(m.parameter_edit(1, 1, device=self.device_id))

        app = P2kedApp(Deaf(), catalog=cat.empty())
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == [], "the edit was sent"
            assert app._editor.channel_pending == 0
            message, refused = said[-1]
            assert "did not take 90" in message
            assert "still reports volume 127" in message
            assert refused
            app._undo_master_edits(1)
            await _wait_for(pilot, lambda: not app._busy)
            assert said[-1] == ("nothing to undo", False)

    async def test_a_broken_wire_is_said_and_logs_nothing(self):
        class Broken(DemoDevice):
            def send_setup_dump(self, dump, *, timeout=None):
                raise TimeoutError("no reply")

        app = P2kedApp(Broken(), catalog=cat.empty())
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app._editor.channel_pending == 0
            assert app.device.dump_log == []
            message, refused = said[-1]
            assert f"channel {LIVE + 1} volume = 90" in message
            assert "no reply" in message
            assert refused


class TestABurstOfNudgesOnOneCellIsCoalesced:
    """Five presses in the time one write takes: none refused, none lost.

    The complaint this answers is a whole one -- "incredibly slow and
    consecutive presses are often lost" -- and its cause is structural
    rather than a mistake. A per-channel edit is a whole-setup write, so
    one nudge is a round trip, and ``_busy`` refused the next key while
    that was in flight.

    The mechanism is unchanged here. What changed is that a press
    arriving during a write is not a refusal but the *next* value the
    same worker sends: one write in flight, gate-checked, read back, and
    one entry on the timeline per value the unit actually received.
    """

    class _Counting(DemoDevice):
        """A fake that counts how many dump writes are in flight at once.

        "Exactly one write in flight" is the load-bearing half of the
        claim -- the mechanism must not change -- and the wire is the
        only place it can be watched from.
        """

        def __init__(self) -> None:
            super().__init__()
            self.inflight = 0
            self.most_at_once = 0

        def send_setup_dump(self, dump, *, timeout=None):
            self.inflight += 1
            self.most_at_once = max(self.most_at_once, self.inflight)
            try:
                super().send_setup_dump(dump, timeout=timeout)
            finally:
                self.inflight -= 1

    class _Holding(_Counting):
        """A fake that stops a dump write on the wire until it is let go.

        The one state an app-level test cannot otherwise reach: the gate
        locked *between* two writes of a burst. ``w`` is live while a
        write is in flight, so the second write has to ask the gate
        again -- and against a fast fake the loop has asked and answered
        before the key that locks it is even dispatched. Holding the
        write makes that gap real.
        """

        def __init__(self) -> None:
            super().__init__()
            self.held = threading.Event()
            self.released = threading.Event()

        def send_setup_dump(self, dump, *, timeout=None):
            self.held.set()
            self.released.wait(timeout=10)  # a forgotten release fails, slowly
            super().send_setup_dump(dump, timeout=timeout)

    async def test_five_presses_end_at_the_last_value_and_refuse_none(self, app):
        """The burst, as fast as the app can be asked for it.

        Channel 6 sits at volume 0 with room above it, and the five
        presses are made with no ``await`` between them -- five
        keypresses inside one whole-dump round trip, which is the case
        the complaint was about.
        """
        device = self._Counting()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")  # arm the gate
            said = _record(app)
            device.dump_log.clear()
            for value in (1, 2, 3, 4, 5):
                app.action_edit_channel(MUTED, "volume", value)
            await _wait_for(pilot, lambda: not app._busy)
            # Not one refusal, and not one "busy": every press counted.
            assert not any(refused for _message, refused in said)
            assert all(message != "busy" for message, _refused in said)
            assert app.device.read_setup().channel(MUTED).volume == 5
            assert len(device.dump_log) == 2, (
                f"{len(device.dump_log)} writes for five presses: the "
                f"intermediate values are not worth a frame each"
            )
            assert device.most_at_once == 1, "two writes were in flight at once"
            # And the log holds the values actually sent, so z is honest.
            assert app._changes == [
                ChannelChange(MUTED, "volume", 0, 1),
                ChannelChange(MUTED, "volume", 1, 5),
            ]
            assert said[-1] == ("channel 6 volume = 5", False)

    async def test_a_minus_after_a_plus_lands_on_the_net_value(self, app):
        """Two up and one back down: the burst nets +1, and the ``-`` is
        a value of its own rather than being swallowed by the ``+``.

        It costs one write, not two, because the last target is the value
        already in flight -- re-sending it would put an entry on the
        timeline for a write that changes nothing.
        """
        device = self._Counting()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            said = _record(app)
            for value in (1, 2, 1):
                app.action_edit_channel(MUTED, "volume", value)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(MUTED).volume == 1
            assert len(device.dump_log) == 1
            assert device.most_at_once == 1
            assert not any(refused for _message, refused in said)
            assert app._changes == [ChannelChange(MUTED, "volume", 0, 1)]

    async def test_the_log_holds_the_values_actually_sent_and_z_walks_them(self, app):
        """One entry per *sent* value -- five presses, two writes, two
        entries -- and ``z`` steps back through the values the unit
        actually held, not through the keys that were pressed."""
        device = self._Counting()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            for value in (1, 2, 3, 4, 5):
                app.action_edit_channel(MUTED, "volume", value)
            await _wait_for(pilot, lambda: not app._busy)
            assert [change.after for change in app._changes] == [1, 5]
            assert app._editor.channel_pending == 2
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(MUTED).volume == 1
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(MUTED).volume == 0
            assert app._changes == []
            assert app._editor.channel_pending == 0

    async def test_a_locked_gate_refuses_every_press_of_a_burst(self, app):
        """The gate is checked at the press, before any slot is filled,
        so a locked one refuses the first key of a burst -- and nothing
        is queued behind the lock for the later ones either."""
        device = self._Counting()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            said = _record(app)
            for value in (1, 2, 3):
                app.action_edit_channel(MUTED, "volume", value)
            await pilot.pause()
            assert device.dump_log == []
            assert device.set_log == []
            assert app._busy is False
            assert app._channel_inflight is None
            assert app._channel_target is None
            assert app._changes == []
            # Three refusals and no write: the sentence is the app's own
            # progress chatter that says "reading ...", so it is the
            # refusals that are counted rather than everything said.
            refused = [message for message, was in said if was]
            assert len(refused) == 3, refused
            for message in refused:
                assert "the write gate is locked" in message

    async def test_a_gate_locked_mid_burst_refuses_the_next_write(self, app):
        """``w`` stays live while a write is in flight, so the burst's
        second write has to ask the gate again -- and a locked one stops
        the burst rather than sending on the first write's authority."""
        device = self._Holding()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            said = _record(app)
            app.action_edit_channel(MUTED, "volume", 40)
            # The write reaches the unit and stops on the wire there.
            await _wait_for(pilot, device.held.is_set)
            # The second press is coalesced into the worker's next write.
            app.action_edit_channel(MUTED, "volume", 50)
            await pilot.press("w")  # locked again, mid-round-trip
            device.released.set()
            await _wait_for(pilot, lambda: not app._busy)
            # One write out, the second refused rather than queued.
            assert len(device.dump_log) == 1
            assert app.device.read_setup().channel(MUTED).volume == 40
            assert app._changes == [ChannelChange(MUTED, "volume", 0, 40)]
            message, refused = said[-1]
            assert "channel 6 volume not sent" in message
            assert "the write gate is locked" in message
            assert refused

    async def test_a_nudge_on_another_cell_during_a_write_is_still_busy(self, app):
        """The one slot holds one cell. A press on a second cell finds
        the wire owned by the first and gets the old refusal, which is
        the whole of what ``_busy`` still guards."""
        device = self._Counting()
        app.device = device
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            said = _record(app)
            device.dump_log.clear()
            app.action_edit_channel(MUTED, "volume", 60)
            # The same channel's other field, and another channel's
            # volume: neither is the cell being written.
            app.action_edit_channel(MUTED, "pan", 90)
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            # The refusals, and not the app's own chatter about reading
            # a bank of names that said the word first.
            refused = [message for message, was in said if was]
            assert refused == ["busy", "busy"]
            assert said[-1] == ("channel 6 volume = 60", False)
            assert len(device.dump_log) == 1
            assert app.device.read_setup().channel(MUTED).volume == 60
            assert app.device.read_setup().channel(MUTED).pan == 64
            assert app.device.read_setup().channel(LIVE).volume == 127


class TestASoundIsWrittenTogether:
    """``rom_id``, ``preset`` and ``bank_map`` in one dump, one entry, one
    undo."""

    async def test_the_three_fields_are_written_and_read_back(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            entry = app.device.read_setup().channel(LIVE)
            before = (entry.preset, entry.bank_map, entry.rom_id)
            app.action_channel_sound(LIVE, rom_id=3, preset=40, bank_map=2)
            await _wait_for(pilot, lambda: not app._busy)
            entry = app.device.read_setup().channel(LIVE)
            assert (entry.rom_id, entry.preset, entry.bank_map) == (3, 40, 2)
            message, refused = said[-1]
            assert (
                message == f"channel {LIVE + 1} sound = preset 40, bank_map 2, rom_id 3"
            )
            assert not refused
            # One entry on the timeline, not three: the unit takes the three
            # fields together, so "undo the sound" is one thing.
            assert app._changes == [
                ChannelChange(LIVE, SOUND_FIELD, before, (40, 2, 3))
            ]
            assert app._editor.channel_pending == 1
            assert len(app.device.dump_log) == 1

    async def test_one_undo_puts_the_whole_sound_back(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            entry = app.device.read_setup().channel(LIVE)
            before = (entry.preset, entry.bank_map, entry.rom_id)
            app.action_channel_sound(LIVE, rom_id=3, preset=40, bank_map=2)
            await _wait_for(pilot, lambda: not app._busy)
            assert before != (40, 2, 3), "the test needs a real change"
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            entry = app.device.read_setup().channel(LIVE)
            assert (entry.preset, entry.bank_map, entry.rom_id) == before
            assert app._editor.channel_pending == 0
            assert app._changes == []

    async def test_the_fields_are_ranged_together(self, app):
        """A sound is aimed at all three or at none: the unit takes them
        together, so a refusal names the first one that is out of range and
        sends none of them."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.action_channel_sound(LIVE, rom_id=3, preset=1000, bank_map=2)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == []
            message, refused = said[-1]
            assert "preset must be 0-895" in message
            assert refused


class TestUndoSendsThePreviousDumpBack:
    """``z`` on a per-channel edit: re-read the dump, put the field back,
    send it, verify the field."""

    async def test_undo_writes_a_dump_with_the_previous_value(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            before = app.device.read_setup().channel(LIVE).volume
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(LIVE).volume == 90
            app.device.received.clear()
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            written = [
                frame
                for frame in app.device.received
                if m.parse(frame).command == m.Command.SETUP_DUMP
            ]
            assert len(written) == 1
            # The frame carries the previous value back: decoding what was
            # sent is the only way to say so, because what the unit holds
            # afterwards is read from its own copy.
            sent = m.parse_setup_dump(m.parse(written[0]))
            assert sent.channel(LIVE).volume == before
            _other_channels_unchanged(sent, app.device.read_setup(), LIVE)
            assert app.device.read_setup().channel(LIVE).volume == before

    async def test_a_dump_the_unit_did_not_take_is_not_claimed_as_undone(self, app):
        """The verify step is not politeness here either: an undo whose
        read-back disagrees is reported, and its entry has already left the
        timeline so the next press does not try the same thing."""

        class Once(DemoDevice):
            """Takes the first dump write and disregards the rest."""

            def send_setup_dump(self, dump, *, timeout=None):
                if self.dump_log:
                    self.handle(m.parameter_edit(1, 1, device=self.device_id))
                    return
                super().send_setup_dump(dump, timeout=timeout)

        app = P2kedApp(Once(), catalog=cat.empty())
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(LIVE).volume == 90
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            message = said[-1][0]
            assert "the unit rejected 1 (channel" in message
            assert app._changes == []
            assert app._editor.channel_pending == 0

    async def test_z_on_the_multi_screen_reverses_a_channel_edit(self, app):
        """The multi screen is where a channel edit is offered, and it binds
        ``z`` for itself for the reason the master editor binds ``w``: a
        modal cuts the app's binding chain."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            # The gate, not the key: this screen does not bind `w` yet, and
            # the app's own is dead behind a modal.
            app._gate.toggle()
            before = app.device.read_setup().channel(LIVE).volume
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(LIVE).volume == 90
            app.screen.action_undo()
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(LIVE).volume == before
            assert app._changes == []


class TestOneTimelineOverBothKinds:
    """``z`` reverses whichever came last, so a master edit and a channel
    edit share the list rather than one log each."""

    async def test_the_newest_of_the_two_is_undone_first(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            # An old master edit, then a channel edit.
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app._changes) == 2
            # First `z`: the channel edit, because it came last.
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.read_setup().channel(LIVE).volume == 127
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 5
            assert app._editor.log.pending == 1
            # ... and the second takes the master edit.
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 0
            assert app._editor.log.pending == 0
            assert app._changes == []

    async def test_the_channel_edit_can_come_first_and_the_master_second(self, app):
        """The other order, so "newest first" is not passing by the accident
        of which kind happened to be made first."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app._changes) == 2
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 0
            assert app.device.read_setup().channel(LIVE).volume == 90
            assert app._editor.channel_pending == 1
            assert len(app._changes) == 1

    async def test_Z_takes_both_kinds_newest_first(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            app.action_edit_channel(QUIET, "pan", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app._changes) == 3
            await pilot.press("Z")
            await _wait_for(pilot, lambda: not app._busy)
            entry = app.device.read_setup()
            assert entry.channel(LIVE).volume == 127
            assert entry.channel(QUIET).pan == 64
            assert app.device.parameters[m.Parameter.MASTER_TRANSPOSE] == 0
            assert app._changes == []
            assert app._editor.log.pending == 0
            assert app._editor.channel_pending == 0

    async def test_z_says_which_of_the_two_it_took(self, app):
        """The sentence has to name the kind, because a dump write and a
        parameter edit are not the same thing to have done to a unit."""
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app._apply_master_edit(m.Parameter.MASTER_TRANSPOSE, 5)
            await _wait_for(pilot, lambda: not app._busy)
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            message, refused = said[-1]
            assert message == f"undid channel {LIVE + 1} volume"
            assert not refused
            await pilot.press("z")
            await _wait_for(pilot, lambda: not app._busy)
            assert said[-1] == ("undid 1 edit", False)

    async def test_a_refused_restore_does_not_stop_the_other_one(self):
        """Per-entry failure: the batch carries on past a refusal.

        One restore lands and the unit refuses the other, which is a
        read-back that disagrees rather than an exception. An undo that
        stopped at the first failure would leave the second entry
        applied and a sentence about one entry; each is verified on its
        own, so the one that took is claimed and the one that did not
        is named.
        """

        class HalfAwake(DemoDevice):
            """A unit that takes one restore and then stops listening.

            Armed by the test once both edits have landed, so the first
            restore of the batch goes through and the second finds a
            unit that no longer answers.
            """

            armed = False
            since_armed = 0

            def send_setup_dump(self, dump, *, timeout=None):
                if self.armed:
                    self.since_armed += 1
                    if self.since_armed > 1:
                        return
                super().send_setup_dump(dump, timeout=timeout)

        app = P2kedApp(HalfAwake(), catalog=cat.empty())
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            app.action_edit_channel(QUIET, "pan", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app._changes) == 2
            app.device.armed = True
            await pilot.press("Z")
            await _wait_for(pilot, lambda: not app._busy)
            message = said[-1][0]
            assert "undid 1 channel edit" in message
            assert "the unit rejected 1 (channel" in message
            entry = app.device.read_setup()
            assert entry.channel(QUIET).pan == 64, "the first one landed"
            assert entry.channel(LIVE).volume == 90, "the second did not"
            # Both entries left the timeline: a refused write is not one
            # the next press gets to try again.
            assert app._changes == []
            assert app._editor.channel_pending == 0


class TestTheDumpFrameOnTheWire:
    """What the bridge does with a frame this size.

    A dump frame is ~1 KB, and the question worth answering is what the
    transport does with it. The answer is one ``send_message`` call with the
    whole thing in it: ``_send`` is the same method every other message
    goes through, and nothing in this path splits or truncates.
    """

    class _Out:
        """A MIDI output that records instead of transmitting."""

        def __init__(self):
            self.sent = []

        def send_message(self, message):
            self.sent.append(list(message))

    class _In:
        def get_message(self):
            return None

        def ignore_types(self, **_kwargs):
            pass

    def _bridge(self):
        out = self._Out()
        return ProteusBridge(self._In(), out, device_id=7, timeout=0.01), out

    def test_one_frame_with_the_whole_dump_in_it(self):
        bridge, out = self._bridge()
        dump = DemoDevice().read_setup()
        written = mutate_channel(dump, LIVE, {"volume": 90})
        bridge.send_setup_dump(written)
        assert len(out.sent) == 1, "the dump was sent as more than one message"
        frame = bytes(out.sent[0])
        assert frame == m.encode_setup_dump(written, device=7)
        assert len(frame) > 500, f"a dump frame of {len(frame)} bytes is small"
        assert m.parse(frame).command == m.Command.SETUP_DUMP

    def test_the_device_id_is_the_bridges_own(self):
        bridge, out = self._bridge()
        bridge.send_setup_dump(DemoDevice().read_setup())
        assert m.parse(bytes(out.sent[0])).device == 7

    def test_it_is_the_setup_dump_command_and_not_a_parameter_edit(self):
        """The other look this could have had -- 362 parameter edits to
        numbers nobody named -- is what it refuses to be: no per-channel
        parameter ID is invented."""
        bridge, out = self._bridge()
        bridge.send_setup_dump(DemoDevice().read_setup())
        assert {m.parse(bytes(sent)).command for sent in out.sent} == {
            m.Command.SETUP_DUMP
        }


class TestTheScreenHasAWayToSayIt:
    """The seam a screen with a channel row builds on.

    Without a ``say`` the sentence still reaches the app's own status line,
    which is the record; with one it lands where the user is looking.
    """

    async def test_the_app_records_it_with_no_screen_line_to_write_to(self, app):
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert said[-1] == (f"channel {LIVE + 1} volume = 90", False)

    async def test_a_screen_that_answers_channel_result_is_told(self, app):
        """The signature the multi screen's ``channel_result`` is expected
        to answer, and the one its ``say`` is too."""

        class Row(MultiScreen):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.said = []
                self.results = []

            def say(self, message, *, refused=False):
                self.said.append((message, refused))

            def channel_result(self, ok, message, change):
                self.results.append((ok, change))

        screen = Row(app.device.read_setup(), app.catalog, None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.push_screen(screen)
            await pilot.pause()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert [ok for ok, _change in screen.results] == [True]
            assert screen.results[0][1] == ChannelChange(LIVE, "volume", 127, 90)
            assert screen.said[-1] == (f"channel {LIVE + 1} volume = 90", False)

    async def test_an_undo_tells_a_screen_that_answers_channel_undone(self, app):
        seen = []

        class Row(MultiScreen):
            def channel_undone(self, changes):
                seen.append(changes)

        screen = Row(app.device.read_setup(), app.catalog, None)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("w")
            app.push_screen(screen)
            await pilot.pause()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            app._undo_master_edits(1)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(seen) == 1
            assert [ok for _change, ok in seen[0]] == [True]
            assert seen[0][0][0] == ChannelChange(LIVE, "volume", 127, 90)

    async def test_the_status_line_is_written_either_way(self, app):
        """The app's own line is the record, and a modal's is the copy the
        user reads. Both halves of that are what :meth:`_say_edit` does."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await _wait_for(pilot, lambda: isinstance(app.screen, MultiScreen))
            app._gate.toggle()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert str(app.query_one("#status", Static).visual) == (
                f"channel {LIVE + 1} volume = 90"
            )
