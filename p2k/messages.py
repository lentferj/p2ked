# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# The System Exclusive frame layout, the manufacturer and product IDs, the
# editor designator byte, the command numbers, the 14-bit LSB-first value
# encoding and the checksum rule are transcribed as data from E-MU's
# "Proteus Family Sound Modules MIDI System Exclusive Specification" v2.2.
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

"""The E-MU Proteus family System Exclusive wire format.

**Partly verified against hardware.** The frame layout, the 14-bit LSB-first
encoding, Identity, Hardware Configuration, Generic Name and the Setup Dump
were all exercised against a real Proteus 2000 on 2026-09-12. Parameter
edits, preset dumps and the checksum rule were not, and are still only as
good as one reading of one document -- the sibling rxved project shipped an
ID conversion that was wrong for months because the failure mode was
silence. DISCLAIMER.md says which is which.

Frame::

    F0 18 0F <dev> 55 <command> [<sub>] [data ...] [checksum] F7

* ``18h`` E-MU, ``0Fh`` Proteus. Two bytes, and neither is a MIDI
  manufacturer *extension* -- ``18h`` is E-MU's single-byte manufacturer ID
  and ``0Fh`` is a product ID within it.
* ``dev`` is the device ID, ``00h``-``7Eh``, with ``7Fh`` meaning broadcast.
  Plain, unlike Roland's ``10h``-based scheme; the panel number is the wire
  number, and this module still refuses out-of-range values rather than
  masking them.
* ``55h`` is the "Special Editor designator byte", present in every editor
  message and in none of the ordinary ones.

Three things differ from the Roland protocol the sibling project speaks, and
all three are places to be careful:

**Values are 14 bits, sent as two 7-bit bytes, LEAST significant first.**
Not most. A pair read the wrong way round is still a valid number, usually a
plausible one, and nothing rejects it -- so :func:`pack14` and
:func:`unpack14` are the only places this is done, and every caller passes
through them.

**Signed values are two's complement in 14 bits.** Parameter values may be
negative (a tuning offset, a patchcord amount), which the encoding has to
carry and the reader has to sign-extend.

**The checksum is an XOR, not a sum.** One byte, the XOR of the data bytes,
and ``7Fh`` explicitly means "ignore the checksum". Only some messages carry
one. Roland's is a two's-complement sum over address *and* data; using
either rule for the other protocol produces a message the device rejects, or
worse, silently ignores.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "SYSEX_START",
    "ChannelState",
    "SetupDump",
    "CHANNEL_PARAMETERS",
    "MASTER_BLOCKS",
    "MASTER_PARAMETER_NAMES",
    "TRAILING_BLOCKS",
    "TrailingBlock",
    "setup_dump_request",
    "parse_setup_dump",
    "SYSEX_END",
    "EMU_ID",
    "PROTEUS_ID",
    "EDITOR_BYTE",
    "BROADCAST_DEVICE",
    "Command",
    "ObjectType",
    "Parameter",
    "MidiMode",
    "NAME_LEN",
    "device_byte",
    "pack14",
    "unpack14",
    "pack14_signed",
    "unpack14_signed",
    "checksum",
    "frame",
    "parse",
    "Packet",
    "identity_request",
    "identity_reply_fields",
    "config_request",
    "parse_config",
    "HardwareConfig",
    "name_request",
    "parse_name",
    "NameReply",
    "parameter_request",
    "parameter_edit",
    "parse_parameter",
    "decode_name",
    "encode_name",
]

SYSEX_START = 0xF0
SYSEX_END = 0xF7

#: E-MU Systems' MIDI manufacturer ID (single byte).
EMU_ID = 0x18

#: Product ID for the Proteus family, immediately after the manufacturer ID.
PROTEUS_ID = 0x0F

#: Every editor message carries this after the device ID. The specification
#: calls it the "Special Editor designator byte"; it is what separates these
#: messages from the family's other System Exclusive traffic.
EDITOR_BYTE = 0x55

#: Device IDs run 00h-7Eh. 7Fh is "all", and is the only one that can be
#: used before the unit's own ID is known.
BROADCAST_DEVICE = 0x7F

#: Names are a fixed 16 characters, space-padded. Not NUL-terminated.
NAME_LEN = 16


class Command:
    """Command bytes, from the specification's command list.

    Only the ones p2ked uses are named. The numbering is not contiguous and
    is not worth guessing at: an unknown command is answered with silence,
    which is indistinguishable from every other failure on a MIDI cable.
    """

    PARAMETER_EDIT = 0x01
    PARAMETER_REQUEST = 0x02
    PARAMETER_MINMAXDEFAULT = 0x03
    PARAMETER_MINMAXDEFAULT_REQUEST = 0x04
    CONFIGURATION = 0x09
    CONFIGURATION_REQUEST = 0x0A
    GENERIC_NAME = 0x0B
    GENERIC_NAME_REQUEST = 0x0C
    PRESET_DUMP = 0x10
    PRESET_DUMP_REQUEST = 0x11
    SETUP_DUMP = 0x1C
    SETUP_DUMP_REQUEST = 0x1D


class Parameter:
    """Parameter IDs p2ked reads. Flat 14-bit numbers, not addresses."""

    #: Omni / Poly / Multi. The one that decides whether any per-channel
    #: setting means anything at all.
    MIDI_MODE = 385
    MIDI_MODE_CHANGE = 386
    MIDI_ID = 388
    #: Which channel the front panel calls "basic".
    MULTIMODE_BASIC_CHANNEL = 139
    MULTIMODE_FX_CTRL_CHANNEL = 140
    MULTIMODE_TEMPO_CTRL_CHAN = 141
    MASTER_CLOCK_TEMPO = 257
    MASTER_FX_BYPASS = 258
    MASTER_TRANSPOSE = 259
    MASTER_TUNE = 260
    MASTER_BEND_RANGE = 264
    MASTER_ARP_STATUS = 641


class MidiMode:
    """``0 = omni, 1 = poly, 2 = multi``, documented and confirmed.

    Only in **multi** is the unit multitimbral. In omni it plays the
    currently displayed preset on every channel; in poly it responds on one
    channel only. Either way the per-channel settings are not in effect, and
    a screen showing them without saying so is inviting somebody to debug a
    channel when the mode is the answer.
    """

    OMNI = 0
    POLY = 1
    MULTI = 2

    NAMES = {OMNI: "omni", POLY: "poly", MULTI: "multi"}

    @classmethod
    def name(cls, value: int) -> str:
        return cls.NAMES.get(value, f"unknown ({value})")

    @classmethod
    def is_multitimbral(cls, value: int) -> bool:
        return value == cls.MULTI


class ObjectType:
    """What a Generic Name request is asking about."""

    PRESET = 1
    INSTRUMENT = 2
    ARP = 3
    SETUP = 4
    DEMO = 5
    RIFF = 6

    NAMES = {
        PRESET: "preset",
        INSTRUMENT: "instrument",
        ARP: "arp",
        SETUP: "setup",
        DEMO: "demo",
        RIFF: "riff",
    }


class ProtocolError(ValueError):
    """A frame is not what it claims to be."""


# --- device id ---------------------------------------------------------------


def device_byte(device: int) -> int:
    """Validate a device ID and return it.

    Deliberately a no-op conversion that still exists as a function. The
    Proteus device ID needs no arithmetic -- what the front panel shows is
    what goes on the wire -- and the sibling rxved project's worst bug was a
    device-ID helper that *did* convert and could not tell which form it had
    been handed. Keeping the check in one named place is what makes it
    reviewable; adding a conversion here would be the bug.
    """
    value = int(device)
    if value == BROADCAST_DEVICE:
        return value
    if not 0x00 <= value <= 0x7E:
        raise ProtocolError(
            f"device ID {value} is outside 0-126 (and is not {BROADCAST_DEVICE}"
            f", the broadcast ID)"
        )
    return value


# --- 14-bit values -----------------------------------------------------------


def pack14(value: int) -> Tuple[int, int]:
    """A 14-bit unsigned value as ``(lsb, msb)``.

    LSB **first**, which is the order the wire wants and the opposite of the
    order the number is usually written in. Returning a tuple in wire order
    rather than two named values is deliberate: a caller cannot then write
    them out in the wrong order without it being visible at the call site.
    """
    if not 0 <= value <= 0x3FFF:
        raise ProtocolError(f"{value} does not fit in 14 bits unsigned")
    return (value & 0x7F, (value >> 7) & 0x7F)


def unpack14(lsb: int, msb: int) -> int:
    """``(lsb, msb)`` back to an unsigned 14-bit value."""
    for byte in (lsb, msb):
        if not 0 <= byte <= 0x7F:
            raise ProtocolError(f"{byte:#04x} is not a 7-bit data byte")
    return (msb << 7) | lsb


def pack14_signed(value: int) -> Tuple[int, int]:
    """A signed value as 14-bit two's complement, ``(lsb, msb)``."""
    if not -0x2000 <= value <= 0x1FFF:
        raise ProtocolError(f"{value} does not fit in 14 bits signed")
    return pack14(value & 0x3FFF)


def unpack14_signed(lsb: int, msb: int) -> int:
    """``(lsb, msb)`` back to a signed value.

    Sign-extended from bit 13. Without this a parameter of -1 reads as
    16383, which is a number a screen will happily show.
    """
    raw = unpack14(lsb, msb)
    return raw - 0x4000 if raw & 0x2000 else raw


# --- frames ------------------------------------------------------------------


def checksum(data: Iterable[int]) -> int:
    """One byte: the XOR of the data bytes.

    The specification says "1 Byte XOR(1's complement) of the sum of the
    DATA bytes", which reads as two different operations. p2ked sends
    :data:`IGNORE_CHECKSUM` rather than guess, and only on the messages that
    require the field at all -- see the module docstring and TODO.md. This
    function implements the plain XOR reading so that a device's own
    checksums can be checked against it once there is a device.
    """
    result = 0
    for byte in data:
        result ^= byte & 0x7F
    return result & 0x7F


#: "Ignore the checksum", which the specification explicitly permits.
IGNORE_CHECKSUM = 0x7F


def frame(
    command: int, payload: Sequence[int] = (), *, device: int = BROADCAST_DEVICE
) -> bytes:
    """Build an editor System Exclusive message.

    ``payload`` is everything between the command byte and ``F7``, already
    encoded -- this function does not know which commands carry a count, a
    sub-command or a checksum, and inventing that knowledge here would put
    the protocol in two places.
    """
    for byte in payload:
        if not 0 <= byte <= 0x7F:
            raise ProtocolError(
                f"{byte:#04x} is not a 7-bit data byte; every byte between "
                f"F0 and F7 must have bit 7 clear"
            )
    if not 0 <= command <= 0x7F:
        raise ProtocolError(f"command {command:#04x} is not a 7-bit value")
    return bytes(
        [
            SYSEX_START,
            EMU_ID,
            PROTEUS_ID,
            device_byte(device),
            EDITOR_BYTE,
            command,
            *payload,
            SYSEX_END,
        ]
    )


class Packet:
    """A parsed editor message."""

    __slots__ = ("device", "command", "payload")

    def __init__(self, device: int, command: int, payload: bytes) -> None:
        self.device = device
        self.command = command
        self.payload = payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Packet(device={self.device}, command={self.command:#04x}, "
            f"payload={self.payload.hex(' ')})"
        )

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, Packet)
            and other.device == self.device
            and other.command == self.command
            and other.payload == self.payload
        )


def parse(message: Sequence[int]) -> Optional[Packet]:
    """Parse one editor message, or ``None`` if it is not one of ours.

    ``None`` rather than an exception for foreign traffic: a shared MIDI
    port carries other devices' messages and other programs' messages, and
    they are not errors. A message that *is* ours and is malformed raises.
    """
    data = bytes(message)
    if len(data) < 7:
        return None
    if data[0] != SYSEX_START or data[-1] != SYSEX_END:
        return None
    if data[1] != EMU_ID or data[2] != PROTEUS_ID:
        return None
    if data[4] != EDITOR_BYTE:
        # E-MU's own non-editor SysEx, which p2ked does not speak.
        return None
    return Packet(device=data[3], command=data[5], payload=data[6:-1])


# --- universal identity ------------------------------------------------------


def identity_request(device: int = BROADCAST_DEVICE) -> bytes:
    """``F0 7E <dev> 06 01 F7`` -- not an E-MU message at all.

    The Universal Non-real-time Identity Request, which every compliant
    device answers. This is how p2ked finds a Proteus without knowing its
    device ID: broadcast it, and the reply carries both the identity and the
    ID the unit is set to.
    """
    return bytes([SYSEX_START, 0x7E, device_byte(device), 0x06, 0x01, SYSEX_END])


def identity_reply_fields(message: Sequence[int]) -> Optional[dict]:
    """Pull the fields out of an Identity Reply, or ``None``.

    Matching the *reply* sub-ID (``02``) and never the request (``01``) is
    what stops a MIDI-Thru loop being mistaken for a device: our own request
    echoed back has a different sub-ID and is rejected on sight.
    """
    data = bytes(message)
    if len(data) < 12 or data[0] != SYSEX_START or data[-1] != SYSEX_END:
        return None
    if data[1] != 0x7E or data[3] != 0x06 or data[4] != 0x02:
        return None
    return {
        "device": data[2],
        "manufacturer": data[5],
        "family": (data[6], data[7]),
        "member": (data[8], data[9]),
        "revision": tuple(data[10:14]),
        "is_emu": data[5] == EMU_ID,
    }


# --- hardware configuration --------------------------------------------------


class HardwareConfig:
    """What the unit says it is made of.

    The answer to ``Configuration Request``: how many user presets it has,
    and for each installed SIMM, that SIMM's ID and how many presets and
    instruments it holds.

    This is the message that makes p2ked a different program from its
    sibling. rxved has to *guess* which expansion board is fitted to an
    XV-2020 and sweep the instrument audibly to find out; a Proteus simply
    says.
    """

    __slots__ = ("user_presets", "simms")

    def __init__(self, user_presets: int, simms: Sequence["SimmInfo"] = ()) -> None:
        self.user_presets = user_presets
        self.simms: Tuple["SimmInfo", ...] = tuple(simms)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"HardwareConfig(user_presets={self.user_presets}, simms={self.simms!r})"

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, HardwareConfig)
            and other.user_presets == self.user_presets
            and other.simms == self.simms
        )


class SimmInfo:
    """One installed ROM, as the unit reports it."""

    __slots__ = ("simm_id", "presets", "instruments")

    def __init__(self, simm_id: int, presets: int, instruments: int) -> None:
        self.simm_id = simm_id
        self.presets = presets
        self.instruments = instruments

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SimmInfo(simm_id={self.simm_id}, presets={self.presets}, "
            f"instruments={self.instruments})"
        )

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, SimmInfo)
            and other.simm_id == self.simm_id
            and other.presets == self.presets
            and other.instruments == self.instruments
        )


def config_request(device: int = BROADCAST_DEVICE) -> bytes:
    """Ask what ROMs are installed. Read-only, and makes no sound."""
    return frame(Command.CONFIGURATION_REQUEST, device=device)


def parse_config(packet: Packet) -> HardwareConfig:
    """Decode a Configuration response.

    Layout, from the specification::

        xx                     number of general information bytes
        { aa aa }              number of user presets        (14-bit)
        yy                     number of SIMMs installed
        zz                     information bytes per SIMM
        { aa aa bb bb cc cc }  per SIMM: ID, presets, instruments

    The general-information block is read by its **declared length** rather
    than assumed to be two bytes, and the per-SIMM block likewise. A future
    model that adds a field there would otherwise be parsed one byte out for
    every SIMM, and the resulting preset counts would look almost right.
    """
    if packet.command != Command.CONFIGURATION:
        raise ProtocolError(
            f"command {packet.command:#04x} is not a Configuration response"
        )
    data = packet.payload
    if not data:
        raise ProtocolError("configuration response is empty")

    general_len = data[0]
    cursor = 1
    general = data[cursor : cursor + general_len]
    if len(general) < general_len:
        raise ProtocolError(
            f"configuration says {general_len} general bytes, {len(general)} present"
        )
    if general_len < 2:
        raise ProtocolError(
            "configuration general block is too short to hold the user preset count"
        )
    user_presets = unpack14(general[0], general[1])
    cursor += general_len

    if len(data) < cursor + 2:
        raise ProtocolError("configuration response ends before the SIMM count")
    simm_count = data[cursor]
    per_simm = data[cursor + 1]
    cursor += 2

    simms: List[SimmInfo] = []
    for index in range(simm_count):
        chunk = data[cursor : cursor + per_simm]
        if len(chunk) < per_simm:
            raise ProtocolError(
                f"configuration declares {simm_count} SIMMs but the data ends "
                f"during SIMM {index + 1}"
            )
        if per_simm < 6:
            raise ProtocolError(
                f"configuration says {per_simm} bytes per SIMM, too few for "
                f"an ID, a preset count and an instrument count"
            )
        simms.append(
            SimmInfo(
                simm_id=unpack14(chunk[0], chunk[1]),
                presets=unpack14(chunk[2], chunk[3]),
                instruments=unpack14(chunk[4], chunk[5]),
            )
        )
        cursor += per_simm
    return HardwareConfig(user_presets=user_presets, simms=simms)


# --- names -------------------------------------------------------------------


class NameReply:
    """One object's name, as the unit reports it."""

    __slots__ = ("object_type", "number", "rom_id", "name")

    def __init__(self, object_type: int, number: int, rom_id: int, name: str) -> None:
        self.object_type = object_type
        self.number = number
        self.rom_id = rom_id
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"NameReply(type={self.object_type}, number={self.number}, "
            f"rom_id={self.rom_id}, name={self.name!r})"
        )

    def __eq__(self, other) -> bool:
        return (
            isinstance(other, NameReply)
            and other.object_type == self.object_type
            and other.number == self.number
            and other.rom_id == self.rom_id
            and other.name == self.name
        )


def decode_name(data: Sequence[int]) -> str:
    """16 bytes to a string, trailing spaces removed.

    Only the trailing ones: a name may legitimately begin with a space, and
    stripping both ends would silently change it.
    """
    return "".join(chr(byte) if 32 <= byte <= 126 else " " for byte in data).rstrip()


def encode_name(name: str) -> List[int]:
    """A string to exactly :data:`NAME_LEN` bytes, space-padded."""
    trimmed = name[:NAME_LEN].ljust(NAME_LEN)
    out = []
    for char in trimmed:
        code = ord(char)
        out.append(code if 32 <= code <= 126 else 32)
    return out


def name_request(
    object_type: int, number: int, rom_id: int, *, device: int = BROADCAST_DEVICE
) -> bytes:
    """Ask for one object's name. Read-only, and **makes no sound**.

    This is the message that shapes the whole program. A Proteus will tell
    you the name of any preset in any installed ROM without selecting it, so
    p2ked can list every name without touching what the instrument is
    playing. Its sibling rxved cannot: an XV-2020's preset banks have no
    addresses, so reading their names means selecting each patch in turn and
    hearing it.
    """
    payload = [object_type, *pack14(number), *pack14(rom_id)]
    return frame(Command.GENERIC_NAME_REQUEST, payload, device=device)


def parse_name(packet: Packet) -> NameReply:
    """Decode a Generic Name response."""
    if packet.command != Command.GENERIC_NAME:
        raise ProtocolError(f"command {packet.command:#04x} is not a Generic Name")
    data = packet.payload
    if len(data) < 5 + NAME_LEN:
        raise ProtocolError(
            f"name message carries {len(data)} bytes, expected at least {5 + NAME_LEN}"
        )
    return NameReply(
        object_type=data[0],
        number=unpack14(data[1], data[2]),
        rom_id=unpack14(data[3], data[4]),
        name=decode_name(data[5 : 5 + NAME_LEN]),
    )


# --- the setup dump ----------------------------------------------------------

#: The nine per-channel parameters, in the order they appear in the dump,
#: with the range each is documented to take (parameter IDs 130-138).
#:
#: The order is the parameter-ID order, and it is **confirmed against
#: hardware**: on a unit where exactly three channels were not at factory
#: defaults, the ninth field read the Bank Select MSB of a ROM that unit
#: actually had fitted, for exactly those three channels and no others. A
#: misaligned field has no reason to land on a real ROM ID precisely where
#: the real customisation is. See docs/RESOLUTION_NOTES.md §8.
CHANNEL_PARAMETERS: Tuple[Tuple[str, int, int], ...] = (
    ("preset", 0, 895),
    ("volume", 0, 127),
    ("pan", 0, 127),
    ("mix_output", -1, 2),
    ("arp", -2, 1),
    ("enable", 0, 1),
    ("bank_map", 0, 6),
    ("receive_program_change", 0, 1),
    ("rom_id", 0, 127),
)


#: The master-parameter blocks a Setup Dump carries, in the order the dump's
#: own header declares them, as the parameter IDs each block holds.
#:
#: **Derived from hardware on 2026-09-12, not from the specification.** The
#: published example layout cannot be used -- it contradicts itself and
#: predates this firmware -- so the blocks were mapped the other way round:
#: each of these 82 values was read a second time as an individual parameter
#: with a Parameter Value Request, and compared with the dump. All 82 agreed.
#: See docs/RESOLUTION_NOTES.md §10.
#:
#: Two things to notice, because neither is guessable from the document:
#:
#: * **IDs the specification marks "(reserved)" are omitted from the dump.**
#:   That is what makes the general block twenty entries rather than the
#:   twenty-three its ID span covers, and the MIDI block twenty-two rather
#:   than twenty-five.
#: * **The block the header calls "reserved" is the Master Arpeggiator.**
#:   Its twenty-one values are parameter IDs 641-661 in order. The
#:   specification's own prose list of the dump's contents does say
#:   "Arpeggiator" at that position; only its example layout calls it
#:   reserved.
#:
#: Three IDs in here have no published name (270, 279 and 660). They are
#: decoded -- they are values at known IDs -- and simply not named; see
#: :data:`MASTER_PARAMETER_NAMES`.
MASTER_BLOCKS: Tuple[Tuple[str, Tuple[int, ...]], ...] = (
    ("master general", tuple(range(257, 261)) + tuple(range(264, 280))),
    ("master MIDI", (385, 386, 388) + tuple(range(391, 410))),
    ("master effects", tuple(range(513, 529))),
    ("master arpeggiator", tuple(range(641, 662))),
    ("non-channel", (139, 140, 141)),
)

#: The specification's name for each master parameter ID, where it has one.
#: Transcribed from the parameter list in E-MU's specification v2.2. IDs
#: absent from this table are absent from that list: they are in the dump and
#: were read back from the unit, but nobody has published what they are, and
#: inventing a name for a number is how a guess becomes a fact.
MASTER_PARAMETER_NAMES: Dict[int, str] = {
    139: "MULTIMODE_BASIC_CHANNEL",
    140: "MULTIMODE_FX_CTRL_CHANNEL",
    141: "MULTIMODE_TEMPO_CTRL_CHAN",
    257: "MASTER_CLOCK_TEMPO",
    258: "MASTER_FX_BYPASS",
    259: "MASTER_TRANSPOSE",
    260: "MASTER_TUNE",
    264: "MASTER_BEND_RANGE",
    265: "MASTER_VEL_CURVE",
    266: "MASTER_OUTPUT_FORMAT",
    267: "MASTER_KNOB_EDIT",
    268: "DEEP_EDIT",
    269: "EDIT_ALL_LAYERS",
    271: "BEATS_MODE",
    272: "BEATS_CHANNEL",
    273: "BEATS_TRIGGER_CHANNEL",
    274: "BEATS_TRIGGER_OFFSET",
    275: "BEATS_IGNORE_TEMPO",
    276: "BEATS_IGNORE_CONTROLLERS",
    277: "MASTER_RIFF_ROM_ID",
    278: "MASTER_RIFF_NDX",
    385: "MIDI_MODE",
    386: "MIDI_MODE_CHANGE",
    388: "MIDI_ID",
    391: "MIDI_A_CONTROL",
    392: "MIDI_B_CONTROL",
    393: "MIDI_C_CONTROL",
    394: "MIDI_D_CONTROL",
    395: "MIDI_E_CONTROL",
    396: "MIDI_F_CONTROL",
    397: "MIDI_G_CONTROL",
    398: "MIDI_H_CONTROL",
    399: "MIDI_FS1_CONTROL",
    400: "MIDI_FS2_CONTROL",
    401: "MIDI_FS3_CONTROL",
    402: "MIDI_TEMPO_CTRL_UP",
    403: "MIDI_TEMPO_CTRL_DOWN",
    404: "MIDI_KNOB_OUT",
    405: "MIDI_SYSEX_DELAY",
    406: "MIDI_I_CONTROL",
    407: "MIDI_J_CONTROL",
    408: "MIDI_K_CONTROL",
    409: "MIDI_L_CONTROL",
    513: "MASTER_FX_A_ALGORITHM",
    514: "MASTER_FX_A_DECAY",
    515: "MASTER_FX_A_HFDAMP",
    516: "MASTER_FXB_SEND_FXA",
    517: "MASTER_FX_A_MIX_SEND_1",
    518: "MASTER_FX_A_MIX_SEND_2",
    519: "MASTER_FX_A_MIX_SEND_3",
    520: "MASTER_FX_B_ALGORITHM",
    521: "MASTER_FX_B_FEEDBACK",
    522: "MASTER_FX_B_LFO_RATE",
    523: "MASTER_FX_B_DELAY",
    524: "MASTER_FX_B_MIX_SEND_1",
    525: "MASTER_FX_B_MIX_SEND_2",
    526: "MASTER_FX_B_MIX_SEND_3",
    527: "MASTER_FX_A_MIX_SEND_4",
    528: "MASTER_FX_B_MIX_SEND_4",
    641: "MASTER_ARP_STATUS",
    642: "MASTER_ARP_MODE",
    643: "MASTER_ARP_PATTERN",
    644: "MASTER_ARP_NOTE",
    645: "MASTER_ARP_VEL",
    646: "MASTER_ARP_GATE_TIME",
    647: "MASTER_ARP_EXT_COUNT",
    648: "MASTER_ARP_EXT_INT",
    649: "MASTER_ARP_SYNC",
    650: "MASTER_ARP_PREDELAY",
    651: "MASTER_ARP_DURATION",
    652: "MASTER_ARP_RECYCLE",
    653: "MASTER_ARP_KBD_THRU",
    654: "MASTER_ARP_LATCH",
    655: "MASTER_ARP_KR_LOW",
    656: "MASTER_ARP_KR_HIGH",
    657: "MASTER_ARP_XMIT_MIDI",
    658: "MASTER_ARP_SONG_START",
    659: "MASTER_ARP_PATTERN_SPEED",
    661: "ARP_POST_DELAY",
}

#: What follows the channel block, keyed by the ``(rows, values per row)``
#: each sub-block declares about itself.
#:
#: The dump does not stop where its header says it does. After the channel
#: block come two further self-describing sub-blocks, each a pair of counts
#: followed by that many rows -- a shape the seven-value header never
#: mentions, and the specification does not document at all.
#:
#: Identified from the specification's *prose*, which says the BEATS trigger
#: parameters are "per 24 triggers" (two of them) and the BEATS part
#: parameters "per 16 parts" (three of them). Those are exactly the two
#: shapes the unit sends, and the values agree: 24 ascending trigger keys
#: with latch off, then 16 parts at "use trigger velocity", no transpose,
#: and group 1-4 four parts at a time. Confirmed by reading IDs 160, 161,
#: 164, 165 and 166 back from the unit, which returned the selected
#: trigger's and part's row exactly. See docs/RESOLUTION_NOTES.md §10.
TRAILING_BLOCKS: Dict[Tuple[int, int], Tuple[str, Tuple[int, ...]]] = {
    (24, 2): ("BEATS triggers", (160, 161)),
    (16, 3): ("BEATS parts", (164, 165, 166)),
}


class TrailingBlock:
    """One self-describing sub-block after the channel block.

    Kept even when the shape is not one of :data:`TRAILING_BLOCKS` -- a
    block whose rows are readable but whose meaning is not is still worth
    reporting, and reporting it is how the next shape gets identified.
    """

    __slots__ = ("label", "offset", "rows", "parameter_ids")

    def __init__(
        self,
        label: str,
        offset: int,
        rows: Sequence[Tuple[int, ...]],
        parameter_ids: Tuple[int, ...],
    ) -> None:
        self.label = label
        self.offset = offset
        self.rows: Tuple[Tuple[int, ...], ...] = tuple(rows)
        #: The parameter IDs each row's values belong to, or ``()`` when the
        #: block's shape is not one p2ked recognises.
        self.parameter_ids = parameter_ids

    @property
    def identified(self) -> bool:
        return bool(self.parameter_ids)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TrailingBlock({self.label!r}, offset={self.offset}, "
            f"rows={len(self.rows)})"
        )


class ChannelState:
    """One MIDI channel's slot in a setup."""

    __slots__ = (
        "channel",
        "preset",
        "volume",
        "pan",
        "mix_output",
        "arp",
        "enable",
        "bank_map",
        "receive_program_change",
        "rom_id",
    )

    def __init__(self, channel: int, **fields) -> None:
        self.channel = channel
        for name, _low, _high in CHANNEL_PARAMETERS:
            setattr(self, name, fields.get(name, 0))

    @property
    def channel_display(self) -> int:
        return self.channel + 1

    @property
    def silent_because(self) -> Optional[str]:
        """Why this channel makes no sound, if a readable reason says so.

        Ordered nearest-cause-first, like the sibling rxved's equivalent.
        Note what is *not* here: the MIDI Mode. In Omni or Poly the unit is
        not multitimbral at all and none of these fields matter -- that is
        the caller's to know and say, because it is a property of the unit
        and not of the channel.
        """
        if not self.enable:
            return "channel is disabled"
        if self.volume == 0:
            return "volume is 0"
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ChannelState(channel={self.channel}, preset={self.preset}, "
            f"rom_id={self.rom_id}, enable={self.enable})"
        )


class SetupDump:
    """A whole setup, as the unit reports it.

    Both halves are decoded now: the per-channel block, and the master
    parameters that surround it. They were established differently and the
    difference matters --

    * the channel block is found by **structural search**, unchanged, and
      is what it always was;
    * the master blocks are decoded **by parameter ID** from
      :data:`MASTER_BLOCKS`, a mapping derived by reading every value back
      from a unit individually, not from the published layout.

    :attr:`master` is keyed by parameter ID rather than by invented
    attribute names, because the ID is the protocol's own name for the
    value and three of the IDs in the dump have no published name at all.
    :data:`MASTER_PARAMETER_NAMES` names the ones E-MU documents.

    :attr:`master` is **empty** rather than wrong when the dump's own
    arithmetic does not add up -- see :func:`parse_setup_dump`.
    """

    __slots__ = (
        "name",
        "channels",
        "channel_count",
        "parameters_per_channel",
        "offset",
        "payload_size",
        "master",
        "trailing",
        "header_counts",
        "undecoded",
    )

    def __init__(
        self,
        name: str,
        channels: Sequence["ChannelState"],
        *,
        channel_count: int,
        parameters_per_channel: int,
        offset: int,
        payload_size: int,
        master: Optional[Dict[int, int]] = None,
        trailing: Sequence["TrailingBlock"] = (),
        header_counts: Sequence[int] = (),
        undecoded: Sequence[str] = (),
    ) -> None:
        self.name = name
        self.channels: Tuple[ChannelState, ...] = tuple(channels)
        self.channel_count = channel_count
        self.parameters_per_channel = parameters_per_channel
        #: Where the channel block was found. Recorded because it was found
        #: by search, not by specification -- see :func:`parse_setup_dump`.
        self.offset = offset
        self.payload_size = payload_size
        #: Master parameter values by parameter ID. Empty when the layout
        #: could not be trusted; never partly guessed.
        self.master: Dict[int, int] = dict(master or {})
        #: The self-describing sub-blocks after the channel block.
        self.trailing: Tuple[TrailingBlock, ...] = tuple(trailing)
        #: The five block counts the header declares, in order.
        self.header_counts: Tuple[int, ...] = tuple(header_counts)
        #: Blocks that were skipped, and why, in words fit to show a user.
        self.undecoded: Tuple[str, ...] = tuple(undecoded)

    def channel(self, channel: int) -> Optional["ChannelState"]:
        for entry in self.channels:
            if entry.channel == channel:
                return entry
        return None

    def parameter(self, parameter_id: int) -> Optional[int]:
        """One master parameter, or ``None`` if this dump did not carry it.

        ``None`` and ``0`` are different answers and the caller has to tell
        them apart: a parameter absent from the dump is not a parameter set
        to zero.
        """
        return self.master.get(parameter_id)

    @property
    def midi_mode(self) -> Optional[int]:
        """Omni / Poly / Multi, if the master block decoded.

        The bridge reads this as parameter 385 directly and should keep
        doing so -- one request, no layout, no way to be wrong. This is the
        same number arriving by the long road, and is worth having only
        because a dump already in hand need not be asked again.
        """
        return self.master.get(Parameter.MIDI_MODE)

    @property
    def midi_id(self) -> Optional[int]:
        return self.master.get(Parameter.MIDI_ID)

    @property
    def basic_channel(self) -> Optional[int]:
        """0-based, like the wire. Channel 9 on the panel reads 8."""
        return self.master.get(Parameter.MULTIMODE_BASIC_CHANNEL)

    @property
    def fx_control_channel(self) -> Optional[int]:
        return self.master.get(Parameter.MULTIMODE_FX_CTRL_CHANNEL)

    @property
    def tempo_control_channel(self) -> Optional[int]:
        return self.master.get(Parameter.MULTIMODE_TEMPO_CTRL_CHAN)

    @property
    def clock_tempo(self) -> Optional[int]:
        """BPM, or ``0`` meaning the unit follows an external clock."""
        return self.master.get(Parameter.MASTER_CLOCK_TEMPO)

    @property
    def fx_bypass(self) -> Optional[int]:
        return self.master.get(Parameter.MASTER_FX_BYPASS)

    @property
    def transpose(self) -> Optional[int]:
        """Semitones, -12 to +12."""
        return self.master.get(Parameter.MASTER_TRANSPOSE)

    @property
    def tune(self) -> Optional[int]:
        """Fine tuning, -63 to +63. Not cents; the specification gives a
        table. p2ked reports the raw value rather than a conversion it has
        not checked."""
        return self.master.get(Parameter.MASTER_TUNE)

    @property
    def bend_range(self) -> Optional[int]:
        """Semitones, 0 to 12."""
        return self.master.get(Parameter.MASTER_BEND_RANGE)

    @property
    def arp_status(self) -> Optional[int]:
        return self.master.get(Parameter.MASTER_ARP_STATUS)

    def trailing_block(self, label: str) -> Optional["TrailingBlock"]:
        for block in self.trailing:
            if block.label == label:
                return block
        return None


def setup_dump_request(device: int = BROADCAST_DEVICE) -> bytes:
    """Ask for the whole setup in one message. Read-only, makes no sound."""
    return frame(Command.SETUP_DUMP_REQUEST, device=device)


def parse_setup_dump(packet: Packet) -> SetupDump:
    """Decode a Setup Dump.

    **The channel block is located by structural search, not by the
    published layout**, and that is deliberate rather than lazy. E-MU's
    specification gives an example layout whose own numbers contradict each
    other -- it allots its "0 reserved parameters" forty data bytes -- and
    the firmware this was written against is newer than any documentation to
    hand, reporting different parameter counts again. Deriving byte offsets
    from that example produces a decode that looks plausible and is wrong:
    ROM IDs of 256, values drifting upward like array indices.

    What *is* trustworthy is the dump's own header, which declares how many
    channels there are and how many parameters each has, and the documented
    range of each parameter. So the block is found by looking for the one
    offset at which every channel's every value falls inside its range. On
    the unit this was written against exactly one offset qualifies.

    Raises :class:`ProtocolError` if no offset qualifies, or if more than
    one does -- an ambiguous answer is not an answer, and guessing between
    two candidates is how the wrong one gets shipped.

    **The master parameters around it are decoded separately, and only when
    the dump's own arithmetic agrees with the search.** The header's five
    block counts, laid out from the end of the setup name, predict where the
    channel block starts. On the unit this was derived from they agree
    exactly -- 30 + 2x(20+22+16+21+3) = 194, which is where the search
    independently lands. That agreement is the licence to read the master
    blocks positionally; without it :attr:`SetupDump.master` stays empty and
    the disagreement is recorded in :attr:`SetupDump.undecoded`, because a
    master value read at the wrong offset is a plausible number nothing
    downstream can reject.

    A block whose declared count is not the number of parameter IDs p2ked
    knows for it is skipped on its own, the rest still decoded: a firmware
    that adds one parameter to one block should cost that block, not the
    dump.
    """
    if packet.command != Command.SETUP_DUMP:
        raise ProtocolError(f"command {packet.command:#04x} is not a Setup Dump")
    data = packet.payload
    if len(data) < 30:
        raise ProtocolError(
            f"setup dump carries {len(data)} bytes, too few for its header"
        )

    channel_count = unpack14(data[10], data[11])
    per_channel = unpack14(data[12], data[13])
    name = decode_name(data[14 : 14 + NAME_LEN])

    if not 0 < channel_count <= 64:
        raise ProtocolError(
            f"setup dump declares {channel_count} MIDI channels, which is "
            f"not a number this family has"
        )
    if per_channel != len(CHANNEL_PARAMETERS):
        raise ProtocolError(
            f"setup dump declares {per_channel} parameters per channel; "
            f"p2ked knows {len(CHANNEL_PARAMETERS)}. A firmware that added "
            f"one would shift every field after it, so this is refused "
            f"rather than decoded into plausible nonsense."
        )

    span = channel_count * per_channel * 2

    def fits(start: int) -> bool:
        for index in range(channel_count * per_channel):
            position = start + index * 2
            value = unpack14_signed(data[position], data[position + 1])
            _name, low, high = CHANNEL_PARAMETERS[index % per_channel]
            if not low <= value <= high:
                return False
        return True

    candidates = [start for start in range(0, len(data) - span + 1) if fits(start)]
    if not candidates:
        raise ProtocolError(
            "no offset in this setup dump holds a channel block in which "
            "every value is in range. Either the parameter order has "
            "changed or this is not a dump p2ked understands."
        )
    if len(candidates) > 1:
        raise ProtocolError(
            f"the channel block is ambiguous: offsets {candidates} all fit. "
            f"Refusing to pick one."
        )

    start = candidates[0]
    channels = []
    for index in range(channel_count):
        fields = {}
        for slot, (field, _low, _high) in enumerate(CHANNEL_PARAMETERS):
            position = start + (index * per_channel + slot) * 2
            fields[field] = unpack14_signed(data[position], data[position + 1])
        channels.append(ChannelState(index, **fields))

    counts = tuple(unpack14(data[i], data[i + 1]) for i in range(0, 10, 2))
    master, undecoded = _parse_master_blocks(data, counts, start)
    trailing, trailing_notes = _parse_trailing_blocks(data, start + span)

    return SetupDump(
        name=name,
        channels=channels,
        channel_count=channel_count,
        parameters_per_channel=per_channel,
        offset=start,
        payload_size=len(data),
        master=master,
        trailing=trailing,
        header_counts=counts,
        undecoded=undecoded + trailing_notes,
    )


def _parse_master_blocks(
    data: Sequence[int], counts: Sequence[int], channel_offset: int
) -> Tuple[Dict[int, int], Tuple[str, ...]]:
    """The five blocks between the setup name and the channel block.

    Positional, and therefore only attempted when the header's own
    arithmetic lands on the offset the structural search found.
    """
    master: Dict[int, int] = {}
    undecoded: List[str] = []

    cursor = 30 + 2 * sum(counts)
    if cursor != channel_offset:
        return master, (
            f"master parameters not decoded: the header's block counts "
            f"{tuple(counts)} put the channel block at byte {cursor}, but it "
            f"is at {channel_offset}. Reading them positionally would "
            f"produce values that look right and are not.",
        )

    cursor = 30
    for (label, ids), count in zip(MASTER_BLOCKS, counts):
        if count == len(ids):
            for index, parameter_id in enumerate(ids):
                position = cursor + index * 2
                master[parameter_id] = unpack14_signed(
                    data[position], data[position + 1]
                )
        else:
            undecoded.append(
                f"{label} block not decoded: it declares {count} parameters "
                f"and p2ked knows {len(ids)} for it. One added parameter "
                f"shifts every value after it."
            )
        cursor += count * 2
    return master, tuple(undecoded)


def _parse_trailing_blocks(
    data: Sequence[int], cursor: int
) -> Tuple[Tuple["TrailingBlock", ...], Tuple[str, ...]]:
    """Whatever follows the channel block, read as it describes itself.

    The seven-value header does not mention this region at all, so nothing
    here is taken on faith: each sub-block states its own row count and row
    width, and is decoded only if that fits inside the payload. An
    unrecognised shape is still returned -- reporting it is how the next one
    gets identified -- and a region that does not divide cleanly into
    sub-blocks is reported rather than forced.
    """
    blocks: List[TrailingBlock] = []
    notes: List[str] = []
    while cursor + 4 <= len(data):
        rows_declared = unpack14(data[cursor], data[cursor + 1])
        width = unpack14(data[cursor + 2], data[cursor + 3])
        end = cursor + 4 + rows_declared * width * 2
        if rows_declared <= 0 or width <= 0 or end > len(data):
            notes.append(
                f"the {len(data) - cursor} bytes at {cursor} are not a "
                f"self-describing block: they declare {rows_declared} rows "
                f"of {width}."
            )
            break
        rows = []
        for row in range(rows_declared):
            base = cursor + 4 + row * width * 2
            rows.append(
                tuple(
                    unpack14_signed(data[base + slot * 2], data[base + slot * 2 + 1])
                    for slot in range(width)
                )
            )
        label, ids = TRAILING_BLOCKS.get(
            (rows_declared, width), (f"unidentified {rows_declared}x{width} block", ())
        )
        blocks.append(TrailingBlock(label, cursor, rows, ids))
        cursor = end
    else:
        if cursor != len(data):
            notes.append(
                f"{len(data) - cursor} bytes at {cursor} are left over after "
                f"the trailing blocks, too few to be one."
            )
    return tuple(blocks), tuple(notes)


# --- parameters --------------------------------------------------------------


def parameter_request(parameter_id: int, *, device: int = BROADCAST_DEVICE) -> bytes:
    """Ask for one parameter's value.

    Note the shape: the Proteus is addressed by **parameter ID**, a flat
    14-bit number, where Roland's machines are addressed by a four-byte
    address into a memory map. There is no arithmetic to get wrong here and
    no base-128 carry to forget -- but equally no structure, so an ID is
    meaningful only against the specification's parameter list.
    """
    payload = [0x01, *pack14(parameter_id)]
    return frame(Command.PARAMETER_REQUEST, payload, device=device)


def parameter_edit(
    parameter_id: int, value: int, *, device: int = BROADCAST_DEVICE
) -> bytes:
    """Set one parameter. **This changes the instrument.**

    Signed, because parameter values can be negative and the encoding is
    two's complement; an unsigned-only encoder would refuse every negative
    offset the machine has.
    """
    payload = [0x02, *pack14(parameter_id), *pack14_signed(value)]
    return frame(Command.PARAMETER_EDIT, payload, device=device)


def parse_parameter(packet: Packet) -> Tuple[int, int]:
    """A Parameter Value message as ``(parameter_id, value)``.

    The value is sign-extended: parameters are signed, and reading one as
    unsigned turns -1 into 16383, which no range check would catch.
    """
    if packet.command != Command.PARAMETER_EDIT:
        raise ProtocolError(f"command {packet.command:#04x} is not a Parameter Value")
    data = packet.payload
    if len(data) < 5:
        raise ProtocolError(
            f"parameter message carries {len(data)} bytes, expected at least 5"
        )
    # data[0] is the count of byte *pairs*, which p2ked reads rather than
    # assumes: the command can legitimately carry many parameters at once.
    return (unpack14(data[1], data[2]), unpack14_signed(data[3], data[4]))
