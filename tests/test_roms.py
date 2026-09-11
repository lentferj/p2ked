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

"""The ROM table and the two numbers that are not the same number."""

import pytest

from p2k import roms


class TestTable:
    def test_every_rom_has_a_unique_msb(self):
        """The MSB identifies the ROM. Two ROMs sharing one would make
        every preset in the second unreachable."""
        seen = [entry.msb for entry in roms.ROMS]
        assert len(seen) == len(set(seen))

    def test_every_rom_id_is_unique(self):
        ids = [entry.id for entry in roms.ROMS]
        assert len(ids) == len(set(ids))

    def test_user_is_msb_zero_and_writable(self):
        assert roms.USER.msb == roms.USER_MSB
        assert roms.USER.writable
        assert all(not entry.writable for entry in roms.ROMS[1:])

    def test_bank_counts_add_up_to_the_rom_count(self):
        for entry in roms.ROMS:
            total = sum(bank.count for bank in roms.banks(entry.id))
            assert total == entry.count, entry.id

    def test_no_bank_exceeds_a_program_change(self):
        for bank in roms.banks():
            assert 0 < bank.count <= roms.PRESETS_PER_BANK, bank.id

    def test_orchestral_one_has_the_third_bank_the_ins_file_loses(self):
        """The instrument-definition file indexes its third bank as 1281
        while labelling it 1282. Believed, that bank vanishes."""
        assert roms.rom("ORCH1").lsbs == (0, 1, 2)


class TestTwoNumbers:
    """A preset's number within its ROM is not its program change.

    The same discipline the sibling rxved applies to Roland's 1-based
    display numbers: both are carried, neither is derived at the point of
    use, and nothing converts silently.
    """

    def test_they_agree_only_in_the_first_bank(self):
        first = roms.preset("XLEAD-0", 5)
        assert first.number == 5 and first.program_change == 5

    def test_and_diverge_after_it(self):
        later = roms.preset("XLEAD-1", 5)
        assert later.program_change == 5
        assert later.number == 133          # 128 + 5

    def test_the_rom_number_counts_across_banks(self):
        last = roms.presets("COMPOSER-7")[-1]
        assert last.program_change == 127
        assert last.number == 1023

    def test_a_preset_knows_all_three_selection_numbers(self):
        entry = roms.preset("WORLD-2", 9)
        assert (entry.msb, entry.lsb, entry.program_change) == (9, 2, 9)


class TestLookup:
    def test_it_inverts_selection(self):
        entry = roms.preset("PHATT-3", 42)
        assert roms.lookup(entry.msb, entry.lsb, entry.program_change) == entry

    def test_an_unclaimed_msb_is_none_not_an_error(self):
        """A ROM this table has no row for is a real possibility."""
        assert roms.lookup(99, 0, 0) is None

    def test_an_lsb_the_rom_does_not_answer_on_is_none(self):
        assert roms.lookup(roms.rom("ORCH2").msb, 3, 0) is None

    def test_a_program_change_past_the_bank_is_none(self):
        assert roms.lookup(7, 0, 200) is None


class TestSimmIdIsAGuess:
    """rom_for_simm_id is a hypothesis, and the code must keep saying so."""

    def test_it_maps_by_bank_select_msb(self):
        assert roms.rom_for_simm_id(7) is roms.rom("XLEAD")

    def test_an_unknown_id_is_none(self):
        assert roms.rom_for_simm_id(99) is None

    def test_the_docstring_still_calls_it_a_guess(self):
        """Guard against the caveat being tidied away later.

        The mapping is unverified, and every screen that shows it says so
        on the strength of this docstring. If the wording goes, the warning
        goes with it.
        """
        text = roms.rom_for_simm_id.__doc__.lower()
        assert "guess" in text
        assert "untested" in text or "not" in text


class TestErrors:
    def test_an_unknown_rom_names_the_ones_that_exist(self):
        with pytest.raises(LookupError, match="XLEAD"):
            roms.rom("NOPE")

    def test_an_out_of_range_preset_says_the_range(self):
        with pytest.raises(LookupError, match="0-127"):
            roms.preset("XLEAD-0", 128)
