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

"""The whole-device name scan: what it reads, and what it keeps.

The scan sends only Generic Name Requests -- the silent read `r` uses -- so
there is no write gate to test. What matters is the scope (user memory and
the fitted ROMs, nothing else), that a ROM's names are kept while a user
bank's are not, and that the offer only appears when there is nothing to
start from.
"""

import asyncio
import threading
import time

import pytest

from p2k import catalog as cat
from p2k import roms
from p2ked.app import P2kedApp
from p2ked.demo import DemoDevice
from p2ked.scan import ScanOfferScreen, ScanScreen

pytestmark = pytest.mark.asyncio


class SlowDemo(DemoDevice):
    """A demo that pauses per bank, so a scan can be caught mid-flight."""

    def read_bank_names(self, bank_id, *, on_progress=None, timeout=None):
        time.sleep(0.08)
        return super().read_bank_names(
            bank_id, on_progress=on_progress, timeout=timeout
        )


def make(tmp_path, catalog=None, device=None, **kwargs):
    return P2kedApp(
        device if device is not None else DemoDevice(),
        catalog=catalog,
        favorites=None,
        installed=kwargs.pop("installed", {4: True}),
        config_path=str(tmp_path / "config.toml"),
        backup_dir=str(tmp_path / "backups"),
        **kwargs,
    )


class TestScope:
    async def test_it_reads_user_memory_and_the_fitted_roms(self, tmp_path):
        app = make(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            banks = app.scan_bank_ids()
            user = [b for b in banks if roms.bank(b).rom.writable]
            assert user == [b for b in roms.bank_ids() if roms.bank(b).rom.writable]
            # Composer (MSB 4) is the only fitted ROM, so only its banks.
            assert all(roms.bank(b).msb == 4 for b in banks if b not in user)
            assert banks  # user memory alone would still be something

    async def test_a_rom_that_is_not_fitted_is_not_scanned(self, tmp_path):
        app = make(tmp_path, installed={4: True})
        async with app.run_test() as pilot:
            await pilot.pause()
            scanned = app.scan_bank_ids()
            assert "XLEAD-0" not in scanned

    async def test_with_no_fitted_roms_it_still_scans_user_memory(self, tmp_path):
        app = make(tmp_path, installed={4: False})
        async with app.run_test() as pilot:
            await pilot.pause()
            banks = app.scan_bank_ids()
            assert banks
            assert all(roms.bank(b).rom.writable for b in banks)


class TestWhatIsKept:
    async def test_a_rom_bank_is_remembered_for_the_file(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        app = make(tmp_path, catalog=cat.Catalog([], path=path))
        async with app.run_test() as pilot:
            await pilot.pause()
            app._scan_apply("XLEAD-0", {0: "lead:One", 1: "lead:Two"})
            # Kept in memory during the scan; written once at the end.
            assert app.catalog.read_name("XLEAD-0", 1) == "lead:Two"
            assert app.catalog.save()
            assert cat.load(path).read_name("XLEAD-0", 1) == "lead:Two"

    async def test_a_user_bank_is_shown_but_not_written(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        app = make(tmp_path, catalog=cat.Catalog([], path=path))
        async with app.run_test() as pilot:
            await pilot.pause()
            app._scan_apply("USER-0", {0: "My Riff"})
            assert app.catalog.live_name("USER-0", 0) == "My Riff"
            assert app.catalog.read_name("USER-0", 0) is None
            assert not (tmp_path / "catalog.json").exists()


class TestTheOffer:
    async def _wait_for(self, app, pilot, cls, tries=120):
        for _ in range(tries):
            if isinstance(app.screen, cls):
                return True
            await asyncio.sleep(0.05)
            await pilot.pause()
        return False

    async def test_it_is_offered_when_the_catalog_is_empty(self, tmp_path):
        app = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            assert await self._wait_for(app, pilot, ScanOfferScreen)

    async def test_it_is_not_offered_when_names_are_known(self, tmp_path):
        app = make(
            tmp_path,
            catalog=cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:One")]),
            offer_scan=True,
        )
        async with app.run_test() as pilot:
            await asyncio.sleep(0.9)
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

    async def test_it_is_not_offered_unless_the_entrypoint_asks(self, tmp_path):
        """A test, a library user, or a screen shot must get no modal."""
        app = make(tmp_path, catalog=cat.empty())
        async with app.run_test() as pilot:
            await asyncio.sleep(0.9)
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

    async def test_never_remembers_the_answer(self, tmp_path, monkeypatch):
        saved = {}

        def fake_save(key, value, path=None):
            saved[key] = value

        monkeypatch.setattr("p2k.config.save_ui_state", fake_save)
        monkeypatch.setattr(
            "p2k.config.load_ui_bool", lambda key, path=None, default=None: False
        )
        app = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._scan_offer_answered("never")
            assert saved == {"scan.offer_dismissed": True}

    async def test_a_dismissed_offer_stays_dismissed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "p2k.config.load_ui_bool",
            lambda key, path=None, default=None: True,
        )
        app = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            await asyncio.sleep(0.9)
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)


class TestAWholeScan:
    async def test_it_reads_the_banks_and_keeps_the_rom_names(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        app = make(tmp_path, catalog=cat.Catalog([], path=path))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            for _ in range(200):
                if not app._busy:
                    break
                await pilot.pause()
            assert not app._busy
            # A ROM bank was read and kept; a user bank was read, not kept.
            assert app.catalog.read_name("COMPOSER-0", 0)
            assert app.catalog.live_name("USER-0", 0)
            assert app.catalog.read_name("USER-0", 0) is None

    async def test_the_demo_refuses_to_keep_anything(self, tmp_path):
        app = make(tmp_path, catalog=cat.empty(), demo=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            assert not app._busy
            assert not (tmp_path / "catalog.json").exists()

    async def test_cancelling_stops_between_banks(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        app = make(tmp_path, catalog=cat.Catalog([], path=path), device=SlowDemo())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_scan_device()
            await pilot.pause()
            assert isinstance(app.screen, ScanScreen)
            app.screen.action_cancel()
            assert app._scan_cancel.is_set()
            for _ in range(400):
                if not app._busy:
                    break
                await pilot.pause()
            assert not app._busy

    async def test_the_cancel_flag_is_what_stops_it(self):
        """The screen raises the flag; the worker reads it between banks."""
        event = threading.Event()
        screen = ScanScreen(event)
        assert not screen.cancelled
        screen.action_cancel()
        assert event.is_set()
        assert screen.cancelled
