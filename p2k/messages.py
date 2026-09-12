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

from typing import Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "SYSEX_START",
    "ChannelState",
    "SetupDump",
    "CHANNEL_PARAMETERS",
    "setup_dump_request",
    "parse_setup_dump",
    "SYSEX_END",
    "EMU_ID",
    "PROTEUS_ID",
    "EDITOR_BYTE",
    "BROADCAST_DEVICE",
    "Command",
    "ObjectType",
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


class ObjectType:
    """What a Generic Name request is asking about."""

    PRESET = 1
    INSTRUMENT = 2
    ARP = 3
    SETUP = 4
    DEMO = 5
    RIFF = 6

    NAMES = {PRESET: "preset", INSTRUMENT: "instrument", ARP: "arp",
             SETUP: "setup", DEMO: "demo", RIFF: "riff"}


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
            f", the broadcast ID)")
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


def frame(command: int, payload: Sequence[int] = (), *,
          device: int = BROADCAST_DEVICE) -> bytes:
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
                f"F0 and F7 must have bit 7 clear")
    if not 0 <= command <= 0x7F:
        raise ProtocolError(f"command {command:#04x} is not a 7-bit value")
    return bytes(
        [SYSEX_START, EMU_ID, PROTEUS_ID, device_byte(device), EDITOR_BYTE,
         command, *payload, SYSEX_END]
    )


class Packet:
    """A parsed editor message."""

    __slots__ = ("device", "command", "payload")

    def __init__(self, device: int, command: int, payload: bytes) -> None:
        self.device = device
        self.command = command
        self.payload = payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"Packet(device={self.device}, command={self.command:#04x}, "
                f"payload={self.payload.hex(' ')})")

    def __eq__(self, other) -> bool:
        return (isinstance(other, Packet) and other.device == self.device
                and other.command == self.command
                and other.payload == self.payload)


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
    return bytes([SYSEX_START, 0x7E, device_byte(device), 0x06, 0x01,
                  SYSEX_END])


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

    def __init__(self, user_presets: int,
                 simms: Sequence["SimmInfo"] = ()) -> None:
        self.user_presets = user_presets
        self.simms: Tuple["SimmInfo", ...] = tuple(simms)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"HardwareConfig(user_presets={self.user_presets}, "
                f"simms={self.simms!r})")

    def __eq__(self, other) -> bool:
        return (isinstance(other, HardwareConfig)
                and other.user_presets == self.user_presets
                and other.simms == self.simms)


class SimmInfo:
    """One installed ROM, as the unit reports it."""

    __slots__ = ("simm_id", "presets", "instruments")

    def __init__(self, simm_id: int, presets: int, instruments: int) -> None:
        self.simm_id = simm_id
        self.presets = presets
        self.instruments = instruments

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"SimmInfo(simm_id={self.simm_id}, presets={self.presets}, "
                f"instruments={self.instruments})")

    def __eq__(self, other) -> bool:
        return (isinstance(other, SimmInfo)
                and other.simm_id == self.simm_id
                and other.presets == self.presets
                and other.instruments == self.instruments)


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
            f"command {packet.command:#04x} is not a Configuration response")
    data = packet.payload
    if not data:
        raise ProtocolError("configuration response is empty")

    general_len = data[0]
    cursor = 1
    general = data[cursor:cursor + general_len]
    if len(general) < general_len:
        raise ProtocolError(
            f"configuration says {general_len} general bytes, {len(general)} "
            f"present")
    if general_len < 2:
        raise ProtocolError(
            "configuration general block is too short to hold the user "
            "preset count")
    user_presets = unpack14(general[0], general[1])
    cursor += general_len

    if len(data) < cursor + 2:
        raise ProtocolError("configuration response ends before the SIMM count")
    simm_count = data[cursor]
    per_simm = data[cursor + 1]
    cursor += 2

    simms: List[SimmInfo] = []
    for index in range(simm_count):
        chunk = data[cursor:cursor + per_simm]
        if len(chunk) < per_simm:
            raise ProtocolError(
                f"configuration declares {simm_count} SIMMs but the data ends "
                f"during SIMM {index + 1}")
        if per_simm < 6:
            raise ProtocolError(
                f"configuration says {per_simm} bytes per SIMM, too few for "
                f"an ID, a preset count and an instrument count")
        simms.append(SimmInfo(
            simm_id=unpack14(chunk[0], chunk[1]),
            presets=unpack14(chunk[2], chunk[3]),
            instruments=unpack14(chunk[4], chunk[5]),
        ))
        cursor += per_simm
    return HardwareConfig(user_presets=user_presets, simms=simms)


# --- names -------------------------------------------------------------------


class NameReply:
    """One object's name, as the unit reports it."""

    __slots__ = ("object_type", "number", "rom_id", "name")

    def __init__(self, object_type: int, number: int, rom_id: int,
                 name: str) -> None:
        self.object_type = object_type
        self.number = number
        self.rom_id = rom_id
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"NameReply(type={self.object_type}, number={self.number}, "
                f"rom_id={self.rom_id}, name={self.name!r})")

    def __eq__(self, other) -> bool:
        return (isinstance(other, NameReply)
                and other.object_type == self.object_type
                and other.number == self.number
                and other.rom_id == self.rom_id
                and other.name == self.name)


def decode_name(data: Sequence[int]) -> str:
    """16 bytes to a string, trailing spaces removed.

    Only the trailing ones: a name may legitimately begin with a space, and
    stripping both ends would silently change it.
    """
    return "".join(
        chr(byte) if 32 <= byte <= 126 else " " for byte in data
    ).rstrip()


def encode_name(name: str) -> List[int]:
    """A string to exactly :data:`NAME_LEN` bytes, space-padded."""
    trimmed = name[:NAME_LEN].ljust(NAME_LEN)
    out = []
    for char in trimmed:
        code = ord(char)
        out.append(code if 32 <= code <= 126 else 32)
    return out


def name_request(object_type: int, number: int, rom_id: int, *,
                 device: int = BROADCAST_DEVICE) -> bytes:
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
        raise ProtocolError(
            f"command {packet.command:#04x} is not a Generic Name")
    data = packet.payload
    if len(data) < 5 + NAME_LEN:
        raise ProtocolError(
            f"name message carries {len(data)} bytes, expected at least "
            f"{5 + NAME_LEN}")
    return NameReply(
        object_type=data[0],
        number=unpack14(data[1], data[2]),
        rom_id=unpack14(data[3], data[4]),
        name=decode_name(data[5:5 + NAME_LEN]),
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


class ChannelState:
    """One MIDI channel's slot in a setup."""

    __slots__ = ("channel", "preset", "volume", "pan", "mix_output", "arp",
                 "enable", "bank_map", "receive_program_change", "rom_id")

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
        return (f"ChannelState(channel={self.channel}, preset={self.preset}, "
                f"rom_id={self.rom_id}, enable={self.enable})")


class SetupDump:
    """A whole setup, as the unit reports it.

    Only the per-channel block is decoded. The master parameters that
    surround it -- including the MIDI Mode, which decides whether any of
    this matters -- are not: the specification's published layout is
    internally inconsistent *and* predates this firmware, so it cannot be
    used to find them. See TODO.md item 10.
    """

    __slots__ = ("name", "channels", "channel_count", "parameters_per_channel",
                 "offset", "payload_size")

    def __init__(self, name: str, channels: Sequence["ChannelState"], *,
                 channel_count: int, parameters_per_channel: int,
                 offset: int, payload_size: int) -> None:
        self.name = name
        self.channels: Tuple[ChannelState, ...] = tuple(channels)
        self.channel_count = channel_count
        self.parameters_per_channel = parameters_per_channel
        #: Where the channel block was found. Recorded because it was found
        #: by search, not by specification -- see :func:`parse_setup_dump`.
        self.offset = offset
        self.payload_size = payload_size

    def channel(self, channel: int) -> Optional["ChannelState"]:
        for entry in self.channels:
            if entry.channel == channel:
                return entry
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
    """
    if packet.command != Command.SETUP_DUMP:
        raise ProtocolError(
            f"command {packet.command:#04x} is not a Setup Dump")
    data = packet.payload
    if len(data) < 30:
        raise ProtocolError(
            f"setup dump carries {len(data)} bytes, too few for its header")

    channel_count = unpack14(data[10], data[11])
    per_channel = unpack14(data[12], data[13])
    name = decode_name(data[14:14 + NAME_LEN])

    if not 0 < channel_count <= 64:
        raise ProtocolError(
            f"setup dump declares {channel_count} MIDI channels, which is "
            f"not a number this family has")
    if per_channel != len(CHANNEL_PARAMETERS):
        raise ProtocolError(
            f"setup dump declares {per_channel} parameters per channel; "
            f"p2ked knows {len(CHANNEL_PARAMETERS)}. A firmware that added "
            f"one would shift every field after it, so this is refused "
            f"rather than decoded into plausible nonsense.")

    span = channel_count * per_channel * 2

    def fits(start: int) -> bool:
        for index in range(channel_count * per_channel):
            position = start + index * 2
            value = unpack14_signed(data[position], data[position + 1])
            _name, low, high = CHANNEL_PARAMETERS[index % per_channel]
            if not low <= value <= high:
                return False
        return True

    candidates = [start for start in range(0, len(data) - span + 1)
                  if fits(start)]
    if not candidates:
        raise ProtocolError(
            "no offset in this setup dump holds a channel block in which "
            "every value is in range. Either the parameter order has "
            "changed or this is not a dump p2ked understands.")
    if len(candidates) > 1:
        raise ProtocolError(
            f"the channel block is ambiguous: offsets {candidates} all fit. "
            f"Refusing to pick one.")

    start = candidates[0]
    channels = []
    for index in range(channel_count):
        fields = {}
        for slot, (field, _low, _high) in enumerate(CHANNEL_PARAMETERS):
            position = start + (index * per_channel + slot) * 2
            fields[field] = unpack14_signed(data[position], data[position + 1])
        channels.append(ChannelState(index, **fields))

    return SetupDump(name=name, channels=channels,
                     channel_count=channel_count,
                     parameters_per_channel=per_channel,
                     offset=start, payload_size=len(data))


# --- parameters --------------------------------------------------------------


def parameter_request(parameter_id: int, *,
                      device: int = BROADCAST_DEVICE) -> bytes:
    """Ask for one parameter's value.

    Note the shape: the Proteus is addressed by **parameter ID**, a flat
    14-bit number, where Roland's machines are addressed by a four-byte
    address into a memory map. There is no arithmetic to get wrong here and
    no base-128 carry to forget -- but equally no structure, so an ID is
    meaningful only against the specification's parameter list.
    """
    payload = [0x01, *pack14(parameter_id)]
    return frame(Command.PARAMETER_REQUEST, payload, device=device)


def parameter_edit(parameter_id: int, value: int, *,
                   device: int = BROADCAST_DEVICE) -> bytes:
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
        raise ProtocolError(
            f"command {packet.command:#04x} is not a Parameter Value")
    data = packet.payload
    if len(data) < 5:
        raise ProtocolError(
            f"parameter message carries {len(data)} bytes, expected at least 5")
    # data[0] is the count of byte *pairs*, which p2ked reads rather than
    # assumes: the command can legitimately carry many parameters at once.
    return (unpack14(data[1], data[2]), unpack14_signed(data[3], data[4]))
