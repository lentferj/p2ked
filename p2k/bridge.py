# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# The port-enumeration helpers, the throttled send, the drain-before-request
# discipline and the clean-exit handling are ported from the sibling rxved
# project's xv/bridge.py, which ports them from s3ked, eosed, k2kremote and
# mpc2emu:
#   Copyright (C) 2025-2026  mpc2emu contributors    - GPL-2.0-or-later
#   Copyright (C) 2026  k2kremote contributors       - GPL-2.0-or-later
#   Copyright (C) 2026  eosed contributors           - GPL-2.0-or-later
#   Copyright (C) 2026  s3ked contributors           - GPL-2.0-or-later
#   Copyright (C) 2026  rxved contributors           - GPL-2.0-or-later
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

"""MIDI transport and device operations for the Proteus family.

**Partly verified against hardware on 2026-09-12.** Identity, Hardware
Configuration and Generic Name were exercised against a real Proteus 2000
and all three worked as written. Everything else here -- parameter edits,
preset dumps, the checksum rule, ``SEND_GAP`` -- has still only ever been
run against :class:`p2ked.demo.DemoDevice`, which was written from the same
reading of the same document, so its agreement proves nothing about them.
DISCLAIMER.md sets out which is which.

Two things shape this module, and both are *advantages* over the Roland
machine the sibling rxved talks to.

**Names are free.** ``Generic Name Request`` returns any preset's name in
any installed ROM without selecting it, so p2ked never has to play the
instrument to learn what is in it. rxved's equivalent operation sends a
program change per slot and is audible for as long as it takes; there is no
counterpart here, and no confirmation prompt, because there is nothing to
warn about.

**The unit says what ROMs it has.** ``Configuration Request`` reports the
installed SIMMs with their IDs and preset counts. rxved has to guess which
expansion board is fitted and sweep to find out.

What is *worse* here: the reply to a request carries no address to match it
against, only an object type and number, so a late reply to an abandoned
request is harder to tell from the answer to the current one. Every request
therefore drains the input first and checks that the reply describes the
object that was asked about.
"""

from __future__ import annotations

import signal
import sys
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import rtmidi  # noqa: E402

from p2k import messages as m
from p2k import roms

__all__ = [
    "SEND_GAP",
    "DEFAULT_TIMEOUT",
    "AUTODETECT_TIMEOUT",
    "MidiUnavailable",
    "DeviceError",
    "DeviceNotFound",
    "list_ports",
    "bidirectional_ports",
    "likely_proteus_ports",
    "install_clean_exit",
    "ProteusBridge",
]

#: Gap enforced after an outgoing message.
#:
#: **A GUESS.** E-MU's specification asks senders to avoid messages over 244
#: data bytes but gives no inter-message timing at all. This is the sibling
#: projects' conservative default. It is not measured, and a name sweep of a
#: 1024-preset ROM spends a thousand of these, so it is also the first thing
#: to measure once there is hardware. See TODO.md.
SEND_GAP = 0.010

#: How long to wait for a reply. Generous: a request a device cannot serve
#: is not refused, it is ignored, so a short timeout turns "busy" into
#: "absent".
DEFAULT_TIMEOUT = 2.0

#: Per-port budget during autodetect.
AUTODETECT_TIMEOUT = 0.6

#: Substrings that hint a port belongs to a Proteus-family unit. Used only
#: to order the autodetect sweep, never to decide the answer -- the Identity
#: Reply decides that. A unit on a DIN cable sits behind an interface whose
#: name says nothing about it.
_HINTS = ("proteus", "audity", "xtreme", "e-mu", "emu", "mp-7", "xl-7",
          "px-7", "pk-6", "halo", "vintage keys", "orbit")


class MidiUnavailable(RuntimeError):
    """No MIDI backend on this host at all."""


class DeviceError(RuntimeError):
    """The device answered, but not with what was asked for."""


class DeviceNotFound(RuntimeError):
    """Nothing answered an Identity Request on any port tried."""


# --- ports -------------------------------------------------------------------


def _client(kind: str):
    try:
        return rtmidi.MidiIn() if kind == "in" else rtmidi.MidiOut()
    except Exception as exc:  # pragma: no cover - depends on the host
        raise MidiUnavailable(
            f"no MIDI backend available ({exc}). On Linux this needs an ALSA "
            f"sequencer; in a container it must be passed through."
        ) from exc


def list_ports() -> Tuple[List[str], List[str]]:
    """``(inputs, outputs)``.

    Both clients are closed before returning. rtmidi leaks its backend
    handle if they are not, which on ALSA shows up later as ports that
    cannot be reopened -- a fault inherited, and fixed, in the sibling
    projects.
    """
    midi_in = _client("in")
    midi_out = _client("out")
    try:
        return (list(midi_in.get_ports()), list(midi_out.get_ports()))
    finally:
        midi_in.delete()
        midi_out.delete()


def bidirectional_ports() -> List[str]:
    """Ports that exist as both an input and an output.

    A synthesizer that can be asked a question has both. Anything else
    cannot answer, so probing it costs a timeout for nothing.
    """
    ins, outs = list_ports()
    return [name for name in ins if name in outs]


def likely_proteus_ports() -> List[str]:
    lowered = [(name, name.lower()) for name in bidirectional_ports()]
    return [name for name, low in lowered if any(h in low for h in _HINTS)]


def install_clean_exit(on_exit: Optional[Callable[[], None]] = None) -> None:
    """Close ports on SIGINT/SIGTERM rather than leaving them open."""
    def handler(signum, _frame):  # pragma: no cover - signal path
        if on_exit is not None:
            try:
                on_exit()
            except Exception:
                pass
        sys.exit(128 + signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):  # pragma: no cover - not main thread
            pass


# --- the bridge --------------------------------------------------------------


class ProteusBridge:
    """One open conversation with one unit."""

    def __init__(self, midi_in, midi_out, *, device_id: int,
                 description: str = "",
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self._in = midi_in
        self._out = midi_out
        self.device_id = m.device_byte(device_id)
        self.description = description
        self.timeout = timeout
        self.config: Optional[m.HardwareConfig] = None
        self.selected: Optional[roms.Preset] = None
        self._in.ignore_types(sysex=False, timing=True, active_sense=True)

    # --- lifecycle ----------------------------------------------------------

    @classmethod
    def open(cls, port: str, *, recv_port: Optional[str] = None,
             device_id: int = m.BROADCAST_DEVICE,
             timeout: float = DEFAULT_TIMEOUT) -> "ProteusBridge":
        ins, outs = list_ports()
        listen = recv_port or port
        if port not in outs:
            raise DeviceError(
                f"no output port named {port!r}; have {outs}")
        if listen not in ins:
            raise DeviceError(
                f"no input port named {listen!r}; have {ins}")
        midi_out = _client("out")
        midi_in = _client("in")
        midi_out.open_port(outs.index(port))
        midi_in.open_port(ins.index(listen))
        return cls(midi_in, midi_out, device_id=device_id,
                   description=f"{port} -> {listen}", timeout=timeout)

    def close(self) -> None:
        for client in (self._in, self._out):
            try:
                client.close_port()
                client.delete()
            except Exception:  # pragma: no cover - teardown
                pass

    # --- the wire ------------------------------------------------------------

    def _drain(self) -> None:
        """Throw away anything already waiting.

        Without this, a reply left over from a timed-out exchange is picked
        up as the answer to the *next* request -- which during a name sweep
        means every name attached to the wrong preset.
        """
        while self._in.get_message() is not None:
            pass

    def _send(self, frame: bytes) -> None:
        self._out.send_message(list(frame))
        time.sleep(SEND_GAP)

    def _await(self, matches: Callable[[m.Packet], bool], *,
               timeout: Optional[float] = None) -> m.Packet:
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        while time.time() < deadline:
            message = self._in.get_message()
            if message is None:
                time.sleep(0.002)
                continue
            packet = m.parse(message[0])
            if packet is None:
                continue          # somebody else's traffic on a shared port
            if packet.device not in (self.device_id, m.BROADCAST_DEVICE):
                continue
            if matches(packet):
                return packet
        raise TimeoutError(
            "no reply. A Proteus does not refuse a request it cannot serve, "
            "it ignores it -- so this means one of: powered off, wrong port, "
            f"device ID mismatch (p2ked is using {self.device_id}), System "
            "Exclusive disabled on the unit, or simply busy. It does not "
            "distinguish them and neither can this message."
        )

    # --- identity ------------------------------------------------------------

    def identify(self, *, timeout: Optional[float] = None) -> Optional[dict]:
        """Ask who is on the other end, on the already-open ports."""
        self._drain()
        self._out.send_message(list(m.identity_request(m.BROADCAST_DEVICE)))
        deadline = time.time() + (
            AUTODETECT_TIMEOUT if timeout is None else timeout)
        while time.time() < deadline:
            message = self._in.get_message()
            if message is None:
                time.sleep(0.002)
                continue
            fields = m.identity_reply_fields(message[0])
            if fields is not None:
                return fields
        return None

    @classmethod
    def autodetect(cls, *, timeout: float = AUTODETECT_TIMEOUT,
                   on_try: Optional[Callable[[str], None]] = None
                   ) -> "ProteusBridge":
        """Find a unit by broadcasting an Identity Request on every port.

        Hinted ports are tried first, which only changes the order. The
        reply decides, and it carries the device ID the unit is set to --
        so discovery ends knowing what to address, with no sweep over IDs.
        """
        hinted = likely_proteus_ports()
        candidates = hinted + [p for p in bidirectional_ports()
                               if p not in hinted]
        if not candidates:
            raise DeviceNotFound(
                "no bidirectional MIDI ports on this host, so nothing can "
                "be asked who it is.")
        for port in candidates:
            if on_try is not None:
                on_try(port)
            bridge = cls.open(port, device_id=m.BROADCAST_DEVICE,
                              timeout=timeout)
            try:
                fields = bridge.identify(timeout=timeout)
            except Exception:
                bridge.close()
                continue
            if fields is not None and fields.get("is_emu"):
                bridge.device_id = m.device_byte(fields["device"])
                return bridge
            bridge.close()
        raise DeviceNotFound(
            "nothing identifying itself as an E-MU device answered on any "
            "port. Check the cable, that the unit is on, and that its System "
            "Exclusive reception is enabled."
        )

    # --- operations ----------------------------------------------------------

    def hardware_config(self, *, timeout: Optional[float] = None
                        ) -> m.HardwareConfig:
        """What ROMs are installed. Read-only, makes no sound.

        The message that saves p2ked from guessing. Its result is cached on
        the bridge because it cannot change while the unit is powered.
        """
        self._drain()
        self._send(m.config_request(device=self.device_id))
        packet = self._await(
            lambda p: p.command == m.Command.CONFIGURATION, timeout=timeout)
        self.config = m.parse_config(packet)
        return self.config

    def preset_name(self, number: int, rom_id: int, *,
                    timeout: Optional[float] = None) -> str:
        """One preset's name. Read-only, and **makes no sound**.

        A unit answers for a preset that does not exist rather than
        ignoring the request: the name comes back as
        :data:`p2k.roms.NOT_INSTALLED`. Callers that care should use
        :func:`p2k.roms.is_absent` rather than expecting a timeout.

        The reply is matched on the object type, number *and* ROM ID it
        describes, not merely on being a name message. There is no address
        in this protocol to match against, so without that check a late
        reply to an abandoned request is indistinguishable from the answer
        to this one -- and during a bank sweep that is every name shifted by
        one preset.
        """
        self._drain()
        self._send(m.name_request(m.ObjectType.PRESET, number, rom_id,
                                  device=self.device_id))

        def matches(packet: m.Packet) -> bool:
            if packet.command != m.Command.GENERIC_NAME:
                return False
            try:
                reply = m.parse_name(packet)
            except m.ProtocolError:
                return False
            return (reply.object_type == m.ObjectType.PRESET
                    and reply.number == number and reply.rom_id == rom_id)

        return m.parse_name(self._await(matches, timeout=timeout)).name

    def rom_id_for(self, bank: roms.Bank) -> int:
        """The System Exclusive ROM ID to use for a bank.

        ``0`` for user memory, which is documented. For a ROM it returns the
        Bank Select MSB, which is **a hypothesis** -- see
        :func:`p2k.roms.rom_for_simm_id`. If the unit has been asked for its
        configuration and reports no SIMM with that ID, this raises rather
        than sending a request that would be answered with silence.
        """
        if bank.rom is roms.USER:
            return roms.USER_ROM_ID
        wanted = bank.rom.msb
        if self.config is not None:
            known = {simm.simm_id for simm in self.config.simms}
            if wanted not in known:
                raise DeviceError(
                    f"this unit reports SIMM IDs {sorted(known)} and none is "
                    f"{wanted}, which is what p2ked would use for "
                    f"{bank.rom.name}. Either that ROM is not fitted, or "
                    f"p2ked's assumption that a SIMM ID equals the Bank "
                    f"Select MSB is wrong -- see TODO.md."
                )
        return wanted

    def read_bank_names(self, bank_id: str, *,
                        on_progress: Optional[Callable[[int, int], None]] = None,
                        timeout: Optional[float] = None) -> Dict[int, str]:
        """Every name in a bank. Read-only, and **makes no sound**.

        Worth restating because the sibling project cannot do it: this reads
        128 preset names out of a ROM without changing what the instrument
        is playing. There is no prompt and no ``--yes`` because there is
        nothing to warn about.
        """
        bank = roms.bank(bank_id)
        rom_id = self.rom_id_for(bank)
        entries = roms.presets(bank_id)
        out: Dict[int, str] = {}
        for index, entry in enumerate(entries, start=1):
            try:
                name = self.preset_name(entry.number, rom_id, timeout=timeout)
            except TimeoutError:
                # One missing name is not a reason to lose the other 127.
                name = None
            if name is not None and not roms.is_absent(name):
                # Empty slots are kept: "default" is what the unit says, and
                # a blank row would leave the user wondering whether the
                # read failed or the slot is genuinely empty.
                out[entry.program_change] = name
            if on_progress is not None:
                on_progress(index, len(entries))
        return out

    def read_parameter(self, parameter_id: int, *,
                       timeout: Optional[float] = None) -> int:
        """One parameter's value. Read-only, makes no sound.

        The reply is matched on the parameter ID it reports, not merely on
        being a parameter message -- there is no address in this protocol to
        match against, and a late reply to an abandoned request would
        otherwise be taken as the answer to this one.
        """
        self._drain()
        self._send(m.parameter_request(parameter_id, device=self.device_id))

        def matches(packet: m.Packet) -> bool:
            if packet.command != m.Command.PARAMETER_EDIT:
                return False
            try:
                return m.parse_parameter(packet)[0] == parameter_id
            except m.ProtocolError:
                return False

        return m.parse_parameter(self._await(matches, timeout=timeout))[1]

    def midi_mode(self, *, timeout: Optional[float] = None) -> int:
        """Omni, Poly or Multi. See :class:`p2k.messages.MidiMode`.

        Read as a parameter rather than out of the setup dump: the dump
        carries it somewhere in the master block p2ked cannot yet locate,
        and this is one documented request that needs no layout at all.
        """
        return self.read_parameter(m.Parameter.MIDI_MODE, timeout=timeout)

    def read_setup(self, *, timeout: Optional[float] = None) -> m.SetupDump:
        """The whole multi/channel setup in one message. Silent.

        One round trip for all 32 channels, where reading the same data as
        individual parameters would need the stateful
        ``MULTIMODE_CHANNEL_SELECT`` set first and then nine requests per
        channel -- 288 exchanges, each depending on a selector set by an
        earlier one.
        """
        self._drain()
        self._send(m.setup_dump_request(device=self.device_id))
        packet = self._await(
            lambda p: p.command == m.Command.SETUP_DUMP, timeout=timeout)
        return m.parse_setup_dump(packet)

    def installed_roms(self, *, timeout: Optional[float] = None
                       ) -> Dict[int, bool]:
        """Which ROM IDs this unit actually answers for. Silent.

        One name request per ROM in the table, reading the reply rather than
        waiting for a timeout: a unit answers a request for an absent ROM
        with the name ``(not installed)``. That makes presence a fast,
        positive test instead of a slow, ambiguous one -- a timeout would
        equally mean the cable is out.

        Independent of :meth:`hardware_config`, and worth having as well as
        it: the configuration response lists SIMMs, this asks the question
        the name reader will actually ask.
        """
        out: Dict[int, bool] = {}
        for entry in roms.ROMS:
            rom_id = (roms.USER_ROM_ID if entry is roms.USER else entry.msb)
            try:
                name = self.preset_name(0, rom_id, timeout=timeout)
            except TimeoutError:
                continue          # unknown, not absent -- say nothing
            out[rom_id] = not roms.is_absent(name)
        return out

    def select(self, entry: roms.Preset, *, channel: int = 0) -> None:
        """Select a preset. **This changes what the unit is playing.**

        Bank Select MSB (CC 0), Bank Select LSB (CC 32), then Program
        Change, in that order -- the bank bytes must arrive before the
        program change or it lands in whichever bank was already selected.
        """
        if not 0 <= channel <= 15:
            raise ValueError(f"channel {channel} is outside 0-15")
        status = 0xB0 | channel
        self._out.send_message([status, 0x00, entry.msb])
        self._out.send_message([status, 0x20, entry.lsb])
        self._out.send_message([0xC0 | channel, entry.program_change])
        time.sleep(SEND_GAP)
        self.selected = entry
