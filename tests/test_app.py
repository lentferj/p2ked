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

    async def test_a_difference_from_the_catalog_is_flagged(self, app):
        """A user bank somebody has saved into is the most useful thing
        this screen can point out."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app.catalog.differs("USER-0", 0)


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
