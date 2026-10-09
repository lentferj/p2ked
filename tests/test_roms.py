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
        assert later.number == 133  # 128 + 5

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


class TestSimmIdIsTheBankSelectMsb:
    """Confirmed against hardware on 2026-09-12.

    A unit reporting SIMM IDs 4, 65 and 67 named, for each, the presets
    p2ked's catalog holds for the ROM at that Bank Select MSB. Three of
    twenty ROMs, so the docstring still records the limit rather than
    claiming the whole table is proven.
    """

    def test_it_maps_by_bank_select_msb(self):
        assert roms.rom_for_simm_id(7) is roms.rom("XLEAD")

    def test_the_confirmed_three_resolve(self):
        for simm_id, rom_id in ((4, "COMPOSER"), (65, "TECHNO"), (67, "BEATGARDEN")):
            assert roms.rom_for_simm_id(simm_id) is roms.rom(rom_id)

    def test_an_unknown_id_is_none(self):
        assert roms.rom_for_simm_id(99) is None

    def test_the_docstring_records_what_was_and_was_not_confirmed(self):
        """The caveat is narrower than it was, and must not vanish.

        Three ROMs is not twenty. If this wording is ever tidied into "the
        SIMM ID is the MSB", the limit goes with it.
        """
        text = roms.rom_for_simm_id.__doc__.lower()
        assert "confirmed against hardware" in text
        assert "not all" in text or "still possible" in text


class TestErrors:
    def test_an_unknown_rom_names_the_ones_that_exist(self):
        with pytest.raises(LookupError, match="XLEAD"):
            roms.rom("NOPE")

    def test_an_out_of_range_preset_says_the_range(self):
        with pytest.raises(LookupError, match="0-127"):
            roms.preset("XLEAD-0", 128)


class TestSentinelNames:
    """What a unit says instead of a name.

    Both observed against hardware on 2026-09-12, neither documented. They
    matter because a browser that shows them as names invents 128 presets
    called "(not installed)", and because `(not installed)` turns "is this
    ROM fitted?" from a timeout into an answer.
    """

    def test_absent_is_recognised(self):
        assert roms.is_absent("(not installed)")
        assert roms.is_absent("   (not installed)   ")

    def test_a_real_name_is_not_absent(self):
        assert not roms.is_absent("abc:Woven Bell")
        assert not roms.is_absent(None)

    def test_empty_slots_are_recognised(self):
        """The unit returns it with the usual blank category prefix."""
        assert roms.is_empty("   :default")
        assert roms.is_empty("default")

    def test_a_real_name_is_not_empty(self):
        assert not roms.is_empty("abc:Rusted Pad")
        assert not roms.is_empty(None)

    def test_the_two_are_different_things(self):
        """An empty slot exists; an absent one does not."""
        assert not roms.is_absent("   :default")
        assert not roms.is_empty("(not installed)")


class TestXLeadTwo:
    """A ROM no instrument-definition file covers.

    Found because a unit reported SIMM ID 14, then identified from E-MU's
    own X-Lead v2 patch list -- 640 presets in five banks, every sampled
    preset matching character for character.
    """

    def test_it_is_in_the_table(self):
        assert roms.rom_for_simm_id(14) is roms.rom("XLEAD2")

    def test_it_has_the_extent_the_unit_reported(self):
        entry = roms.rom("XLEAD2")
        assert entry.count == 640
        assert entry.lsbs == (0, 1, 2, 3, 4)

    def test_its_last_preset_is_the_one_the_unit_answers_for(self):
        """The unit named 639 and said "(not installed)" at 640."""
        assert roms.presets("XLEAD2-4")[-1].number == 639

    def test_it_is_not_confused_with_x_lead_one(self):
        """Different ROMs, different MSBs, different sizes."""
        assert roms.rom("XLEAD").msb == 7
        assert roms.rom("XLEAD2").msb == 14
        assert roms.rom("XLEAD").count != roms.rom("XLEAD2").count


class TestWhatADisagreementMeans:
    """A name differing from the catalog means different things by bank.

    In a ROM bank it means the printed list is wrong and the unit is right,
    which is the case for 11 of one ROM's 640 names, every one a whitespace
    difference E-MU's own document normalised away.

    A **user** bank cannot support the comparison at all: its printed names
    are E-MU's own placeholders (``usr:A0``, or anything like it), so a
    difference against them is guaranteed and means nothing. That is what
    marked every slot of every user bank with ``*`` and printed "saved over
    the factory preset" 128 times.

    Names here are invented, per CLAUDE.md; the shape of the difference is
    the real one.
    """

    def _catalog(self):
        from p2k import catalog as cat

        c = cat.Catalog(
            [
                cat.Entry("USER-0", 0, "Printed A Placeholder"),
                cat.Entry("XLEAD2-0", 90, "abc:Woven 1"),
            ]
        )
        c.set_live_name("USER-0", 0, "My Own Sound")
        c.set_live_name("XLEAD2-0", 90, "abc:Woven  1")  # two spaces
        return c

    def test_a_user_bank_is_never_marked_as_edited(self):
        """The bug: reading a user bank flagged every preset in it.

        E-MU's instrument definitions cannot document user memory, so the
        user banks carry placeholders where somebody's saved work goes. A
        real name can never equal one, so the comparison was guaranteed to
        "fail" for all 512 slots whether or not anybody had touched them.
        """
        c = self._catalog()
        assert not c.differs("USER-0", 0)
        assert c.disagreement("USER-0", 0) is None
        # The live name is still the one shown, and still says it came from
        # the unit -- which was always the real signal here.
        assert c.display_name("USER-0", 0) == "My Own Sound"
        assert c.is_live("USER-0", 0)

    def test_a_rom_difference_means_the_book_is_wrong(self):
        c = self._catalog()
        assert "printed list is wrong" in c.disagreement("XLEAD2-0", 90)

    def test_agreement_is_not_a_disagreement(self):
        from p2k import catalog as cat

        c = cat.Catalog([cat.Entry("USER-0", 1, "Same")])
        c.set_live_name("USER-0", 1, "Same")
        assert c.disagreement("USER-0", 1) is None

    def test_an_unread_slot_says_nothing(self):
        from p2k import catalog as cat

        c = cat.Catalog([cat.Entry("USER-0", 2, "Book")])
        assert c.disagreement("USER-0", 2) is None

    def test_a_bank_the_table_does_not_know_keeps_the_comparison(self):
        """A LookupError must not switch the check off everywhere.

        Invented bank ids -- a test fixture, a future ROM the table has not
        grown yet -- are not user memory, so a printed name there keeps its
        authority. This is also the shape of :class:`Catalog` used with a
        catalog keyed by something other than p2k's bank ids.
        """
        from p2k import catalog as cat

        c = cat.Catalog([cat.Entry("invented-0", 0, "Printed Name")])
        c.set_live_name("invented-0", 0, "Saved Over")
        assert c.differs("invented-0", 0)

    def test_a_user_bank_with_nothing_read_says_nothing_either(self):
        from p2k import catalog as cat

        c = cat.Catalog([cat.Entry("USER-0", 9, "Any Placeholder")])
        assert not c.differs("USER-0", 9)
        assert c.disagreement("USER-0", 9) is None


class TestTheBankBaseOffset:
    """TODO 18. The offset was re-walked on every call.

    ``presets()`` used to walk ``rom.lsbs`` to find a bank's offset from the
    start of its ROM, and the browser calls it once per highlighted row. The
    table already knew the answer; it just was not written down.

    What makes it safe to write down: ``ROMS`` is module data, built at
    import, and nothing writes to it. The fitted-ROM filter the app toggles
    is a list of bank ids in ``P2kedApp`` -- it decides which banks are
    *shown*, not which numbers they answer on, so it cannot invalidate this.
    The item's stated objection (``lsbs`` changes at runtime) turned out to
    be about the app's filter rather than the table, and this test says what
    is actually relied on.
    """

    def test_the_base_is_the_position_times_the_bank_size(self):
        for entry in roms.ROMS:
            for index, lsb in enumerate(entry.lsbs):
                bank = roms.bank(f"{entry.id}-{lsb}")
                assert bank.base == index * roms.PRESETS_PER_BANK, (
                    f"{bank.id}: {bank.base} is not {index} banks in"
                )

    def test_the_first_preset_number_is_the_base(self):
        for bank in roms.banks():
            if not bank.count:
                continue
            first, last = roms.presets(bank.id)[0], roms.presets(bank.id)[-1]
            assert first.number == bank.base
            assert last.number == bank.base + bank.count - 1

    def test_a_later_bank_does_not_restart_its_numbering(self):
        """The whole point of ``number`` versus ``program_change``: a preset
        is numbered within its ROM, so bank 1 preset 0 is ROM preset 128.
        Recomputing the offset per call is where a slip would hide."""
        for bank in roms.banks():
            if bank.base == 0:
                continue
            assert roms.presets(bank.id)[0].program_change == 0
            assert roms.presets(bank.id)[0].number != 0
