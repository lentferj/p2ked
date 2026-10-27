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

"""The browser remembering its own UI state, beside the settings file.

A preference that comes back without saying so is the failure this file
exists to prevent. rxved remembers where the user was and how the list was
narrowed; until now p2ked restarted on bank 0, row 0, the full list, every
run. That sounds like the friendly behaviour -- but a launch that opens on
a narrowed list with nothing on screen saying why is the *silent narrowing*
CLAUDE.md warns about, wearing its friendliest coat. So both halves are
pinned together:

* **What was remembered comes back** -- the store round-trips, every
  transition writes as it happens, and a fresh launch restores bank row,
  slot row, view, rating filter and category filter.
* **Whatever comes back is said and sane** -- the sub-title names every
  narrowing still in force, a hand-edited file must not wedge the app or
  narrow to a filter nobody would have chosen, and a cursor that now
  writes a file still plays nothing.

Fixture names are invented, per CLAUDE.md: E-MU's preset names are not
committed to this repository, and a test fixture is not an exception. The
``syn:``/``tld:`` prefixes and every preset label here are made up.

Key names and the injected path are frozen by
``docs/PLAN-remembered-ui-state.md`` §2: ``browser.*``, the unchanged
``scan.offer_dismissed``, and ``config.ui_state_path(...)`` beside the
``config.toml`` a test passes in.
"""

import asyncio

import pytest
from textual.widgets import DataTable, Input

from p2k import catalog as cat
from p2k import config
from p2k.favorites import Favorites
from p2ked.app import (
    VIEW_ALL,
    VIEW_ALL_FAVOURITES,
    VIEW_BANK_FAVOURITES,
    P2kedApp,
    RatingFilter,
    RatingFilterScreen,
)
from p2ked.demo import DemoDevice
from p2ked.prompts import PromptScreen

#: Which ROM is fitted in every fixture, so the bank list is deterministic
#: and bank row 4 is the first Composer bank. Nothing here restores into a
#: *user* bank: a user bank auto-reads its names off the demo device on a
#: worker at startup and refills the preset table when the read lands --
#: racing the same settle timer the restored slot cursor rides, and a gap
#: in a test is not a gap.
COMPOSER_FIRST_ROW = 4

#: The seeded ratings, in bank order. All kept ≥2 so the restored ``≥2``
#: filter keeps them, and six of them so restored slot row 5 exists.
SEED_RATINGS = (3, 4, 5, 3, 3, 3)


def make(tmp_path, *, catalog=None, installed=None, **kwargs):
    """An app pointed at ``tmp_path`` for everything: config, ui state, db.

    Mirrors ``tests/test_scan.py``'s ``make()``: injected store, injected
    paths, nothing written outside ``tmp_path``. The Composer ROM is
    reported fitted by default; passing ``installed=None`` would mean the
    unit was never asked, which none of these tests need.
    """
    store = Favorites(str(tmp_path / "f.db"))
    kw = {
        "catalog": catalog if catalog is not None else cat.empty(),
        "favorites": store,
        "installed": {4: True} if installed is None else installed,
        "config_path": str(tmp_path / "config.toml"),
        **kwargs,
    }
    return P2kedApp(DemoDevice(), **kw), store


def ui_state_path(tmp_path) -> str:
    """Where the app's remembered state lands: beside the injected config."""
    return config.ui_state_path(str(tmp_path / "config.toml"))


def remember(tmp_path, keys) -> None:
    """Seed the injected ui-state file.

    ``keys`` is a mapping of *full* key names -- ``browser.bank_index``
    and friends -- because the frozen names carry a dot no keyword can.
    """
    path = ui_state_path(tmp_path)
    for key, value in keys.items():
        config.save_ui_state(key, value, path)


async def _until(pilot, ready, attempts=40) -> None:
    """Wait until ``ready()``, or fail after a bounded count of pauses.
    Borrowed from ``tests/test_favorites.py``: a fixed number of pauses
    would be a guess about how many trips through the message loop this
    machine takes, and a guess in a test is a flake.
    """
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _pick_exact_rating(app, pilot, stars: int) -> None:
    """The whole ``V`` gesture: open, walk to the ``=N`` row, space, enter.

    The same presses ``tests/test_favorites.py``'s filter tests pin; the
    screen's row order is not asserted twice here.
    """
    await pilot.press("V")
    await _until(pilot, lambda: isinstance(app.screen, RatingFilterScreen))
    await pilot.press(*["down"] * stars, "space")
    await pilot.pause()
    await pilot.press("enter")
    await _until(pilot, lambda: not isinstance(app.screen, RatingFilterScreen))


def _seeded_app(tmp_path):
    """A narrowable app with everything to restore.

    Categories and favourites are seeded on the first Composer bank, so
    the restored narrowing has rows to keep and slot row 5 exists.
    """
    remember(
        tmp_path,
        {
            "browser.bank_index": COMPOSER_FIRST_ROW,
            "browser.slot_cursor": 5,
            "browser.view_mode": VIEW_BANK_FAVOURITES,
            "browser.categories": "syn",
            "browser.rating_stars": 3,
            "browser.rating_at_least": True,
        },
    )
    catalog = cat.Catalog(
        [cat.Entry("COMPOSER-0", i, f"syn:Invented {i}") for i in range(8)]
    )
    app, store = make(tmp_path, catalog=catalog)
    for number, rating in zip(range(len(SEED_RATINGS)), SEED_RATINGS, strict=True):
        store.add("COMPOSER-0", number, name=f"syn:Invented {number}", rating=rating)
    return app, store


class TestTheStoreRoundTrips:
    """``p2k.config`` alone: save it, read it back, forget it.

    The store is vinsynlib's, bound here as ``p2k.config`` -- so the round
    trip is what p2ked cannot fix in its own app: it is the library's
    behaviour (and the file's format) everything above has to trust. Same
    reason ``test_favorites``'s channel round trip exists.
    """

    def test_each_scalar_type_round_trips(self, tmp_path):
        path = ui_state_path(tmp_path)
        config.save_ui_state("browser.bank_index", 3, path)
        config.save_ui_state("browser.slot_cursor", 17, path)
        config.save_ui_state("browser.view_mode", VIEW_BANK_FAVOURITES, path)
        config.save_ui_state("browser.categories", "syn,tld", path)
        config.save_ui_state("browser.rating_stars", 3, path)
        config.save_ui_state("browser.rating_at_least", True, path)
        config.save_ui_state("scan.offer_dismissed", True, path)
        assert config.load_ui_int("browser.bank_index", path) == 3
        assert config.load_ui_int("browser.slot_cursor", path) == 17
        assert config.load_ui_str("browser.view_mode", path) == VIEW_BANK_FAVOURITES
        assert config.load_ui_str("browser.categories", path) == "syn,tld"
        assert config.load_ui_int("browser.rating_stars", path) == 3
        assert config.load_ui_bool("browser.rating_at_least", path) is True
        # The one key p2ked already had, still spelled the way it was
        # before this change: renaming a remembered dismissal would
        # silently re-offer the scan to everyone who said never.
        assert config.load_ui_bool("scan.offer_dismissed", path) is True

    def test_a_missing_file_is_nothing_remembered(self, tmp_path):
        assert config.load_ui_int("browser.bank_index", "/no/such/file") is None

    def test_a_missing_key_is_nothing_remembered(self, tmp_path):
        path = ui_state_path(tmp_path)
        config.save_ui_state("browser.view_mode", VIEW_ALL, path)
        assert config.load_ui_int("browser.bank_index", path) is None
        assert config.load_ui_bool("scan.offer_dismissed", path) is None

    def test_none_forgets_the_key(self, tmp_path):
        """Clearing writes an absence, not a false.

        A filter remembered as ``False`` would come back next launch as a
        filter that matches nothing but its own tombstone; removing the
        key is how "no filter" survives a restart.
        """
        path = ui_state_path(tmp_path)
        config.save_ui_state("browser.rating_stars", 3, path)
        config.save_ui_state("browser.rating_stars", None, path)
        assert config.load_ui_int("browser.rating_stars", path) is None

    def test_a_bool_is_not_an_int_and_an_int_is_not_a_bool(self, tmp_path):
        """``isinstance(True, int)`` is how a wrong channel shipped once.

        The library is the one place this has to be checked, and the check
        is the same one the channel cache already carries: a hand-edited
        ``rating_stars = true`` must not come back as one star, and
        ``rating_at_least = 3`` is not a bool.
        """
        path = ui_state_path(tmp_path)
        config.save_ui_state("browser.rating_stars", True, path)
        config.save_ui_state("browser.rating_at_least", 3, path)
        assert config.load_ui_int("browser.rating_stars", path) is None
        assert config.load_ui_bool("browser.rating_at_least", path) is None

    def test_a_non_scalar_is_refused_not_rounded(self, tmp_path):
        """The store takes scalars only, and says so loudly.

        Categories are a joined string *because* of this refusal -- a list
        would have to be smuggled through a type the file cannot hold.
        """
        with pytest.raises(TypeError):
            config.save_ui_state(
                "browser.categories", ["syn", "tld"], ui_state_path(tmp_path)
            )


class TestSavingOneKeyLeavesTheOthersAlone:
    """One save call, one key -- every other key in the file survives.

    The trap rxved's first ``_save_ui_state`` shipped: rewriting the whole
    map with only the latest key in it. ``None`` meaning "unset" for one
    key while meaning "keep" for the rest is the single way this can be
    written correctly, and a store that cannot pass this class cannot hold
    a cleared filter and a saved position at the same time.
    """

    def _deposit(self, path):
        config.save_ui_state("browser.bank_index", 2, path)
        config.save_ui_state("browser.slot_cursor", 40, path)
        config.save_ui_state("browser.rating_stars", 3, path)
        config.save_ui_state("browser.rating_at_least", False, path)

    def test_saving_a_fourth_key_keeps_three(self, tmp_path):
        path = ui_state_path(tmp_path)
        self._deposit(path)
        # The view is written by a different keypress, later in the
        # session, than the three position keys were.
        config.save_ui_state("browser.view_mode", VIEW_ALL_FAVOURITES, path)
        assert config.load_ui_int("browser.bank_index", path) == 2
        assert config.load_ui_int("browser.slot_cursor", path) == 40
        assert config.load_ui_int("browser.rating_stars", path) == 3
        assert config.load_ui_bool("browser.rating_at_least", path) is False
        assert config.load_ui_str("browser.view_mode", path) == VIEW_ALL_FAVOURITES

    def test_clearing_the_filter_keeps_the_position(self, tmp_path):
        path = ui_state_path(tmp_path)
        self._deposit(path)
        config.save_ui_state("browser.rating_stars", None, path)
        config.save_ui_state("browser.rating_at_least", None, path)
        # Where the user was is not which filter was on, and forgetting
        # one must not mean forgetting the other.
        assert config.load_ui_int("browser.bank_index", path) == 2
        assert config.load_ui_int("browser.slot_cursor", path) == 40
        assert config.load_ui_int("browser.rating_stars", path) is None
        assert config.load_ui_bool("browser.rating_at_least", path) is None


class TestTheAppStartsWhereItLeftOff:
    """Restore on construction: the file is seeded by hand, then read.

    The file is written *before the app is ever built* -- exactly what
    yesterday's run left behind -- and the app is then given its settle
    timer's worth of time, so what comes back is what yesterday wrote and
    not what startup's programmatic cursor moves put there first.
    """

    async def test_narrowings_and_rows_all_come_back(self, tmp_path):
        app, store = _seeded_app(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert app.view_mode == VIEW_BANK_FAVOURITES
                assert app.rating_filter == RatingFilter(stars=3, at_least=True)
                assert app._categories == {"syn"}
                # The settle timer is 0.1s; twice that is what "after the
                # settle timer" means in a wait.
                await pilot.pause(0.2)
                banks = app.query_one("#bank-table")
                presets = app.query_one("#preset-table", DataTable)
                assert banks.cursor_row == COMPOSER_FIRST_ROW
                assert presets.cursor_row == 5
        finally:
            store.close()

    async def test_the_restored_bank_is_the_one_under_the_restored_row(self, tmp_path):
        """The slot cursor has to land on the restored bank's table.

        A slot cursor is an index into the preset table, so restoring it
        without restoring the bank would point at a *different* preset --
        the one way "remember where I was" can quietly mean "somewhere
        else".
        """
        app, store = _seeded_app(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause(0.2)
                assert app._current_bank == "COMPOSER-0"
                table = app.query_one("#preset-table", DataTable)
                # The row the cursor sits on is seeded slot 5's own row.
                cells = table.get_row_at(5)
                assert "5" in str(cells[2])
        finally:
            store.close()

    async def test_the_slot_cursor_restores_once_and_is_not_a_standing_rule(
        self, tmp_path
    ):
        """One-shot: yesterday's row is applied once, then gone.

        A standing override would make scrolling impossible -- every
        programmatic move snapping back to yesterday's row forever.
        """
        app, store = _seeded_app(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.pause(0.2)
                assert app.query_one("#preset-table", DataTable).cursor_row == 5
                assert app._saved_slot_cursor is None
        finally:
            store.close()


def _category_catalog():
    """Two invented prefixes on the first Composer bank.

    A *user* bank's names get adopted off the demo device at startup,
    which would replace these fixtures' names with the demo's own; a ROM
    bank's are the catalog's, so the prefixes here are what `C` offers.
    """
    return cat.Catalog(
        [
            cat.Entry("COMPOSER-0", 0, "syn:One"),
            cat.Entry("COMPOSER-0", 1, "tld:Two"),
        ]
    )


class TestATransitionWritesTheFileAsItHappens:
    """Each remembered transition writes its key the moment it lands.

    This is the point of the whole change (plan §3.3), and the only way
    the *last* thing the user did is the thing that comes back -- a save
    at exit is one crashed session away from wrong.
    """

    #: Two invented prefixes in one bank, so a second category filter can
    #: differ from the first one instead of being the same value written
    #: over itself.

    async def _wait_free(self, app, pilot) -> None:
        """The startup auto-read of a user bank owns the wire for a moment;
        until it hands off, a pressed cursor move can land between its
        fills. Every driving test waits for the peace."""
        await _until(pilot, lambda: not app._busy)
        await pilot.pause()

    async def test_the_view_key_is_written_by_v(self, tmp_path):
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._wait_free(app, pilot)
                await pilot.press("v")
                await _until(pilot, lambda: app.view_mode == VIEW_BANK_FAVOURITES)
                path = ui_state_path(tmp_path)
                assert config.load_ui_str("browser.view_mode", path) == (
                    VIEW_BANK_FAVOURITES
                )
        finally:
            store.close()

    async def test_a_rating_filter_writes_both_of_its_keys(self, tmp_path):
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await _pick_exact_rating(app, pilot, stars=3)
                assert app.rating_filter == RatingFilter(stars=3)
                path = ui_state_path(tmp_path)
                assert config.load_ui_int("browser.rating_stars", path) == 3
                assert config.load_ui_bool("browser.rating_at_least", path) is False
        finally:
            store.close()

    async def test_a_category_filter_writes_the_joined_string(self, tmp_path):
        remember(tmp_path, {"browser.bank_index": COMPOSER_FIRST_ROW})
        app, store = make(tmp_path, catalog=_category_catalog())
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._wait_free(app, pilot)
                await pilot.press("C")
                await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
                await pilot.press(*list("syn"), "enter")
                await _until(pilot, lambda: not isinstance(app.screen, PromptScreen))
                assert app._categories == {"syn"}
                path = ui_state_path(tmp_path)
                assert config.load_ui_str("browser.categories", path) == "syn"
        finally:
            store.close()

    async def test_clearing_writes_the_absence_it_means(self, tmp_path):
        """``x`` + enter clears the rating; a blank prompt clears categories.

        The only way clearing survives a restart: the keys are *removed*
        (``TestTheStoreRoundTrips`` pins the removal), so the next launch
        reads no filter rather than a filter whose value is a memory of
        one.
        """
        remember(tmp_path, {"browser.bank_index": COMPOSER_FIRST_ROW})
        app, store = make(tmp_path, catalog=_category_catalog())
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._wait_free(app, pilot)
                await _pick_exact_rating(app, pilot, stars=2)
                path = ui_state_path(tmp_path)
                assert config.load_ui_int("browser.rating_stars", path) == 2

                await pilot.press("V")
                await _until(pilot, lambda: isinstance(app.screen, RatingFilterScreen))
                await pilot.press("x", "enter")
                await _until(
                    pilot, lambda: not isinstance(app.screen, RatingFilterScreen)
                )
                assert app.rating_filter is None
                assert config.load_ui_int("browser.rating_stars", path) is None
                assert config.load_ui_bool("browser.rating_at_least", path) is None

                await pilot.press("C")
                await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
                app.screen.query_one("#value", Input).value = "tld"
                await pilot.press("enter")
                await _until(pilot, lambda: not isinstance(app.screen, PromptScreen))
                assert app._categories == {"tld"}
                assert config.load_ui_str("browser.categories", path) == "tld"

                await pilot.press("C")
                await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
                app.screen.query_one("#value", Input).value = ""
                await pilot.press("enter")
                await _until(pilot, lambda: not isinstance(app.screen, PromptScreen))
                assert app._categories == set()
                assert config.load_ui_str("browser.categories", path) is None
        finally:
            store.close()

    async def test_cycling_back_to_all_is_still_a_state_worth_saving(self, tmp_path):
        """``v`` around the cycle writes the mode itself, not a deletion.

        "all presets" is a state the user chose as much as the narrowings
        are; tomorrow's run owes them the same list, not its opposite.
        """
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._wait_free(app, pilot)
                for _ in range(3):
                    await pilot.press("v")
                    await pilot.pause()
                assert app.view_mode == VIEW_ALL
                path = ui_state_path(tmp_path)
                assert config.load_ui_str("browser.view_mode", path) == VIEW_ALL
        finally:
            store.close()


class TestTheSlotCursorObeysThePane:
    """A slot cursor is saved only while the preset pane has focus.

    Startup moves the preset cursor programmatically -- the fills, the
    focus hand-off, the settle-timer re-apply -- and every one of those
    moves is startup's business, not the user's memory. So the save guard
    is the focus test, and these are the moves the guard has to separate:
    restored (keep), refilled (ignore), moved by the user (save), refilled
    again after the user's move (stop saving).
    """

    def _seeded(self, tmp_path):
        # Restored into the first Composer bank, a ROM: no auto-read races,
        # and the all-view row 2 exists.
        remember(
            tmp_path,
            {
                "browser.bank_index": COMPOSER_FIRST_ROW,
                "browser.slot_cursor": 2,
            },
        )
        return make(tmp_path)

    async def test_startup_programmatic_moves_do_not_overwrite_it(self, tmp_path):
        """Startup's own moves never reach the file -- a move without focus
        is startup's, whoever calls it.

        The restore's own ``move_cursor`` would pass this either way: it
        lands on row 2, the very row the file already holds, so recording
        it and ignoring it leave an identical file. That is why the test
        ends with an unfocused *move to a different row* -- the same
        ``RowHighlighted`` a refill delivers, minus the refill -- while the
        bank pane holds focus. Recording it would write row 0 over the
        user's row 2; only the focus guard keeps the file at 2.
        """
        app, store = self._seeded(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.pause(0.3)
                path = ui_state_path(tmp_path)
                # The file still says what the user said, not what
                # startup's fills did on their way to settling...
                assert config.load_ui_int("browser.slot_cursor", path) == 2
                # ...and the cursor itself *came back* -- the restore
                # applied it.
                presets = app.query_one("#preset-table", DataTable)
                assert presets.cursor_row == 2

                # Now the move the guard has to swallow: a programmatic
                # preset move with the pane unfocused -- keystroke-shaped
                # on the wire (it posts one RowHighlighted, no fill, no
                # restore involved) but not a gesture the user made. The
                # cursor really moves; the file must not follow it.
                app.query_one("#bank-table").focus()
                presets.move_cursor(row=0)
                await pilot.pause(0.1)
                assert presets.cursor_row == 0
                assert config.load_ui_int("browser.slot_cursor", path) == 2
        finally:
            store.close()

    async def test_a_refill_while_the_pane_is_unfocused_saves_nothing(self, tmp_path):
        app, store = self._seeded(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.pause(0.3)
                banks = app.query_one("#bank-table")
                banks.focus()
                banks.move_cursor(row=1)
                await pilot.pause(0.1)
                path = ui_state_path(tmp_path)
                assert config.load_ui_int("browser.bank_index", path) == 1
                # Still 2: refilling the preset pane moved its cursor to
                # row 0, and a refill was never a place the user pointed.
                assert config.load_ui_int("browser.slot_cursor", path) == 2
        finally:
            store.close()

    async def test_a_move_in_the_preset_pane_is_remembered(self, tmp_path):
        """Every stop the user makes in the preset pane is the new memory.

        The file is read against the cursor itself rather than a baked
        number on purpose: this test is about the *guard* (focused moves
        are saved), and the restore's own cursor behaviour is pinned by
        ``TestTheAppStartsWhereItLeftOff``. Baking "row 5" in would make
        this class fail for a reason its contract does not own.
        """
        app, store = self._seeded(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.pause(0.3)
                presets = app.query_one("#preset-table", DataTable)
                presets.focus()
                await pilot.press("down", "down", "down")
                await pilot.pause()
                path = ui_state_path(tmp_path)
                assert config.load_ui_int("browser.slot_cursor", path) == (
                    presets.cursor_row
                )
        finally:
            store.close()

    async def test_walking_back_to_the_banks_stops_the_saving(self, tmp_path):
        """Save-while-focused means *stop*-while-not, in the same file.

        The half that keeps Friday night's row from being overwritten by
        whatever the refill of Saturday's first look puts at row 0.
        """
        app, store = self._seeded(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.pause(0.3)
                presets = app.query_one("#preset-table", DataTable)
                presets.focus()
                await pilot.press("down", "down", "down")
                await pilot.pause()
                path = ui_state_path(tmp_path)
                # Wherever the restore left the cursor, the last user stop
                # is what the file now says: the save tracks the cursor.
                saved = config.load_ui_int("browser.slot_cursor", path)
                assert saved == presets.cursor_row

                banks = app.query_one("#bank-table")
                banks.focus()
                banks.move_cursor(row=1)
                await pilot.pause(0.1)
                assert config.load_ui_int("browser.slot_cursor", path) == saved
        finally:
            store.close()


class TestAHandEditedFileMustNotWedge:
    """Bad values are ignored, not obeyed.

    The ui-state file is a plain local file sitting beside the settings,
    gitignored and described as safe to delete; a user who hand-edits it
    is not the enemy, and a file that wedges the launch is. Each key is
    validated against its own rule before it is trusted (plan §3.1): an
    out-of-range row is not a bank, a view name nobody's key can reach is
    not a view, a bool is not one star, and "at least zero" is not a
    filter at all -- it is everything, which is exactly the silent
    narrowing this feature must never produce unasked.
    """

    async def test_out_of_range_and_mistyped_values_are_ignored(self, tmp_path):
        remember(
            tmp_path,
            {
                "browser.bank_index": 99999,
                "browser.slot_cursor": -3,
                "browser.view_mode": "somewhere-else",
                "browser.rating_stars": True,
                "browser.rating_at_least": True,
            },
        )
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.pause(0.2)
                assert app.view_mode == VIEW_ALL
                assert app.rating_filter is None
                assert app._categories == set()
                assert app._current_bank == "USER-0"
                assert app.query_one("#bank-table").cursor_row == 0
                assert app.query_one("#preset-table", DataTable).cursor_row == 0
        finally:
            store.close()

    async def test_at_least_zero_is_not_a_filter(self, tmp_path):
        """``stars = 0, at_least = true``.

        ``RatingFilter(0, True)`` is not one of the filter states --
        ``tests/test_favorites.py`` pins that only ``(0, False)`` among the
        zero rows is a real filter -- so restoring it would narrow exactly
        nothing and still say ``rating ≥0`` in the header.
        """
        remember(
            tmp_path,
            {
                "browser.rating_stars": 0,
                "browser.rating_at_least": True,
            },
        )
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert app.rating_filter is None
                assert app.sub_title == "sending on MIDI channel 1"
        finally:
            store.close()

    async def test_good_keys_of_a_bad_file_still_apply(self, tmp_path):
        """One bad key does not throw away the file's good ones.

        The restore validates each key against its own rule, so the user's
        remembered bank still comes back when their remembered view name
        is nonsense -- ignoring a key is not ignoring the file.
        """
        remember(
            tmp_path,
            {
                "browser.bank_index": COMPOSER_FIRST_ROW,
                "browser.view_mode": "somewhere-else",
            },
        )
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                await pilot.pause(0.2)
                assert app._current_bank == "COMPOSER-0"
                assert app.query_one("#bank-table").cursor_row == COMPOSER_FIRST_ROW
                assert app.view_mode == VIEW_ALL
        finally:
            store.close()


class TestNoPathNoFile:
    """``P2kedApp(DemoDevice())`` must not invent a place to remember.

    ``_config_path is None`` has always meant "do not remember the
    channel"; the ui state gets the same answer, or every library user,
    test run and screenshot drops a ``ui-state.toml`` into whatever
    directory it happened to be run from.
    """

    async def test_without_a_path_it_runs_and_remembers_nothing(
        self, tmp_path, monkeypatch
    ):
        import os

        scratch = tmp_path / "elsewhere"
        scratch.mkdir()
        monkeypatch.chdir(scratch)
        here = os.getcwd()
        app = P2kedApp(DemoDevice())
        assert app._ui_state_path is None
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            app._remember("browser.view_mode", VIEW_BANK_FAVOURITES)
            app._remember("browser.bank_index", 2)
            await pilot.pause()
        assert not (tmp_path / "ui-state.toml").exists()
        assert not (scratch / "ui-state.toml").exists()
        assert os.getcwd() == here, "the app moved somewhere to remember"


class TestTheHeaderSaysWhyTheListIsShort:
    """No silent narrowing: the sub-title names each narrowing in force.

    A remembered filter and a forgotten filter look identical from the
    list itself; "why is my list short" is answered on the line above it
    (plan §3.4). The order and the separator are part of what the reader
    sees, so the restored case is asserted exactly and not by substring.
    """

    #: The plan's frozen separator, spelled out rather than computed.
    SEP = "   ·   "

    async def test_a_restored_narrowing_is_named_in_full(self, tmp_path):
        remember(
            tmp_path,
            {
                "browser.bank_index": COMPOSER_FIRST_ROW,
                "browser.view_mode": VIEW_ALL_FAVOURITES,
                "browser.categories": "syn",
                "browser.rating_stars": 2,
                "browser.rating_at_least": True,
            },
        )
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                # Nothing pressed: what the header says at *mount* is the
                # claim -- a title that only updates after a keypress is
                # the same silent narrowing with an extra step.
                await pilot.pause()
                assert app.sub_title == (
                    "sending on MIDI channel 1"
                    + self.SEP
                    + "rating ≥2"
                    + self.SEP
                    + "syn"
                    + self.SEP
                    + "every favourite, all banks"
                )
        finally:
            store.close()

    async def test_a_stored_view_comes_back_named(self, tmp_path):
        """A remembered view is also a narrowing, and the header says which.

        Without a rating or a category this is still not yesterday's list:
        "favourites in this bank" looks close enough to an empty "all
        presets" that only the header tells them apart.
        """
        remember(tmp_path, {"browser.view_mode": VIEW_BANK_FAVOURITES})
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert app.sub_title == (
                    "sending on MIDI channel 1" + self.SEP + "favourites in this bank"
                )
        finally:
            store.close()

    async def test_with_nothing_active_it_is_exactly_the_channel(self, tmp_path):
        """An empty file changes nothing about the plain launch.

        The existing suite pins this line; the remembering must not add a
        "nothing" clause to what a fresh run shows.
        """
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert app.sub_title == "sending on MIDI channel 1"
        finally:
            store.close()


class TestTheCursorStillPlaysNothing:
    """``test_app``'s ``TestCursorIsSilent``, again, with a file to write.

    Moving through the browser still sends no MIDI -- this change makes no
    wire traffic, and none of the remembering may add any. What the same
    movements now *do* is write a file, which is the point: a local TOML
    write makes no sound. The demo device's own record is still the
    witness, and the startup mirroring is the half that keeps "remember
    where I was" from ever becoming "play what I left".
    """

    def _log_is_empty(self, app) -> None:
        device = app.device
        assert device.selected_log == [], "the cursor selected a preset"
        assert device.set_log == [], "the cursor sent a parameter"
        assert device.dump_log == [], "the cursor sent a dump"

    async def _wait_free(self, app, pilot) -> None:
        """Let the startup auto-read hand the wire back before driving."""
        await _until(pilot, lambda: not app._busy)
        await pilot.pause()

    async def test_moving_through_banks_and_presets_writes_and_silences(self, tmp_path):
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._wait_free(app, pilot)
                app.query_one("#preset-table", DataTable).focus()
                for _ in range(10):
                    await pilot.press("down")
                await pilot.pause()
                banks = app.query_one("#bank-table")
                banks.focus()
                for _ in range(5):
                    await pilot.press("down")
                await pilot.pause()
                self._log_is_empty(app)
                path = ui_state_path(tmp_path)
                assert config.load_ui_int("browser.slot_cursor", path) == 10
                assert config.load_ui_int("browser.bank_index", path) == 5
        finally:
            store.close()

    async def test_a_bank_move_remembers_no_slot_row(self, tmp_path):
        """The bank move's refill is a move in the preset pane, but not one
        the user made there -- nothing written for it, nothing sent for it.
        """
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._wait_free(app, pilot)
                banks = app.query_one("#bank-table")
                banks.focus()
                banks.move_cursor(row=2)
                await pilot.pause(0.1)
                self._log_is_empty(app)
                path = ui_state_path(tmp_path)
                assert config.load_ui_int("browser.bank_index", path) == 2
                assert config.load_ui_int("browser.slot_cursor", path) is None
        finally:
            store.close()

    async def test_enter_is_still_the_only_thing_that_selects(self, tmp_path):
        """Ten cursor writes are not a selection; enter is exactly one.

        Mirroring ``test_app``'s third cursor test with the file now in
        play: the writes in between must not add a selection to the demo
        device's log.
        """
        app, store = make(tmp_path)
        try:
            async with app.run_test(size=(200, 50)) as pilot:
                await self._wait_free(app, pilot)
                presets = app.query_one("#preset-table", DataTable)
                presets.focus()
                for _ in range(10):
                    await pilot.press("down")
                await pilot.press("enter")
                for _ in range(6):
                    await pilot.pause()
                assert len(app.device.selected_log) == 1
                path = ui_state_path(tmp_path)
                assert config.load_ui_int("browser.slot_cursor", path) == 10
        finally:
            store.close()


class TestTheOfferUsesTheInjectedPath:
    """The scan offer's dismissal rides the same file the browser does.

    Behaviour for the user is unchanged (``scan.offer_dismissed``, same
    key, same meaning); what changes is that the app reads and writes
    through the path it was *given*, so the offer can be tested without
    reaching around the module. ``tests/test_scan.py``'s rewrites hold
    these too; they live here as well because this file is about the one
    file both features share.
    """

    async def _wait_for(self, app, pilot, cls, tries=120):
        for _ in range(tries):
            if isinstance(app.screen, cls):
                return True
            await asyncio.sleep(0.05)
            await pilot.pause()
        return False

    async def test_never_remembers_the_answer(self, tmp_path, monkeypatch):
        """``never`` writes the real key at the real injected path.

        Same intent as ``test_scan``'s monkeypatched version this
        replaces: answer once, never be offered again -- and the answer has
        to land in the file beside the config the app was given, not in
        whatever directory the process was started from.
        """
        scratch = tmp_path / "elsewhere"
        scratch.mkdir()
        # CWD redirected too: before the injected path existed, the module
        # default's path *was* the working directory's file, and a test run
        # must not leave a dismissal in the developer's real one.
        monkeypatch.chdir(scratch)
        path = ui_state_path(tmp_path)
        app, _store = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._scan_offer_answered("never")
            assert config.load_ui_bool("scan.offer_dismissed", path) is True

    async def test_a_dismissed_offer_stays_dismissed(self, tmp_path, monkeypatch):
        """``test_scan``'s second rewrite, asserted here as one contract."""
        from p2ked.scan import ScanOfferScreen

        scratch = tmp_path / "elsewhere"
        scratch.mkdir()
        monkeypatch.chdir(scratch)
        config.save_ui_state("scan.offer_dismissed", True, ui_state_path(tmp_path))
        app, _store = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            await asyncio.sleep(0.9)
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

    async def test_no_answer_means_the_offer_comes_back(self, tmp_path, monkeypatch):
        """The third leg ``test_scan`` does not hold: without a dismissal
        in the injected file, the offer is still made."""
        from p2ked.scan import ScanOfferScreen

        scratch = tmp_path / "elsewhere"
        scratch.mkdir()
        monkeypatch.chdir(scratch)
        app, _store = make(tmp_path, catalog=cat.empty(), offer_scan=True)
        async with app.run_test() as pilot:
            assert await self._wait_for(app, pilot, ScanOfferScreen)
