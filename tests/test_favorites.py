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

from p2k.favorites import Favorites, rating_cell
from p2ked.app import RatingFilterScreen
from p2ked.multi import ValuePickerScreen

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
        # The rating pair. `*` is Textual's *asterisk* key, and `V` is the
        # shift pair of `v` -- one of them writes a rating and the other
        # only narrows, so neither sits one slip away from its twin.
        assert keys["edit_rating"] == "asterisk"
        assert keys["rating_filter"] == "V"

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
    """The unit's ROMs, the ones p2ked can name, and always user memory."""

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
            # MSB 0 is user memory: it is always present on the unit and does
            # not depend on a ROM being fitted, so it is always listed.
            assert msbs == {0, 4, 14}
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
        # `*` is the asterisk key to Textual and an asterisk to a reader.
        # The rating is bound to it rather than to `r`, which is already
        # reading names off the unit.
        "asterisk": "*",
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


async def _until(pilot, ready, attempts=40) -> None:
    """Wait until ``ready()`` is true, or fail saying so.

    A fixed count of pauses would be a guess about how many trips through
    the message loop this machine takes, and a guess in a test is a flake.
    """
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


class TestRatingCell:
    """What the rating column shows, and which glyph it is shown with.

    A rating is the only annotation that reads as a picture, so the
    rendering is worth pinning on its own: blank for "not rated" rather
    than five dots, and five cells rather than three stars, because
    ``★★★`` is ambiguous where ``★★★··`` is not.
    """

    def test_a_slot_with_no_rating_is_blank(self):
        """Blank for "not rated", the way the favourite marker column is."""
        assert rating_cell(0) == ""

    def test_a_full_rating_is_five_stars(self):
        assert rating_cell(5) == "★★★★★"

    def test_a_partial_rating_shows_the_rest_dim(self):
        assert rating_cell(3) == "★★★··"
        assert rating_cell(1) == "★····"

    def test_it_keeps_the_catalogue_marker_to_itself(self):
        """``*`` means "the unit and the book disagree" in this table.

        In the name column, on the detail line, in ``p2kcli find`` and in
        ``p2kcli names``. A rating is the user's own opinion of a slot and
        that mark is a fact about one, so they cannot share a glyph.
        """
        for stars in range(6):
            assert "*" not in rating_cell(stars), stars

    def test_it_is_the_library_s_own_function(self):
        """p2ked keeps no copy: one function decides the whole cell.

        The behaviour tests above pin what the cell reads; this pins that
        there is only *one* thing that decides it. A local copy could pass
        every one of them and then drift from the library's the first time
        either side was edited, which is the drift the re-export exists to
        make impossible.
        """
        from vinsynlib.favorites import rating_cell as family_rating_cell

        assert rating_cell is family_rating_cell


@pytest.mark.asyncio
class TestTheRatingKey:
    """``*`` rates the favourite under the cursor, 0 to 5.

    The picker is the master editor's own -- the same list an enumerated
    parameter opens -- so the answer is a number of stars rather than a
    number to type, and ``no rating`` is one of the six rows.
    """

    def _app(self, tmp_path, marks=()):
        """An app over the first bank, with ``marks`` already favourited.

        ``marks`` is ``(program change, rating)`` pairs.
        """
        from p2k import roms
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        bank = roms.bank_ids()[0]
        store = Favorites(str(tmp_path / "f.db"))
        for program_change, rating in marks:
            store.add(
                bank,
                program_change,
                name=f"invented {program_change}",
                rating=rating,
            )
        app = P2kedApp(DemoDevice(), favorites=store)
        return app, store, bank

    def _row(self, app, program_change: int) -> int:
        """Where a preset sits in the table, which is bank order."""
        return [e.program_change for e in app._current].index(program_change)

    async def _pick(self, app, pilot, stars: int) -> None:
        """One row of the open picker, and enter."""
        app.screen.query_one("#choices").move_cursor(row=stars)
        await pilot.pause()
        await pilot.press("enter")
        await _until(pilot, lambda: not isinstance(app.screen, ValuePickerScreen))

    async def _rate(self, app, pilot, program_change: int, stars: int) -> None:
        """The whole gesture: ``*``, then a row in the picker, then enter."""
        table = app.query_one("#preset-table")
        table.focus()
        table.move_cursor(row=self._row(app, program_change))
        await pilot.pause()
        await pilot.press("asterisk")
        await _until(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
        await self._pick(app, pilot, stars)

    async def test_asterisk_rates_the_favourite_under_the_cursor(self, tmp_path):
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(
            tmp_path,
            marks=[(every[2].program_change, 0), (every[5].program_change, 0)],
        )
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await self._rate(app, pilot, every[2].program_change, 3)
                row = store.get(bank, every[2].program_change)
                assert row is not None and row.rating == 3
                # The row next door keeps what it had, which the picker
                # makes easy to check and easy to get wrong.
                assert store.get(bank, every[5].program_change).rating == 0
        finally:
            store.close()

    async def test_the_picker_opens_on_what_the_slot_already_has(self, tmp_path):
        """Six rows, the current one marked and under the cursor.

        Opening on the current rating rather than at the top is the same
        courtesy the enumerations give, and it is what makes ``*`` twice
        on a slot the cheapest way to see what it has.
        """
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 4)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app.query_one("#preset-table").focus()
                app.query_one("#preset-table").move_cursor(
                    row=self._row(app, every[2].program_change)
                )
                await pilot.press("asterisk")
                await _until(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
                choices = app.screen.query_one("#choices")
                assert choices.cursor_row == 4
                assert "now ★★★★·" in str(app.screen.query_one("Label").visual)
                # The first row is the words, not a blank: a rating of
                # nothing has to be choosable and not merely implied.
                assert choices.get_row("0") == ["no rating"]
                assert choices.get_row("4") == ["[b]★★★★·[/b]"]
        finally:
            store.close()

    async def test_asterisk_changes_a_rating_that_is_already_there(self, tmp_path):
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 4)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await self._rate(app, pilot, every[2].program_change, 2)
                assert store.get(bank, every[2].program_change).rating == 2
        finally:
            store.close()

    async def test_rating_nothing_keeps_the_favourite(self, tmp_path):
        """A rating of 0 clears the annotation, not the favourite.

        ``set_rating`` writes the column and leaves the row alone, so the
        slot stays favourited with its tags, note and date intact. The
        name is not asserted: this bank is read on sight and the read
        adopts whatever the unit says, which is the app's own doing.
        """
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 3)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await self._rate(app, pilot, every[2].program_change, 0)
                row = store.get(bank, every[2].program_change)
                assert row is not None, "un-rating must not un-favourite"
                assert row.rating == 0
        finally:
            store.close()

    async def _said(self, app, key, program_change=None):
        """Press ``key`` on the preset row, and return what the app said.

        The startup sentence and the read's progress lines are in there
        too, so the assertion is "this sentence was said" rather than "it
        was the last one".
        """
        said = []
        app.notify_status = lambda message, refused=False: said.append(
            (message, refused)
        )
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            table = app.query_one("#preset-table")
            table.focus()
            if program_change is not None:
                table.move_cursor(row=self._row(app, program_change))
            await pilot.press(key)
            await pilot.pause()
            return said

    async def test_a_slot_that_is_not_a_favourite_is_refused(self, tmp_path):
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 0)])
        try:
            said = await self._said(app, "asterisk", every[7].program_change)
            # p2ked's own sentence, the same one `t` and `n` are refused
            # with -- a rating hangs off a favourite, and annotating is
            # not what the user asked for.
            assert ("not a favourite yet -- press f first", True) in said
        finally:
            store.close()

    async def test_an_empty_list_has_nothing_to_rate(self, tmp_path):
        """An empty view leaves no row, and a keypress owes an answer.

        Said rather than done nothing, because silence is
        indistinguishable from a key that is not bound.
        """
        from p2ked.app import VIEW_BANK_FAVOURITES

        app, store, _bank = self._app(tmp_path)  # nothing favourited here
        try:
            app.view_mode = VIEW_BANK_FAVOURITES
            said = await self._said(app, "asterisk")
            assert ("no preset under the cursor to rate", True) in said
        finally:
            store.close()

    async def test_with_no_database_there_is_nothing_to_rate(self, tmp_path):
        """``--favorites`` pointed somewhere unopenable, or no store."""
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        said = []
        app = P2kedApp(DemoDevice())
        app.notify_status = lambda message, refused=False: said.append(
            (message, refused)
        )
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            app.action_edit_rating()
            await pilot.pause()
        assert said, "a store-less rating must say so"
        assert any("no favourites database" in m for m, _ in said)

    async def test_the_column_shows_the_stars(self, tmp_path):
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 3)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                table = app.query_one("#preset-table")
                labels = [str(c.label) for c in table.columns.values()]
                column = labels.index("★")
                # Pinned to five, not fitted: fitted, it is five wide in a
                # bank you have rated and one wide in a bank you have not,
                # so the row you just rated would jump sideways.
                assert table.columns["rating"].width == 5
                assert table.get_row(every[2].key)[column] == "★★★··"
                # And blank on the row that has none, which is the point of
                # blank-means-absent.
                assert table.get_row(every[4].key)[column] == ""
        finally:
            store.close()


class TestTheRatingFilter:
    """``V`` narrows by rating: exactly, or that many and up.

    Last of the three narrowings, and over all three views, so the key
    does the same thing whichever of them is showing. The tests below
    reach ``_visible`` directly: the filter is a question about the list,
    and the key that asks it is tested separately.
    """

    def _app(self, tmp_path, marks=(), view=None):
        from p2k import roms
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        bank = roms.bank_ids()[0]
        store = Favorites(str(tmp_path / "f.db"))
        for program_change, rating in marks:
            store.add(
                bank,
                program_change,
                name=f"invented {program_change}",
                rating=rating,
            )
        app = P2kedApp(DemoDevice(), favorites=store)
        if view is not None:
            app.view_mode = view
        return app, store, bank

    def test_the_states_are_six_thresholds_times_two_widths(self):
        from p2ked.app import RATING_FILTER_STATES

        assert [(f.stars, f.at_least) for f in RATING_FILTER_STATES] == [
            (0, False),
            (1, False),
            (2, False),
            (3, False),
            (4, False),
            (5, False),
            (1, True),
            (2, True),
            (3, True),
            (4, True),
            (5, True),
        ]

    def test_nothing_has_no_floor(self):
        """At least *nothing* matches everything, which is not a filter.

        Exactly-nothing is a real one, and it is in the list.
        """
        from p2ked.app import RATING_FILTER_STATES, RatingFilter

        assert RatingFilter(stars=0, at_least=False) in RATING_FILTER_STATES
        assert RatingFilter(stars=0, at_least=True) not in RATING_FILTER_STATES

    def test_no_filter_is_none_and_not_a_state(self):
        from p2ked.app import P2kedApp, RATING_FILTER_STATES
        from p2ked.demo import DemoDevice

        assert None not in RATING_FILTER_STATES
        assert P2kedApp(DemoDevice()).rating_filter is None

    def test_exact_and_floor_are_different_questions(self):
        from p2ked.app import RatingFilter

        assert RatingFilter(stars=2).matches(2)
        assert not RatingFilter(stars=2).matches(3)
        assert RatingFilter(stars=2, at_least=True).matches(3)
        assert not RatingFilter(stars=2, at_least=True).matches(1)
        # The label is what the header says, so it has to name which of
        # the two widths is in force.
        assert RatingFilter(stars=2).label == "rating =2"
        assert RatingFilter(stars=2, at_least=True).label == "rating ≥2"

    def test_an_exact_filter_keeps_only_that_rating(self, tmp_path):
        from p2ked.app import RatingFilter, VIEW_BANK_FAVOURITES

        app, store, bank = self._app(
            tmp_path, marks=[(2, 3), (3, 3), (7, 5), (9, 0)], view=VIEW_BANK_FAVOURITES
        )
        try:
            app.rating_filter = RatingFilter(stars=3)
            # Bank order, and only the 3s -- the 5 stays put and the
            # unrated one is not a match for anything but "=0".
            assert [e.program_change for e in app._visible(bank)] == [2, 3]
        finally:
            store.close()

    def test_a_floor_filter_keeps_that_rating_and_more(self, tmp_path):
        from p2ked.app import RatingFilter, VIEW_BANK_FAVOURITES

        app, store, bank = self._app(
            tmp_path, marks=[(2, 3), (3, 5), (7, 1), (9, 0)], view=VIEW_BANK_FAVOURITES
        )
        try:
            app.rating_filter = RatingFilter(stars=3, at_least=True)
            assert [e.program_change for e in app._visible(bank)] == [2, 3]
            app.rating_filter = RatingFilter(stars=1, at_least=True)
            assert [e.program_change for e in app._visible(bank)] == [2, 3, 7]
        finally:
            store.close()

    def test_the_unrated_are_their_own_category(self, tmp_path):
        """ "Which of my favourites have I not rated yet" is the question
        this filter gets asked most, and it is the only one that cannot be
        asked with a floor."""
        from p2ked.app import RatingFilter, VIEW_BANK_FAVOURITES

        app, store, bank = self._app(
            tmp_path, marks=[(2, 3), (3, 0), (7, 0)], view=VIEW_BANK_FAVOURITES
        )
        try:
            app.rating_filter = RatingFilter(stars=0)
            assert [e.program_change for e in app._visible(bank)] == [3, 7]
        finally:
            store.close()

    def test_clearing_puts_every_row_back(self, tmp_path):
        from p2ked.app import RatingFilter, VIEW_BANK_FAVOURITES

        app, store, bank = self._app(
            tmp_path, marks=[(2, 3), (3, 5), (7, 1)], view=VIEW_BANK_FAVOURITES
        )
        try:
            everything = len(app._visible(bank))
            app.rating_filter = RatingFilter(stars=5)
            assert len(app._visible(bank)) == 1
            app.rating_filter = None
            assert len(app._visible(bank)) == everything
        finally:
            store.close()

    def test_it_narrows_favourites_in_this_bank_too(self, tmp_path):
        from p2ked.app import RatingFilter, VIEW_BANK_FAVOURITES

        app, store, bank = self._app(
            tmp_path, marks=[(2, 4), (3, 1), (7, 4)], view=VIEW_BANK_FAVOURITES
        )
        try:
            assert len(app._visible(bank)) == 3
            app.rating_filter = RatingFilter(stars=3, at_least=True)
            assert [e.program_change for e in app._visible(bank)] == [2, 7]
        finally:
            store.close()

    def test_it_narrows_every_favourite_across_banks(self, tmp_path):
        from p2k import roms
        from p2ked.app import (
            P2kedApp,
            RatingFilter,
            VIEW_ALL_FAVOURITES,
        )
        from p2ked.demo import DemoDevice

        first = roms.bank_ids()[0]
        second = roms.bank_ids()[1]
        store = Favorites(str(tmp_path / "f.db"))
        store.add(first, 2, name="invented 2", rating=5)
        store.add(first, 9, name="invented 9", rating=1)
        store.add(second, 4, name="invented 4", rating=3)
        app = P2kedApp(DemoDevice(), favorites=store)
        try:
            app.view_mode = VIEW_ALL_FAVOURITES
            assert len(app._visible(first)) == 3
            app.rating_filter = RatingFilter(stars=3)
            # The one 3-star across every bank, and neither the 5 nor
            # the 1 -- the filter does not care which bank a row is in.
            assert [(e.bank_id, e.program_change) for e in app._visible(first)] == [
                (second, 4)
            ]
        finally:
            store.close()

    def test_it_narrows_the_full_list_to_the_matching_favourites(self, tmp_path):
        """The full list narrows too, which is why it is applied last.

        A filter that only reached the favourites views would be a
        different filter depending on which view was showing, which is how
        a keypress ends up doing something nobody can predict.
        """
        from p2ked.app import RatingFilter

        app, store, bank = self._app(tmp_path, marks=[(2, 3), (7, 3)])
        try:
            assert len(app._visible(bank)) > 100, "the full list is every preset"
            app.rating_filter = RatingFilter(stars=3, at_least=True)
            assert [e.program_change for e in app._visible(bank)] == [2, 7]
        finally:
            store.close()

    def test_it_is_applied_after_the_view_and_the_categories(self, tmp_path):
        """A rating filter is the last word, not a fourth branch.

        A bank favourite that matches no rating has to go whatever else it
        matches -- otherwise ``V`` would narrow the full list and leave
        the favourites views alone, which is one key doing two things.
        """
        from p2k import catalog as cat
        from p2k import roms
        from p2ked.app import P2kedApp, RatingFilter, VIEW_BANK_FAVOURITES
        from p2ked.demo import DemoDevice

        bank = roms.bank_ids()[0]
        presets = roms.presets(bank)
        rows = [presets[0].program_change, presets[1].program_change]
        catalog = cat.Catalog(
            [
                cat.Entry(bank, rows[0], "syn:One"),
                cat.Entry(bank, rows[1], "syn:Two"),
            ]
        )
        store = Favorites(str(tmp_path / "f.db"))
        for number, rating in zip(rows, [4, 0], strict=True):
            store.add(bank, number, name=f"invented {number}", rating=rating)
        app = P2kedApp(DemoDevice(), catalog=catalog, favorites=store)
        try:
            app.view_mode = VIEW_BANK_FAVOURITES
            assert len(app._visible(bank)) == 2
            # Categories first, rating last: `syn` keeps both of them, and
            # the rating then takes the unrated one away as well.
            app._categories = {"syn"}
            assert len(app._visible(bank)) == 2
            app.rating_filter = RatingFilter(stars=3, at_least=True)
            assert [e.program_change for e in app._visible(bank)] == [rows[0]]
        finally:
            store.close()

    async def _open(self, app, pilot):
        await pilot.press("V")
        await _until(pilot, lambda: isinstance(app.screen, RatingFilterScreen))

    @pytest.mark.asyncio
    async def test_the_key_narrows_the_list_and_says_so(self, tmp_path):
        """``V``, down to a row, space, enter.

        The sentence goes when the next one does; the header does not. A
        filter that survives only as long as its own status message is a
        silent narrowing the moment another key is pressed.
        """
        from p2k import roms
        from p2ked.app import RatingFilter

        bank = roms.bank_ids()[0]
        app, store, bank = self._app(tmp_path, marks=[(2, 3), (3, 3), (7, 5)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert app.query_one("#preset-table").row_count == len(
                    roms.presets(bank)
                )
                await self._open(app, pilot)
                # Down to the "3" row -- exactly three, not three and up --
                # and space to mark it.
                await pilot.press("down", "down", "down", "space")
                await pilot.pause()
                assert app.screen._current == RatingFilter(stars=3)
                await pilot.press("enter")
                await _until(
                    pilot, lambda: not isinstance(app.screen, RatingFilterScreen)
                )
                assert app.rating_filter == RatingFilter(stars=3)
                # The two 3s, and not the 5: an exact threshold is a
                # question about one value.
                assert [e.program_change for e in app._current] == [2, 3]
                assert "rating =3" in app.sub_title
        finally:
            store.close()

    @pytest.mark.asyncio
    async def test_the_floor_column_is_reachable(self, tmp_path):
        """Right steps into ``≥``, which a row cursor could not reach."""
        from p2ked.app import RatingFilter

        app, store, _bank = self._app(tmp_path, marks=[(2, 3), (7, 5)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await self._open(app, pilot)
                await pilot.press("down", "down", "down", "right", "space")
                await pilot.pause()
                assert app.screen._current == RatingFilter(stars=3, at_least=True)
                await pilot.press("enter")
                await _until(
                    pilot, lambda: not isinstance(app.screen, RatingFilterScreen)
                )
                assert app.rating_filter == RatingFilter(stars=3, at_least=True)
                assert [e.program_change for e in app._current] == [2, 7]
                assert "rating ≥3" in app.sub_title
        finally:
            store.close()

    @pytest.mark.asyncio
    async def test_escape_leaves_the_filter_alone(self, tmp_path):
        """Escape is "leave it alone", and ``x`` is a *choice*.

        Clearing the marked cell and then walking away has to change
        nothing, or escape would be a clear key nobody asked for.
        """
        from p2ked.app import RatingFilter

        app, store, bank = self._app(tmp_path, marks=[(2, 3), (3, 5)])
        try:
            app.rating_filter = RatingFilter(stars=5)
            shown = len(app._visible(bank))
            async with app.run_test(size=(200, 50)) as pilot:
                await self._open(app, pilot)
                await pilot.press("x")  # clear, which is a choice
                await pilot.press("escape")  # and then walk away from it
                await _until(
                    pilot, lambda: not isinstance(app.screen, RatingFilterScreen)
                )
                assert app.rating_filter == RatingFilter(stars=5)
                assert len(app._visible(bank)) == shown
        finally:
            store.close()

    @pytest.mark.asyncio
    async def test_x_then_enter_clears_it(self, tmp_path):
        from p2ked.app import RatingFilter

        app, store, bank = self._app(tmp_path, marks=[(2, 3), (3, 3), (7, 5)])
        try:
            everything = len(app._visible(bank))
            app.rating_filter = RatingFilter(stars=3)
            async with app.run_test(size=(200, 50)) as pilot:
                await self._open(app, pilot)
                await pilot.press("x")
                await pilot.press("enter")
                await _until(
                    pilot, lambda: not isinstance(app.screen, RatingFilterScreen)
                )
                assert app.rating_filter is None
                assert len(app._visible(bank)) == everything
                # The header is back to the channel and nothing else.
                assert app.sub_title == "sending on MIDI channel 1"
        finally:
            store.close()

    @pytest.mark.asyncio
    async def test_the_star_column_labels_what_it_holds(self, tmp_path):
        """The filter's own column says ★, like the browser's.

        Two tables showing ratings should not spell them differently, and
        the filter's third column is the same ``rating_cell`` the browser
        draws with.
        """
        app, store, _bank = self._app(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._open(app, pilot)
                table = app.screen.query_one("#ratings")
                assert [str(c.label) for c in table.columns.values()] == [
                    "=",
                    "≥",
                    "rating",
                ]
                assert table.get_row("3")[-1] == "★★★··"
                assert table.get_row("0")[-1] == "no rating"
        finally:
            store.close()


@pytest.mark.asyncio
class TestUndoingARating:
    """``z`` puts the previous rating back, and sends nothing.

    A rating is a write to the local favourites database, like a favourite
    toggle and unlike every edit: no frame goes out, and the undo has no
    MIDI in it.
    """

    def _app(self, tmp_path, marks=()):
        from p2k import roms
        from p2ked.app import P2kedApp
        from p2ked.demo import DemoDevice

        bank = roms.bank_ids()[0]
        store = Favorites(str(tmp_path / "f.db"))
        for program_change, rating in marks:
            store.add(
                bank,
                program_change,
                name=f"invented {program_change}",
                rating=rating,
            )
        app = P2kedApp(DemoDevice(), favorites=store)
        return app, store, bank

    async def _rate(self, app, pilot, program_change: int, stars: int) -> None:
        app.query_one("#preset-table").focus()
        app.query_one("#preset-table").move_cursor(
            row=[e.program_change for e in app._current].index(program_change)
        )
        await pilot.press("asterisk")
        await _until(pilot, lambda: isinstance(app.screen, ValuePickerScreen))
        app.screen.query_one("#choices").move_cursor(row=stars)
        await pilot.press("enter")
        await _until(pilot, lambda: not isinstance(app.screen, ValuePickerScreen))

    async def test_undo_puts_the_previous_rating_back(self, tmp_path):
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 4)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await self._rate(app, pilot, every[2].program_change, 2)
                assert store.get(bank, every[2].program_change).rating == 2
                assert len(app._changes) == 1
                await pilot.press("z")
                await pilot.pause()
                assert store.get(bank, every[2].program_change).rating == 4
                assert app._changes == []
        finally:
            store.close()

    async def test_nothing_is_sent_when_a_rating_is_undone(self, tmp_path):
        """No frame, of any kind, for a rating or for its undo.

        The device logs every parameter write, every setup dump and every
        selection; a favourites write is none of them, so all three stay
        empty from the ``*`` press to the ``z`` press.
        """
        from p2k import roms

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 1)])
        said = []
        app.notify_status = lambda message, refused=False: said.append(message)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await self._rate(app, pilot, every[2].program_change, 5)
                device = app.device
                assert device.set_log == [], "a rating sent a parameter"
                assert device.dump_log == [] and device.selected_log == []
                await pilot.press("z")
                await _until(pilot, lambda: not app._changes)
                assert device.set_log == [], "an undo of a rating sent a parameter"
                assert device.dump_log == [], "an undo of a rating sent a dump"
                assert device.selected_log == []
                # And it is said, in the same sentence style the other
                # undo kinds use.
                assert said[-1] == "undid 1 rating"
        finally:
            store.close()

    async def test_a_toggle_and_a_rating_are_two_entries_one_sentence(self, tmp_path):
        """``Z`` over both, and the report names both.

        One clause rather than two because "undid 1 favourite and 1
        rating" is one thing the user did, even though it is two entries
        on the timeline. Undoing them is the interesting order: the toggle
        goes first, and it un-favourites the slot -- while the rating
        survives on the row the store keeps, which is the whole point of
        ``remove`` not deleting.
        """
        from p2k import roms
        from p2ked.app import FavouriteChange, RatingChange

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 3)])
        said = []
        app.notify_status = lambda message, refused=False: said.append(message)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._changes = [
                    FavouriteChange(bank, every[2].program_change, True),
                    RatingChange(bank, every[2].program_change, 3),
                ]
                # No wire, so no worker: this is the local half of `Z`,
                # which is the half that touches the favourites store.
                app._undo_master_edits(None)
                assert app._changes == []
                assert store.get(bank, every[2].program_change) is None, (
                    "undoing the toggle has to un-favourite it"
                )
                dormant = store.dormant()
                assert [(f.bank_id, f.number, f.rating) for f in dormant] == [
                    (bank, every[2].program_change, 3)
                ], "the rating survives on the row the store keeps"
                await pilot.pause()
                assert said[-1] == "undid 1 favourite and 1 rating"
        finally:
            store.close()

    async def test_a_rating_rides_the_same_timeline_as_the_edits(self, tmp_path):
        """One list, not one log per kind, and ``z`` cannot tell them apart.

        Which is the point: a rating made between two edits has to be
        undoing *between* them, and two logs would each have to be asked
        which of them happened last. See :class:`EditChange`.
        """
        from p2k import roms
        from p2ked.app import EditChange, RatingChange

        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store, bank = self._app(tmp_path, marks=[(every[2].program_change, 3)])
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app._changes = [EditChange()]
                await self._rate(app, pilot, every[2].program_change, 5)
                app._changes.append(EditChange())
                assert [type(c).__name__ for c in app._changes] == [
                    "EditChange",
                    "RatingChange",
                    "EditChange",
                ]
                assert isinstance(app._changes[1], RatingChange)
                assert store.get(bank, every[2].program_change).rating == 5
                await pilot.pause()
        finally:
            store.close()
