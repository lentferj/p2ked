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

"""A stand-in Proteus, so p2ked runs with no hardware and no MIDI ports.

**This is not a convenience here, it is the only way p2ked is developed.**
There is no Proteus 2000 to test against, so every line of this project was
written against this file. That places a burden on it that the sibling
projects' demo bridges do not carry: a fake that is wrong in the same way
the real code is wrong will agree with it perfectly and prove nothing.

So this one is written from the *specification*, deliberately, rather than
from p2k.bridge -- it builds real System Exclusive frames with
:mod:`p2k.messages` and parses them back. A frame this fake accepts is a
frame the encoder really produced, which is the one useful thing a fake can
establish without hardware. What it cannot establish is whether the machine
agrees, and nothing here should be read as evidence that it does.

Names it invents are invented. The word pool is chosen to be obviously not
E-MU's, so that a screenshot taken in demo mode cannot be mistaken for a
real unit's contents.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

from p2k import messages as m
from p2k import roms

__all__ = ["DemoDevice", "DEMO_DEVICE_ID", "DEMO_SIMMS"]

#: The fake answers on a device ID that is neither 0 nor the broadcast ID.
#: A fake living at 0 would let a caller that forgot to set the ID work by
#: accident, and then fail against a real unit set to anything else.
DEMO_DEVICE_ID = 0x05

#: Which ROMs the fake pretends are fitted. Four SIMMs, as a Proteus 2000
#: holds, and deliberately *not* the first four in p2k.roms -- a fake whose
#: ROM list happens to match the table's order would hide an indexing bug.
DEMO_SIMMS: Tuple[str, ...] = ("COMPOSER", "XLEAD", "WORLD", "PHATT")

_ADJECTIVES = (
    "Velvet",
    "Rusted",
    "Glass",
    "Hollow",
    "Distant",
    "Folded",
    "Amber",
    "Quiet",
    "Drifting",
    "Woven",
    "Paper",
    "Tidal",
    "Copper",
    "Slow",
    "Bitter",
    "Pale",
)
_NOUNS = (
    "Bell",
    "Pad",
    "Bass",
    "Lead",
    "Choir",
    "Pluck",
    "Sweep",
    "Stack",
    "Drone",
    "Keys",
    "Brass",
    "Wash",
    "Spike",
    "Hum",
    "Comb",
    "Grain",
)


def demo_name(bank_id: str, program_change: int) -> str:
    """A stable invented name. Deterministic, so tests can assert on it."""
    seed = sum(ord(char) for char in bank_id) * 31 + program_change * 17
    adjective = _ADJECTIVES[seed % len(_ADJECTIVES)]
    noun = _NOUNS[(seed // len(_ADJECTIVES)) % len(_NOUNS)]
    return f"{adjective} {noun}"[: m.NAME_LEN]


class DemoDevice:
    """Answers the subset of the protocol p2ked speaks.

    Not a subclass of the real bridge: :mod:`p2k.bridge` imports rtmidi at
    module scope, and the point of this class is to work where that import
    fails.
    """

    def __init__(
        self,
        *,
        latency: float = 0.0,
        device_id: int = DEMO_DEVICE_ID,
        simms: Tuple[str, ...] = DEMO_SIMMS,
    ) -> None:
        self.description = "demo (no MIDI ports opened)"
        self.device_id = device_id
        self.latency = latency
        self.timeout = 1.0
        self.simms = tuple(simms)
        #: What the fake is "playing", so selection is not a no-op.
        self.selected: Optional[roms.Preset] = None
        #: (preset, channel) for every selection, in order.
        self.selected_log: List[Tuple[roms.Preset, int]] = []
        self.selected_channel: int = 0
        #: Every frame the fake was handed, for tests that care about the
        #: wire rather than the result.
        self.received: List[bytes] = []
        #: Channels the fake says are enabled. None of them is channel 1: a
        #: fake whose only live channel was the first would let an
        #: off-by-one in the channel numbering pass unnoticed. Channel 6 is
        #: enabled but at volume 0, so the second reason a channel can be
        #: silent is exercised too -- masked behind a disabled channel it
        #: would never be reached.
        self._enabled = (5, 8, 9)
        self._closed = False

    # --- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._closed = True

    def _tick(self) -> None:
        if self.latency:
            time.sleep(self.latency)

    # --- the wire ------------------------------------------------------------

    def handle(self, frame: bytes) -> Optional[bytes]:
        """Take a System Exclusive frame, return the reply or ``None``.

        The whole fake funnels through here, so everything it answers was
        encoded by :mod:`p2k.messages` and decoded by it too.
        """
        self.received.append(bytes(frame))
        self._tick()

        identity = m.identity_reply_fields(frame)
        if identity is not None:
            return None  # that is a reply, not a request

        if (
            len(frame) >= 6
            and frame[1] == 0x7E
            and frame[3] == 0x06
            and frame[4] == 0x01
        ):
            return self._identity_reply()

        packet = m.parse(frame)
        if packet is None:
            return None
        if packet.device not in (self.device_id, m.BROADCAST_DEVICE):
            # Addressed to another unit. Silence, exactly as the real thing:
            # there is no "wrong device" error on a MIDI cable.
            return None

        if packet.command == m.Command.CONFIGURATION_REQUEST:
            return self._config_reply()
        if packet.command == m.Command.SETUP_DUMP_REQUEST:
            return self._setup_reply()
        if packet.command == m.Command.GENERIC_NAME_REQUEST:
            return self._name_reply(packet)
        return None

    def _identity_reply(self) -> bytes:
        return bytes(
            [
                m.SYSEX_START,
                0x7E,
                self.device_id,
                0x06,
                0x02,
                m.EMU_ID,
                0x0F,
                0x00,
                0x02,
                0x00,
                0x01,
                0x00,
                0x00,
                0x00,
                m.SYSEX_END,
            ]
        )

    #: Invented master-parameter values, by parameter ID; anything in a
    #: block and not named here is sent as 0. Chosen to be obviously a
    #: demo (120 bpm, effects off) and not one unit's settings.
    MASTER_VALUES = {
        257: 120,  # clock tempo, bpm
        264: 2,  # bend range, semitones
        266: 1,  # output format
        272: -1,
        273: -1,  # BEATS channels: use basic channel
        385: m.MidiMode.MULTI,
        386: 1,  # mode change enabled
        513: 1,
        520: 1,  # effects algorithms, min is 1
        641: 0,  # arpeggiator off
        644: 10,
        646: 100,
        648: 1,
        656: 127,
        # Basic and FX-control channel 9 (0-based 8). Not decoration:
        # a dump where every master value is 0 makes the channel
        # block's structural search ambiguous, which the real unit's
        # dump is not -- so the demo must not be flatter than life.
        139: 8,
        140: 8,
        141: 0,  # basic / FX / tempo channels
    }

    def _setup_reply(self) -> bytes:
        """A setup dump shaped like the real one.

        The master blocks are laid out by :data:`p2k.messages.MASTER_BLOCKS`,
        which came from a unit rather than from the specification, so unlike
        the rest of this file this part is *not* an independent reading of
        the document -- there is no document to read. It is here so the
        browser has something to show, and so the block arithmetic is
        exercised at all.

        The channel block is deliberately not at offset 0: the parser finds
        it by structural search, and a fake that put it first would let a
        parser that simply started at the beginning pass.
        """
        channels = 32
        per = len(m.CHANNEL_PARAMETERS)
        counts = tuple(len(ids) for _label, ids in m.MASTER_BLOCKS)
        payload: List[int] = []
        for count in counts + (channels, per):
            payload.extend(m.pack14(count))
        payload.extend(m.encode_name("Demo Setup"))
        for _label, ids in m.MASTER_BLOCKS:
            for parameter_id in ids:
                payload.extend(m.pack14_signed(self.MASTER_VALUES.get(parameter_id, 0)))
        for channel in range(channels):
            preset = channel
            rom_id = 0
            enable = 1 if channel in self._enabled else 0
            volume = 0 if channel == 5 else 127
            if channel in self._enabled and channel != 5:
                rom_id = roms.rom(self.simms[0]).msb
                preset = channel * 3
            values = {
                "preset": preset,
                "volume": volume,
                "pan": 64,
                "mix_output": 1,
                "arp": 0,
                "enable": enable,
                "bank_map": 0,
                "receive_program_change": 1,
                "rom_id": rom_id,
            }
            for name, _low, _high in m.CHANNEL_PARAMETERS:
                payload.extend(m.pack14_signed(values[name]))
        # The two self-describing sub-blocks the real dump ends with: 24
        # BEATS triggers of two values, then 16 BEATS parts of three.
        payload.extend(m.pack14(24))
        payload.extend(m.pack14(2))
        for trigger in range(24):
            payload.extend(m.pack14_signed(36 + trigger))  # trigger key
            payload.extend(m.pack14_signed(0))  # latch: off
        payload.extend(m.pack14(16))
        payload.extend(m.pack14(3))
        for part in range(16):
            payload.extend(m.pack14_signed(-1))  # use trigger vel
            payload.extend(m.pack14_signed(0))  # transpose
            payload.extend(m.pack14_signed(part // 4 + 1))  # group
        return m.frame(m.Command.SETUP_DUMP, payload, device=self.device_id)

    def _config_reply(self) -> bytes:
        payload: List[int] = []
        general = list(m.pack14(roms.USER.count))
        payload.append(len(general))
        payload.extend(general)
        payload.append(len(self.simms))
        payload.append(6)  # bytes per SIMM
        for rom_id in self.simms:
            entry = roms.rom(rom_id)
            # The fake reports SIMM ID == Bank Select MSB. That is p2ked's
            # working hypothesis and is NOT established -- see
            # roms.rom_for_simm_id. A fake is not evidence; this one exists
            # so the code path runs, not so the hypothesis looks confirmed.
            payload.extend(m.pack14(entry.msb))
            payload.extend(m.pack14(entry.count))
            payload.extend(m.pack14(entry.count // 4))
        return m.frame(m.Command.CONFIGURATION, payload, device=self.device_id)

    def _name_reply(self, packet) -> Optional[bytes]:
        data = packet.payload
        if len(data) < 5:
            return None
        object_type = data[0]
        number = m.unpack14(data[1], data[2])
        rom_id = m.unpack14(data[3], data[4])
        if object_type != m.ObjectType.PRESET:
            return None
        found = self._locate(number, rom_id)
        if found is None:
            # Two kinds of nothing, and the unit tells them apart.
            #
            # An object it does not have -- an object type it does not
            # speak, or a ROM ID that is in nobody's table -- gets
            # **silence**, which is what every other mistake on this cable
            # looks like too. That is the case `installed_roms` has to
            # step around.
            #
            # A preset that does not exist, in a ROM it does know, gets
            # the name `(not installed)`. Confirmed against a Proteus 2000
            # on 2026-09-12, and re-confirmed on 2026-10-02: X-Lead v2,
            # Techno Synth and Beat Garden all answer it one past their
            # last preset. Because it is an answer rather than silence,
            # presence becomes a positive test instead of a timeout.
            #
            # The fake used to return silence for both, which quietly made
            # every absent ROM look like a timeout and left the
            # configuration answer and the name-probe answer unable to
            # agree on anything.
            if not self._rom_is_known(rom_id):
                return None
            return self._name_frame(object_type, number, rom_id, roms.NOT_INSTALLED)
        bank_id, program_change = found
        return self._name_frame(
            object_type, number, rom_id, demo_name(bank_id, program_change)
        )

    def _name_frame(
        self, object_type: int, number: int, rom_id: int, name: str
    ) -> bytes:
        return m.frame(
            m.Command.GENERIC_NAME,
            [object_type, *m.pack14(number), *m.pack14(rom_id), *m.encode_name(name)],
            device=self.device_id,
        )

    def _rom_is_known(self, rom_id: int) -> bool:
        """Whether the table claims this ROM ID at all, fitted or not."""
        if rom_id == roms.USER_ROM_ID:
            return True
        return roms.rom_for_simm_id(rom_id) is not None

    def _locate(self, number: int, rom_id: int) -> Optional[Tuple[str, int]]:
        """ROM-relative preset number to ``(bank id, program change)``.

        ``None`` for a preset the fake does not have -- an unfitted ROM,
        or a number past the end of a fitted one. Which of those it was is
        not decided here; `_name_reply` decides what to say about it.
        """
        entry = (
            roms.USER if rom_id == roms.USER_ROM_ID else roms.rom_for_simm_id(rom_id)
        )
        if entry is None or entry.id not in self.simms + (roms.USER.id,):
            return None
        if not 0 <= number < entry.count:
            return None
        lsb_index, program_change = divmod(number, roms.PRESETS_PER_BANK)
        if lsb_index >= len(entry.lsbs):
            return None
        return (f"{entry.id}-{entry.lsbs[lsb_index]}", program_change)

    # --- the operations p2ked uses ------------------------------------------

    def identify(self, *, timeout: Optional[float] = None):
        return m.identity_reply_fields(self._identity_reply())

    def read_parameter(self, parameter_id: int, *, timeout=None) -> int:
        self._tick()
        return {
            m.Parameter.MIDI_MODE: m.MidiMode.MULTI,
            m.Parameter.MIDI_ID: self.device_id,
        }.get(parameter_id, 0)

    def midi_mode(self, *, timeout=None) -> int:
        return self.read_parameter(m.Parameter.MIDI_MODE)

    def read_setup(self, *, timeout: Optional[float] = None) -> m.SetupDump:
        reply = self.handle(m.setup_dump_request(device=self.device_id))
        return m.parse_setup_dump(m.parse(reply))

    def hardware_config(self, *, timeout: Optional[float] = None) -> m.HardwareConfig:
        reply = self.handle(m.config_request(device=self.device_id))
        return m.parse_config(m.parse(reply))

    def preset_name(
        self, number: int, rom_id: int, *, timeout: Optional[float] = None
    ) -> str:
        """One preset's name. Read-only, and **makes no sound**.

        Same contract as :meth:`p2k.bridge.ProteusBridge.preset_name`:
        silence is a :class:`TimeoutError`, never a ``None``. The two were
        written to different signatures once, and the difference is exactly
        where a ``None`` would reach a caller written against the bridge's
        -- so the demo raises, like the real thing, and the divergence is
        gone rather than documented.
        """
        reply = self.handle(
            m.name_request(m.ObjectType.PRESET, number, rom_id, device=self.device_id)
        )
        if reply is None:
            raise TimeoutError(
                "the demo device does not answer for that object; a real "
                "unit would have gone silent, which is what this means"
            )
        return m.parse_name(m.parse(reply)).name

    def read_bank_names(
        self,
        bank_id: str,
        *,
        on_progress: Optional[Callable[[int, int], None]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[int, str]:
        """Every name in a bank. **Makes no sound** -- see p2k.bridge.

        Deliberately the same loop as the bridge's, absent slots included,
        so a test exercises the code path the real thing runs.
        """
        bank = roms.bank(bank_id)
        rom_id = roms.USER_ROM_ID if bank.rom is roms.USER else bank.rom.msb
        out: Dict[int, str] = {}
        entries = roms.presets(bank_id)
        for index, entry in enumerate(entries, start=1):
            try:
                name = self.preset_name(entry.number, rom_id, timeout=timeout)
            except TimeoutError:
                # One missing name is not a reason to lose the other 127.
                name = None
            if name is not None and not roms.is_absent(name):
                out[entry.program_change] = name
            if on_progress is not None:
                on_progress(index, len(entries))
        return out

    def select(self, entry: roms.Preset, *, channel: int = 0) -> None:
        """Select a preset. **This changes what the unit is playing.**

        The channel is recorded, not ignored. The real bridge puts it in
        the status byte (``0xB0 | channel``); a demo that dropped it let a
        test named for the channel pass while asserting only that
        *something* was sent.
        """
        self._tick()
        self.selected = entry
        self.selected_channel = channel
        self.selected_log.append((entry, channel))
