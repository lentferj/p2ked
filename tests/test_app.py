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

"""The browser, driven headlessly against the demo device.

Names used here are invented, per CLAUDE.md.
"""

import pytest

from p2k import catalog as cat
from p2k import roms
from textual.widgets import DataTable

from p2ked.app import ChannelScreen, P2kedApp
from p2ked.demo import DemoDevice

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app():
    catalog = cat.Catalog(
        [
            cat.Entry("USER-0", 0, "Velvet Bell"),
            cat.Entry("USER-0", 1, "Rusted Pad"),
        ]
    )
    return P2kedApp(DemoDevice(), catalog=catalog)


class TestStartup:
    async def test_it_starts_and_fills_both_panes(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#bank-table").row_count == len(roms.bank_ids())
            assert app.query_one("#preset-table").row_count == 128


class TestCursorIsSilent:
    """The property that decides whether this can sit open next to a
    running sequencer. Same test as the sibling rxved's, for the same
    reason."""

    async def test_moving_in_the_preset_pane_sends_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#preset-table").focus()
            for _ in range(10):
                await pilot.press("down")
            await pilot.pause()
            assert app.device.selected_log == []

    async def test_changing_bank_sends_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(5):
                await pilot.press("down")
            await pilot.pause()
            assert app.device.selected_log == []

    async def test_enter_is_what_selects(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#preset-table").focus()
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            assert len(app.device.selected_log) == 1


class TestReadingNamesIsSilent:
    """The thing p2ked can do that its sibling cannot.

    Reading a bank's names sends only System Exclusive requests. If this
    ever starts selecting presets, the help text and the README become
    lies, and somebody's take gets interrupted.
    """

    async def test_r_reads_names_without_selecting_anything(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app.device.selected_log == []
            assert app.catalog.is_live("USER-0", 0)

    async def test_the_names_read_come_from_the_device(self, app):
        from p2ked.demo import demo_name

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app.catalog.live_name("USER-0", 5) == demo_name("USER-0", 5)

    async def test_a_user_bank_read_is_not_flagged_as_edited(self, app):
        """The reported bug: every preset in every user bank carried `*`.

        The catalog's user-bank "names" are E-MU's placeholders, so reading
        a real bank off the unit and comparing produced 128 differences and
        128 footnotes saying "saved over the factory preset" -- on a bank
        nobody had edited, and on a bank that had, indistinguishably.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app.catalog.is_live("USER-0", 0)
            assert not app.catalog.differs("USER-0", 0)
            assert app.catalog.disagreement("USER-0", 0) is None

    async def test_the_first_read_is_the_session_baseline(self, app):
        """Nothing is marked on the read that establishes the baseline --
        there is no earlier state for it to be different from."""
        said: list[str] = []
        app.notify_status = lambda message, **_kw: said.append(message)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app._baseline["USER-0"], "the read left no baseline"
            assert not app._session_change("USER-0", 0)
            assert any("baseline" in m for m in said)

    async def test_a_name_changed_since_p2ked_was_opened_is_flagged(self, app):
        """The signal that used to be claimed from a document that could
        not support it: the unit says something different now."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            original = app.catalog.live_name("USER-0", 0)
            # What a second read would find after the preset is edited
            # elsewhere -- on the unit's front panel, or by another tool.
            app.catalog.set_live_name("USER-0", 0, "Edited Somewhere Else")
            assert app._session_change("USER-0", 0)
            assert app._marked_because("USER-0", 0) == (
                "changed since p2ked was opened"
            )
            assert original != "Edited Somewhere Else"
            # The mark survives a re-render and is not re-anchored by it.
            app._fill_presets("USER-0")
            assert app._session_change("USER-0", 0), "the baseline re-anchored"

    async def test_a_bank_never_read_this_session_cannot_be_flagged(self, app):
        """No baseline, no mark: p2ked does not guess what a bank held."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert not app._session_change("USER-1", 0)
            assert app._marked_because("USER-1", 0) is None

    async def test_the_status_line_counts_session_changes(self, app):
        """The status line is where the change is announced; the row then
        carries it for the rest of the session."""
        said: list[str] = []
        app.notify_status = lambda message, **_kw: said.append(message)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            said.clear()
            # Stand in for the answer a second read would get back.
            app._adopt_names("USER-0", {0: "Edited Somewhere Else", 1: "Another Edit"})
            assert any("2 changed since p2ked was opened" in m for m in said)

    async def test_an_unchanged_second_read_says_so(self, app):
        said: list[str] = []
        app.notify_status = lambda message, **_kw: said.append(message)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            said.clear()
            app._adopt_names("USER-0", dict(app._baseline["USER-0"]))
            assert any("nothing changed" in m for m in said)
            assert not any("differ" in m for m in said)


class TestOneOperationAtATime:
    """The `_busy` flag: one thing on the wire, and a refusal rather than a
    queue.

    It is the only thing stopping two concurrent workers, and it used to be
    dead code -- checked in four places, set in none of them, so every
    check read `False` forever and the flag it was written to guard never
    happened. A bank read is about two and a half seconds, so a second
    press during one is a real wait, not a theoretical one.
    """

    @pytest.fixture
    def wired(self):
        """An app whose workers are counted instead of run.

        Spawning is the question, not traffic: a worker can sit in the
        pool before its first line, so "did it send anything" cannot tell
        a refused operation from a slow one.
        """
        app = P2kedApp(DemoDevice(), catalog=cat.empty())
        spawned = []

        app._read_worker = lambda bank: spawned.append(("read", bank))
        app._channels_worker = lambda: spawned.append(("channels",))
        app._info_worker = lambda: spawned.append(("info",))
        app._select_worker = lambda entry: spawned.append(("select",))
        return app, spawned

    async def test_nothing_starts_while_the_wire_is_busy(self, wired):
        app, spawned = wired
        async with app.run_test() as pilot:
            await pilot.pause()
            spawned.clear()
            app._busy = True
            app.action_read_names()
            app.action_channels()
            app.action_device_info()
            app.query_one("#preset-table").focus()
            app.action_select_preset()
            assert spawned == [], f"refused operations still started: {spawned}"

    async def test_the_flag_is_taken_before_the_worker_is_spawned(self, wired):
        """The race the flag exists for.

        ``@work(thread=True)`` returns immediately, so a worker that set
        the flag on its own thread would set it too late and two presses
        in one tick would both pass. Set synchronously here, the first
        press finishes the assignment before the second is dispatched.
        """
        app, spawned = wired
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            spawned.clear()
            for _ in range(5):
                app.action_read_names()
            assert len(spawned) == 1, spawned
            assert app._busy is True

    async def test_a_finished_read_releases_the_wire(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            app.action_read_names()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "a successful read never released it"

    async def test_a_failed_operation_releases_the_wire(self):
        """A worker that raises must not strand the flag.

        Otherwise one bad cable leaves the browser permanently refusing
        every operation, and the only symptom is a status bar that keeps
        saying "busy".
        """

        class Broken(DemoDevice):
            def read_bank_names(self, *args, **kwargs):
                raise TimeoutError("no reply")

        app = P2kedApp(Broken(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            app.action_read_names()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "a failed read stranded the flag"

    async def test_device_info_releases_the_wire(self, app):
        """`i` clears it too, which it did not: it had no `_busy` handling
        at all, so once the flag started working, pressing `i` would lock
        the browser for good."""
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            app.action_device_info()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "the info screen stranded the flag"

    async def test_a_selection_releases_the_wire(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#preset-table").focus()
            app._busy = False
            app.action_select_preset()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "a selection stranded the flag"


class TestChannel:
    async def test_selection_goes_out_on_the_chosen_channel(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.channel = 9
            app.query_one("#preset-table").focus()
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            assert len(app.device.selected_log) == 1
            _entry, channel = app.device.selected_log[0]
            assert channel == 9, (
                "the selection went out on the wrong channel; the test used "
                "to assert only that something was sent"
            )


class TestChannelScreen:
    """The channel view, and what it refuses to claim.

    Its job is to say which channels would sound. Its other job, equally
    load-bearing, is to say that it does not know the MIDI Mode -- in Omni
    or Poly none of these settings apply, and a screen that quietly implied
    otherwise would send somebody hunting a channel setting when the mode is
    the problem. That is the mistake the sibling rxved made on a real synth.
    """

    async def _open(self, app, pilot):
        await pilot.pause()
        await pilot.press("m")
        for _ in range(8):
            await pilot.pause()
        return app.screen

    async def test_m_opens_it_with_every_channel(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            assert isinstance(screen, ChannelScreen)
            table = screen.query_one("#channel-table", DataTable)
            assert table.row_count == 32

    async def test_opening_it_selects_nothing(self, app):
        async with app.run_test() as pilot:
            await self._open(app, pilot)
            assert app.device.selected_log == []

    async def test_it_names_what_a_channel_plays(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            table = screen.query_one("#channel-table", DataTable)
            keys = [c.key.value for c in table.columns.values()]
            # Demo channel 9 is enabled and points at a real ROM.
            plays = str(table.get_row("8")[keys.index("plays")])
            assert "Composer" in plays

    async def test_both_reasons_for_silence_are_distinguished(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            reasons = {
                c.channel_display: c.silent_because for c in screen._dump.channels
            }
            assert reasons[1] == "channel is disabled"
            assert reasons[6] == "volume is 0"  # enabled, but silent
            assert reasons[9] is None

    async def test_it_says_which_channels_would_sound(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            report = " ".join(screen._lines())
            assert "Channels that would sound: 9, 10" in report

    async def test_the_midi_mode_is_read_and_shown(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            from p2k.messages import MidiMode

            assert screen._mode == MidiMode.MULTI

    async def test_a_non_multitimbral_mode_suppresses_the_rest(self):
        """In Omni the channel settings are stored but not in effect.

        Listing per-channel faults there would send somebody to fix a
        channel when the mode is the answer -- the exact wrong turn the
        sibling rxved nearly took on an XV-2020.
        """
        from p2k.messages import MidiMode
        from p2ked.app import ChannelScreen

        dump = DemoDevice().read_setup()
        screen = ChannelScreen(dump, cat.empty(), MidiMode.OMNI)
        lines = screen._lines()
        assert len(lines) == 1
        assert "NOT multitimbral" in lines[0]
        assert "not in effect" in lines[0]

    async def test_an_unreadable_mode_is_said_not_assumed(self):
        from p2ked.app import ChannelScreen

        dump = DemoDevice().read_setup()
        screen = ChannelScreen(dump, cat.empty(), None)
        report = " ".join(screen._lines())
        assert "could not be read" in report
        assert "rather than assuming" in report

    async def test_it_explains_the_second_interface(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            assert "two MIDI interfaces" in " ".join(screen._lines())
