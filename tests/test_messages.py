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

"""The wire format.

**These tests prove self-consistency, not correctness.** No Proteus has seen
any of these bytes. A test suite written from the same reading of the same
document as the code will agree with it whether that reading is right or
wrong -- which is exactly how the sibling rxved's device-ID bug survived a
green suite for months. What these do catch is the class of mistake that is
internally visible: an encoder and decoder that disagree, a range that is
not enforced, a sign that is lost.
"""

import pytest

from p2k import messages as m
from p2ked.demo import DemoDevice


class TestFourteenBit:
    """Values are two 7-bit bytes, LEAST significant first.

    The byte order is the point. A pair read the wrong way round is still a
    valid number and usually a plausible one, so nothing downstream can
    notice; only a test at this level can.
    """

    def test_lsb_comes_first(self):
        assert m.pack14(1) == (1, 0)
        assert m.pack14(128) == (0, 1)

    def test_round_trip(self):
        for value in (0, 1, 127, 128, 1000, 0x3FFF):
            assert m.unpack14(*m.pack14(value)) == value

    def test_the_top_of_the_range_fits(self):
        assert m.pack14(0x3FFF) == (0x7F, 0x7F)

    def test_out_of_range_is_refused(self):
        for value in (-1, 0x4000):
            with pytest.raises(m.ProtocolError):
                m.pack14(value)

    def test_a_byte_with_bit_seven_set_is_refused(self):
        with pytest.raises(m.ProtocolError):
            m.unpack14(0x80, 0)


class TestSignedValues:
    """Parameters can be negative, and the encoding is two's complement."""

    def test_round_trip(self):
        for value in (-8192, -1000, -1, 0, 1, 8191):
            assert m.unpack14_signed(*m.pack14_signed(value)) == value

    def test_minus_one_is_all_ones(self):
        assert m.pack14_signed(-1) == (0x7F, 0x7F)

    def test_reading_signed_as_unsigned_is_the_bug_this_prevents(self):
        """-1 read unsigned is 16383, a number any range check accepts."""
        packed = m.pack14_signed(-1)
        assert m.unpack14(*packed) == 16383
        assert m.unpack14_signed(*packed) == -1

    def test_out_of_range_is_refused(self):
        for value in (-8193, 8192):
            with pytest.raises(m.ProtocolError):
                m.pack14_signed(value)


class TestDeviceId:
    """No arithmetic here, deliberately -- see messages.device_byte."""

    def test_the_panel_number_is_the_wire_number(self):
        for value in (0, 1, 0x7E):
            assert m.device_byte(value) == value

    def test_broadcast_is_allowed(self):
        assert m.device_byte(m.BROADCAST_DEVICE) == 0x7F

    def test_out_of_range_is_refused_not_masked(self):
        """Masking would turn 128 into 0 and address the wrong unit."""
        for value in (-1, 128, 200):
            with pytest.raises(m.ProtocolError):
                m.device_byte(value)


class TestFrames:
    def test_the_header_is_the_documented_one(self):
        frame = m.frame(m.Command.CONFIGURATION_REQUEST, device=3)
        assert frame[:6] == bytes([0xF0, 0x18, 0x0F, 0x03, 0x55, 0x0A])
        assert frame[-1] == 0xF7

    def test_a_payload_byte_with_bit_seven_set_is_refused(self):
        with pytest.raises(m.ProtocolError):
            m.frame(m.Command.CONFIGURATION, [0x80])

    def test_parse_round_trips_a_frame(self):
        frame = m.frame(0x0B, [1, 2, 3], device=5)
        packet = m.parse(frame)
        assert packet.device == 5
        assert packet.command == 0x0B
        assert packet.payload == bytes([1, 2, 3])

    def test_foreign_traffic_is_none_not_an_error(self):
        """A shared port carries other devices' messages. Not errors."""
        assert m.parse([0xF0, 0x41, 0x10, 0x00, 0x10, 0x12, 0xF7]) is None
        assert m.parse([0x90, 0x40, 0x7F]) is None
        assert m.parse([]) is None

    def test_a_non_editor_emu_message_is_ignored(self):
        """Without the 55h designator it is not ours to parse."""
        frame = bytes([0xF0, 0x18, 0x0F, 0x00, 0x44, 0x01, 0xF7])
        assert m.parse(frame) is None


class TestIdentity:
    def test_a_request_is_not_an_emu_message_at_all(self):
        assert m.identity_request(0x7F) == bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])

    def test_our_own_request_is_not_mistaken_for_a_reply(self):
        """The sub-ID differs, which is what defeats a MIDI-Thru loop."""
        assert m.identity_reply_fields(m.identity_request(0x7F)) is None

    def test_a_reply_is_decoded(self):
        reply = bytes(
            [
                0xF0,
                0x7E,
                0x05,
                0x06,
                0x02,
                0x18,
                0x0F,
                0x00,
                0x02,
                0x00,
                0x01,
                0x00,
                0x00,
                0x00,
                0xF7,
            ]
        )
        fields = m.identity_reply_fields(reply)
        assert fields["device"] == 5
        assert fields["is_emu"] is True


class TestNames:
    def test_names_are_sixteen_bytes_space_padded(self):
        assert len(m.encode_name("short")) == m.NAME_LEN

    def test_a_long_name_is_truncated_not_refused(self):
        assert len(m.encode_name("x" * 40)) == m.NAME_LEN

    def test_only_trailing_space_is_stripped(self):
        """A name may legitimately begin with a space."""
        assert m.decode_name(m.encode_name(" Lead")) == " Lead"

    def test_round_trip(self):
        assert m.decode_name(m.encode_name("Velvet Bell")) == "Velvet Bell"

    def test_a_name_request_carries_type_number_and_rom(self):
        frame = m.name_request(m.ObjectType.PRESET, 133, 7, device=0)
        packet = m.parse(frame)
        assert packet.command == m.Command.GENERIC_NAME_REQUEST
        assert packet.payload[0] == m.ObjectType.PRESET
        assert m.unpack14(packet.payload[1], packet.payload[2]) == 133
        assert m.unpack14(packet.payload[3], packet.payload[4]) == 7

    def test_parsing_a_name_reply(self):
        payload = [
            m.ObjectType.PRESET,
            *m.pack14(133),
            *m.pack14(7),
            *m.encode_name("Woven Bell"),
        ]
        reply = m.parse_name(m.parse(m.frame(m.Command.GENERIC_NAME, payload)))
        assert (reply.number, reply.rom_id, reply.name) == (133, 7, "Woven Bell")

    def test_a_short_name_message_is_refused(self):
        with pytest.raises(m.ProtocolError):
            m.parse_name(m.parse(m.frame(m.Command.GENERIC_NAME, [1, 0, 0])))


class TestConfiguration:
    """The message that tells p2ked what ROMs are fitted."""

    def _payload(self, user_presets, simms, *, per_simm=6, general=None):
        general = general if general is not None else list(m.pack14(user_presets))
        payload = [len(general), *general, len(simms), per_simm]
        for simm_id, presets, instruments in simms:
            chunk = [*m.pack14(simm_id), *m.pack14(presets), *m.pack14(instruments)]
            chunk += [0] * (per_simm - len(chunk))
            payload += chunk
        return payload

    def test_it_decodes(self):
        payload = self._payload(512, [(4, 1024, 256), (7, 512, 128)])
        config = m.parse_config(m.parse(m.frame(m.Command.CONFIGURATION, payload)))
        assert config.user_presets == 512
        assert len(config.simms) == 2
        assert config.simms[0].simm_id == 4
        assert config.simms[1].presets == 512

    def test_the_declared_lengths_are_obeyed_not_assumed(self):
        """A longer general block must not shift every SIMM by a byte.

        The whole point of reading the declared lengths: a future model that
        adds a field there would otherwise produce preset counts that are
        wrong and still plausible.
        """
        payload = self._payload(
            512, [(4, 1024, 256)], general=[*m.pack14(512), 9, 9]
        )  # two extra bytes
        config = m.parse_config(m.parse(m.frame(m.Command.CONFIGURATION, payload)))
        assert config.user_presets == 512
        assert config.simms[0] == m.SimmInfo(4, 1024, 256)

    def test_a_longer_per_simm_block_is_obeyed_too(self):
        payload = self._payload(512, [(4, 1024, 256), (7, 512, 128)], per_simm=8)
        config = m.parse_config(m.parse(m.frame(m.Command.CONFIGURATION, payload)))
        assert [s.simm_id for s in config.simms] == [4, 7]

    def test_a_truncated_response_is_refused(self):
        payload = self._payload(512, [(4, 1024, 256)])[:-3]
        with pytest.raises(m.ProtocolError):
            m.parse_config(m.parse(m.frame(m.Command.CONFIGURATION, payload)))

    def test_no_simms_is_a_valid_answer(self):
        config = m.parse_config(
            m.parse(m.frame(m.Command.CONFIGURATION, self._payload(512, [])))
        )
        assert config.simms == ()

    def test_the_wrong_command_is_refused(self):
        with pytest.raises(m.ProtocolError):
            m.parse_config(m.parse(m.frame(m.Command.GENERIC_NAME, [0])))


class TestChecksum:
    def test_it_is_an_xor(self):
        assert m.checksum([0x01, 0x02]) == 0x03
        assert m.checksum([0x7F, 0x7F]) == 0x00

    def test_it_stays_inside_seven_bits(self):
        assert 0 <= m.checksum(range(0, 128)) <= 0x7F


class TestSetupDumpLayout:
    """The Setup Dump's master blocks.

    Unlike everything above, the *table* these exercise was not read out of
    a document -- there is no document that gets it right. It was derived on
    2026-09-12 by reading each of the 82 master values back from a Proteus
    2000 as an individual parameter and matching it against the dump; all 82
    agreed. See docs/RESOLUTION_NOTES.md §10.

    That does not make these tests evidence of correctness either. They are
    built from the same table as the parser, and prove what the tests above
    prove: that the pieces agree with each other, that the declared counts
    are obeyed rather than assumed, and that a dump which does not add up is
    refused rather than decoded into plausible nonsense.
    """

    #: Invented, and deliberately not all zero: a flat payload makes the
    #: channel block's structural search ambiguous.
    FILLER = {257: 120, 264: 2, 385: 2, 513: 1, 520: 1, 139: 8, 140: 8}

    def _payload(self, *, counts=None, master=None, trailing=True, channels=32):
        counts = counts or tuple(len(ids) for _l, ids in m.MASTER_BLOCKS)
        values = dict(self.FILLER)
        values.update(master or {})
        per = len(m.CHANNEL_PARAMETERS)
        data = []
        for count in tuple(counts) + (channels, per):
            data.extend(m.pack14(count))
        data.extend(m.encode_name("Invented Setup"))
        for (_label, ids), count in zip(m.MASTER_BLOCKS, counts):
            for index in range(count):
                key = ids[index] if index < len(ids) else None
                data.extend(m.pack14_signed(values.get(key, 0)))
        for channel in range(channels):
            # Varied on purpose. A block where every channel is identical
            # makes a shifted window fit just as well, and the parser
            # rightly refuses an ambiguous dump; a real one is not that
            # flat either.
            fields = {
                "preset": channel * 7,
                "volume": 127,
                "pan": 64,
                "mix_output": 1,
                "arp": 0,
                "enable": 1,
                "bank_map": 0,
                "receive_program_change": 1,
                "rom_id": 0,
            }
            for field, _low, _high in m.CHANNEL_PARAMETERS:
                data.extend(m.pack14_signed(fields[field]))
        if trailing:
            data.extend(m.pack14(24))
            data.extend(m.pack14(2))
            for trigger in range(24):
                data.extend(m.pack14_signed(36 + trigger))
                data.extend(m.pack14_signed(0))
            data.extend(m.pack14(16))
            data.extend(m.pack14(3))
            for part in range(16):
                data.extend(m.pack14_signed(-1))
                data.extend(m.pack14_signed(0))
                data.extend(m.pack14_signed(part // 4 + 1))
        return data

    def _parse(self, **kwargs):
        frame = m.frame(m.Command.SETUP_DUMP, self._payload(**kwargs))
        return m.parse_setup_dump(m.parse(frame))

    def test_the_header_arithmetic_lands_on_the_channel_block(self):
        """The two independent answers must be the same one.

        The channel block is found by structural search; the header's five
        block counts predict where it starts. That they agree is what makes
        reading the master blocks positionally legitimate at all.
        """
        dump = self._parse()
        declared = sum(len(ids) for _label, ids in m.MASTER_BLOCKS)
        assert dump.offset == 30 + 2 * declared
        assert dump.undecoded == ()

    def test_every_master_parameter_is_decoded(self):
        dump = self._parse()
        expected = {pid for _label, ids in m.MASTER_BLOCKS for pid in ids}
        assert set(dump.master) == expected
        assert dump.clock_tempo == 120
        assert dump.bend_range == 2
        assert dump.midi_mode == m.MidiMode.MULTI
        assert dump.basic_channel == 8

    def test_reserved_ids_are_absent_from_the_blocks(self):
        """The dump omits the IDs the specification marks reserved.

        This is the whole reason the general block is 20 entries and not
        the 23 its ID span covers. Putting one back shifts every value
        after it onto the wrong parameter, which no range check would
        catch, so the omission is asserted rather than left to a comment.
        """
        present = {pid for _label, ids in m.MASTER_BLOCKS for pid in ids}
        for reserved in (256, 261, 262, 263, 384, 387, 389, 390, 512, 640):
            assert reserved not in present

    def test_unnamed_ids_are_decoded_but_not_named(self):
        """270, 279 and 660 are in the dump and in no published list.

        They are decoded -- a value at a known ID is a fact -- and left
        unnamed, because naming a number nobody has documented turns a gap
        into a claim.
        """
        dump = self._parse()
        for unnamed in (270, 279, 660):
            assert unnamed in dump.master
            assert unnamed not in m.MASTER_PARAMETER_NAMES

    def test_an_absent_parameter_reads_none_not_zero(self):
        dump = self._parse()
        assert dump.parameter(261) is None
        assert dump.parameter(m.Parameter.MASTER_TRANSPOSE) == 0

    def test_a_block_that_declares_a_different_count_is_skipped_alone(self):
        """One firmware's extra parameter should cost one block.

        Decoding it anyway would slide every value in that block onto its
        neighbour's ID; abandoning the whole dump would lose the four
        blocks that are still fine.
        """
        counts = list(len(ids) for _l, ids in m.MASTER_BLOCKS)
        counts[1] += 1  # master MIDI grew by one
        dump = self._parse(counts=counts)
        assert 385 not in dump.master  # the block that grew
        assert 257 in dump.master  # the ones that did not
        assert 513 in dump.master
        assert len(dump.undecoded) == 1
        assert "master MIDI" in dump.undecoded[0]

    def test_a_header_that_does_not_add_up_decodes_no_master_values(self):
        """Better empty than plausibly wrong.

        A count that is too small by one leaves the channel block where the
        search finds it but every master value one slot out -- all of them
        in range, none of them right.
        """
        # The real block lengths, but a lying header: the channel block
        # stays where the search finds it and only the arithmetic breaks.
        data = self._payload()
        data[0:2] = m.pack14(len(m.MASTER_BLOCKS[0][1]) - 1)
        dump = m.parse_setup_dump(m.parse(m.frame(m.Command.SETUP_DUMP, data)))
        assert dump.master == {}
        assert dump.undecoded and "not decoded" in dump.undecoded[0]

    def test_the_trailing_blocks_describe_themselves(self):
        dump = self._parse()
        labels = [block.label for block in dump.trailing]
        assert labels == ["BEATS triggers", "BEATS parts"]
        triggers = dump.trailing_block("BEATS triggers")
        assert triggers.parameter_ids == (160, 161)
        assert len(triggers.rows) == 24
        assert triggers.rows[0] == (36, 0)
        parts = dump.trailing_block("BEATS parts")
        assert parts.parameter_ids == (164, 165, 166)
        assert [row[2] for row in parts.rows[:5]] == [1, 1, 1, 1, 2]

    def test_a_trailing_block_of_an_unknown_shape_is_kept_unidentified(self):
        """Reporting a shape nobody recognises is how the next one is found."""
        data = self._payload(trailing=False)
        data.extend(m.pack14(3))
        data.extend(m.pack14(2))
        for row in range(3):
            data.extend(m.pack14_signed(row))
            data.extend(m.pack14_signed(0))
        dump = m.parse_setup_dump(m.parse(m.frame(m.Command.SETUP_DUMP, data)))
        assert len(dump.trailing) == 1
        block = dump.trailing[0]
        assert not block.identified
        assert "3x2" in block.label
        assert len(block.rows) == 3

    def test_a_dump_that_stops_at_the_channel_block_is_still_read(self):
        """The trailing region is not in the header, so it is not required."""
        dump = self._parse(trailing=False)
        assert dump.trailing == ()
        assert dump.undecoded == ()
        assert len(dump.master) == sum(len(ids) for _label, ids in m.MASTER_BLOCKS)


class TestSetupDumpEncoder:
    """Writing a setup back, and the round trip that proves it can be.

    **What the round trip establishes is self-consistency, not
    correctness**, like every other test in this file. What it does
    establish is narrow and still worth having: a parser and an encoder
    that agree with each other, and a re-encode that produces the
    identical bytes. That is what the next feature rests on -- read a
    dump, change one per-channel value, write the whole setup back -- and
    a dump that came back one value different would be a setup silently
    corrupted by an edit, with nothing on the cable to say so.

    Nothing here has been near a unit. An incoming Setup Dump is a
    documented receive path -- "The command stations still receive and
    understand the old setup dump and will transmit one if explicitly
    requested to do so via sysex" (spec p. 29) -- and p2ked has never sent
    one. docs/RESOLUTION_NOTES.md §12 records both that and the two
    caveats that follow from it.
    """

    #: Neither 0 nor the broadcast ID, so a message that forgot to address
    #: itself does not pass by luck.
    DEVICE = 0x0B

    #: Invented master values, and deliberately not all zero: a flat
    #: payload leaves the parser's structural search with nothing to
    #: discriminate between offsets, and it rightly refuses such a dump.
    #: The negative ones do most of the discriminating -- a negative value
    #: is out of range for eight of the nine per-channel parameters, so
    #: the master region cannot masquerade as a channel block. It is also
    #: what a unit somebody has played looks like: a transpose, a fine
    #: tune and two BEATS channels, all off centre.
    FILLER = {
        139: 8,
        140: 8,
        257: 120,
        259: -24,
        260: -63,
        264: 2,
        272: -1,
        273: -1,
        385: 2,
        513: 1,
        520: 1,
    }

    #: The two self-describing sub-blocks a real dump ends with, carrying
    #: the values the unit reports: ascending trigger keys with latch off,
    #: then parts using the trigger velocity, no transpose, in groups of
    #: four. ``row_values`` may be a callable of the row number.
    BEATS = ((24, 2, (36, 0)), (16, 3, lambda part: (-1, 0, part // 4 + 1)))

    #: The same two blocks with the parts carrying nothing but zeros: an
    #: untouched BEATS part. Only the keys have to stay real, and that is
    #: the parser's doing rather than this test's -- a trailing region
    #: that is entirely in range makes the channel block ambiguous, so
    #: the parser refuses the dump rather than picking an offset. See
    #: test_a_trailing_region_entirely_in_range_is_not_locatable.
    QUIET_BEATS = ((24, 2, (36, 0)), (16, 3, (0, 0, 1)))

    #: A shape p2ked does not recognise. It is decoded, reported as
    #: unidentified, and has to come back exactly as it went.
    UNIDENTIFIED = ((3, 2, (5, 0)),)

    # --- building dumps -----------------------------------------------------

    def _master(self, **overrides):
        """All 82 master values, with a few invented ones on top."""
        values = {pid: 0 for _label, ids in m.MASTER_BLOCKS for pid in ids}
        values.update(self.FILLER)
        values.update(overrides)
        return values

    def _dump(
        self,
        *,
        name="Invented Setup",
        channels=32,
        channel_values=None,
        master=None,
        trailing=BEATS,
    ):
        """A whole setup, built the way the demo builds one, then parsed.

        Parsed rather than assembled by hand on purpose: a dump that has
        been through the parser carries the real ``offset``,
        ``header_counts`` and ``undecoded``, so the round-trip comparison
        is against everything the object holds and not only the parts the
        encoder happens to write.
        """
        values = self._master()
        values.update(master or {})
        data = []
        counts = tuple(len(ids) for _label, ids in m.MASTER_BLOCKS)
        for count in counts + (channels, len(m.CHANNEL_PARAMETERS)):
            data.extend(m.pack14(count))
        data.extend(m.encode_name(name))
        for _label, ids in m.MASTER_BLOCKS:
            for parameter_id in ids:
                data.extend(m.pack14_signed(values[parameter_id]))
        # The preset spread covers the whole documented range and passes
        # 127 early, which is what keeps the parser from finding a second
        # offset for the channel block -- see TestSetupDumpLayout.
        step = 895 // max(1, channels - 1)
        for channel in range(channels):
            fields = {
                "preset": channel * step,
                "volume": 127,
                "pan": 64,
                "mix_output": 1,
                "arp": 0,
                "enable": 1,
                "bank_map": 0,
                "receive_program_change": 1,
                "rom_id": 0,
            }
            fields.update((channel_values or {}).get(channel, {}))
            for field, _low, _high in m.CHANNEL_PARAMETERS:
                data.extend(m.pack14_signed(fields[field]))
        data.extend(self._trailing_bytes(trailing))
        return m.parse_setup_dump(m.parse(m.frame(m.Command.SETUP_DUMP, data)))

    @staticmethod
    def _trailing_bytes(blocks):
        data = []
        for rows, width, row_values in blocks:
            data.extend(m.pack14(rows))
            data.extend(m.pack14(width))
            for row in range(rows):
                values = row_values(row) if callable(row_values) else row_values
                for value in values:
                    data.extend(m.pack14_signed(value))
        return data

    # --- the round trip -----------------------------------------------------

    def _round_trip(self, dump, device=None):
        """Encode a dump, parse it back, and assert it survived.

        Both directions are checked. The parsed copy describes the same
        setup, field for field; and encoding *that* copy produces the
        identical bytes again. The second is the stronger claim, and the
        one an editor relies on when it changes one value and writes the
        whole setup back.
        """
        device = self.DEVICE if device is None else device
        wire = m.encode_setup_dump(dump, device=device)
        again = m.parse_setup_dump(m.parse(wire))
        assert m.encode_setup_dump(again, device=device) == wire
        self._assert_same_dump(dump, again)
        return wire

    def _assert_same_dump(self, dump, again):
        """Every field, including the ones the parser derived from the wire.

        ``offset`` and ``payload_size`` are in here because they are
        derived from the layout: an encoder that moved the channel block
        by one byte would leave every value intact and both of these
        different, which is the shape of a corruption no range check
        catches.
        """
        assert again.name == dump.name
        assert again.channel_count == dump.channel_count
        assert again.parameters_per_channel == dump.parameters_per_channel
        assert again.header_counts == dump.header_counts
        assert again.offset == dump.offset
        assert again.payload_size == dump.payload_size
        assert again.master == dump.master
        assert again.undecoded == dump.undecoded
        assert len(again.channels) == len(dump.channels)
        for channel, kept in zip(dump.channels, again.channels):
            assert kept.channel == channel.channel
            for field, _low, _high in m.CHANNEL_PARAMETERS:
                assert getattr(kept, field) == getattr(channel, field)
        assert len(again.trailing) == len(dump.trailing)
        for block, kept in zip(dump.trailing, again.trailing):
            assert kept.label == block.label
            assert kept.offset == block.offset
            assert kept.rows == block.rows
            assert kept.parameter_ids == block.parameter_ids

    def test_an_unmodified_dump_round_trips(self):
        self._round_trip(self._dump())

    def test_the_demo_devices_own_dump_round_trips(self):
        """The fake's frame, reproduced from the dump it built.

        The demo's ``_setup_reply`` and this encoder are two
        implementations of one layout -- which is why the byte-for-byte
        agreement is a consistency check and not evidence about the unit.
        """
        demo = DemoDevice()
        dump = demo.read_setup()
        wire = self._round_trip(dump, device=demo.device_id)
        assert wire == demo._setup_reply()

    # --- the frame ----------------------------------------------------------

    def test_the_frame_is_the_specifications_shape(self):
        """``{F0h, 18h, 0Fh, dd, 55h, 1Ch, ...}``, and no checksum byte.

        The example for command ``1Ch`` (spec p. 28) ends in ``F7h`` with
        no checksum, so the payload is exactly the dump's bytes -- and a
        checksum byte appended here would be read back as data.
        """
        wire = self._round_trip(self._dump())
        assert wire[:6] == bytes([0xF0, 0x18, 0x0F, self.DEVICE, 0x55, 0x1C])
        assert wire[-1] == 0xF7
        payload = wire[6:-1]
        assert all(byte <= 0x7F for byte in payload)

        counts = [len(ids) for _label, ids in m.MASTER_BLOCKS]
        declared = [m.unpack14(payload[i], payload[i + 1]) for i in range(0, 10, 2)]
        assert declared == counts
        assert m.unpack14(payload[10], payload[11]) == 32
        assert m.unpack14(payload[12], payload[13]) == len(m.CHANNEL_PARAMETERS)
        assert m.decode_name(payload[14 : 14 + m.NAME_LEN]) == "Invented Setup"

        master_bytes = 2 * sum(counts)
        channel_bytes = 2 * 32 * len(m.CHANNEL_PARAMETERS)
        trailing_bytes = len(self._trailing_bytes(self.BEATS))
        # The header's own arithmetic lands on the channel block, which is
        # what makes the master values' positions legitimate at all.
        assert m.parse_setup_dump(m.parse(wire)).offset == 30 + master_bytes
        assert len(payload) == 30 + master_bytes + channel_bytes + trailing_bytes
        assert trailing_bytes == 200  # the two BEATS sub-blocks, as §10 found them

    def test_the_device_id_is_the_one_asked_for(self):
        wire = m.encode_setup_dump(self._dump(), device=0x42)
        assert m.parse(wire).device == 0x42

    def test_a_device_id_out_of_range_is_refused_not_masked(self):
        for value in (-1, 0x80, 200):
            with pytest.raises(m.ProtocolError):
                m.encode_setup_dump(self._dump(), device=value)

    # --- the edges ----------------------------------------------------------

    def test_a_channel_value_at_each_range_extreme_round_trips(self):
        """Every low and every high, not a sample of them.

        An extreme is where an encoder is tempted to clip, and a clipped
        value is a setup that is nearly the one the unit just sent.
        """
        for field, low, high in m.CHANNEL_PARAMETERS:
            for value in (low, high):
                dump = self._dump(channel_values={3: {field: value}})
                assert getattr(dump.channel(3), field) == value
                self._round_trip(dump)

    def test_a_name_shorter_than_name_len_round_trips(self):
        for name in ("Hi", "", " " * 16, "N" * m.NAME_LEN):
            dump = self._dump(name=name)
            assert dump.name == name.rstrip()
            wire = self._round_trip(dump)
            payload = m.parse(wire).payload
            assert payload[14 : 14 + m.NAME_LEN] == bytes(m.encode_name(name))

    def test_negative_master_values_round_trip(self):
        """Signed because the parser signed them.

        Transpose and fine tune are negative on any unit somebody has
        played, and -8192 is the widest value the encoding carries -- an
        encoder that packed these unsigned would send 16383 back.
        """
        dump = self._dump(master={270: -8192})
        assert dump.transpose == -24
        assert dump.tune == -63
        assert dump.master[270] == -8192
        wire = self._round_trip(dump)
        assert m.parse_setup_dump(m.parse(wire)).master[270] == -8192

    def test_a_master_value_that_does_not_fit_is_refused(self):
        """-8193 is not a 14-bit two's complement value. It is not sent."""
        with pytest.raises(m.ProtocolError):
            m.encode_setup_dump(self._dump(master={260: -8193}), device=self.DEVICE)

    def test_the_beats_blocks_come_back(self):
        dump = self._dump()
        labels = [block.label for block in dump.trailing]
        assert labels == ["BEATS triggers", "BEATS parts"]
        self._round_trip(dump)

    def test_the_beats_blocks_round_trip_when_the_parts_carry_nothing(self):
        """A part nobody has touched reads as zeros, and is written as them."""
        dump = self._dump(trailing=self.QUIET_BEATS)
        parts = dump.trailing_block("BEATS parts")
        assert parts.rows[0] == (0, 0, 1)
        self._round_trip(dump)

    def test_a_dump_with_no_trailing_blocks_round_trips(self):
        dump = self._dump(trailing=())
        assert dump.trailing == ()
        wire = self._round_trip(dump)
        payload = m.parse(wire).payload
        master_bytes = 2 * sum(len(ids) for _label, ids in m.MASTER_BLOCKS)
        expected = 30 + master_bytes + 2 * 32 * len(m.CHANNEL_PARAMETERS)
        assert len(payload) == expected

    def test_an_unidentified_trailing_block_round_trips(self):
        """A shape p2ked cannot name is still written back unchanged.

        Dropping it would be the one edit nobody asked for.
        """
        dump = self._dump(trailing=self.UNIDENTIFIED)
        block = dump.trailing[0]
        assert not block.identified
        assert block.rows == ((5, 0), (5, 0), (5, 0))
        self._round_trip(dump)

    def test_a_trailing_region_entirely_in_range_is_not_locatable(self):
        """Why the tests above cannot use an all-zero trailing region.

        The parser finds the channel block by looking for the one offset
        at which every value in range fits, and a block of zeros supplies
        no value that rules an offset out -- so a dump whose trailing
        region is entirely in range is *ambiguous* and is refused. That
        refusal is the right answer, and it is also the answer before the
        encoder is involved at all.
        """
        dump = self._dump(trailing=())
        # Rebuild the same dump with an all-zero trailing region.
        blocks = ((24, 2, (0, 0)), (16, 3, (0, 0, 0)))
        payload = list(m.parse(m.encode_setup_dump(dump, device=self.DEVICE)).payload)
        payload.extend(self._trailing_bytes(blocks))
        with pytest.raises(m.ProtocolError) as refused:
            m.parse_setup_dump(m.parse(m.frame(m.Command.SETUP_DUMP, payload)))
        assert "ambiguous" in str(refused.value)

    def test_fewer_channels_round_trip(self):
        for channels in (16, 8):
            dump = self._dump(channels=channels)
            assert len(dump.channels) == channels
            self._round_trip(dump)

    # --- the thing this exists for ------------------------------------------

    def test_an_edit_changes_only_the_bytes_it_should(self):
        """One field edited, every other byte identical.

        This is the per-channel edit the encoder was written for, and the
        property that makes it safe: a whole setup is written back, but
        the bytes that move are the two belonging to the edited field and
        nothing else.
        """
        demo = DemoDevice()
        dump = demo.read_setup()
        assert dump.channel(5).volume == 0  # the demo's silent channel
        before = m.encode_setup_dump(dump, device=demo.device_id)

        dump.channel(5).volume = 100
        after = m.encode_setup_dump(dump, device=demo.device_id)

        old = list(m.parse(before).payload)
        new = list(m.parse(after).payload)
        assert len(new) == len(old)
        changed = [index for index, (a, b) in enumerate(zip(new, old)) if a != b]

        slot = [name for name, _low, _high in m.CHANNEL_PARAMETERS].index("volume")
        start = dump.offset + (5 * dump.parameters_per_channel + slot) * 2
        assert changed, "the edit moved no bytes at all"
        assert all(start <= index < start + 2 for index in changed)
        assert m.unpack14_signed(new[start], new[start + 1]) == 100

        edited = m.parse_setup_dump(m.parse(after))
        original = m.parse_setup_dump(m.parse(before))
        assert edited.channel(5).volume == 100
        for channel in edited.channels:
            if channel.channel != 5:
                kept = original.channel(channel.channel)
                for field, _low, _high in m.CHANNEL_PARAMETERS:
                    assert getattr(channel, field) == getattr(kept, field)
        assert edited.master == original.master
        assert edited.name == original.name
        assert [b.rows for b in edited.trailing] == [b.rows for b in original.trailing]

    # --- what it refuses ----------------------------------------------------

    def test_a_setup_that_was_not_fully_decoded_is_refused(self):
        """The bytes p2ked could not read cannot be written back.

        They would be dropped, which is exactly the silent change this
        module refuses everywhere else.
        """
        dump = self._dump()
        dump.undecoded = ("2 bytes at 770 are not a self-describing block",)
        with pytest.raises(m.ProtocolError) as refused:
            m.encode_setup_dump(dump, device=self.DEVICE)
        assert "not fully decoded" in str(refused.value)

    def test_a_setup_missing_a_master_value_is_refused(self):
        """Writing 0 in its place would be a change nobody made."""
        dump = self._dump()
        del dump.master[m.Parameter.MASTER_TRANSPOSE]
        with pytest.raises(m.ProtocolError) as refused:
            m.encode_setup_dump(dump, device=self.DEVICE)
        assert "no value for master parameter" in str(refused.value)

    def test_a_setup_declaring_other_block_counts_is_refused(self):
        """A block carrying a different number of values shifts the rest."""
        dump = self._dump()
        counts = list(dump.header_counts)
        counts[1] += 1
        dump.header_counts = tuple(counts)
        with pytest.raises(m.ProtocolError) as refused:
            m.encode_setup_dump(dump, device=self.DEVICE)
        assert "block counts" in str(refused.value)

    def test_a_setup_whose_channels_do_not_match_its_header_is_refused(self):
        dump = self._dump()
        dump.channels = dump.channels[:-1]
        with pytest.raises(m.ProtocolError) as refused:
            m.encode_setup_dump(dump, device=self.DEVICE)
        assert "declares" in str(refused.value)

    def test_a_setup_with_an_unknowable_parameter_count_is_refused(self):
        dump = self._dump()
        dump.parameters_per_channel = 8
        with pytest.raises(m.ProtocolError) as refused:
            m.encode_setup_dump(dump, device=self.DEVICE)
        assert "parameters per channel" in str(refused.value)

    def test_a_trailing_block_with_no_rows_is_refused(self):
        """Its width is not recoverable from nothing."""
        dump = self._dump()
        dump.trailing = dump.trailing + (m.TrailingBlock("nowhere", 0, [], ()),)
        with pytest.raises(m.ProtocolError) as refused:
            m.encode_setup_dump(dump, device=self.DEVICE)
        assert "no rows" in str(refused.value)

    def test_a_setup_with_an_impossible_channel_count_is_refused(self):
        """Zero, and one more than the family has, are both refusals."""
        dump = self._dump()
        for count in (0, 65):
            dump.channel_count = count
            dump.channels = [m.ChannelState(number) for number in range(count)]
            with pytest.raises(m.ProtocolError) as refused:
                m.encode_setup_dump(dump, device=self.DEVICE)
            assert "not a number this family has" in str(refused.value)

    def test_a_trailing_block_whose_rows_disagree_is_refused(self):
        """It cannot describe its own width, so it cannot be written."""
        dump = self._dump()
        dump.trailing = dump.trailing + (
            m.TrailingBlock("crooked", 0, [(1, 0), (2, 0, 0)], ()),
        )
        with pytest.raises(m.ProtocolError) as refused:
            m.encode_setup_dump(dump, device=self.DEVICE)
        assert "differing widths" in str(refused.value)

    def test_it_is_exported(self):
        assert "encode_setup_dump" in m.__all__
