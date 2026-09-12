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
            ("XLEAD2-1", 0), ("XLEAD2-1", 63), ("XLEAD2-1", 126),
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
            assert store.get("TECHNO-0", 42) is not None, \
                "a bank the listing never mentions must survive --replace"
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
        assert keys["cycle_favorites"] == "F"
        assert keys["pick_categories"] == "C"

    def test_the_store_is_injected_not_opened(self, tmp_path):
        """A test must never write into the user's real database."""
        app, store = self._app(tmp_path)
        assert app.favorites is store
        store.close()

    def test_favourites_only_hides_the_rest(self, tmp_path):
        from p2k import roms
        bank = roms.bank_ids()[0]
        every = roms.presets(bank)
        app, store = self._app(tmp_path, marks=[(bank, every[2].program_change),
                                                (bank, every[5].program_change)])
        try:
            assert len(app._visible(bank)) == len(every)
            app._favorites_only = True
            shown = app._visible(bank)
            assert [e.program_change for e in shown] == \
                [every[2].program_change, every[5].program_change]
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
