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

"""The defects an external audit raised, each pinned by a test.

Every fixture here is invented. The audit is credited in TODO.md; three of
its findings did not survive checking and are not represented here, because
a test for something the code does not do is a test that never fails.
"""

import sqlite3

import pytest

from p2k import catalog as cat
from p2k import config
from p2k import favorites as fav
from p2ked.app import P2kedApp
from p2ked.demo import DemoDevice


@pytest.fixture
def store(tmp_path):
    with fav.Favorites(str(tmp_path / "f.db")) as db:
        yield db


@pytest.fixture
def app():
    return P2kedApp(DemoDevice(), catalog=cat.empty())


class TestUnfavouritingKeepsWhatTheUserTyped:
    """Item 25. The one finding on the list that lost data.

    `f` un-favourites without asking, and the row was deleted -- so a
    rating, tags, a note and the original date went with it, on the store
    this project's own documentation calls genuinely the user's.
    """

    def test_a_toggle_cycle_keeps_rating_tags_and_note(self, store):
        store.add("XLEAD2-1", 5, name="Invented",
                  rating=4, tags="a, b", note="hello")
        before = store.get("XLEAD2-1", 5)

        assert store.toggle("XLEAD2-1", 5) is False     # off
        assert store.get("XLEAD2-1", 5) is None, "it should not be a favourite"
        assert store.toggle("XLEAD2-1", 5) is True      # on again

        after = store.get("XLEAD2-1", 5)
        assert (after.rating, after.tags, after.note) == (4, "a, b", "hello")
        assert after.added == before.added, (
            "the date it was first favourited is the one ordering the user "
            "cannot reconstruct")

    def test_an_unfavourited_slot_is_not_a_favourite(self, store):
        store.add("XLEAD2-1", 5, name="Invented", rating=3)
        store.remove("XLEAD2-1", 5)
        assert len(store) == 0
        assert store.keys() == set()
        assert store.keys_for_bank("XLEAD2-1") == set()
        assert store.all() == []
        assert store.search("Invented") == []
        assert "XLEAD2-1:005" not in store

    def test_what_it_still_holds_is_visible(self, store):
        store.add("XLEAD2-1", 5, name="Invented", rating=3)
        store.remove("XLEAD2-1", 5)
        held = store.dormant()
        assert [(f.bank_id, f.number, f.rating) for f in held] == [
            ("XLEAD2-1", 5, 3)]

    def test_forget_really_deletes(self, store):
        store.add("XLEAD2-1", 5, name="Invented", rating=3)
        store.remove("XLEAD2-1", 5)
        assert store.forget("XLEAD2-1", 5) is True
        assert store.dormant() == []

    def test_a_v1_database_upgrades_without_losing_rows(self, tmp_path):
        """The column is added to an existing file, not required of it."""
        path = str(tmp_path / "old.db")
        db = sqlite3.connect(path)
        db.executescript(
            """
            CREATE TABLE favorites (
                bank_id TEXT NOT NULL, number INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT '', rating INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
                added REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (bank_id, number));
            """)
        db.execute("INSERT INTO favorites (bank_id, number, name, rating) "
                   "VALUES ('XLEAD2-1', 7, 'Invented', 5)")
        db.execute("PRAGMA user_version = 1")
        db.commit()
        db.close()

        with fav.Favorites(path) as store:
            kept = store.get("XLEAD2-1", 7)
            assert kept is not None, "an existing row must stay a favourite"
            assert kept.rating == 5


class TestTheChannelKeys:
    """Item 24. `[` and `]` were bound to actions that did not exist."""

    async def test_the_keys_move_the_channel(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.channel = 4
            await pilot.press("]")
            for _ in range(3):
                await pilot.pause()
            assert app.channel == 5
            await pilot.press("[")
            for _ in range(3):
                await pilot.pause()
            assert app.channel == 4

    async def test_they_clamp_rather_than_wrap(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.channel = 15
            await pilot.press("]")
            for _ in range(3):
                await pilot.pause()
            assert app.channel == 15, "channel 16 must not wrap to 1"
            app.channel = 0
            await pilot.press("[")
            for _ in range(3):
                await pilot.pause()
            assert app.channel == 0

    async def test_moving_the_channel_sends_no_midi(self, app):
        """The cursor-silence rule, applied to these keys."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("]")
            await pilot.press("[")
            for _ in range(4):
                await pilot.pause()
            assert app.device.selected_log == []


class TestEnterMeansTheRowYouAreLookingAt:
    """Item 35. With neither table focused, Enter played the hidden pane."""

    async def test_enter_does_nothing_when_the_preset_pane_is_not_focused(
            self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.set_focus(None)
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            assert app.device.selected_log == [], (
                "Enter played a preset from a pane the user is not in")

    async def test_enter_still_works_when_it_is_focused(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#preset-table").focus()
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            assert len(app.device.selected_log) == 1


class TestSearchSaysWhenTheUnitDisagrees:
    """Items 12 and 23. The browser marked it; search dropped the mark."""

    def _catalog(self):
        c = cat.empty()
        c._entries["lead:005"] = cat.Entry(bank_id="lead", program_change=5,
                                           name="Printed Name")
        c._entries["lead:006"] = cat.Entry(bank_id="lead", program_change=6,
                                           name="Printed Other")
        c.set_live_name("lead", 5, "Printed Name")      # agrees
        c.set_live_name("lead", 6, "Saved Over")        # disagrees
        return c

    def test_a_hit_carries_whether_the_two_sources_differ(self):
        c = self._catalog()
        assert c.search("printed name") == [("lead", 5, "Printed Name", False)]
        assert c.search("saved over") == [("lead", 6, "Saved Over", True)]


class TestSplitRefusesABareBankId:
    """Item 30. Its docstring is the contract; int('') is not a message."""

    def test_it_names_the_problem(self):
        with pytest.raises(ValueError, match="names a bank but not a slot"):
            fav._split("XLEAD2-1")

    def test_the_forms_it_documents_still_work(self):
        assert fav._split(("XLEAD2-1", 63)) == ("XLEAD2-1", 63)
        assert fav._split("XLEAD2-1:063") == ("XLEAD2-1", 63)

    def test_membership_inherits_the_message(self, store):
        with pytest.raises(ValueError, match="names a bank but not a slot"):
            "XLEAD2-1" in store


class TestNamesReachTheFavouritesWhenTheUnitSuppliesThem:
    """Item 28. refresh_names existed, documented for this, never called."""

    async def test_reading_a_bank_relabels_its_favourites(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "f.db"))
        app = P2kedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            store.add("USER-0", 0, name="")
            app._adopt_names("USER-0", {0: "Invented By Unit"})
            await pilot.pause()
            assert store.get("USER-0", 0).name == "Invented By Unit"
        store.close()


class TestARememberedPort:
    """Item 27. The config module could remember it; nothing ever did."""

    def test_the_port_round_trips(self, tmp_path):
        path = str(tmp_path / "config.toml")
        config.save_last_port("U6MIDI Pro:U6MIDI Pro MIDI 1 44:0", path)
        assert config.load_last_port(path) == (
            "U6MIDI Pro:U6MIDI Pro MIDI 1 44:0")

    def test_a_device_id_of_true_is_not_device_1(self, tmp_path):
        """isinstance(True, int) is True, and device 1 is a real device.

        A wrong device ID is answered with silence by this instrument,
        which is the failure mode that hides behind every other.
        """
        path = str(tmp_path / "config.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("device_id = true\n")
        assert config.load_device_id(path) is None

    def test_an_out_of_range_device_id_is_ignored(self, tmp_path):
        path = str(tmp_path / "config.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("device_id = 999\n")
        assert config.load_device_id(path) is None
