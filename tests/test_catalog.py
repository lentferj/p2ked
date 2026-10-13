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

"""The catalog file: keeping names read off a unit across sessions.

A ROM is uniquely identified and never changes, so a name it reports is
permanent. These tests pin the two halves of that: the catalog can remember
a name read off the unit and write it back, and a name kept for a bank the
extractor does not cover survives the extractor being run again.
"""

import json
import sys

from p2k import catalog as cat


def write(tmp_path, banks, **extra):
    path = tmp_path / "catalog.json"
    payload = {"source": "test", "generated": "2026-01-01", "banks": banks}
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestRemember:
    def test_a_remembered_name_is_written_to_the_file(self, tmp_path):
        path = write(tmp_path, {"XLEAD-0": [{"pc": 0, "name": "lead:"}]})
        catalog = cat.load(path)
        catalog.remember("XLEAD-0", 7, "lead:Read Off The Unit")
        assert catalog.save()

        again = cat.load(path)
        assert again.read_name("XLEAD-0", 7) == "lead:Read Off The Unit"
        assert again.display_name("XLEAD-0", 7) == "lead:Read Off The Unit"

    def test_a_read_name_does_not_overwrite_the_printed_one(self, tmp_path):
        """The two are kept apart so the `*` disagreement survives a restart."""
        path = write(tmp_path, {"XLEAD-0": [{"pc": 7, "name": "lead:Printed"}]})
        catalog = cat.load(path)
        catalog.remember("XLEAD-0", 7, "lead:From The Unit")
        catalog.save()

        again = cat.load(path)
        assert again.name("XLEAD-0", 7) == "lead:Printed"
        assert again.read_name("XLEAD-0", 7) == "lead:From The Unit"
        assert again.differs("XLEAD-0", 7)

    def test_it_merges_rather_than_replacing_the_file(self, tmp_path):
        """A bank the read did not touch keeps what it had."""
        path = write(
            tmp_path,
            {
                "XLEAD-0": [{"pc": 0, "name": "lead:One"}],
                "COMPOSER-0": [{"pc": 0, "name": "pno:One"}],
            },
        )
        catalog = cat.load(path)
        catalog.remember("XLEAD-0", 1, "lead:Two")
        catalog.save()

        again = cat.load(path)
        assert again.name("COMPOSER-0", 0) == "pno:One"
        assert again.read_name("XLEAD-0", 1) == "lead:Two"

    def test_a_catalog_with_no_path_is_never_written(self, tmp_path):
        """``--demo`` and the tests build one in memory; it must not write."""
        catalog = cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:One")])
        catalog.remember("XLEAD-0", 1, "lead:Two")
        assert not catalog.save()
        assert not list(tmp_path.iterdir())

    def test_an_explicit_path_writes_even_when_none_was_loaded(self, tmp_path):
        target = str(tmp_path / "catalog.json")
        catalog = cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:One")])
        assert catalog.save(target)
        assert cat.load(target).name("XLEAD-0", 0) == "lead:One"

    def test_save_needs_a_path(self, tmp_path):
        """No path and no argument: nowhere to write, so nothing is written."""
        catalog = cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:One")])
        assert not catalog.save()


class TestExtractorPreserves:
    def test_a_bank_the_extractor_does_not_cover_is_kept(self, tmp_path):
        """Names read off an unfitted ROM must survive a rebuild."""
        path = write(tmp_path, {"XLEAD2-0": [{"pc": 0, "name": "ld:"}]})

        sys.path.insert(0, "tools")
        import extract_catalog

        banks_out = {"COMPOSER-0": [{"pc": 0, "name": "pno:One"}]}
        assert extract_catalog.merge_existing(banks_out, cat.load(path)) is True
        assert banks_out["XLEAD2-0"] == [{"pc": 0, "name": "ld:"}]
        assert banks_out["COMPOSER-0"] == [{"pc": 0, "name": "pno:One"}]

    def test_merging_an_empty_catalog_changes_nothing(self, tmp_path):
        sys.path.insert(0, "tools")
        import extract_catalog

        banks_out = {"COMPOSER-0": [{"pc": 0, "name": "pno:One"}]}
        assert extract_catalog.merge_existing(banks_out, cat.empty()) is False
        assert banks_out == {"COMPOSER-0": [{"pc": 0, "name": "pno:One"}]}
