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
        assert m.identity_request(0x7F) == bytes(
            [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])

    def test_our_own_request_is_not_mistaken_for_a_reply(self):
        """The sub-ID differs, which is what defeats a MIDI-Thru loop."""
        assert m.identity_reply_fields(m.identity_request(0x7F)) is None

    def test_a_reply_is_decoded(self):
        reply = bytes([0xF0, 0x7E, 0x05, 0x06, 0x02, 0x18, 0x0F, 0x00,
                       0x02, 0x00, 0x01, 0x00, 0x00, 0x00, 0xF7])
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
        payload = [m.ObjectType.PRESET, *m.pack14(133), *m.pack14(7),
                   *m.encode_name("Woven Bell")]
        reply = m.parse_name(m.parse(m.frame(m.Command.GENERIC_NAME, payload)))
        assert (reply.number, reply.rom_id, reply.name) == (
            133, 7, "Woven Bell")

    def test_a_short_name_message_is_refused(self):
        with pytest.raises(m.ProtocolError):
            m.parse_name(m.parse(m.frame(m.Command.GENERIC_NAME, [1, 0, 0])))


class TestConfiguration:
    """The message that tells p2ked what ROMs are fitted."""

    def _payload(self, user_presets, simms, *, per_simm=6, general=None):
        general = general if general is not None else list(
            m.pack14(user_presets))
        payload = [len(general), *general, len(simms), per_simm]
        for simm_id, presets, instruments in simms:
            chunk = [*m.pack14(simm_id), *m.pack14(presets),
                     *m.pack14(instruments)]
            chunk += [0] * (per_simm - len(chunk))
            payload += chunk
        return payload

    def test_it_decodes(self):
        payload = self._payload(512, [(4, 1024, 256), (7, 512, 128)])
        config = m.parse_config(
            m.parse(m.frame(m.Command.CONFIGURATION, payload)))
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
            512, [(4, 1024, 256)],
            general=[*m.pack14(512), 9, 9])        # two extra bytes
        config = m.parse_config(
            m.parse(m.frame(m.Command.CONFIGURATION, payload)))
        assert config.user_presets == 512
        assert config.simms[0] == m.SimmInfo(4, 1024, 256)

    def test_a_longer_per_simm_block_is_obeyed_too(self):
        payload = self._payload(512, [(4, 1024, 256), (7, 512, 128)],
                                per_simm=8)
        config = m.parse_config(
            m.parse(m.frame(m.Command.CONFIGURATION, payload)))
        assert [s.simm_id for s in config.simms] == [4, 7]

    def test_a_truncated_response_is_refused(self):
        payload = self._payload(512, [(4, 1024, 256)])[:-3]
        with pytest.raises(m.ProtocolError):
            m.parse_config(m.parse(m.frame(m.Command.CONFIGURATION, payload)))

    def test_no_simms_is_a_valid_answer(self):
        config = m.parse_config(
            m.parse(m.frame(m.Command.CONFIGURATION, self._payload(512, []))))
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
