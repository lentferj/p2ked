# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# The key-hint legend is ported from the sibling rxved project, which ports
# it from s3ked, eosed and k2kremote:
#   Copyright (C) 2026  rxved / s3ked / eosed / k2kremote contributors
#                                                    - GPL-2.0-or-later
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

"""``p2ked`` -- a terminal browser for the Proteus 2000's presets.

Two panes: banks on the left, that bank's presets on the right, with the
three numbers that select one -- Program Change, Bank Select LSB, Bank
Select MSB -- on every row, in that order, because that is the order a
sequencer's MIDI track asks for them.

Two rules, both about not lying to the user:

**Moving the cursor never sends anything.** Selecting a preset changes what
the instrument plays, audibly, and a browser that did that on arrow-key
movement would be unusable next to a running sequencer. Selection is bound
to Enter and nothing else, and a test enforces it.

**Reading names is free and is not selection.** A Proteus names any preset
on request without playing it, so `r` reads a whole bank silently. Its
sibling rxved cannot do this and has to warn; p2ked has nothing to warn
about, and must not imply otherwise.

**Workers do MIDI; the main thread does everything else.** Every
``@work(thread=True)`` method talks to the device and then hands off with
``call_from_thread``. Nothing else belongs in one.
"""

from __future__ import annotations

import argparse
import sys
import threading
from typing import Dict, List, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Header, Input, Label, Static

from p2k import catalog as cat
from p2k import messages as params
from p2k import roms

__all__ = ["P2kedApp", "main", "build_parser", "KEY_HINTS", "wrap_blocks"]

_SEP = " · "

#: What `F` steps through, in order. Named after rxved's, deliberately:
#: the same key should mean the same three things across these projects.
VIEW_ALL = "all"
VIEW_BANK_FAVOURITES = "bank-favourites"
VIEW_ALL_FAVOURITES = "all-favourites"
VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)
VIEW_LABELS = {
    VIEW_ALL: "all presets",
    VIEW_BANK_FAVOURITES: "favourites in this bank",
    VIEW_ALL_FAVOURITES: "every favourite, all banks",
}

KEY_HINTS = (
    "↑↓ move", "tab pane", "⏎ select on the unit", "r read names",
    "m channels", "/ search", "c channel", "f favourite",
    "F favourites only", "C category", "a all ROMs", "i device", "? help",
    "q quit",
)


def wrap_blocks(blocks, width: int, sep: str = _SEP) -> str:
    """Pack hints into lines no wider than ``width``.

    Ported from rxved, which ports it from s3ked. Breaks happen only
    *between* blocks, so a hint is never split mid-label; a block wider than
    ``width`` takes its own line rather than being cut. The point is that
    the legend wraps instead of truncating -- a footer that silently drops
    its last few keys teaches the user those keys do not exist.
    """
    lines, current = [], ""
    for block in blocks:
        candidate = block if not current else current + sep + block
        if width and len(candidate) > width and current:
            lines.append(current)
            current = block
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


class KeyHints(Static):
    """The legend, wrapped to the window rather than truncated."""

    DEFAULT_CSS = "KeyHints { height: auto; background: $panel; padding: 0 1; }"

    def on_mount(self) -> None:
        self._render_hints()

    def on_resize(self) -> None:
        self._render_hints()

    def _render_hints(self) -> None:
        # NOT named _render: Widget._render is Textual's own, and shadowing
        # it makes every layout pass ask a None for its height. The failure
        # is an AttributeError deep in the framework, nowhere near here.
        self.update(wrap_blocks(KEY_HINTS, max(self.size.width - 2, 20)))


class ReportScreen(ModalScreen[None]):
    """A scrollable block of text: device details, help."""

    DEFAULT_CSS = """
    ReportScreen { align: center middle; }
    ReportScreen > Vertical {
        width: 84; height: 80%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    ReportScreen .body { height: 1fr; overflow-y: auto; }
    """

    BINDINGS = [Binding("escape", "close", "Close"),
                Binding("q", "close", "Close")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]{self._title}[/b]")
            yield Static(self._body, classes="body")
            yield Static("[dim]esc / q to close[/dim]")

    def action_close(self) -> None:
        self.dismiss(None)


class PromptScreen(ModalScreen[Optional[str]]):
    """One line of text."""

    DEFAULT_CSS = """
    PromptScreen { align: center middle; }
    PromptScreen > Vertical {
        width: 70; height: auto; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, current: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._prompt)
            yield Input(value=self._current, id="value")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChannelScreen(ModalScreen[None]):
    """Every MIDI channel: what it plays, and why it might not.

    The counterpart to the sibling rxved's multi-mode screen, and shaped by
    two differences.

    **Thirty-two channels, not sixteen.** A Proteus 2000 has two MIDI
    interfaces. Both halves are shown, because a channel that answers on an
    unwired interface is exactly the kind of thing somebody needs to see.

    **Read-only, and silent.** One Setup Dump gets the lot; nothing is
    selected and nothing sounds.

    **The MIDI Mode comes first, above the table**, because it decides
    whether anything below it applies: in Omni or Poly the unit is not
    multitimbral and the per-channel settings are not in effect. Saying
    "channel 3 is disabled" to somebody whose unit is in Omni would be true
    and useless. It is read as a parameter (id 385) rather than out of the
    dump, which needs no knowledge of the dump's master-block layout at all.
    """

    DEFAULT_CSS = """
    ChannelScreen { align: center middle; }
    ChannelScreen > Vertical {
        width: 96; height: 90%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    ChannelScreen DataTable { height: 1fr; }
    ChannelScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS = [Binding("escape", "close", "Close"),
                Binding("q", "close", "Close")]

    def __init__(self, dump, catalog, mode=None) -> None:
        super().__init__()
        self._dump = dump
        self._catalog = catalog
        #: ``None`` when it could not be read -- which is said, not hidden.
        self._mode = mode

    def compose(self) -> ComposeResult:
        title = (f"[b]Channels — setup “{self._dump.name}”[/b]"
                 if self._dump.name else "[b]Channels[/b]")
        if self._mode is None:
            title += "  [dim](MIDI mode could not be read)[/dim]"
        elif params.MidiMode.is_multitimbral(self._mode):
            title += f"  MIDI mode [b]{params.MidiMode.name(self._mode)}[/b]"
        else:
            title += (f"  [b]MIDI mode {params.MidiMode.name(self._mode)} — "
                      f"NOT multitimbral[/b]")
        with Vertical():
            yield Label(title)
            yield DataTable(id="channel-table", cursor_type="row",
                            zebra_stripes=True)
            yield Static(self._report(), classes="note")
            yield Static("[dim]esc / q to close[/dim]")

    def on_mount(self) -> None:
        table = self.query_one("#channel-table", DataTable)
        for label, key in (("ch", "ch"), ("plays", "plays"), ("vol", "vol"),
                           ("pan", "pan"), ("out", "out"), ("rxPC", "rxpc"),
                           ("", "flag")):
            table.add_column(label, key=key)
        for entry in self._dump.channels:
            table.add_row(*self._row(entry), key=str(entry.channel))

    def _plays(self, entry) -> str:
        """What this channel is set to, named if p2ked can name it."""
        rom = (roms.USER if entry.rom_id == roms.USER_ROM_ID
               else roms.rom_for_simm_id(entry.rom_id))
        if rom is None:
            return f"[dim]ROM {entry.rom_id}, preset {entry.preset}[/dim]"
        index, program_change = divmod(entry.preset, roms.PRESETS_PER_BANK)
        if index >= len(rom.lsbs):
            return f"[dim]{rom.name}, preset {entry.preset} (out of range)[/dim]"
        bank_id = f"{rom.id}-{rom.lsbs[index]}"
        name = self._catalog.display_name(bank_id, program_change)
        return f"{rom.name} {entry.preset:>3}  {name}".rstrip()

    def _row(self, entry):
        why = entry.silent_because
        return (
            str(entry.channel_display),
            self._plays(entry),
            str(entry.volume) if entry.volume else "[b]0[/b]",
            str(entry.pan - 64),
            str(entry.mix_output),
            "on" if entry.receive_program_change else "[b]OFF[/b]",
            f"[b]{why}[/b]" if why else "",
        )

    def _report(self) -> List[str]:
        return "\n".join(f"· {line}" for line in self._lines())

    def _lines(self) -> List[str]:
        out: List[str] = []
        if self._mode is not None and not params.MidiMode.is_multitimbral(
                self._mode):
            # First, and alone: in this mode nothing below is in effect, and
            # listing per-channel faults would send somebody to fix a
            # channel when the mode is the answer.
            out.append(
                f"This unit is in {params.MidiMode.name(self._mode).upper()} "
                f"mode, which is NOT multitimbral. The channel settings "
                f"below are stored but not in effect. Only in MULTI does a "
                f"per-channel setting mean anything.")
            return out
        audible = [c for c in self._dump.channels if c.silent_because is None]
        if audible:
            out.append(
                "Channels that would sound: "
                + ", ".join(str(c.channel_display) for c in audible))
        else:
            out.append("No channel on this unit would sound.")

        deaf = [c for c in self._dump.channels
                if not c.receive_program_change]
        if deaf:
            out.append(
                "Ignores Program Change on channel "
                + ", ".join(str(c.channel_display) for c in deaf)
                + " — a select aimed there does nothing.")

        out.append(
            "This unit has two MIDI interfaces, so channels 17-32 are the "
            "second one. They are real channels whether or not anything is "
            "plugged into it.")
        if self._mode is None:
            out.append(
                "The MIDI Mode could not be read. In Omni or Poly none of "
                "the above is in effect, so treat it as unknown rather than "
                "assuming this unit is multitimbral.")
        return out

    def action_close(self) -> None:
        self.dismiss(None)


class P2kedApp(App):
    """The browser."""

    CSS = """
    Screen { layers: base; }
    #panes { height: 1fr; }
    /* Sized to its content, not to a number. rxved can use a fixed 34
       because its bank labels are five characters; these run to
       "Orchestral Sessions Vol. 1 bank 0", and a fixed width does not clip
       the end of a label -- the table scrolls sideways and clips the
       *start*, so the pane reads "chno Synth bank 0" and looks corrupt.
       Capped so a narrow terminal still leaves room for the presets. */
    #bank-table {
        width: auto; min-width: 24; max-width: 56;
        border-right: solid $panel;
    }
    #preset-table { width: 1fr; }
    DataTable { height: 1fr; }
    #detail { height: 3; padding: 0 1; border-top: solid $panel; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    """

    BINDINGS = [
        # NOT a priority binding: a focused DataTable consumes Enter for its
        # own row selection, and a priority Enter at App level fires over
        # modal screens too. Enter arrives as RowSelected instead.
        Binding("enter", "select_preset", "Select on the unit", show=False),
        Binding("r", "read_names", "Read names"),
        Binding("m", "channels", "Channels"),
        Binding("slash", "search", "Search"),
        Binding("c", "pick_channel", "Channel"),
        Binding("f", "toggle_favorite", "Favourite"),
        Binding("F", "cycle_favorites", "Favourites view"),
        Binding("C", "pick_categories", "Categories"),
        Binding("a", "toggle_all_roms", "All ROMs"),
        Binding("i", "device_info", "Device"),
        Binding("question_mark", "help", "Help"),
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, device, *, catalog=None, channel: int = 0,
                 favorites=None, installed=None,
                 config_path: Optional[str] = None) -> None:
        super().__init__()
        self.device = device
        self.catalog = catalog if catalog is not None else cat.empty()
        self.channel = channel
        #: Injected rather than opened here, so a test never writes into the
        #: user's real database. rxved learned that one the hard way, by
        #: leaving two files in it.
        self.favorites = favorites
        self._lock = threading.RLock()
        #: ``{rom id: present}`` as the unit answered, or None if it was
        #: never asked. None means show everything: a bank list silently
        #: shortened by a failed query is worse than a long one.
        self.installed: Optional[Dict[int, bool]] = installed
        #: False = only the ROMs this unit actually has.
        self._all_roms = False
        self._bank_ids: List[str] = self._visible_banks()
        self._current_bank = self._bank_ids[0]
        self._current: List[roms.Preset] = []
        self._busy = False
        self._filling = False
        #: Which of the three views `F` is on.
        self.view_mode = VIEW_ALL
        #: Empty = every category. Categories are the "bas:" style prefix
        #: E-MU puts on a preset name.
        self._categories: set = set()

    def _rom_id_of(self, bank_id: str) -> int:
        entry = roms.bank(bank_id)
        return (roms.USER_ROM_ID
                if getattr(entry, "rom", None) is roms.USER else entry.msb)

    def _visible_banks(self) -> List[str]:
        """Bank ids to list: by default only ROMs the unit actually has.

        A Proteus 2000 has four SIMM sockets and a table of twenty possible
        ROMs, so listing all seventy-four banks means most of what is on
        screen cannot be played. Filtering needs the unit's answer, so when
        there is none -- demo mode, or a query that failed -- everything is
        shown rather than a list quietly cut down to nothing.
        """
        every = roms.bank_ids()
        if self._all_roms or not self.installed:
            return every
        kept = [b for b in every if self.installed.get(self._rom_id_of(b), False)]
        return kept or every

    def action_toggle_all_roms(self) -> None:
        """Every ROM in the table, or only the ones fitted."""
        if not self.installed:
            self.notify_status(
                "the unit was not asked which ROMs are fitted, so all are "
                "shown")
            return
        self._all_roms = not self._all_roms
        self._bank_ids = self._visible_banks()
        if self._current_bank not in self._bank_ids:
            self._current_bank = self._bank_ids[0]
        self._fill_banks()
        self._fill_presets(self._current_bank)
        self.notify_status(
            f"showing all {len(self._bank_ids)} banks" if self._all_roms
            else f"showing the {len(self._bank_ids)} banks this unit has")

    def _fill_banks(self) -> None:
        table = self.query_one("#bank-table", DataTable)
        self._filling = True
        try:
            table.clear()
            for bank_id in self._bank_ids:
                entry = roms.bank(bank_id)
                marked = len(self._favorite_keys(bank_id))
                table.add_row(entry.label, str(entry.msb), str(entry.lsb),
                              str(entry.count),
                              # blank rather than "0": a column of zeroes is
                              # noise, and the eye wants the few that differ
                              str(marked) if marked else "",
                              key=bank_id)
        finally:
            self._filling = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="panes"):
            yield DataTable(id="bank-table", cursor_type="row")
            yield DataTable(id="preset-table", cursor_type="row")
        yield Static("", id="detail")
        yield Static("", id="status")
        yield KeyHints()

    def on_mount(self) -> None:
        self.title = "p2ked"
        banks = self.query_one("#bank-table", DataTable)
        for label, key in (("bank", "bank"), ("MSB", "msb"), ("LSB", "lsb"),
                           ("n", "n"), ("♥", "fav")):
            banks.add_column(label, key=key)
        self._fill_banks()

        presets = self.query_one("#preset-table", DataTable)
        # The favourite marker gets a column of its own rather than a
        # character glued to the name: a name that starts with a marker
        # cannot be read straight down, and cannot be sorted or searched
        # without the marker getting in the way.
        for label, key in (("♥", "fav"), ("#", "pc"), ("name", "name"),
                           ("PC", "pcn"), ("LSB", "lsb"), ("MSB", "msb"),
                           ("ROM#", "rom")):
            presets.add_column(label, key=key)
        self._fill_presets(self._current_bank)
        banks.focus()
        self.notify_status(
            f"{len(self.catalog)} names from the catalog"
            if self.catalog else
            "no name catalog -- numbers only. Build one with "
            "tools/extract_catalog.py, or press r to read them off the unit."
        )

    # --- filling ------------------------------------------------------------

    def category_of(self, bank_id: str, program_change: int) -> str:
        """The ``bas:`` style prefix E-MU puts on a preset name.

        Returns an empty string for the handful that carry none, which are
        then grouped under "(none)" rather than silently vanishing from a
        category filter.
        """
        name = self.catalog.display_name(bank_id, program_change) or ""
        head, sep, _rest = name.partition(":")
        return head.strip() if sep and len(head) <= 4 else ""

    def categories(self, bank_id: str) -> List[str]:
        seen = {self.category_of(bank_id, e.program_change)
                for e in roms.presets(bank_id)}
        return sorted(c for c in seen if c)

    def _favorite_keys(self, bank_id: str) -> set:
        if self.favorites is None:
            return set()
        return self.favorites.keys_for_bank(bank_id)

    def _all_favourites(self) -> List[roms.Preset]:
        """Every favourite in every bank, in bank order then number.

        Built from the presets themselves rather than from the favourites
        rows, so a row naming a bank this build does not know is skipped
        instead of crashing the list.
        """
        if self.favorites is None:
            return []
        out = []
        wanted = {}
        for favourite in self.favorites.all(order="bank"):
            wanted.setdefault(favourite.bank_id, set()).add(favourite.number)
        for bank_id in roms.bank_ids():
            numbers = wanted.get(bank_id)
            if not numbers:
                continue
            out.extend(e for e in roms.presets(bank_id)
                       if e.program_change in numbers)
        return out

    def _visible(self, bank_id: str) -> List[roms.Preset]:
        """The presets the current view and filters leave showing."""
        if self.view_mode == VIEW_ALL_FAVOURITES:
            entries = self._all_favourites()
        else:
            entries = roms.presets(bank_id)
            if self.view_mode == VIEW_BANK_FAVOURITES:
                marked = self._favorite_keys(bank_id)
                entries = [e for e in entries
                           if e.program_change in marked]
        if self._categories:
            entries = [e for e in entries
                       if self.category_of(e.bank_id, e.program_change)
                       in self._categories]
        return entries

    def _fill_presets(self, bank_id: str) -> None:
        table = self.query_one("#preset-table", DataTable)
        self._current_bank = bank_id
        self._current = self._visible(bank_id)
        marked = self._favorite_keys(bank_id)
        column = table.columns.get("pc")
        if column is not None:
            from rich.text import Text
            column.label = Text(
                "bank / #" if self.view_mode == VIEW_ALL_FAVOURITES else "#")
        self._filling = True
        try:
            table.clear()
            for entry in self._current:
                name = self.catalog.display_name(entry.bank_id,
                                                 entry.program_change)
                if self.catalog.differs(entry.bank_id, entry.program_change):
                    shown = f"[b]{name}[/b] [dim]*[/dim]"
                elif self.catalog.is_live(entry.bank_id,
                                          entry.program_change):
                    shown = f"[b]{name}[/b]"
                else:
                    shown = name
                across = self.view_mode == VIEW_ALL_FAVOURITES
                fav_here = (self._favorite_keys(entry.bank_id) if across
                            else marked)
                star = ("[b]♥[/b]" if entry.program_change in fav_here else "")
                number = (f"{roms.bank(entry.bank_id).label} "
                          f"{entry.program_change:03d}" if across
                          else f"{entry.program_change:03d}")
                table.add_row(
                    star, number, shown,
                    str(entry.program_change), str(entry.lsb), str(entry.msb),
                    str(entry.number), key=entry.key,
                )
        finally:
            self._filling = False
        self._show_detail(0)

    # --- favourites ---------------------------------------------------------

    def action_toggle_favorite(self) -> None:
        """Mark or unmark the preset under the cursor. Sends no MIDI."""
        if self.favorites is None:
            self.notify_status(
                "no favourites database: pass --favorites, or let it use the "
                "default path")
            return
        entry = self._cursor_entry()
        if entry is None:
            return
        name = self.catalog.display_name(entry.bank_id, entry.program_change)
        if self.favorites.get(entry.bank_id, entry.program_change) is not None:
            self.favorites.remove(entry.bank_id, entry.program_change)
            self.notify_status(f"unfavourited {name}")
        else:
            self.favorites.add(entry.bank_id, entry.program_change, name=name)
            self.notify_status(f"favourited {name}")
        self._refill_bank_count(entry.bank_id)
        self._refill_keeping_place()

    def _refill_bank_count(self, bank_id: str) -> None:
        """Update one bank's favourite count in place.

        In place rather than by rebuilding the table: rebuilding moves the
        cursor, and rxved's comment on the same table records that as a real
        annoyance found the same way.
        """
        table = self.query_one("#bank-table", DataTable)
        try:
            marked = len(self._favorite_keys(bank_id))
            table.update_cell(bank_id, "fav", str(marked) if marked else "")
        except Exception:
            pass

    def action_cycle_favorites(self) -> None:
        """Step: all presets -> this bank's favourites -> every favourite.

        **Always exactly three steps**, even when a view comes up empty.
        Skipping an empty view to be helpful would make one keypress land
        somewhere different depending on what happens to be favourited, and
        a key whose behaviour you cannot predict is worse than an empty list
        that explains itself.
        """
        if self.favorites is None:
            self.notify_status("no favourites database")
            return
        index = VIEW_CYCLE.index(self.view_mode)
        self.view_mode = VIEW_CYCLE[(index + 1) % len(VIEW_CYCLE)]
        self._refill_keeping_place()
        shown = len(self._current)
        if self.view_mode == VIEW_ALL:
            self.notify_status(VIEW_LABELS[self.view_mode])
        elif not shown:
            where = ("this bank" if self.view_mode == VIEW_BANK_FAVOURITES
                     else "any bank")
            self.notify_status(
                f"{VIEW_LABELS[self.view_mode]} - nothing favourited in "
                f"{where} yet")
        else:
            self.notify_status(
                f"{VIEW_LABELS[self.view_mode]} - {shown}")

    def action_pick_categories(self) -> None:
        """Filter by the ``bas:`` style prefix."""
        available = self.categories(self._current_bank)
        if not available:
            self.notify_status(
                "no categories here: the catalog has no names for this bank")
            return
        current = ", ".join(sorted(self._categories))

        def chosen(text):
            if text is None:
                return
            wanted = {t.strip() for t in text.split(",") if t.strip()}
            unknown = wanted - set(available)
            if unknown:
                self.notify_status(
                    f"not in this bank: {', '.join(sorted(unknown))}")
                return
            self._categories = wanted
            self._refill_keeping_place()
            self.notify_status(
                f"categories: {', '.join(sorted(wanted))}" if wanted
                else "every category")

        self.push_screen(
            PromptScreen(
                f"categories, comma separated (blank for all). "
                f"This bank has: {', '.join(available)}", current),
            chosen)

    def _cursor_entry(self):
        table = self.query_one("#preset-table", DataTable)
        row = table.cursor_row
        if not self._current or row is None or row >= len(self._current):
            return None
        return self._current[row]

    def _refill_keeping_place(self) -> None:
        table = self.query_one("#preset-table", DataTable)
        row = table.cursor_row or 0
        self._fill_presets(self._current_bank)
        if self._current:
            table.move_cursor(row=min(row, len(self._current) - 1))

    def _show_detail(self, row: int) -> None:
        if not self._current or row >= len(self._current):
            self.query_one("#detail", Static).update("")
            return
        entry = self._current[row]
        name = self.catalog.display_name(entry.bank_id, entry.program_change)
        why = self.catalog.disagreement(
            entry.bank_id, entry.program_change, entry.rom.writable)
        note = f"  [dim]* {why}[/dim]" if why else ""
        self.query_one("#detail", Static).update(
            f"[b]{entry.bank.label} {entry.program_change:03d}[/b]  {name}"
            f"{note}\n"
            f"Program Change [b]{entry.program_change}[/b]   "
            f"Bank Select LSB [b]{entry.lsb}[/b] (CC#32)   "
            f"MSB [b]{entry.msb}[/b] (CC#0)   "
            f"[dim]preset {entry.number} within {entry.rom.name}[/dim]"
        )

    def notify_status(self, message: str, *, refused: bool = False) -> None:
        prefix = "[b]refused[/b] · " if refused else ""
        self.query_one("#status", Static).update(prefix + message)

    # --- navigation ---------------------------------------------------------

    def on_data_table_row_highlighted(self, event) -> None:
        if self._filling:
            return
        if event.data_table.id == "bank-table":
            row = event.cursor_row
            if 0 <= row < len(self._bank_ids):
                self._fill_presets(self._bank_ids[row])
        elif event.data_table.id == "preset-table":
            self._show_detail(event.cursor_row)

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a preset row selects it. Enter arrives here, not as a
        binding -- a focused DataTable consumes the key for itself."""
        if event.data_table.id == "preset-table":
            self.action_select_preset()

    def action_switch_pane(self) -> None:
        banks = self.query_one("#bank-table", DataTable)
        presets = self.query_one("#preset-table", DataTable)
        (presets if banks.has_focus else banks).focus()

    # --- operations ---------------------------------------------------------

    def _cursor_preset(self) -> Optional[roms.Preset]:
        table = self.query_one("#preset-table", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._current):
            return self._current[row]
        return None

    def action_select_preset(self) -> None:
        entry = self._cursor_preset()
        if entry is None:
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._select_worker(entry)

    @work(thread=True)
    def _select_worker(self, entry: roms.Preset) -> None:
        """**MIDI only.**"""
        try:
            with self._lock:
                self.device.select(entry, channel=self.channel)
        except Exception as exc:
            self.call_from_thread(
                self.notify_status, f"select: {exc}", refused=True)
            return
        self.call_from_thread(
            self.notify_status,
            f"selected {entry} on MIDI channel {self.channel + 1} "
            f"(PC {entry.program_change}, LSB {entry.lsb}, MSB {entry.msb})")

    def action_read_names(self) -> None:
        """Read this bank's names off the unit. Makes no sound."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._read_worker(self._current_bank)

    @work(thread=True)
    def _read_worker(self, bank_id: str) -> None:
        """**MIDI only** -- the catalog is updated on the main thread."""
        self._busy = True
        try:
            def progress(done: int, total: int) -> None:
                self.call_from_thread(
                    self.notify_status,
                    f"reading {bank_id}: {done}/{total} (silent)")

            with self._lock:
                names = self.device.read_bank_names(
                    bank_id, on_progress=progress)
        except Exception as exc:
            self.call_from_thread(
                self.notify_status, f"read: {exc}", refused=True)
            return
        finally:
            self._busy = False
        self.call_from_thread(self._adopt_names, bank_id, names)

    def _adopt_names(self, bank_id: str, names: Dict[int, str]) -> None:
        for program_change, name in names.items():
            self.catalog.set_live_name(bank_id, program_change, name)
        differing = sum(1 for pc in names
                        if self.catalog.differs(bank_id, pc))
        if bank_id == self._current_bank:
            self._fill_presets(bank_id)
        self.notify_status(
            f"read {len(names)} names from {bank_id}"
            + (f"; {differing} differ from the catalog" if differing else ""))

    def action_channels(self) -> None:
        """Show every MIDI channel. Reads one message; makes no sound."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._channels_worker()

    @work(thread=True)
    def _channels_worker(self) -> None:
        """**MIDI only** -- the screen is built on the main thread."""
        self._busy = True
        try:
            with self._lock:
                dump = self.device.read_setup()
                try:
                    mode = self.device.midi_mode()
                except Exception:
                    # A dump without a mode is still worth showing; the
                    # screen says the mode is unknown rather than assuming.
                    mode = None
        except Exception as exc:
            self.call_from_thread(
                self.notify_status, f"channels: {exc}", refused=True)
            return
        finally:
            self._busy = False
        self.call_from_thread(self._show_channels, dump, mode)

    def _show_channels(self, dump, mode) -> None:
        self.push_screen(ChannelScreen(dump, self.catalog, mode))

    def action_search(self) -> None:
        def done(text) -> None:
            if not text:
                return
            hits = self.catalog.search(text)
            if not hits:
                self.notify_status(f"nothing matching {text!r}")
                return
            lines = [f"{len(hits)} match(es) for {text!r}", ""]
            for bank_id, program_change, name in hits[:400]:
                try:
                    entry = roms.preset(bank_id, program_change)
                except LookupError:
                    continue
                lines.append(
                    f"{bank_id:<12} {program_change:03d}  {name:<18} "
                    f"PC {entry.program_change:>3}  LSB {entry.lsb:>2}  "
                    f"MSB {entry.msb:>3}")
            if len(hits) > 400:
                lines.append(f"... and {len(hits) - 400} more")
            self.push_screen(ReportScreen("Search", "\n".join(lines)))

        self.push_screen(PromptScreen("Search preset names:"), done)

    def _remember_channel(self, channel: int) -> None:
        """Save the send channel for next time.

        Only OSError is swallowed -- a read-only directory or a full disk,
        where forgetting beats refusing to run. A broader except would hide
        a bug: rxved's first version of this caught everything and so never
        noticed it was failing on every call.
        """
        if self._config_path is None:
            return
        from p2k import config

        try:
            config.save_channel(channel, self._config_path)
        except OSError:
            pass

    def action_pick_channel(self) -> None:
        def done(text) -> None:
            if not text:
                return
            try:
                value = int(text)
            except ValueError:
                self.notify_status(f"{text!r} is not a number", refused=True)
                return
            if not 1 <= value <= 16:
                self.notify_status("channel is 1-16", refused=True)
                return
            self.channel = value - 1
            self._remember_channel(self.channel)
            self.notify_status(f"sending on MIDI channel {value}")

        self.push_screen(
            PromptScreen("MIDI channel (1-16):", str(self.channel + 1)), done)

    def action_device_info(self) -> None:
        self._info_worker()

    @work(thread=True)
    def _info_worker(self) -> None:
        """**MIDI only** -- the report is built on the main thread."""
        try:
            with self._lock:
                fields = self.device.identify()
                config = self.device.hardware_config()
        except Exception as exc:
            self.call_from_thread(
                self.notify_status, f"device: {exc}", refused=True)
            return
        self.call_from_thread(self._show_info, fields, config)

    def _show_info(self, fields, config) -> None:
        lines = [f"connection   {self.device.description}", ""]
        if fields:
            lines.append(f"manufacturer {fields['manufacturer']:#04x}"
                         + ("  (E-MU)" if fields["is_emu"] else ""))
            lines.append(f"family       {fields['family']}")
            lines.append(f"device ID    {fields['device']}")
        lines.append("")
        lines.append(f"user presets {config.user_presets}")
        lines.append(f"SIMMs fitted {len(config.simms)}")
        for simm in config.simms:
            guess = roms.rom_for_simm_id(simm.simm_id)
            lines.append(
                f"  id {simm.simm_id:<4} {simm.presets:>4} presets  "
                + (guess.name if guess else "not in p2ked's table"))
        lines.append("")
        lines.append("ROM names read the SIMM ID as that ROM's Bank Select")
        lines.append("MSB. Confirmed against hardware for three ROMs on")
        lines.append("2026-09-12, which is not all twenty.")
        lines.append("")
        lines.append(f"catalog      {len(self.catalog)} names"
                     + (f" from {self.catalog.source}"
                        if self.catalog.source else ""))
        self.push_screen(ReportScreen("Device", "\n".join(lines)))

    def action_help(self) -> None:
        self.push_screen(ReportScreen("p2ked", _HELP))


_HELP = """\
Two panes. Left: every bank p2ked knows how to address. Right: that bank's
presets, with the three numbers that select one.

  PC    Program Change            -- 0-127 within the bank
  LSB   Bank Select LSB, CC#32    -- which bank within the ROM
  MSB   Bank Select MSB, CC#0     -- which ROM

They are shown PC first because that is the order a sequencer asks for them.
The unit receives them the other way round: both Bank Select bytes must
arrive BEFORE the program change, or the program change lands in whatever
bank was already selected.

"ROM#" is the preset's number within its ROM, which is what the unit's own
display shows and what System Exclusive asks for. PC is the wire byte within
the bank. They are different numbers and p2ked never converts silently
between them.

  ⏎   select this preset ON THE UNIT -- it will sound
  r   read this bank's names from the unit -- SILENT, nothing is selected
  /   search names
  c   set the MIDI channel selections are sent on
  i   device identity and which ROMs are fitted

Reading names makes no sound. A Proteus will name any preset in any fitted
ROM without selecting it, so there is nothing to warn about and no prompt.

Moving the cursor sends nothing at all.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p2ked", description="Browse an E-MU Proteus 2000's presets.")
    parser.add_argument("--port")
    parser.add_argument("--recv-port")
    parser.add_argument("--demo", action="store_true",
                        help="built-in demo device; opens no MIDI ports")
    parser.add_argument("--device-id", type=int, default=None)
    parser.add_argument("--channel", type=int, default=None)
    parser.add_argument("--catalog", default=None)
    parser.add_argument("--config", default=None,
                        help="settings cache (default: ./config.toml)")
    parser.add_argument("--all-roms", action="store_true",
                        help="list every ROM in the table, not just the "
                             "ones this unit has")
    parser.add_argument("--favorites", default=None,
                        help="favourites database "
                             "(default: the per-platform data directory)")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.channel is not None and not 1 <= args.channel <= 16:
        sys.exit("error: --channel is 1-16")

    if args.demo:
        from p2ked.demo import DemoDevice

        device = DemoDevice()
    else:
        from p2k import bridge as b
        from p2k import messages as msg

        b.install_clean_exit()
        try:
            if args.port:
                device = b.ProteusBridge.open(
                    args.port, recv_port=args.recv_port,
                    device_id=(args.device_id if args.device_id is not None
                               else msg.BROADCAST_DEVICE))
                if args.device_id is None:
                    # Adopt the ID the unit reports. Broadcast is not a
                    # safe default: this Proteus ignores it, so every read
                    # times out while identity still answers.
                    learned = device.learn_device_id(timeout=0.8)
                    if learned is not None:
                        print(f"  device ID {learned}", file=sys.stderr)
                    else:
                        print("  no identity reply; using broadcast",
                              file=sys.stderr)
            else:
                device = b.ProteusBridge.autodetect(
                    on_try=lambda n: print(f"  probing {n}...",
                                           file=sys.stderr))
        except Exception as exc:
            sys.exit(f"error: {exc}")

    from p2k import config as cfg

    config_path = getattr(args, "config", None) or cfg.DEFAULT_PATH
    # The channel given on the command line wins; otherwise the one used
    # last time, so `c` does not have to be pressed again every run.
    channel = ((args.channel - 1) if args.channel is not None
               else (cfg.load_channel(config_path) or 0))

    catalog = cat.load(args.catalog)
    from p2k.favorites import Favorites

    store = Favorites(args.favorites)

    # Ask the unit which ROMs it has before the interface starts. This is
    # MIDI, so it does not belong on a Textual worker or in on_mount; doing
    # it here keeps the rule that workers do MIDI and the main thread does
    # the rest. A failure is not fatal -- every bank is shown instead.
    installed = None
    if not args.all_roms and hasattr(device, "installed_roms"):
        try:
            print("  asking which ROMs are fitted...", file=sys.stderr)
            installed = device.installed_roms(timeout=0.6)
            have = sum(1 for present in installed.values() if present)
            print(f"  {have} of {len(installed)} ROMs answered",
                  file=sys.stderr)
        except Exception as exc:
            print(f"  could not ask ({exc}); showing every bank",
                  file=sys.stderr)

    app = P2kedApp(device, catalog=catalog, favorites=store,
                   installed=installed, config_path=config_path,
                   channel=channel)
    try:
        app.run()
    finally:
        store.close()
        device.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
