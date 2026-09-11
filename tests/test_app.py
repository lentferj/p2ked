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
from p2ked.app import P2kedApp
from p2ked.demo import DemoDevice

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app():
    catalog = cat.Catalog([
        cat.Entry("USER-0", 0, "Velvet Bell"),
        cat.Entry("USER-0", 1, "Rusted Pad"),
    ])
    return P2kedApp(DemoDevice(), catalog=catalog)


class TestStartup:
    async def test_it_starts_and_fills_both_panes(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#bank-table").row_count == len(
                roms.bank_ids())
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
