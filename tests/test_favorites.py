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

"""The favourites store, and importing a listing into it.

Names here are invented. E-MU's preset names are not committed to this
repository, and a fixture is not an exception to that.
"""

import importlib.util
import os

import pytest

from p2k.favorites import Favorites

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "import_favourites.py")


def _tool():
    spec = importlib.util.spec_from_file_location("import_favourites", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LISTING = """\
Invented listing for the tests
=============================

Nonesuch ROM -- Bank 1     (MSB 99 | LSB 1)   [XLEAD2-1]
  marked with highlighter; PDF page 22; 3 favourite(s)
  ----------------------------------------------------
  PC   0   syn:Glass Meridian
  PC  63   led:Slow Tideline
  PC 126   pad:Amber Drift   <-- faint, please confirm

Nonesuch ROM -- Bank 3     (MSB 99 | LSB 3)   [COMPOSER-3]
  marked with highlighter; PDF page 12; 1 favourite(s)
  ----------------------------------------------------
  PC  16   prc:Kelp Forest
"""


@pytest.fixture()
def listing(tmp_path):
    path = tmp_path / "Favourites.txt"
    path.write_text(LISTING, encoding="utf-8")
    return str(path)


class TestStore:
    def test_slot_is_the_identity_not_the_name(self, tmp_path):
        db = str(tmp_path / "f.db")
        with Favorites(db) as store:
            store.add("XLEAD2-1", 63, name="led:Slow Tideline")
        with Favorites(db) as store:
            # renaming the slot must not lose the favourite
            store.add("XLEAD2-1", 63, name="something else entirely")
            assert len(store) == 1
            assert store.get("XLEAD2-1", 63) is not None

    def test_same_number_in_two_banks_is_two_favourites(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add("XLEAD2-1", 63)
            store.add("XLEAD2-2", 63)
            assert len(store) == 2


class TestImport:
    def test_parses_bank_number_and_flag(self, listing):
        rows = _tool().parse(listing)
        assert [(r[0], r[1]) for r in rows] == [
            ("XLEAD2-1", 0),
            ("XLEAD2-1", 63),
            ("XLEAD2-1", 126),
            ("COMPOSER-3", 16),
        ]
        assert rows[2][3] is True, "the faint mark should be flagged"
        assert rows[2][2] == "pad:Amber Drift", "the note is not part of the name"
        assert rows[0][3] is False

    def test_import_tags_the_faint_ones_for_checking(self, listing, tmp_path):
        db = str(tmp_path / "f.db")
        _tool().main([listing, "--favorites", db])
        with Favorites(db) as store:
            assert len(store) == 4
            flagged = store.with_tag("check-scan")
            assert [(f.bank_id, f.number) for f in flagged] == [("XLEAD2-1", 126)]

    def test_rerunning_adds_nothing(self, listing, tmp_path):
        db = str(tmp_path / "f.db")
        _tool().main([listing, "--favorites", db])
        _tool().main([listing, "--favorites", db])
        with Favorites(db) as store:
            assert len(store) == 4

    def test_replace_only_touches_the_banks_named(self, listing, tmp_path):
        db = str(tmp_path / "f.db")
        with Favorites(db) as store:
            store.add("TECHNO-0", 42, name="kept")
            store.add("XLEAD2-1", 7, name="replaced away")
        _tool().main([listing, "--favorites", db, "--replace"])
        with Favorites(db) as store:
            assert store.get("TECHNO-0", 42) is not None, (
                "a bank the listing never mentions must survive --replace"
            )
            assert store.get("XLEAD2-1", 7) is None

    def test_a_pc_line_before_any_bank_is_refused(self, tmp_path):
        path = tmp_path / "bad.txt"
        path.write_text("  PC   5   syn:Orphan\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            _tool().parse(str(path))


class TestBrowserWiring:
    """`f`, `F` and `C` in the browser. Names here are invented."""

    def _app(self, tmp_path, marks=()):
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        store = Favorites(str(tmp_path / "f.db"))
        for bank, pc in marks:
            store.add(bank, pc, name=f"invented {pc}")
        return P2kedApp(DemoDevice(), favorites=store), store

    def test_the_keys_exist(self, tmp_path):
        from p2ked.app import P2kedApp

        keys = {b.action: b.key for b in P2kedApp.BINDINGS}
        assert keys["toggle_favorite"] == "f"
        assert keys["pick_categories"] == "C"
        # `v`, not the family's `F`. `f` writes the favourites database and
        # cycling the view only reads it, so a shift-pair between them put a
        # write one slip away from a read. rxved's reasoning.
        assert keys["cycle_favorites"] == "v"

    def test_the_store_is_injected_not_opened(self, tmp_path):
        """A test must never write into the user's real database."""
        app, store = self._app(tmp_path)
        assert app.favorites is store
        store.close()

    def test_favourites_only_hides_the_rest(self, tmp_path):
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store = self._app(
            tmp_path,
            marks=[(bank, every[2].program_change), (bank, every[5].program_change)],
        )
        try:
            assert len(app._visible(bank)) == len(every)
            from p2ked.app import VIEW_BANK_FAVOURITES

            app.view_mode = VIEW_BANK_FAVOURITES
            shown = app._visible(bank)
            assert [e.program_change for e in shown] == [
                every[2].program_change,
                every[5].program_change,
            ]
        finally:
            store.close()

    def test_a_category_filter_keeps_bank_order(self, tmp_path):
        from p2k import roms

        bank = roms.bank_ids()[0]
        app, store = self._app(tmp_path)
        try:
            cats = app.categories(bank)
            if not cats:
                pytest.skip("no catalog installed, so no categories")
            app._categories = {cats[0]}
            shown = app._visible(bank)
            assert shown, "a category that exists must match something"
            numbers = [e.program_change for e in shown]
            assert numbers == sorted(numbers), "order must stay bank order"
            assert all(app.category_of(bank, n) == cats[0] for n in numbers)
        finally:
            store.close()

    def test_an_unprefixed_name_has_no_category(self, tmp_path):
        app, store = self._app(tmp_path)
        try:
            assert app.category_of("nosuchbank", 0) == ""
        finally:
            store.close()


class TestBankListing:
    """Only the ROMs the unit has, unless told otherwise."""

    def _app(self, tmp_path, installed=None):
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        store = Favorites(str(tmp_path / "f.db"))
        return P2kedApp(DemoDevice(), favorites=store, installed=installed), store

    def test_without_an_answer_every_bank_is_listed(self, tmp_path):
        """A list silently cut down by a failed query is worse than a long one."""
        from p2k import roms

        app, store = self._app(tmp_path, installed=None)
        try:
            assert app._visible_banks() == roms.bank_ids()
        finally:
            store.close()

    def test_only_the_fitted_roms_are_listed(self, tmp_path):
        from p2k import roms

        app, store = self._app(tmp_path, installed={4: True, 14: True})
        try:
            shown = app._visible_banks()
            assert shown, "something must be listed"
            assert len(shown) < len(roms.bank_ids())
            msbs = {roms.bank(b).msb for b in shown}
            assert msbs == {4, 14}
        finally:
            store.close()

    def test_the_toggle_shows_everything_again(self, tmp_path):
        from p2k import roms

        app, store = self._app(tmp_path, installed={4: True})
        try:
            assert len(app._visible_banks()) < len(roms.bank_ids())
            app._all_roms = True
            assert app._visible_banks() == roms.bank_ids()
        finally:
            store.close()

    def test_an_answer_with_nothing_fitted_still_lists_everything(self, tmp_path):
        """Better a useless list than an empty screen with no explanation."""
        from p2k import roms

        app, store = self._app(tmp_path, installed={4: False, 14: False})
        try:
            assert app._visible_banks() == roms.bank_ids()
        finally:
            store.close()

    #: Textual's key names are not what a legend shows: the key it calls
    #: left_square_bracket is printed as "[". Anything not here is expected
    #: to appear in the legend under its own name.
    SHOWN_AS = {
        "left_square_bracket": "[",
        "right_square_bracket": "]",
        "slash": "/",
        "question_mark": "?",
    }
    #: Keys the legend covers by description rather than by name.
    IMPLIED = {"enter", "tab"}

    def test_the_keys_are_all_in_the_legend(self):
        """A legend that omits a key teaches the user the key does not exist."""
        from p2ked.app import KEY_HINTS, P2kedApp

        legend = " ".join(KEY_HINTS)
        missing = []
        for binding in P2kedApp.BINDINGS:
            if binding.key in self.IMPLIED:
                continue
            shown = self.SHOWN_AS.get(binding.key, binding.key)
            if f"{shown} " not in legend:
                missing.append(binding.key)
        assert not missing, f"bound but missing from the legend: {missing}"


class TestTheThreeWayCycle:
    """`F` steps all -> this bank's favourites -> every favourite.

    Always three steps, even when a view is empty: skipping an empty one to
    be helpful makes a keypress land somewhere different depending on what
    happens to be favourited.
    """

    def _app(self, tmp_path, marks=()):
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        store = Favorites(str(tmp_path / "f.db"))
        for bank, pc in marks:
            store.add(bank, pc, name=f"invented {pc}")
        return P2kedApp(DemoDevice(), favorites=store), store

    def test_the_cycle_has_exactly_three_steps(self):
        from p2ked.app import VIEW_CYCLE, VIEW_ALL

        assert len(VIEW_CYCLE) == 3 and VIEW_CYCLE[0] == VIEW_ALL

    def test_all_favourites_spans_banks(self, tmp_path):
        from p2k import roms
        from p2ked.app import VIEW_ALL_FAVOURITES, VIEW_BANK_FAVOURITES

        a, b = roms.bank_ids()[0], roms.bank_ids()[1]
        app, store = self._app(tmp_path, marks=[(a, 3), (b, 9)])
        try:
            app.view_mode = VIEW_BANK_FAVOURITES
            assert [e.program_change for e in app._visible(a)] == [3]
            app.view_mode = VIEW_ALL_FAVOURITES
            spanning = app._visible(a)
            assert {e.bank_id for e in spanning} == {a, b}
            assert len(spanning) == 2
        finally:
            store.close()

    def test_an_unknown_bank_in_the_store_is_skipped(self, tmp_path):
        from p2ked.app import VIEW_ALL_FAVOURITES
        from p2k import roms

        app, store = self._app(
            tmp_path, marks=[(roms.bank_ids()[0], 1), ("NOSUCH-9", 4)]
        )
        try:
            app.view_mode = VIEW_ALL_FAVOURITES
            shown = app._visible(roms.bank_ids()[0])
            assert [e.program_change for e in shown] == [1]
        finally:
            store.close()

    def test_every_view_is_reachable_and_returns_to_the_start(self, tmp_path):
        from p2ked.app import VIEW_CYCLE

        app, store = self._app(tmp_path)
        try:
            seen = []
            for _ in range(len(VIEW_CYCLE) + 1):
                seen.append(app.view_mode)
                index = VIEW_CYCLE.index(app.view_mode)
                app.view_mode = VIEW_CYCLE[(index + 1) % len(VIEW_CYCLE)]
            assert seen[:-1] == list(VIEW_CYCLE)
            assert seen[-1] == VIEW_CYCLE[0], "it must wrap"
        finally:
            store.close()


@pytest.mark.asyncio
class TestTheBankPaneFits:
    """The bank pane must not clip its own labels.

    A fixed width does not truncate the end of a label; the table scrolls
    sideways and clips the *start*, so "Techno Synth bank 0" reads as
    "chno Synth bank 0" and the pane looks corrupt rather than narrow.
    """

    def _app(self, tmp_path):
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice
        from p2k import catalog as cat

        store = Favorites(str(tmp_path / "f.db"))
        return P2kedApp(DemoDevice(), catalog=cat.load(None), favorites=store), store

    @pytest.mark.parametrize("size", [(200, 50), (160, 40), (120, 40)])
    async def test_nothing_is_clipped_at_usable_widths(self, tmp_path, size):
        from textual.widgets import DataTable

        app, store = self._app(tmp_path)
        try:
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                table = app.query_one("#bank-table", DataTable)
                assert table.virtual_size.width <= table.size.width, (
                    f"the bank pane is {table.size.width} wide but needs "
                    f"{table.virtual_size.width}"
                )
        finally:
            store.close()

    async def test_the_presets_still_get_the_rest(self, tmp_path):
        from textual.widgets import DataTable

        app, store = self._app(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                banks = app.query_one("#bank-table", DataTable)
                presets = app.query_one("#preset-table", DataTable)
                assert presets.size.width > banks.size.width, (
                    "the bank pane must not eat the window"
                )
        finally:
            store.close()

    async def test_the_bank_pane_has_a_favourite_count(self, tmp_path):
        from textual.widgets import DataTable
        from p2k import roms

        bank = roms.bank_ids()[0]
        store = Favorites(str(tmp_path / "f.db"))
        store.add(bank, 3)
        store.add(bank, 9)
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        app = P2kedApp(DemoDevice(), favorites=store)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                table = app.query_one("#bank-table", DataTable)
                labels = [str(c.label) for c in table.columns.values()]
                assert "♥" in labels
                row = table.get_row(bank)
                assert row[labels.index("♥")] == "2"
        finally:
            store.close()


class TestTheChannelIsRemembered:
    """The channel set last time should be the default next time.

    rxved had the save function from its first commit and never called it,
    so it loaded a channel from a file nothing ever wrote. The round trip is
    what makes that impossible to repeat quietly.
    """

    def test_saving_then_loading_round_trips(self, tmp_path):
        from p2k import config

        path = str(tmp_path / "config.toml")
        config.save_channel(9, path)
        assert config.load_channel(path) == 9

    def test_another_setting_does_not_drop_it(self, tmp_path):
        from p2k import config

        path = str(tmp_path / "config.toml")
        config.save_channel(5, path)
        config.save_last_port("some port", path)
        assert config.load_channel(path) == 5
        assert config.load_last_port(path) == "some port"

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        from p2k import config

        assert config.load_channel(str(tmp_path / "nope.toml")) is None

    def test_an_out_of_range_channel_is_ignored(self, tmp_path):
        """A hand-edited file must not put the app on channel 99."""
        from p2k import config

        path = str(tmp_path / "config.toml")
        path_obj = tmp_path / "config.toml"
        path_obj.write_text("channel = 99\n", encoding="utf-8")
        assert config.load_channel(path) is None

    def test_an_unparsable_file_is_not_fatal(self, tmp_path):
        from p2k import config

        path_obj = tmp_path / "config.toml"
        path_obj.write_text("this is not toml = = =\n", encoding="utf-8")
        assert config.load_channel(str(path_obj)) is None


class TestEveryConstructorArgumentIsStored:
    """A keyword accepted and then dropped crashes only when used.

    config_path was added to the signature and its assignment did not land.
    Nothing failed until the channel was actually changed on a running
    program, because no test reached that line -- so the check here is
    structural rather than behavioural.
    """

    def test_the_accepted_keywords_become_attributes(self, tmp_path):
        import inspect
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        store = Favorites(str(tmp_path / "f.db"))
        try:
            app = P2kedApp(
                DemoDevice(),
                favorites=store,
                config_path=str(tmp_path / "config.toml"),
                channel=3,
                installed={4: True},
            )
            for name in inspect.signature(P2kedApp.__init__).parameters:
                if name in ("self", "device", "catalog"):
                    continue
                assert hasattr(app, name) or hasattr(app, f"_{name}"), (
                    f"{name} is accepted but never stored"
                )
        finally:
            store.close()

    def test_changing_the_channel_writes_it(self, tmp_path):
        from p2k import config
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        path = str(tmp_path / "config.toml")
        store = Favorites(str(tmp_path / "f.db"))
        try:
            app = P2kedApp(DemoDevice(), favorites=store, config_path=path)
            app._remember_channel(8)
            assert config.load_channel(path) == 8
        finally:
            store.close()


class TestUserBanksReadThemselves:
    """A catalog name for a user preset is a placeholder and always wrong.

    ROM names are fixed, so the catalog knows them. A user bank holds
    whatever somebody saved there, and only the instrument knows -- it gives
    up a whole bank in about two and a half seconds, silently.
    """

    def _app(self, tmp_path):
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        store = Favorites(str(tmp_path / "f.db"))
        return P2kedApp(DemoDevice(), favorites=store), store

    def test_user_banks_are_recognised(self, tmp_path):
        from p2k import roms

        app, store = self._app(tmp_path)
        try:
            assert app._is_user_bank("USER-0")
            assert app._is_user_bank("USER-3")
            for bank_id in roms.bank_ids():
                if bank_id.startswith("COMPOSER") or bank_id.startswith("XLEAD"):
                    assert not app._is_user_bank(bank_id)
        finally:
            store.close()

    def test_a_rom_bank_is_never_auto_read(self, tmp_path):
        app, store = self._app(tmp_path)
        try:
            app._auto_read_user_names("COMPOSER-4")
            assert "COMPOSER-4" not in app._auto_read
        finally:
            store.close()

    def test_a_user_bank_is_read_once_only(self, tmp_path):
        app, store = self._app(tmp_path)
        calls = []
        app._read_worker = lambda bank_id: calls.append(bank_id)
        try:
            app._auto_read_user_names("USER-1")
            app._auto_read_user_names("USER-1")
            app._auto_read_user_names("USER-1")
            assert calls == ["USER-1"], "re-reading on every cursor move"
        finally:
            store.close()

    def test_nothing_is_read_while_the_wire_is_busy(self, tmp_path):
        app, store = self._app(tmp_path)
        calls = []
        app._read_worker = lambda bank_id: calls.append(bank_id)
        app._busy = True
        try:
            app._auto_read_user_names("USER-2")
            assert calls == []
            assert "USER-2" not in app._auto_read, (
                "a skipped read must not count as done"
            )
        finally:
            store.close()

    def test_a_read_skipped_by_a_busy_wire_is_not_forgotten(self, tmp_path):
        """The reported bug: scrolling 0 -> 1 -> 2 quickly read bank 1 and
        then nothing, because bank 2's read was dropped on the floor.

        The old code tested ``_busy`` *before* deciding it wanted the bank,
        so a bank that arrived while the wire was busy left no trace and
        nothing re-drove it -- the cursor was already there, so no further
        highlight event was ever going to fire.
        """
        app, store = self._app(tmp_path)
        calls = []
        app._read_worker = lambda bank_id: calls.append(bank_id)
        try:
            app._auto_read_user_names("USER-1")  # the bus is free: it starts
            assert calls == ["USER-1"]
            assert app._busy is True
            app._auto_read_user_names("USER-2")  # bus busy: deferred, not lost
            assert calls == ["USER-1"]
            assert "USER-2" not in app._auto_read
            assert app._wanted == "USER-2"

            # Bank 1's read lands. This is what used to happen with nothing
            # following it.
            app._read_finished()
            assert calls == ["USER-1", "USER-2"], (
                "the deferred read was not picked up when the wire freed"
            )
            assert app._wanted is None
        finally:
            store.close()

    def test_a_deferred_read_goes_ahead_even_after_the_reader_moved_on(self, tmp_path):
        """The bank is not dropped once the cursor has left it.

        It is the same read the auto-read was always going to do, one
        cursor stop later; dropping it would mean a bank scrolled past is
        never loaded until it is visited again, which is the reported bug
        arriving by another road. What *does* clear a want is the read
        having happened.
        """
        app, store = self._app(tmp_path)
        calls = []
        app._read_worker = lambda bank_id: calls.append(bank_id)
        try:
            app._current_bank = "COMPOSER-0"
            app._wanted = "USER-2"
            app._pump_reading()
            assert calls == ["USER-2"]
            # The read is in flight: nothing else starts, and the want is
            # already consumed, so landing does not read it twice.
            assert app._wanted is None
            app._read_finished()
            assert calls == ["USER-2"], "a consumed want was re-read"
        finally:
            store.close()
