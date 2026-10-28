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

import time

import pytest

from p2k import catalog as cat
from p2k import roms
from textual.widgets import DataTable, Label

from p2ked.app import P2kedApp
from p2ked.demo import DemoDevice
from p2ked.multi import MultiScreen, mode_summary
from p2ked.prompts import PromptScreen

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app():
    catalog = cat.Catalog(
        [
            cat.Entry("USER-0", 0, "Velvet Bell"),
            cat.Entry("USER-0", 1, "Rusted Pad"),
        ]
    )
    return P2kedApp(DemoDevice(), catalog=catalog)


class TestStartup:
    async def test_it_starts_and_fills_both_panes(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#bank-table").row_count == len(roms.bank_ids())
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
            # Settled first: Enter while the launch's auto-read owns the
            # wire is refused, and the selection never happens.
            for _ in range(200):
                if not app._busy:
                    break
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

    async def test_a_user_bank_read_is_not_flagged_as_edited(self, app):
        """The reported bug: every preset in every user bank carried `*`.

        The catalog's user-bank "names" are E-MU's placeholders, so reading
        a real bank off the unit and comparing produced 128 differences and
        128 footnotes saying "saved over the factory preset" -- on a bank
        nobody had edited, and on a bank that had, indistinguishably.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app.catalog.is_live("USER-0", 0)
            assert not app.catalog.differs("USER-0", 0)
            assert app.catalog.disagreement("USER-0", 0) is None

    async def test_the_first_read_is_the_session_baseline(self, app):
        """Nothing is marked on the read that establishes the baseline --
        there is no earlier state for it to be different from."""
        said: list[str] = []
        app.notify_status = lambda message, **_kw: said.append(message)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app._baseline["USER-0"], "the read left no baseline"
            assert not app._session_change("USER-0", 0)
            assert any("baseline" in m for m in said)

    async def test_a_name_changed_since_p2ked_was_opened_is_flagged(self, app):
        """The signal that used to be claimed from a document that could
        not support it: the unit says something different now."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            original = app.catalog.live_name("USER-0", 0)
            # What a second read would find after the preset is edited
            # elsewhere -- on the unit's front panel, or by another tool.
            app.catalog.set_live_name("USER-0", 0, "Edited Somewhere Else")
            assert app._session_change("USER-0", 0)
            assert app._marked_because("USER-0", 0) == (
                "changed since p2ked was opened"
            )
            assert original != "Edited Somewhere Else"
            # The mark survives a re-render and is not re-anchored by it.
            app._fill_presets("USER-0")
            assert app._session_change("USER-0", 0), "the baseline re-anchored"

    async def test_a_bank_never_read_this_session_cannot_be_flagged(self, app):
        """No baseline, no mark: p2ked does not guess what a bank held."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert not app._session_change("USER-1", 0)
            assert app._marked_because("USER-1", 0) is None

    async def test_the_status_line_counts_session_changes(self, app):
        """The status line is where the change is announced; the row then
        carries it for the rest of the session."""
        said: list[str] = []
        app.notify_status = lambda message, **_kw: said.append(message)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            said.clear()
            # Stand in for the answer a second read would get back.
            app._adopt_names("USER-0", {0: "Edited Somewhere Else", 1: "Another Edit"})
            assert any("2 changed since p2ked was opened" in m for m in said)

    async def test_an_unchanged_second_read_says_so(self, app):
        said: list[str] = []
        app.notify_status = lambda message, **_kw: said.append(message)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            said.clear()
            app._adopt_names("USER-0", dict(app._baseline["USER-0"]))
            assert any("nothing changed" in m for m in said)
            assert not any("differ" in m for m in said)


class TestOneOperationAtATime:
    """The `_busy` flag: one thing on the wire, and a refusal rather than a
    queue.

    It is the only thing stopping two concurrent workers, and it used to be
    dead code -- checked in four places, set in none of them, so every
    check read `False` forever and the flag it was written to guard never
    happened. A bank read is about two and a half seconds, so a second
    press during one is a real wait, not a theoretical one.
    """

    @pytest.fixture
    def wired(self):
        """An app whose workers are counted instead of run.

        Spawning is the question, not traffic: a worker can sit in the
        pool before its first line, so "did it send anything" cannot tell
        a refused operation from a slow one.
        """
        app = P2kedApp(DemoDevice(), catalog=cat.empty())
        spawned = []

        app._read_worker = lambda bank: spawned.append(("read", bank))
        app._channels_worker = lambda: spawned.append(("channels",))
        app._info_worker = lambda: spawned.append(("info",))
        app._select_worker = lambda entry: spawned.append(("select",))
        return app, spawned

    async def test_nothing_starts_while_the_wire_is_busy(self, wired):
        app, spawned = wired
        async with app.run_test() as pilot:
            await pilot.pause()
            spawned.clear()
            app._busy = True
            app.action_read_names()
            app.action_channels()
            app.action_device_info()
            app.query_one("#preset-table").focus()
            app.action_select_preset()
            assert spawned == [], f"refused operations still started: {spawned}"

    async def test_the_flag_is_taken_before_the_worker_is_spawned(self, wired):
        """The race the flag exists for.

        ``@work(thread=True)`` returns immediately, so a worker that set
        the flag on its own thread would set it too late and two presses
        in one tick would both pass. Set synchronously here, the first
        press finishes the assignment before the second is dispatched.
        """
        app, spawned = wired
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            spawned.clear()
            for _ in range(5):
                app.action_read_names()
            assert len(spawned) == 1, spawned
            assert app._busy is True

    async def test_a_finished_read_releases_the_wire(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            app.action_read_names()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "a successful read never released it"

    async def test_a_failed_operation_releases_the_wire(self):
        """A worker that raises must not strand the flag.

        Otherwise one bad cable leaves the browser permanently refusing
        every operation, and the only symptom is a status bar that keeps
        saying "busy".
        """

        class Broken(DemoDevice):
            def read_bank_names(self, *args, **kwargs):
                raise TimeoutError("no reply")

        app = P2kedApp(Broken(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            app.action_read_names()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "a failed read stranded the flag"

    async def test_device_info_releases_the_wire(self, app):
        """`i` clears it too, which it did not: it had no `_busy` handling
        at all, so once the flag started working, pressing `i` would lock
        the browser for good."""
        async with app.run_test() as pilot:
            await pilot.pause()
            app._busy = False
            app.action_device_info()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "the info screen stranded the flag"

    async def test_a_selection_releases_the_wire(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#preset-table").focus()
            app._busy = False
            app.action_select_preset()
            for _ in range(200):
                await pilot.pause()
                if not app._busy:
                    break
            assert app._busy is False, "a selection stranded the flag"


class TestChannel:
    async def test_selection_goes_out_on_the_chosen_channel(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.channel = 9
            # Settled first, for the reason the enter test above is: a
            # refused Enter selects nothing.
            for _ in range(200):
                if not app._busy:
                    break
                await pilot.pause()
            app.query_one("#preset-table").focus()
            await pilot.press("enter")
            for _ in range(6):
                await pilot.pause()
            assert len(app.device.selected_log) == 1
            _entry, channel = app.device.selected_log[0]
            assert channel == 9, (
                "the selection went out on the wrong channel; the test used "
                "to assert only that something was sent"
            )


class TestTheChannelIsAlwaysOnScreen:
    """The send channel, said where it stays.

    It used to be said only in the sentence that announced a change --
    "channel 3" on the status line, which the next status message
    replaced. A channel is the one setting that decides whether a
    selection lands anywhere at all, so it belongs in the header, the way
    rxved shows its own send channel.

    ``self.channel`` is the wire value, 0-based; everything a reader sees
    is 1-16, because that is what the unit's display and its manual use.
    """

    async def test_the_header_shows_the_channel_at_startup(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "midi channel 1" in app.sub_title.lower()

    async def test_the_bracket_keys_move_it(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("right_square_bracket")
            await pilot.pause()
            assert "midi channel 2" in app.sub_title.lower()
            await pilot.press("left_square_bracket")
            await pilot.pause()
            assert "midi channel 1" in app.sub_title.lower()

    async def test_it_is_clamped_rather_than_wrapped(self, app):
        """Wrapping from 16 to 1 on a key held down a moment too long is
        how a selection ends up on a channel the user did not choose and
        cannot see they are on. The same rule the status line follows,
        now visible on the line that persists."""
        async with app.run_test() as pilot:
            await pilot.pause()
            app.channel = 0
            await pilot.press("left_square_bracket")
            await pilot.pause()
            assert "midi channel 1" in app.sub_title.lower()
            app.channel = 15
            await pilot.press("right_square_bracket")
            await pilot.pause()
            assert "midi channel 16" in app.sub_title.lower()

    async def test_the_c_prompt_moves_it(self, app):
        """The other door -- and the sentence the prompt says is now the
        one the header keeps."""
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_pick_channel()
            await pilot.pause()
            assert isinstance(app.screen, PromptScreen)
            await pilot.press(*list("12"))
            await pilot.press("enter")
            await pilot.pause()
            assert app.channel == 11
            assert "midi channel 12" in app.sub_title.lower()

    async def test_it_follows_the_channel_the_command_line_gave(self):
        """``--channel`` is how a session gets its channel, and the header
        has to say what the app was started with, not a default."""
        app = P2kedApp(DemoDevice(), catalog=cat.empty(), channel=6)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "midi channel 7" in app.sub_title.lower()


class TestMultiScreen:
    """The multi screen: every channel, and what it refuses to claim.

    Two jobs, and the second is the load-bearing one. The screen says which
    channels would sound -- and it says that it does not know the MIDI Mode.
    In Omni or Poly no per-channel setting is in effect, so a screen that
    quietly listed them anyway would send somebody hunting a channel setting
    when the mode is the answer. That is the mistake the sibling rxved made
    on a real synth.
    """

    async def _open(self, app, pilot):
        """``m``, retried until the multi screen is showing.

        One press is not enough: the launch's own name auto-read owns the
        wire at startup, and a press landing in it is refused with "busy"
        -- on a slow runner that outlasts a fixed handful of pauses, which
        is how CI got back the default screen and failed on ``_fitted``.
        So press until it is there or a wall-clock deadline says it never
        will be, the way ``tests/test_modal_ux.py``'s ``_open_multi``
        already does.
        """
        await pilot.pause()
        start = time.monotonic()
        while not isinstance(app.screen, MultiScreen):
            await pilot.press("m")
            for _ in range(8):
                if isinstance(app.screen, MultiScreen):
                    break
                await pilot.pause()
            if time.monotonic() - start >= 60.0:
                break
        return app.screen

    async def test_m_opens_it_with_every_channel(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            assert isinstance(screen, MultiScreen)
            table = screen.query_one("#multi-table", DataTable)
            assert table.row_count == 32

    async def test_opening_it_selects_nothing(self, app):
        async with app.run_test() as pilot:
            await self._open(app, pilot)
            assert app.device.selected_log == []

    async def test_it_names_what_a_channel_plays(self, app):
        """A preset the catalog can name is named, not numbered.

        The ROM's name in the last column is not the preset's name, and the
        two disagree often enough to be worth separate columns. This puts a
        name in the catalog -- what `r` reading a bank off the unit does --
        before the screen is built, so the row is checked against it.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            app.catalog.set_live_name("COMPOSER-0", 24, "wnd:B-Sax")
            screen = await self._open(app, pilot)
            table = screen.query_one("#multi-table", DataTable)
            keys = [c.key.value for c in table.columns.values()]
            # Demo channel 9 is enabled and points at Composer preset 24.
            row = str(table.get_row("8")[keys.index("plays")])
            assert row == "Composer 24 wnd:B-Sax"

    async def test_a_channel_the_catalog_cannot_name_says_which_rom_and_preset(
        self, app
    ):
        """And where nobody can name it, the ids are said -- not invented."""
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            table = screen.query_one("#multi-table", DataTable)
            keys = [c.key.value for c in table.columns.values()]
            row = str(table.get_row("8")[keys.index("plays")])
            assert row == "ROM 4 preset 24"

    async def test_a_user_memory_channel_is_named_from_the_catalog(self):
        """User memory is the one ROM the catalog has real names for.

        Built directly rather than through `m`: the demo points its live
        channels at a ROM. The preset is in the *second* bank, which is
        where the dump's ROM-relative preset number and the catalog's
        bank-relative program change stop being the same number -- an
        earlier version of this row used one for the other and could not
        name anything past 128.
        """
        dump = DemoDevice().read_setup()
        dump.channels[0].rom_id = roms.USER_ROM_ID
        dump.channels[0].preset = 129  # bank 1, program change 1
        catalog = cat.Catalog([cat.Entry("USER-1", 1, "My Riff")])
        assert MultiScreen(dump, catalog, None)._plays(dump.channels[0]) == (
            "User 129 My Riff"
        )

    async def test_every_reason_a_channel_is_silent_is_listed(self, app):
        """The whole set, in a stable order -- not one sentence.

        The screen this replaced carried a single ``silent_because``, so a
        channel with two faults showed one of them and the reader fixed
        that one, re-opened the screen, and found the second.
        """
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            reasons = {
                c.channel_display: c.silence_reasons(multitimbral=True, fitted=None)
                for c in screen._dump.channels
            }
            # Channel 1 is off, and an off channel reads preset 0 -- so both
            # are said, nearest cause first, plus the send the demo leaves
            # its disabled channels routed to.
            assert reasons[1] == [
                "channel is disabled (MIDI Enable is off)",
                "no preset assigned",
                "routed to send 2, not the preset's output",
            ]
            # Channel 6 is enabled but at volume 0: the second cause, which
            # a disabled channel in front of it would have masked. Its mix
            # output is the preset's own, so the volume is all that is
            # wrong with it.
            assert reasons[6] == ["volume is 0"]
            # Channels 9 and 10 are on, at full volume, and using the
            # preset's own output -- so nothing the unit reports stands
            # between them and a sound, and they are not listed at all.
            assert reasons[9] == []
            assert reasons[10] == []

    async def test_a_channel_pointing_at_a_rom_that_is_not_fitted_says_so(self, app):
        """The one reason that comes from what the unit said it has fitted.

        The app hands the screen the ROM table startup read off the unit,
        rather than the screen asking again -- so this checks that it got
        there, and that the row shows it.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            app.installed = {}  # the unit reported no SIMMs
            app.action_channels()
            for _ in range(8):
                await pilot.pause()
            screen = app.screen
            assert screen._fitted == {}
            assert "ROM 4 is not fitted" in screen._row(screen._dump.channels[8])[-1]
            assert "ROM 4 is not fitted" in screen._report()

    async def test_it_says_which_channels_would_sound(self):
        """The headline sentence, on data it is true of.

        Two halves, and the demo supplies both on its own now that an
        enabled channel uses the preset's own output: channels 9 and 10
        would sound. This one goes further and hands the screen a dump
        where *every* channel is live except one that ignores Program
        Change, which is the other thing worth knowing before aiming a
        select at a channel.
        """
        dump = DemoDevice().read_setup()
        for entry in dump.channels:
            entry.enable = 1
            entry.volume = 127
            entry.mix_output = -1  # use the preset's own output
        dump.channels[3].receive_program_change = 0
        report = MultiScreen(dump, cat.empty(), None)._report()
        assert report.startswith("Every one of the 32 channels would sound.")
        assert "Ignores Program Change on channel 4" in report
        assert "— a select aimed there does nothing" in report

    async def test_the_demo_s_own_enabled_channels_would_sound(self, app):
        """The honest version of the sentence above, on the demo's real data.

        The demo deliberately switches three channels on. It used to route
        all thirty-two through Send 2, so the screen said every one of them
        would not sound -- a fault the data did not have, reported by a
        read path, which is the one thing it must not do. The fix was in
        the data: an enabled channel uses the preset's own output. Channel
        6 stays silent for the reason it is *meant* to show, volume 0.
        """
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            dump = screen._dump
            enabled = [c for c in dump.channels if c.enable]
            assert [c.channel_display for c in enabled] == [6, 9, 10]
            fitting = screen._fitted
            says_sound = {
                c.channel_display
                for c in dump.channels
                if not c.silence_reasons(multitimbral=True, fitted=fitting)
            }
            assert says_sound == {9, 10}
            assert "2 of 32 channels would sound" not in screen._report()
            assert "30 of 32 channels would not sound:" in screen._report()
            # And the rows carry it: "why not" is blank for those two.
            table = screen.query_one("#multi-table", DataTable)
            keys = [c.key.value for c in table.columns.values()]
            assert str(table.get_row("8")[keys.index("why")]) == ""
            assert str(table.get_row("9")[keys.index("why")]) == ""
            assert "volume is 0" in str(table.get_row("5")[keys.index("why")])

    async def test_it_says_which_channels_would_not_sound(self, app):
        """And it says what it cannot see, rather than leaving a silence on
        screen that the reader has to interpret.

        The demo's own data is counted as it stands: three channels are
        switched on, one of them at volume 0, and the twenty-nine that are
        off are still routed to Send 2. Two would sound; thirty would not.
        """
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            report = screen._report()
            assert "30 of 32 channels would not sound:" in report
            # The three kinds of fault the demo's data really has, each
            # named once -- not rounded into "everything is broken".
            assert "channel is disabled (MIDI Enable is off)" in report
            assert "volume is 0" in report
            assert "routed to send 2, not the preset's output" in report
            assert "ch  1  " in report
            assert "ch  9  " not in report
            assert "the cable" in report
            assert "the monitor" in report

    async def test_the_midi_mode_is_read_and_shown(self, app):
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            from p2k.messages import MidiMode

            assert screen._mode == MidiMode.MULTI
            assert "multi" in mode_summary(screen._mode)

    async def test_a_non_multitimbral_mode_suppresses_the_rest(self):
        """In Omni the channel settings are stored but not in effect.

        Listing per-channel faults there would send somebody to fix a
        channel when the mode is the answer -- the exact wrong turn the
        sibling rxved nearly took on an XV-2020.
        """
        from p2k.messages import MidiMode

        dump = DemoDevice().read_setup()
        screen = MultiScreen(dump, cat.empty(), MidiMode.OMNI)
        report = screen._report()
        assert "single-preset mode" in report
        assert "is in effect" in report
        assert "Nothing below is a fault" in report
        # The per-channel reasons are gone, not merely relabelled: with 32
        # soundless channels, three lines about the mode is the whole report.
        assert len(report.splitlines()) == 1
        assert "channel is disabled" not in report
        assert "routed to send" not in report
        # And the rows carry none either -- this is what feeds them.
        assert screen._multitimbral is False
        assert all(
            not c.silence_reasons(multitimbral=screen._multitimbral, fitted=None)
            for c in dump.channels
        )
        assert "NOT multitimbral" in mode_summary(MidiMode.OMNI)

    async def test_an_unreadable_mode_is_said_not_assumed(self, app):
        """A mode that could not be read is said so, and not rounded up to
        multi by silence."""
        async with app.run_test() as pilot:
            await pilot.pause()
            # What the app's worker hands this when `midi_mode()` raised.
            app._show_channels(app.device.read_setup(), None)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, MultiScreen)
            assert screen._mode is None
            assert "could not be read" in str(screen.query_one(Label).visual)
            assert "could not be read" in mode_summary(None)

    async def test_it_explains_the_second_interface(self, app):
        """Thirty-two rows, and half of them are another interface.

        A reader who does not know that will read the empty bottom half as
        a fault, which is why the sentence is on the screen at all.
        """
        async with app.run_test() as pilot:
            screen = await self._open(app, pilot)
            assert "two MIDI interfaces" in screen._report()
            assert "channels 17-32" in screen._report()


class TestNamesKeptFromTheUnit:
    """A name read off a ROM is permanent, so it is written down.

    The ROM is uniquely identified and its contents never change, which is
    what lets a ROM taken out of the machine still be browsed, searched and
    favourited from the name p2ked kept.
    """

    async def test_reading_a_rom_bank_is_written_to_the_catalog_file(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        catalog = cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:One")], path=path)
        app = P2kedApp(DemoDevice(), catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._remember_names("XLEAD-0", {0: "lead:Read", 1: "lead:Also"})
            assert cat.load(path).read_name("XLEAD-0", 1) == "lead:Also"

    async def test_a_user_bank_is_not_written_down(self, tmp_path):
        """User memory is the user's work, not the ROM's; it stays live."""
        path = str(tmp_path / "catalog.json")
        catalog = cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:One")], path=path)
        app = P2kedApp(DemoDevice(), catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._remember_names("USER-0", {0: "My Riff"})
            assert not (tmp_path / "catalog.json").exists()


class TestAbsentRomIsShownInItalics:
    async def test_a_named_rom_that_is_not_fitted_is_still_listed(self):
        from p2k import roms

        catalog = cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:BoXT Mono")])
        app = P2kedApp(DemoDevice(), catalog=catalog, installed={4: True})
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "XLEAD-0" in app._bank_ids
            assert app._rom_is_absent(roms.rom("XLEAD").msb)

    async def test_its_bank_and_presets_render_in_italics(self):
        catalog = cat.Catalog([cat.Entry("XLEAD-0", 0, "lead:BoXT Mono")])
        app = P2kedApp(DemoDevice(), catalog=catalog, installed={4: True})
        async with app.run_test() as pilot:
            await pilot.pause()
            banks = app.query_one("#bank-table", DataTable)
            assert "[i]" in str(banks.get_row("XLEAD-0")[0])
            app._fill_presets("XLEAD-0")
            presets = app.query_one("#preset-table", DataTable)
            assert "[i]" in str(presets.get_row("XLEAD-0:0000")[3])
