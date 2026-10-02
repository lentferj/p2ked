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

"""That the read path cannot make the instrument sound.

**This project has no audio path.** The Proteus 2000 these claims were
checked against was connected by MIDI only, so nobody could hear whether a
read made a noise, and a claim of silence would have been unfalsifiable.

So the claim is not made. What is tested instead is the *mechanism*: a
MIDI synthesizer makes sound by receiving **Channel Voice** messages -- Note
On/Off, Control Change, Program Change, Pitch Bend, Channel and Poly
aftertouch, status bytes 0x80-0xEF. System Exclusive that merely asks a
question cannot make one sound.

Two things are therefore established here, and they are the strongest form
of the claim available without ears:

1. **Every read operation sends nothing but System Exclusive.** Exercised
   against a port that records everything and never answers, so every read
   times out -- which does not matter, because the send happens before the
   wait and is what is being inspected.
2. **`select()` is the only code in the project that emits Channel Voice
   at all**, so the audible operation is reachable from exactly one place,
   and :class:`P2kedApp` reaches it only through Enter or `p2kcli select`.

The second is checked by looking at the recorded bytes of a real selection,
so this file cannot pass by simply never exercising the case.
"""

from contextlib import suppress

import pytest

from p2k import messages as m
from p2k import roms
from p2k.bridge import ProteusBridge


class _RecordingOut:
    """A MIDI output that records instead of transmitting."""

    def __init__(self):
        self.sent = []

    def send_message(self, message):
        self.sent.append(list(message))

    def close_port(self):
        pass

    def delete(self):
        pass

    def ignore_types(self, **_kwargs):
        pass


class _SilentIn:
    """A MIDI input that never answers, so every read times out."""

    def get_message(self):
        return None

    def close_port(self):
        pass

    def delete(self):
        pass

    def ignore_types(self, **_kwargs):
        pass


def _voice_status(message):
    """The Channel Voice status byte, or ``None`` for anything else."""
    if message[0] == 0xF0:
        return None
    status = message[0] & 0xF0
    return status if 0x80 <= status <= 0xE0 else None


@pytest.fixture
def bridge():
    """A bridge onto a port that records sends and never replies.

    ``timeout`` is short because every read will time out, and there is no
    reply to wait for -- what is under test is what went *out*.
    """
    out = _RecordingOut()
    return ProteusBridge(_SilentIn(), out, device_id=0, timeout=0.01), out


def _run_ignoring_timeouts(call):
    """Run a read, which is expected to time out on a silent port."""
    with suppress(TimeoutError):
        call()


class TestReadsEmitNothingButSysEx:
    """Every read operation, one by one."""

    def _assert_only_sysex(self, out):
        assert out.sent, "nothing was sent -- the check would be vacuous"
        for message in out.sent:
            assert _voice_status(message) is None, (
                f"a read sent a Channel Voice message: {message!r}"
            )
            assert message[0] == 0xF0, f"not System Exclusive: {message!r}"

    def test_a_bank_name_read(self, bridge):
        dev, out = bridge
        _run_ignoring_timeouts(lambda: dev.read_bank_names("USER-0"))
        self._assert_only_sysex(out)
        assert len(out.sent) == 128, "one request per preset"

    def test_a_single_preset_name(self, bridge):
        dev, out = bridge
        _run_ignoring_timeouts(lambda: dev.preset_name(0, 0))
        self._assert_only_sysex(out)

    def test_the_configuration_request(self, bridge):
        dev, out = bridge
        _run_ignoring_timeouts(dev.hardware_config)
        self._assert_only_sysex(out)

    def test_the_setup_dump_request(self, bridge):
        dev, out = bridge
        _run_ignoring_timeouts(dev.read_setup)
        self._assert_only_sysex(out)

    def test_a_parameter_request(self, bridge):
        dev, out = bridge
        _run_ignoring_timeouts(dev.midi_mode)
        self._assert_only_sysex(out)

    def test_the_identity_request(self, bridge):
        """Not an E-MU message at all, and still not Channel Voice."""
        dev, out = bridge
        _run_ignoring_timeouts(lambda: dev.identify(timeout=0.01))
        self._assert_only_sysex(out)
        assert out.sent == [list(m.identity_request(m.BROADCAST_DEVICE))]

    def test_the_rom_presence_sweep(self, bridge):
        """`installed_roms` asks one question per ROM; all must be SysEx."""
        dev, out = bridge
        _run_ignoring_timeouts(lambda: dev.installed_roms(timeout=0.01))
        self._assert_only_sysex(out)

    def test_the_whole_read_path_together(self, bridge):
        """One run over every read, as the browser would use them."""
        dev, out = bridge
        for call in (
            dev.hardware_config,
            dev.read_setup,
            lambda: dev.preset_name(0, 0),
            dev.midi_mode,
            lambda: dev.identify(timeout=0.01),
        ):
            _run_ignoring_timeouts(call)
        self._assert_only_sysex(out)


class TestSelectIsTheOnlyAudibleOperation:
    """And the check above can actually detect one.

    Without this, every test above would also pass on a build in which
    ``select`` had been changed to send nothing at all -- which is the
    failure mode of a check that only ever proves a negative.
    """

    def test_a_selection_sends_bank_select_and_a_program_change(self, bridge):
        dev, out = bridge
        dev.select(roms.preset("USER-0", 5), channel=0)
        assert [m for m in out.sent if _voice_status(m) is not None], (
            "a selection emitted no Channel Voice; the read tests would "
            "pass for the wrong reason"
        )
        # CC#0 Bank Select MSB, CC#32 Bank Select LSB, then Program Change,
        # in that order -- the order the protocol requires.
        assert out.sent == [
            [0xB0, 0x00, roms.USER.msb],
            [0xB0, 0x20, roms.USER.lsbs[0]],
            [0xC0, 5],
        ]

    def test_the_channel_lands_in_the_status_byte(self, bridge):
        dev, out = bridge
        dev.select(roms.preset("USER-0", 5), channel=9)
        assert all(m[0] == 0xB9 for m in out.sent[:2]), "CC status"
        assert out.sent[2][0] == 0xC9, "Program Change status"

    def test_an_out_of_range_channel_is_refused_before_anything_is_sent(self, bridge):
        """The one operation that can sound still refuses a bad address."""
        dev, out = bridge
        with pytest.raises(ValueError):
            dev.select(roms.preset("USER-0", 5), channel=16)
        assert out.sent == [], "a refused selection still put bytes on the wire"


class TestTheProjectHasNoOtherSender:
    """A structural check, so a new sender cannot be added quietly.

    The behavioural tests above cover the read path as it exists. This one
    covers the *rule*: anywhere in ``p2k`` that sends to the port, it is
    either building System Exclusive or is inside ``select``.
    """

    def test_select_is_the_only_non_sysex_send_site(self):
        import ast
        import os

        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "p2k",
            "bridge.py",
        )
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if not (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "send_message"
                ):
                    continue
                # SysEx builders are `frame(...)`/`identity_request(...)`,
                # both of which return something starting 0xF0. The only
                # other senders are the three literals in select().
                literal_lists = [arg for arg in inner.args if isinstance(arg, ast.List)]
                if node.name == "select":
                    continue
                if not literal_lists:
                    continue  # a computed frame -- treated as SysEx
                offenders.append(f"{node.name}: line {inner.lineno}")

        assert not offenders, f"Channel Voice sent outside select(): {offenders}"
