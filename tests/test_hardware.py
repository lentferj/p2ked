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

"""Tests against a real Proteus 2000. **Opt-in: see :mod:`tests.conftest`.**

Everything else in this suite runs against :mod:`p2ked.demo`, which is the
point of it -- the suite is fast, needs no hardware, and passes on a machine
with no MIDI stack at all. That is also its limit: a demo device agrees with
whatever p2ked believes, so every offset below the API surface was only ever
checked against p2ked's own transcription of E-MU's documents, and the
sibling rxved shipped a wrong device-ID conversion with a green suite for
months (CLAUDE.md, "There is no hardware").

This file is the other half. It asks the machine, and the machine's answer
is the one that cannot be transcribed wrong:

* **Read-only, structural.** The dump's declared counts against the block
  table p2ked builds, every master value agreed between the dump and its own
  parameter read (the RESOLUTION_NOTES §10 check, now repeatable), the
  channel block's shape and the channel values that both documents agree on.
* **The per-channel probe**, read-only, so TODO 47's answer is a command
  rather than a manual session.
* **One write, read back and restored.** FX bypass, because it is one master
  parameter, immediately audible going and coming (the effects drop out and
  return), and trivial to put back.

**What these tests deliberately do not do.** They never assert on a preset,
instrument or riff *name*: E-MU's ROM contents are not this project's to
redistribute, and a fixture naming them would be a copy of them (CLAUDE.md).
They never *select* a preset -- that changes what plays, and it stays behind
its own confirmation in the app, which is not something a test should bypass.
They never assert a range the two documents disagree about (§12): ROM IDs,
the arpeggiator and bank-map fields are not asserted here, because the spec
prints "?" for the first and neither document publishes the others.

Where the app's write gate is: **in the app.** The fixture holds the bridge,
not the TUI, because a test that armed the gate through keypresses would be
testing the pilot harness twice. The gate's logic is tested in the ordinary
suite; what is tested here is the wire -- that a Parameter Value Edit sent by
this code is the one the unit performs.
"""

from typing import cast

import pytest

from p2k import messages as m
from p2ked.masteredit import MASTER_BY_ID, probe_channel_ids

#: How long each probe read waits before counting a parameter ID as silent.
#: A Proteus answers a request it cannot serve with *silence*, so an ID
#: outside the real range costs the whole timeout -- and the default hinted
#: range is 362 IDs wide. Half a second each is a few minutes worst case on
#: a unit that ignores most of them, which is a hardware session's price.
PROBE_TIMEOUT = 0.5


class TestHardwareStructuralReads:
    """The reads every screen depends on, at their declared shapes.

    Structural assertions only: a count is right, a value is inside a range
    both documents print, the connection learned a device ID rather than
    broadcasting. A name would be E-MU's ROM and is not asserted on
    (CLAUDE.md).
    """

    def test_the_connection_learned_a_device_id(self, unit):
        """Not the broadcast ID: a caller that forgot to set the ID must not
        work by accident on one unit and fail on the next."""
        assert unit.device_id != m.BROADCAST_DEVICE, (
            "the bridge is still addressing the broadcast ID; the unit "
            "answered one identity request and its ID was not adopted"
        )

    def test_the_configuration_agrees_with_the_rom_table(self, unit):
        """One Configuration request, against the table's shape.

        The unit says how many SIMMs it carries and how big each is; a
        Proteus 2000 holds four. Whether each reported SIMM ID *is* the
        table's Bank Select MSB is the unestablished hypothesis CLAUDE.md
        names -- so this test asserts the structure (bounded, unique, at
        most four) and *prints* the answer for a human to record, rather
        than asserting a mapping p2ked has not earned.
        """
        config = unit.hardware_config()
        assert config.user_presets > 0, (
            f"the unit reported {config.user_presets} user presets"
        )
        assert len(config.simms) <= 4, (
            f"the unit reported {len(config.simms)} SIMMs; a Proteus 2000 holds four"
        )
        simm_ids = [simm_id for simm_id, _presets, _instruments in config.simms]
        assert len(set(simm_ids)) == len(simm_ids), (
            f"duplicate SIMM IDs in the configuration answer: {simm_ids}"
        )
        for simm_id, presets, instruments in config.simms:
            assert 0 <= simm_id <= 127, f"SIMM ID {simm_id} is not a byte"
            assert presets > 0, f"SIMM {simm_id} holds {presets} presets"
            assert instruments > 0, f"SIMM {simm_id} holds {instruments} instruments"
        print(
            "\nconfiguration: "
            f"{config.user_presets} user presets, SIMMs "
            + ", ".join(
                f"{simm_id}:{presets}p/{instruments}i"
                for simm_id, presets, instruments in config.simms
            )
            + "\n-- record these against the ROM table (docs/TODO item 9 "
            "and the SIMM-ID hypothesis in CLAUDE.md) rather than asserting "
            "them: the mapping is not established yet"
        )

    def test_the_dump_declares_the_blocks_p2ked_builds(self, unit):
        """The dump's own header counts, against :data:`MASTER_BLOCKS`.

        The parse trusts the header it is given; a firmware that shipped an
        extra master block would leave p2ked silently short by that block's
        values, which is exactly the failure a structural check catches.
        """
        dump = unit.read_setup()
        assert len(dump.header_counts) == len(m.MASTER_BLOCKS), (
            f"the dump declares {len(dump.header_counts)} master-block "
            f"counts, p2ked builds {len(m.MASTER_BLOCKS)}"
        )
        for (label, ids), declared in zip(
            m.MASTER_BLOCKS, dump.header_counts, strict=True
        ):
            assert declared == len(ids), (
                f"the {label} block came back {declared} values wide, "
                f"p2ked expects {len(ids)}"
            )
        assert dump.master, (
            "the dump's master block did not decode (empty) -- its own "
            "arithmetic did not add up; that is a failure, not a layout "
            "p2ked gets to leave half-decoded"
        )

    def test_the_dump_and_the_parameter_reads_agree(self, unit):
        """Every master value, two ways: in the dump, and one by one.

        This is RESOLUTION_NOTES §10's agreement, which was measured once
        by hand. It is the check that catches the divergence the whole
        apparatus is built to survive: two readings of the same value
        disagreeing is the only evidence a wrong block table ever produces.
        """
        dump = unit.read_setup()
        for parameter_id, dumped in sorted(dump.master.items()):
            read = unit.read_parameter(parameter_id)
            assert read == dumped, (
                f"parameter {parameter_id} reads {read} on its own but the "
                f"dump carries {dumped}"
            )

    def test_the_channel_block_holds_thirty_two_rows_of_nine(self, unit):
        dump = unit.read_setup()
        assert dump.channel_count == 32
        assert dump.parameters_per_channel == len(m.CHANNEL_PARAMETERS) == 9
        assert len(dump.channels) == 32

    def test_channel_values_are_inside_the_ranges_both_documents_print(
        self, unit
    ) -> None:
        """Volume, pan and the two switches -- and nothing else.

        §12 records where the documents disagree: the spec prints ``?`` for
        a channel's ROM ID range, and neither document publishes the
        arpeggiator or bank-map fields. Asserting those would be pinning
        p2ked's own guess to a unit and calling the agreement proof.
        """
        dump = unit.read_setup()
        for entry in dump.channels:
            where = f"channel {entry.channel_display}"
            assert 0 <= entry.volume <= 127, f"{where} volume is {entry.volume}"
            assert 0 <= entry.pan <= 127, f"{where} pan is {entry.pan}"
            assert entry.enable in (0, 1), f"{where} enable is {entry.enable}"
            assert entry.receive_program_change in (0, 1), (
                f"{where} receives Program Change as {entry.receive_program_change}"
            )


class TestHardwareTheChannelProbe:
    """:func:`~p2ked.masteredit.probe_channel_ids`, read-only.

    The per-channel parameter IDs are TODO 47: not in any document to hand,
    so p2ked refuses to invent them. This is the read-only way to establish
    them -- the test asserts the probe only ever asks, and *prints* what
    answered for the human running it to record in TODO item 47. It does not
    match the answers against the dump's nine fields itself: a value that
    agrees once is not a mapping, and that finding is a session's to make,
    not an assignment a test gets to automate.
    """

    def test_the_probe_only_reads_and_reports_what_answers(self, unit) -> None:
        asked: list = []

        def read(parameter_id: int):
            asked.append(parameter_id)
            try:
                return unit.read_parameter(parameter_id, timeout=PROBE_TIMEOUT)
            except TimeoutError:
                # Silence is an answer of a kind: this ID is not served.
                return None

        result = probe_channel_ids(read)
        low = cast(int, result["low"])
        high = cast(int, result["high"])
        answered = cast(list, result["answered"])

        assert low == 662 and high == 1024, f"the hinted range moved: {low}-{high}"
        assert set(answered) <= set(range(low, high))
        assert len(asked) == high - low, (
            f"the probe asked for {len(asked)} IDs, the range holds {high - low}"
        )

        shown = ", ".join(str(parameter_id) for parameter_id in answered)
        if answered:
            values = ", ".join(
                f"{parameter_id}={read(parameter_id)!r}" for parameter_id in answered
            )
            print(
                f"\nprobe {low}-{high}: {len(answered)} answered: {shown}\n"
                f"values re-read: {values}\n"
                "-- establish which answering ID is which of the dump's nine "
                "fields by editing one on the front panel and re-reading, "
                "then record the mapping in docs/TODO item 47. Do not let a "
                "test make that assignment."
            )
        else:
            print(
                f"\nprobe {low}-{high}: nothing answered. The range is a "
                "hint (the block after the master arpeggiator at 641-661), "
                "not a finding -- widen it in a session and record the "
                "answer in docs/TODO item 47."
            )


class TestHardwareOneWrite:
    """The first write p2ked sends a unit: FX bypass, read back, restored.

    The edit screen's apparatus -- gate, undo log, read-back -- is the app's,
    and is tested in the ordinary suite against the demo. Here the question
    is the wire: does a Parameter Value Edit from this code change the value
    it names on the unit? A DT1 is unacknowledged, so the only evidence is
    the read-back; a disagreement is the unit declining the write, or a wrong
    parameter ID, and both are worth failing a session over.

    The write is audible for about a second -- the effects drop out and come
    back -- and is put back in a ``finally`` whichever way the assertion
    goes, because a hardware session that leaves the unit changed is worse
    than one that never wrote.
    """

    def test_an_master_fx_write_is_read_back_and_restored(self, unit) -> None:
        bypass = MASTER_BY_ID[m.Parameter.MASTER_FX_BYPASS]
        before = unit.read_parameter(bypass.parameter_id)
        if before not in (0, 1):
            pytest.skip(
                f"the unit reports FX bypass as {before}, which is neither "
                "on nor bypassed -- that is a finding to record, not a "
                "state to flip and flip back"
            )
        target = 1 - before
        try:
            unit.set_parameter(bypass.parameter_id, target)
            landed = unit.read_parameter(bypass.parameter_id)
            assert landed == target, (
                f"wrote FX bypass {target} ({bypass.choices[target]}), the "
                f"unit reports {landed}. A DT1 is unacknowledged: the unit "
                "declined it, or the parameter ID is wrong"
            )
        finally:
            if unit.read_parameter(bypass.parameter_id) != before:
                unit.set_parameter(bypass.parameter_id, before)
        assert unit.read_parameter(bypass.parameter_id) == before, (
            "the FX bypass was not put back; set it back on the front panel"
        )
