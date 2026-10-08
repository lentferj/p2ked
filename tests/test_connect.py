# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# p2ked is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# p2ked is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.

"""How a launch finds the unit: the remembered port, and the sweep.

Ported in the same shape as the sibling x5ded's and rxved's
tests/test_connect.py.

The browser here already had *a* remembered-port path, inline in
`p2ked/app.py`, and p2kcli had none at all -- so every `p2kcli` invocation
broadcast an Identity Request on every bidirectional MIDI port on the
machine. The browser's inline path was closer to right: it tried the
remembered port first and fell through to the sweep. But it fell through
*silently*, which is indistinguishable from the fast path having worked, and
it was thirty lines of argument-handling in `main()` rather than something
with a name and a test. Both are now `ProteusBridge.connect()`.

What is tested here is the *wiring*, not the policy: the policy itself is
`vinsynlib.midi.open_remembered_or_swept`, and its own tests live with it.
These prove that p2ked hands it the right probe, the right remembered pair,
and the right answer to --scan.

No hardware and no MIDI ports here: `open` and `autodetect` are stubbed with
what they would have found. p2k/bridge.py is at 24% coverage and has never
had a synthetic test -- it needs a cable -- so nothing here pretends to cover
the wire.
"""

from __future__ import annotations

import pytest

from p2k import bridge as b
from p2k import config as cfg

PROTEUS_PORT = "Midi Out: E-MU Proteus 2000 1 20:0"
OTHER_PORT = "Midi Out: Scarlett 18i8 USB MIDI 1 24:0"
SPLIT_IN = "Midi In: Something Else 1 30:0"

#: What `identify` returns on a port. `is_emu` is the decision; `device` is
#: what the reported ID is read from. Invented, like the rest of the suite's
#: fixtures.
REPLY = {
    "manufacturer": 0x7D,
    "device": 0x09,
    "family": (0x00, 0x00),
    "is_emu": True,
}
FOREIGN_REPLY = {"manufacturer": 0x42, "device": 0x00, "is_emu": False}


class _FakeBridge:
    """Stands in for an opened bridge. Closes are counted, not needed."""

    def __init__(self, port, recv, *, answers, device_id, timeout=None):
        self.port = port
        self.recv_port = recv
        #: What identify() returns: REPLY for a Proteus, None for a port that
        #: stays silent, FOREIGN_REPLY for someone else's box. None and a
        #: foreign reply are the same case to this code -- not the unit.
        self.answers = answers
        self.device_id = device_id
        #: The timeout the bridge was opened with, NOT the session default.
        #: Keeping the two apart is what lets the timeout test fail when the
        #: probe forgets to reset it.
        self.timeout = b.DEFAULT_TIMEOUT if timeout is None else timeout
        self.closed = False

    def identify(self, *, timeout=None):
        return self.answers

    def learn_device_id(self, *, timeout=None):
        """Adopt the reported ID, or None when there is no E-MU there."""
        if not self.answers or not self.answers.get("is_emu"):
            return None
        self.device_id = self.answers["device"]
        return self.device_id

    def close(self):
        self.closed = True


class _Rig:
    """Records what was opened, what answered, and whether a sweep happened.

    `answering` maps a port name to what identify() returns there. `ports` is
    what the host actually has, which is not the same thing -- a remembered
    name can still be a port with nothing behind it, and that is the case
    --scan exists for.
    """

    def __init__(self, answering, *, ports=None):
        self.answering = answering
        self.ports = ports if ports is not None else list(answering)
        self.opened = []
        self.tried = []
        self.swept = 0
        self.made = []

    def install(self, monkeypatch):
        rig = self

        def fake_open(
            cls,
            /,
            port,
            *,
            recv_port=None,
            device_id=0,
            **rest,
        ):
            # `rest` is `timeout=...`, the discovery timeout. It is passed
            # through to the fake bridge rather than dropped: the test that
            # cares asserts bridge.timeout changed from it, which can only
            # fail if the stub actually received it.
            assert set(rest) <= {"timeout"}, f"unexpected kwargs: {rest}"
            rig.opened.append(port)
            made = _FakeBridge(
                port,
                recv_port or port,
                answers=rig.answering.get(port),
                device_id=device_id,
                timeout=rest.get("timeout"),
            )
            rig.made.append(made)
            return made

        def fake_autodetect(
            cls,
            *,
            timeout=b.AUTODETECT_TIMEOUT,
            on_try=None,
            exclude=(),
            device_id=None,
        ):
            # Mirrors the real one's shape -- hinted ports first, the
            # `is_emu` flag decides rather than a name, excluded ports are
            # skipped -- so the ordering, the decision and the exclusion are
            # exercised rather than stubbed away.
            rig.swept += 1
            for name in rig.ports:
                if name in exclude:
                    continue
                if on_try is not None:
                    on_try(name)
                rig.tried.append(name)
                reply = rig.answering.get(name)
                if reply and reply.get("is_emu"):
                    chosen = reply["device"] if device_id is None else device_id
                    return fake_open(cls, name, device_id=chosen)
            raise b.DeviceNotFound("nothing answered")

        monkeypatch.setattr(b, "list_ports", lambda: (list(rig.ports), list(rig.ports)))
        monkeypatch.setattr(b, "likely_proteus_ports", lambda: [])
        monkeypatch.setattr(b.ProteusBridge, "open", classmethod(fake_open))
        monkeypatch.setattr(b.ProteusBridge, "autodetect", classmethod(fake_autodetect))
        return rig

    def unclosed(self):
        """Bridges that were opened and never closed."""
        return [x.port for x in self.made if not x.closed]


def _remembered(tmp_path, send=PROTEUS_PORT, recv=""):
    """A settings file holding one remembered port pair."""
    path = str(tmp_path / "config.toml")
    cfg.save_ports(send, recv or send, path)
    return path


# --- the normal path: trust the config ---------------------------------------


class TestTheRememberedPort:
    def test_it_is_used_without_sweeping(self, monkeypatch, tmp_path):
        """One Identity Request to the saved port, and nothing else.

        The whole point. A sweep pings every MIDI device on the machine once
        per launch and takes seconds on a box with thirty ports -- and this
        unit never gets found by name, because it is behind whatever
        interface the user happens to have.
        """
        path = _remembered(tmp_path)
        rig = _Rig({PROTEUS_PORT: REPLY, OTHER_PORT: None}).install(monkeypatch)

        b.ProteusBridge.connect(config_path=path)

        assert rig.swept == 0, "swept every port when the answer was on file"
        assert rig.opened == [PROTEUS_PORT]

    def test_the_remembered_pair_is_both_halves(self, monkeypatch, tmp_path):
        """The input port is remembered too, so a unit on a separate
        interface does not fall back to probing the output name."""
        path = str(tmp_path / "config.toml")
        cfg.save_ports(OTHER_PORT, SPLIT_IN, path)
        _Rig({OTHER_PORT: REPLY}).install(monkeypatch)

        got = b.ProteusBridge.connect(config_path=path)

        assert got.recv_port == SPLIT_IN

    def test_the_device_id_is_learned_not_assumed(self, monkeypatch, tmp_path):
        """Broadcast on the way in, the reported ID on the way out.

        This Proteus ignores the broadcast ID for everything except identity,
        so a bridge left on it reads nothing. Both paths learn the ID from the
        reply; neither assumes 0.
        """
        path = _remembered(tmp_path)
        rig = _Rig({PROTEUS_PORT: REPLY}).install(monkeypatch)

        got = b.ProteusBridge.connect(config_path=path)

        assert rig.opened == [PROTEUS_PORT]
        assert got.device_id == REPLY["device"], "the ID was not adopted"
        assert got.device_id != 0

    def test_the_session_timeout_is_not_the_probe_timeout(self, monkeypatch, tmp_path):
        """A short discovery timeout must not become the working one.

        Otherwise every later request that does not name its own runs at the
        probe's value, and a slow but working connection looks like a timeout
        on every call.
        """
        path = _remembered(tmp_path)
        _Rig({PROTEUS_PORT: REPLY}).install(monkeypatch)

        got = b.ProteusBridge.connect(config_path=path)

        assert got.timeout == b.DEFAULT_TIMEOUT
        assert got.timeout != b.AUTODETECT_TIMEOUT

    def test_it_does_not_rewrite_the_config(self, monkeypatch, tmp_path):
        """The file is this path's *input*.

        Rewriting it unchanged would make a plain launch mutate the thing it
        was asked to trust, and any later change to what is stored would be
        invisible in a diff. This is what the browser's inline
        remembered-port path got wrong: it wrote on the fast path too.
        """
        path = _remembered(tmp_path)
        _Rig({PROTEUS_PORT: REPLY}).install(monkeypatch)

        b.ProteusBridge.connect(config_path=path)

        assert cfg.load_last_port(path) == PROTEUS_PORT

    def test_someone_elses_box_is_not_the_unit(self, monkeypatch, tmp_path):
        """An Identity Reply from another manufacturer is a reply, and not an
        answer. Using it would send a preset change to hardware the user
        never chose."""
        path = _remembered(tmp_path)
        rig = _Rig({PROTEUS_PORT: FOREIGN_REPLY, OTHER_PORT: REPLY}).install(
            monkeypatch
        )

        got = b.ProteusBridge.connect(config_path=path)

        assert rig.swept == 1, "a foreign reply was taken for the unit"
        assert got.port == OTHER_PORT

    def test_a_dead_remembered_port_leaves_nothing_open(self, monkeypatch, tmp_path):
        path = _remembered(tmp_path)
        rig = _Rig({PROTEUS_PORT: None, OTHER_PORT: REPLY}).install(monkeypatch)

        b.ProteusBridge.connect(config_path=path)

        # The remembered one was closed on the way to falling back; the one
        # the sweep found is the caller's to close.
        assert rig.made[0].port == PROTEUS_PORT
        assert rig.made[0].closed is True


# --- the fallback: sweep ----------------------------------------------------


class TestTheSweep:
    def test_it_runs_when_nothing_is_remembered(self, monkeypatch, tmp_path):
        """A first run, and every p2kcli invocation before this commit."""
        path = str(tmp_path / "config.toml")  # never written
        rig = _Rig({OTHER_PORT: REPLY}).install(monkeypatch)

        b.ProteusBridge.connect(config_path=path)

        assert rig.swept == 1
        assert OTHER_PORT in rig.tried

    def test_it_runs_when_asked_for(self, monkeypatch, tmp_path):
        """--scan: what is needed after the unit moves to a renumbered port.

        The saved name is still a port on this host -- it is what the unit
        was on -- and nothing answers there now, because the unit is
        somewhere else. `ports` says it exists; `answering` says what is
        behind it.
        """
        path = _remembered(tmp_path)
        rig = _Rig({OTHER_PORT: REPLY}, ports=[PROTEUS_PORT, OTHER_PORT]).install(
            monkeypatch
        )

        got = b.ProteusBridge.connect(config_path=path, scan=True)

        assert rig.swept == 1
        assert got.port == OTHER_PORT, "opened the saved port anyway"

    def test_scan_does_not_probe_the_remembered_port_first(self, monkeypatch, tmp_path):
        """--scan asks for the sweep, not for a check of the file and then
        the sweep."""
        path = _remembered(tmp_path)
        rig = _Rig({OTHER_PORT: REPLY}, ports=[PROTEUS_PORT, OTHER_PORT]).install(
            monkeypatch
        )

        b.ProteusBridge.connect(config_path=path, scan=True)

        assert rig.opened == [OTHER_PORT], "the saved port was probed first"

    def test_a_dead_remembered_port_falls_back_and_says_so(self, monkeypatch, tmp_path):
        """Not silently. This is the one thing the browser's inline
        remembered-port path got wrong: it fell through to the sweep and
        printed only the sweep's own lines, so a launch that had lost its
        port looked exactly like a fast one."""
        path = _remembered(tmp_path)
        rig = _Rig({PROTEUS_PORT: None, OTHER_PORT: REPLY}).install(monkeypatch)
        said: list[str] = []

        got = b.ProteusBridge.connect(config_path=path, on_try=said.append)

        assert rig.swept == 1
        assert got.port == OTHER_PORT
        assert said[0] == f"{PROTEUS_PORT} (remembered, did not answer)"

    def test_the_fast_path_says_nothing(self, monkeypatch, tmp_path):
        """One Identity Request, and silence about it."""
        path = _remembered(tmp_path)
        _Rig({PROTEUS_PORT: REPLY}).install(monkeypatch)
        said: list[str] = []

        b.ProteusBridge.connect(config_path=path, on_try=said.append)

        assert said == []

    def test_it_remembers_what_it_found(self, monkeypatch, tmp_path):
        """The end the whole thing is for: one sweep, then never again."""
        path = str(tmp_path / "config.toml")
        _Rig({PROTEUS_PORT: REPLY}, ports=[OTHER_PORT, PROTEUS_PORT]).install(
            monkeypatch
        )

        b.ProteusBridge.connect(config_path=path)

        assert cfg.load_last_port(path) == PROTEUS_PORT

    def test_the_next_launch_does_not_sweep(self, monkeypatch, tmp_path):
        path = str(tmp_path / "config.toml")
        first = _Rig({PROTEUS_PORT: REPLY}, ports=[OTHER_PORT, PROTEUS_PORT])
        first.install(monkeypatch)
        b.ProteusBridge.connect(config_path=path)
        assert first.swept == 1

        second = _Rig({PROTEUS_PORT: REPLY}, ports=[OTHER_PORT, PROTEUS_PORT])
        second.install(monkeypatch)
        b.ProteusBridge.connect(config_path=path)

        assert second.swept == 0
        assert second.opened == [PROTEUS_PORT]

    def test_nothing_answered_is_the_sweeps_own_error(self, monkeypatch, tmp_path):
        """The user needs the sweep's sentence, not the stale port's."""
        path = _remembered(tmp_path)
        _Rig({PROTEUS_PORT: None, OTHER_PORT: None}).install(monkeypatch)

        with pytest.raises(b.DeviceNotFound, match="nothing answered"):
            b.ProteusBridge.connect(config_path=path)

    def test_on_try_is_optional(self, monkeypatch, tmp_path):
        """`--demo` and library callers pass none, and that must not crash."""
        path = str(tmp_path / "config.toml")
        _Rig({OTHER_PORT: REPLY}).install(monkeypatch)

        b.ProteusBridge.connect(config_path=path)

    def test_the_sweep_still_names_each_port_it_tries(self, monkeypatch, tmp_path):
        """The family's existing reporting, unchanged: one line per port
        tried, built from the on_try the caller supplies as
        "  probing <port>..."."""
        path = str(tmp_path / "config.toml")
        _Rig({OTHER_PORT: REPLY}, ports=[PROTEUS_PORT, OTHER_PORT]).install(monkeypatch)
        said: list[str] = []

        b.ProteusBridge.connect(config_path=path, on_try=said.append)

        assert said, "the sweep said nothing about what it was trying"
        assert said[0] == PROTEUS_PORT, "said so out of order"
        assert said[-1] == OTHER_PORT

    def test_a_dead_remembered_port_is_not_probed_twice(self, monkeypatch, tmp_path):
        """The sweep skips the port the probe just found dead.

        Without the exclusion every fallback pays the stale port's discovery
        timeout a second time, for an answer it already has.
        """
        path = _remembered(tmp_path)
        rig = _Rig({PROTEUS_PORT: None, OTHER_PORT: REPLY}).install(monkeypatch)

        b.ProteusBridge.connect(config_path=path)

        assert rig.opened.count(PROTEUS_PORT) == 1
        assert PROTEUS_PORT not in rig.tried

    def test_the_fallback_reason_reaches_the_caller(self, monkeypatch, tmp_path):
        """`on_fallback` gets the port and the error, so a front end can say
        *why* the remembered port failed -- the difference between "the unit
        moved" and "no MIDI backend at all"."""
        path = _remembered(tmp_path)
        _Rig({PROTEUS_PORT: None, OTHER_PORT: REPLY}).install(monkeypatch)
        heard: list[tuple[str, BaseException]] = []

        b.ProteusBridge.connect(
            config_path=path,
            on_fallback=lambda port, exc: heard.append((port, exc)),
        )

        assert heard and heard[0][0] == PROTEUS_PORT
        assert isinstance(heard[0][1], b.DeviceError)

    def test_a_missing_backend_is_not_reported_as_a_stale_port(
        self, monkeypatch, tmp_path
    ):
        """No MIDI backend is not a remembered port that went quiet."""
        path = _remembered(tmp_path)

        def unavailable(*_a, **_k):
            raise b.MidiUnavailable("no MIDI backend available")

        monkeypatch.setattr(b.ProteusBridge, "open", classmethod(unavailable))
        with pytest.raises(b.MidiUnavailable):
            b.ProteusBridge.connect(config_path=path)

    def test_a_named_device_id_is_used_rather_than_overwritten(
        self, monkeypatch, tmp_path
    ):
        """`--device-id` a caller already knows must survive the reply."""
        path = str(tmp_path / "config.toml")
        _Rig({OTHER_PORT: REPLY}).install(monkeypatch)

        got = b.ProteusBridge.connect(config_path=path, device_id=5)

        assert got.device_id == 5, "the reply overwrote the caller's device ID"


# --- the remembered-pair reader ---------------------------------------------


class TestTheRememberedPair:
    def test_nothing_remembered_is_nothing(self, tmp_path):
        path = str(tmp_path / "config.toml")
        assert cfg.load_port_pair(path) is None

    def test_one_port_is_a_whole_pair(self, tmp_path):
        """The browser has always written `recv_port` only when it differed
        from `port`, so a config with only `port` is the common case and must
        read as a complete pair. Reading it as half a pair would mean
        sweeping on every launch, which is the thing this exists to stop."""
        path = str(tmp_path / "config.toml")
        cfg.save_last_port(PROTEUS_PORT, path)
        assert cfg.load_port_pair(path) == (PROTEUS_PORT, PROTEUS_PORT)

    def test_a_separate_input_port_is_kept(self, tmp_path):
        path = str(tmp_path / "config.toml")
        cfg.save_ports(PROTEUS_PORT, SPLIT_IN, path)
        assert cfg.load_port_pair(path) == (PROTEUS_PORT, SPLIT_IN)


# --- the error taxonomy -----------------------------------------------------


def test_the_errors_are_the_family_s_own():
    """So `open_remembered_or_swept` can recognise a probe that failed, and
    so p2kcli's existing `except midi.MidiUnavailable` covers the local
    class. RuntimeError throughout, so no `except` clause in p2ked changed
    what it catches."""
    assert issubclass(b.DeviceError, b.midi.DeviceError)
    assert issubclass(b.DeviceNotFound, b.midi.DeviceNotFound)
    assert issubclass(b.MidiUnavailable, b.midi.MidiUnavailable)
    assert issubclass(b.DeviceError, RuntimeError)
    assert issubclass(b.DeviceNotFound, RuntimeError)
    assert not issubclass(b.DeviceNotFound, b.DeviceError), (
        "nothing answered is not the same fault as answered wrongly"
    )
