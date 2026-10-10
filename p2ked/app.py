# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# The legend itself is now vinsynlib's, which carries the copyright of every
# sibling it was assembled from; see src/vinsynlib/ui/hints.py there.
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
from typing import Dict, List, Optional, Tuple

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Header, Label, Static

from p2k import catalog as cat
from p2k import roms
from p2ked._report import say_connected, say_fallback, say_probing
from p2ked.masteredit import (
    MASTER_BY_ID,
    MASTER_PARAMETERS,
    EditGate,
    EditLog,
    MasterEditor,
)
from p2ked.multi import MasterEditScreen, MultiScreen
from p2ked.prompts import PromptScreen
from vinsynlib import cli as vincli
from vinsynlib.keys import wrap_blocks  # re-exported: it is in __all__
from vinsynlib.ui.hints import KeyHints

# The legend's wrapping and the widget that draws it are the family's; see
# src/vinsynlib/keys.py and src/vinsynlib/ui/hints.py, which carry the
# copyright of every sibling the shared version was assembled from. The
# library's KeyHints takes the blocks as a constructor argument where the
# local one read this module's KEY_HINTS global, so the construction site
# below passes KEY_HINTS explicitly. The CSS selector is unchanged -- same
# class name, so the stylesheet rule still matches.

__all__ = [
    "P2kedApp",
    "PromptScreen",
    "main",
    "build_parser",
    "KEY_HINTS",
    "wrap_blocks",
]

#: What the favourites view steps through, in order. Named after rxved's,
#: deliberately: the same key should mean the same three things across these
#: projects. (It is `v` in both; see KEY_HINTS.)
VIEW_ALL = "all"
VIEW_BANK_FAVOURITES = "bank-favourites"
VIEW_ALL_FAVOURITES = "all-favourites"
VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)
VIEW_LABELS = {
    VIEW_ALL: "all presets",
    VIEW_BANK_FAVOURITES: "favourites in this bank",
    VIEW_ALL_FAVOURITES: "every favourite, all banks",
}

#: The legend. The shared blocks in the family's order, with this tool's own
#: hints in the one place the shared legend leaves room for them -- after
#: "n note", before "i device" -- so a reader's eye finds them in the same
#: spot in all nine.
#:
#: ``v favourites view`` lives there too, and that is a declared divergence:
#: the family puts the favourites view on ``F``, one shift-slip from the
#: ``f`` that *writes* the favourites database. rxved moved it to ``v`` for
#: exactly that reason and p2ked now agrees with it -- a read should not sit
#: under a shift away from a write. See tests/test_conformance.py, which
#: asserts this and nothing else about it.
KEY_HINTS = (
    "↑↓ move",
    "tab pane",
    "⏎ select on the unit",
    "r read names",
    "/ search",
    "[ ] channel",
    "c set channel",
    "f favourite",
    "t tags",
    "n note",
    # `m` means channels in a browser everywhere in this family. Here that
    # was already true: the multi screen shows what every MIDI channel plays.
    "m channels",
    # p2ked's own, plus the one key it borrows from rxved rather than the
    # family.
    "v favourites view",
    "C category",
    "a all ROMs",
    # The write path, in the family's own words: these three are the
    # `EDITOR_KEYS` entries p2ked now binds, spelled as the family spells
    # them so a reader who has used rxved already knows what they do. They
    # are in the legend because a write must be findable from the legend --
    # a key that changes the unit and is documented nowhere is a key that
    # gets pressed by accident.
    "w write gate",
    "z undo",
    "Z undo all",
    "i device",
    "? help",
    "q quit",
)


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

    BINDINGS = [Binding("escape", "close", "Close"), Binding("q", "close", "Close")]

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
        # Enter is NOT bound here, and the rest of the family agrees: a
        # focused DataTable consumes Enter for its own row selection, so it
        # arrives as RowSelected instead. Binding it at App level would mean
        # taking Enter from the table and every other table key with it.
        # Checked from the legend side in tests/test_conformance.py.
        Binding("r", "read_names", "Read names"),
        Binding("m", "channels", "Multi"),
        Binding("slash", "search", "Search"),
        Binding("left_square_bracket", "channel_down", "Channel -"),
        Binding("right_square_bracket", "channel_up", "Channel +"),
        Binding("c", "pick_channel", "Channel"),
        Binding("f", "toggle_favorite", "Favourite"),
        Binding("v", "cycle_favorites", "Favourites view"),
        Binding("t", "edit_tags", "Tags"),
        Binding("n", "edit_note", "Note"),
        Binding("C", "pick_categories", "Categories"),
        Binding("a", "toggle_all_roms", "All ROMs"),
        Binding("i", "device_info", "Device"),
        Binding("question_mark", "help", "Help"),
        Binding("tab", "switch_pane", "Switch pane"),
        Binding("q", "quit", "Quit"),
        # The editor's gate, on the family's own key. Locked by default: a
        # write needs an explicit act, and the legend shows which state it is
        # in, so "why did my edit not send?" is answered on screen.
        Binding("w", "toggle_write_gate", "Write gate"),
        Binding("z", "undo", "Undo edit"),
        Binding("Z", "undo_all", "Undo all edits"),
    ]

    #: True while a worker owns the wire. Declared here, above the methods
    #: that read it, because mypy infers an attribute's type from the first
    #: assignment it has seen and this one is made at the end of
    #: ``__init__``. See there for what the flag is for.
    _busy: bool

    #: What ``--allow-write`` was given on the command line: the state the
    #: gate below starts in, recorded because the gate itself is created on
    #: first use. Declared here for the same reason ``_busy`` is.
    _allow_write: bool

    # --- the write gate ------------------------------------------------------

    @property
    def _gate(self) -> EditGate:
        """One gate per app, created on first use.

        Armed when it is first made if ``--allow-write`` was given, and
        locked otherwise. The flag is a starting state rather than a second
        gate, because two gates would mean a caller could hold one the app
        does not check -- and the screen's ``w`` and the app's ``w`` toggle
        the same object either way.
        """
        if getattr(self, "_write_gate", None) is None:
            self._write_gate = EditGate(armed=self._allow_write)
        return self._write_gate

    @property
    def _editor(self) -> MasterEditor:
        """One editor per app: the gate above, and the log beside it."""
        if getattr(self, "_master_editor", None) is None:
            self._master_editor = MasterEditor(self._gate, EditLog())
        return self._master_editor

    def action_toggle_write_gate(self) -> None:
        self._gate.toggle()
        self.notify_status(self._gate.describe())

    def action_undo(self) -> None:
        """``z`` in the browser: reverse the last logged master edit.

        The edit screen binds the same key to the same name -- a modal
        screen's bindings take precedence over the app's, so there is no
        double handling -- but an edit is made *through* the screen and
        undone *from* the browser after it closes, so the key has to work
        with no screen open. It is the app's because the worker is: see
        :meth:`_undo_master_edits`.
        """
        self._undo_master_edits(1)

    def action_undo_all(self) -> None:
        """``Z``: every logged master edit, newest first."""
        self._undo_master_edits(self._editor.log.pending)

    def action_edit_master(self) -> None:
        """Open the master-parameter editor.

        Reads first, because the editor shows what each value is now, and
        because an edit without a read before it cannot be undone -- there
        would be nothing to send back.
        """
        if self.device is None:
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._edit_master_worker()

    @work(thread=True)
    def _edit_master_worker(self) -> None:
        """**MIDI only** -- every value is read here, the screen is built on
        the main thread."""
        values: Dict[int, Optional[int]] = {}
        try:
            with self._lock:
                dump = self.device.read_setup()
                for parameter in MASTER_PARAMETERS:
                    try:
                        values[parameter.parameter_id] = self.device.read_parameter(
                            parameter.parameter_id
                        )
                    except Exception:
                        values[parameter.parameter_id] = None
        except Exception as exc:
            self.call_from_thread(self.notify_status, f"multi: {exc}", refused=True)
            self._busy = False
            return
        self.call_from_thread(self._show_master_edit, dump, values)

    def _show_master_edit(self, dump, values) -> None:
        self._busy = False
        screen = MasterEditScreen(
            dump,
            values,
            self._editor,
            on_apply=self._apply_master_edit,
            on_undo=self._undo_master_edits,
        )
        # Kept, so a worker that finishes after the screen closed still has
        # somewhere to report -- and so the gate's state, which the screen
        # shows, is the same one the edits went through.
        self._edit_screen = screen
        self.push_screen(screen)

    def _apply_master_edit(self, parameter_id: int, value: int) -> None:
        """Send one master edit, then read it back.

        The gate and the range are checked here, on the main thread and
        before anything is spawned -- the same shape as ``_busy`` below.
        This is the only place an edit can be stopped before it reaches
        the wire: the screen offers the edit, but the app is what sends it,
        so a check that lived on the screen would be a check the next
        caller of this method could simply not make.

        A refusal says so and sends nothing. :meth:`MasterEditor.allow`
        answers both cases -- a locked gate and a value outside the
        parameter's range -- because both are a reader's question rather
        than a failure of the program.
        """
        parameter = MASTER_BY_ID.get(parameter_id)
        if parameter is None:
            self.notify_status(
                f"parameter {parameter_id} is not one p2ked edits", refused=True
            )
            return
        refusal = self._editor.allow(parameter, value)
        if refusal is not None:
            self.notify_status(refusal, refused=True)
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._apply_worker(parameter_id, value)

    @work(thread=True)
    def _apply_worker(self, parameter_id: int, value: int) -> None:
        """Read, write, read again -- one operation on one thread.

        A write and its verification are not split across threads: another
        read landing between them would be read back as the write's result,
        which is exactly the failure this machinery exists to catch.
        """
        failure: Optional[BaseException] = None
        before: Optional[int] = None
        after: Optional[int] = None
        try:
            with self._lock:
                before = self.device.read_parameter(parameter_id)
                self.device.set_parameter(parameter_id, value)
                after = self.device.read_parameter(parameter_id)
        except Exception as exc:
            failure = exc
        self.call_from_thread(
            self._edit_applied, parameter_id, value, failure, before, after
        )

    def _edit_applied(self, parameter_id, value, failure, before, after) -> None:
        """Report an edit, and log it only if the read-back agreed.

        Three outcomes, not two: the operation could not be carried out at
        all (``failure``), the unit refused (the read-back says something
        else), and it worked. All three are said differently, because "the
        value did not change" is a different thing to act on from "the wire
        broke".
        """
        self._busy = False
        parameter = MASTER_BY_ID.get(parameter_id)
        if failure is not None:
            label = parameter.label if parameter else f"parameter {parameter_id}"
            ok, message = False, f"{label}: {failure}"
        elif parameter is None:  # pragma: no cover - the table is fixed
            ok, message = False, f"parameter {parameter_id} is not one p2ked edits"
        else:
            ok, message = self._editor.finish(
                parameter, value, before=before, after=after
            )
        if getattr(self, "_edit_screen", None) is not None:
            self._edit_screen.result(ok, message)
        self.notify_status(message, refused=not ok)

    def _undo_master_edits(self, count: int) -> None:
        """Reverse the last ``count`` edits. Nothing read-only about it."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        plan = self._editor.undo_plan(count)
        if not plan:
            self.notify_status("nothing to undo")
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._undo_worker(plan)

    @work(thread=True)
    def _undo_worker(self, plan) -> None:
        results: List[Tuple[int, bool]] = []
        try:
            with self._lock:
                for parameter_id, value in plan:
                    try:
                        self.device.set_parameter(parameter_id, value)
                        results.append((parameter_id, True))
                    except Exception:
                        results.append((parameter_id, False))
        finally:
            self.call_from_thread(self._edit_undone, results)

    def _edit_undone(self, results) -> None:
        self._busy = False
        self.notify_status(self._editor.undo_report(results))

    def __init__(
        self,
        device,
        *,
        catalog=None,
        channel: int = 0,
        favorites=None,
        installed=None,
        config_path: Optional[str] = None,
        allow_write: bool = False,
    ) -> None:
        super().__init__()
        self.device = device
        #: What ``--allow-write`` asked for. The gate is built lazily -- see
        #: :attr:`_gate` -- so the flag is kept here as the state to start it
        #: in rather than passed to a gate that does not exist yet.
        self._allow_write = allow_write
        self.catalog = catalog if catalog is not None else cat.empty()
        self.channel = channel
        #: Injected rather than opened here, so a test never writes into the
        #: user's real database. rxved learned that one the hard way, by
        #: leaving two files in it.
        self.favorites = favorites
        #: Where the send channel is remembered. Injected and None in tests,
        #: so a test cannot drop a config into the working directory.
        self._config_path = config_path
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
        #: True while a worker owns the wire. **Set synchronously on the
        #: main thread**, before the worker is spawned, and cleared in the
        #: worker's ``finally``.
        #:
        #: It has to be set before ``@work(thread=True)`` returns, because
        #: that call returns immediately: a worker that set the flag on its
        #: own thread would do it too late, and two quick keypresses would
        #: both read False and both start. Set synchronously, the first
        #: press completes the assignment before the second is dispatched,
        #: because the two run on one thread.
        #:
        #: Not a lock -- ``self._lock`` is that -- but a refusal, so the
        #: second press says so instead of queueing behind a 2.5 s bank
        #: read the user cannot see.
        self._busy = False
        self._filling = False
        #: Which of the three views `v` is on.
        self.view_mode = VIEW_ALL
        #: User banks whose names have already been fetched this session.
        self._auto_read: set = set()
        #: The bank waiting for its names because something else had the
        #: wire. One slot, not a queue -- see :meth:`_auto_read_user_names`.
        self._wanted: Optional[str] = None
        #: ``{bank_id: {program change: name}}`` as each bank was first read
        #: this session -- the baseline a later read is compared against.
        #: Only user banks are ever read unprompted (a ROM's names are the
        #: catalog's job), so in practice this is "what your user memory said
        #: when you opened p2ked". See :meth:`_session_change`.
        self._baseline: Dict[str, Dict[int, str]] = {}
        #: Empty = every category. Categories are the "bas:" style prefix
        #: E-MU puts on a preset name.
        self._categories: set = set()

    def _rom_id_of(self, bank_id: str) -> int:
        entry = roms.bank(bank_id)
        return (
            roms.USER_ROM_ID if getattr(entry, "rom", None) is roms.USER else entry.msb
        )

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
                "the unit was not asked which ROMs are fitted, so all are shown"
            )
            return
        self._all_roms = not self._all_roms
        self._bank_ids = self._visible_banks()
        if self._current_bank not in self._bank_ids:
            self._current_bank = self._bank_ids[0]
        self._fill_banks()
        self._fill_presets(self._current_bank)
        self.notify_status(
            f"showing all {len(self._bank_ids)} banks"
            if self._all_roms
            else f"showing the {len(self._bank_ids)} banks this unit has"
        )

    def _fill_banks(self) -> None:
        table = self.query_one("#bank-table", DataTable)
        self._filling = True
        try:
            table.clear()
            for bank_id in self._bank_ids:
                entry = roms.bank(bank_id)
                marked = len(self._favorite_keys(bank_id))
                table.add_row(
                    entry.label,
                    str(entry.msb),
                    str(entry.lsb),
                    str(entry.count),
                    # blank rather than "0": a column of zeroes is
                    # noise, and the eye wants the few that differ
                    str(marked) if marked else "",
                    key=bank_id,
                )
        finally:
            self._filling = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="panes"):
            yield DataTable(id="bank-table", cursor_type="row")
            yield DataTable(id="preset-table", cursor_type="row")
        yield Static("", id="detail")
        yield Static("", id="status")
        # The library's widget takes the blocks; the local one read this
        # module's KEY_HINTS global, which a library cannot do.
        yield KeyHints(KEY_HINTS)

    def on_mount(self) -> None:
        self.title = "p2ked"
        banks = self.query_one("#bank-table", DataTable)
        for label, key in (
            ("bank", "bank"),
            ("MSB", "msb"),
            ("LSB", "lsb"),
            ("n", "n"),
            ("♥", "fav"),
        ):
            banks.add_column(label, key=key)
        self._fill_banks()

        presets = self.query_one("#preset-table", DataTable)
        # The favourite marker gets a column of its own rather than a
        # character glued to the name: a name that starts with a marker
        # cannot be read straight down, and cannot be sorted or searched
        # without the marker getting in the way.
        for label, key in (
            ("♥", "fav"),
            ("#", "pc"),
            ("name", "name"),
            ("PC", "pcn"),
            ("LSB", "lsb"),
            ("MSB", "msb"),
            ("ROM#", "rom"),
        ):
            presets.add_column(label, key=key)
        self._fill_presets(self._current_bank)
        banks.focus()
        self.notify_status(
            f"{len(self.catalog)} names from the catalog"
            if self.catalog
            else "no name catalog -- numbers only. Build one with "
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
        seen = {
            self.category_of(bank_id, e.program_change) for e in roms.presets(bank_id)
        }
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
            out.extend(e for e in roms.presets(bank_id) if e.program_change in numbers)
        return out

    def _visible(self, bank_id: str) -> List[roms.Preset]:
        """The presets the current view and filters leave showing."""
        if self.view_mode == VIEW_ALL_FAVOURITES:
            entries = self._all_favourites()
        else:
            entries = roms.presets(bank_id)
            if self.view_mode == VIEW_BANK_FAVOURITES:
                marked = self._favorite_keys(bank_id)
                entries = [e for e in entries if e.program_change in marked]
        if self._categories:
            entries = [
                e
                for e in entries
                if self.category_of(e.bank_id, e.program_change) in self._categories
            ]
        return entries

    def _is_user_bank(self, bank_id: str) -> bool:
        entry = roms.bank(bank_id)
        return getattr(entry, "rom", None) is roms.USER

    def _session_change(self, bank_id: str, program_change: int) -> bool:
        """Whether this slot's name changed since this session began.

        The baseline is the **first read of that bank in this session**, which
        for a user bank is the lumpy thing p2ked already does the moment you
        look at it -- so "what the unit said when you opened it", without a
        catalog that could know. A ROM bank has no baseline (it is only read
        when asked, and it does not change), so this is False there, and its
        `*` comes from :meth:`p2k.catalog.Catalog.differs` instead.

        The baseline is frozen for the session on purpose. Re-anchoring after
        every read would make a `*` vanish the moment it is noticed, which is
        the opposite of useful.
        """
        original = self._baseline.get(bank_id, {}).get(program_change)
        if original is None:
            return False
        live = self.catalog.live_name(bank_id, program_change)
        return live is not None and live != original

    def _marked_because(self, bank_id: str, program_change: int) -> Optional[str]:
        """Why this slot carries ``*``, or ``None``.

        Two different complaints, and a reader is owed the difference:
        something the user did since p2ked was opened, and a printed list
        that is simply wrong. The first only exists for a bank that has been
        read twice this session; the second only exists where the printed
        list has authority, which is a ROM.
        """
        if self._session_change(bank_id, program_change):
            return "changed since p2ked was opened"
        return self.catalog.disagreement(bank_id, program_change)

    def _auto_read_user_names(self, bank_id: str) -> None:
        """Fetch a user bank's names the first time it is looked at.

        A ROM bank's names are fixed, so the catalog knows them and there is
        nothing to ask the instrument. A **user** bank's are whatever
        somebody saved there, so a catalog entry for one is a placeholder
        and always wrong -- `usr:A0` is not a name, it is an admission. The
        instrument has the real ones and gives up a whole bank in about two
        and a half seconds, silently.

        Once per bank per session, and never while something else is on the
        wire -- but a bank skipped because the wire was busy is *remembered*,
        and read when it frees. That is the whole difference between this
        and what it used to do:

            scroll 0 -> 1 -> 2 quickly
              old: bank 1 reads, bank 2 is dropped on the floor, and nothing
                   runs until the cursor moves off it and back on
              now: bank 1 reads, then bank 2 reads, with no further input

        The want is recorded *before* the busy test, because returning before
        recording it is what lost the bank in the first place. One slot, not
        a queue: whichever bank is on screen when the wire frees is the one
        that gets read, and a bank passed over in the interim is not
        re-visited for its own sake.
        """
        if self.device is None:
            return
        if bank_id in self._auto_read or not self._is_user_bank(bank_id):
            return
        self._wanted = bank_id
        self._pump_reading()

    def _pump_reading(self) -> None:
        """Start the read that is waiting, if there is one and the bus is free.

        Main thread only. Every path that finishes with the wire clears
        ``_busy`` and then calls this, so a read deferred by a busy bus is
        picked up without anybody having to notice it was skipped.

        A deferred bank is *not* dropped if the reader has moved on. The
        auto-read was always going to read it -- it is the same read, one
        cursor stop later -- and scrolling back to a bank that is already
        loaded is the point. The alternative, dropping it, means a bank
        scrolled past is never loaded until it is visited again, which is
        the bug this whole mechanism was written about.
        """
        wanted = self._wanted
        if wanted is None or self._busy or self.device is None:
            return
        if wanted in self._auto_read:
            self._wanted = None
            return
        self._wanted = None
        self._auto_read.add(wanted)
        self._busy = True  # main thread, before the spawn; see _busy
        self._read_worker(wanted)

    def _fill_presets(self, bank_id: str) -> None:
        table = self.query_one("#preset-table", DataTable)
        self._current_bank = bank_id
        self._current = self._visible(bank_id)
        marked = self._favorite_keys(bank_id)
        # The all-favourites view spans every bank, so asking the store per
        # row was one SQL query per line, redrawn on every toggle. One query
        # for the whole set instead -- which is what Favorites.keys exists
        # for, and says so in its docstring.
        every_bank: dict = {}
        if self.view_mode == VIEW_ALL_FAVOURITES and self.favorites is not None:
            for key in self.favorites.keys():
                bank, _, number = key.rpartition(":")
                every_bank.setdefault(bank, set()).add(int(number))
        column = table.columns.get("pc")
        if column is not None:
            from rich.text import Text

            column.label = Text(
                "bank / #" if self.view_mode == VIEW_ALL_FAVOURITES else "#"
            )
        self._filling = True
        try:
            table.clear()
            for entry in self._current:
                name = self.catalog.display_name(entry.bank_id, entry.program_change)
                if self._marked_because(entry.bank_id, entry.program_change):
                    shown = f"[b]{name}[/b] [dim]*[/dim]"
                elif self.catalog.is_live(entry.bank_id, entry.program_change):
                    shown = f"[b]{name}[/b]"
                else:
                    shown = name
                across = self.view_mode == VIEW_ALL_FAVOURITES
                fav_here = every_bank.get(entry.bank_id, set()) if across else marked
                star = "[b]♥[/b]" if entry.program_change in fav_here else ""
                number = (
                    f"{roms.bank(entry.bank_id).label} {entry.program_change:03d}"
                    if across
                    else f"{entry.program_change:03d}"
                )
                table.add_row(
                    star,
                    number,
                    shown,
                    str(entry.program_change),
                    str(entry.lsb),
                    str(entry.msb),
                    str(entry.number),
                    key=entry.key,
                )
        finally:
            self._filling = False
        self._show_detail(0)
        self._auto_read_user_names(bank_id)

    # --- favourites ---------------------------------------------------------

    def action_toggle_favorite(self) -> None:
        """Mark or unmark the preset under the cursor. Sends no MIDI."""
        if self.favorites is None:
            self.notify_status(
                "no favourites database: pass --favorites, or let it use the "
                "default path"
            )
            return
        entry = self._cursor_entry()
        if entry is None:
            return
        name = self.catalog.display_name(entry.bank_id, entry.program_change)
        # Favorites.toggle, not remove-then-add: un-favouriting keeps the
        # row so that a rating, tags, a note and the original date survive
        # being toggled off and on. Doing it here as a delete followed by a
        # fresh add destroyed all four, and `f` is one keystroke.
        now = self.favorites.toggle(entry.bank_id, entry.program_change, name=name)
        self.notify_status(f"{'favourited' if now else 'unfavourited'} {name}")
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

    def _favourite_under_cursor(self):
        """The favourite row for the slot under the cursor, if there is one.

        Tags and notes hang off a favourite, so there is nothing to attach
        them to until `f` has been pressed. Saying so is better than
        silently creating one: the user asked to annotate, not to favourite.
        """
        entry = self._cursor_entry()
        if entry is None or self.favorites is None:
            return None, None
        bank_id = entry.bank_id
        number = entry.program_change
        return (bank_id, number), self.favorites.get(bank_id, number)

    def action_edit_tags(self) -> None:
        where, existing = self._favourite_under_cursor()
        if where is None:
            return
        if existing is None:
            self.notify_status("not a favourite yet -- press f first", refused=True)
            return

        def apply(value):
            if value is None:
                return
            self.favorites.set_tags(where[0], where[1], value)
            self._refill_keeping_place()
            self.notify_status("tags set")

        self.push_screen(PromptScreen("Tags (comma separated):", existing.tags), apply)

    def action_edit_note(self) -> None:
        where, existing = self._favourite_under_cursor()
        if where is None:
            return
        if existing is None:
            self.notify_status("not a favourite yet -- press f first", refused=True)
            return

        def apply(value):
            if value is None:
                return
            self.favorites.set_note(where[0], where[1], value)
            self._refill_keeping_place()
            self.notify_status("note set")

        self.push_screen(PromptScreen("Note:", existing.note), apply)

    def action_cycle_favorites(self) -> None:
        """Step: all presets -> this bank's favourites -> every favourite.

        **Always exactly three steps**, even when a view comes up empty.
        Skipping an empty view to be helpful would make one keypress land
        somewhere different depending on what happens to be favourited, and
        a key whose behaviour you cannot predict is worse than an empty list
        that explains itself.

        ``v``, not the family's ``F``: ``f`` writes the favourites database
        and this only reads it, so a shift-slip between them is a write
        arriving one slip away from a read. rxved's reasoning, and p2ked
        follows it.
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
            where = (
                "this bank" if self.view_mode == VIEW_BANK_FAVOURITES else "any bank"
            )
            self.notify_status(
                f"{VIEW_LABELS[self.view_mode]} - nothing favourited in {where} yet"
            )
        else:
            self.notify_status(f"{VIEW_LABELS[self.view_mode]} - {shown}")

    def action_pick_categories(self) -> None:
        """Filter by the ``bas:`` style prefix."""
        available = self.categories(self._current_bank)
        if not available:
            self.notify_status(
                "no categories here: the catalog has no names for this bank"
            )
            return
        current = ", ".join(sorted(self._categories))

        def chosen(text):
            if text is None:
                return
            wanted = {t.strip() for t in text.split(",") if t.strip()}
            unknown = wanted - set(available)
            if unknown:
                self.notify_status(f"not in this bank: {', '.join(sorted(unknown))}")
                return
            self._categories = wanted
            self._refill_keeping_place()
            self.notify_status(
                f"categories: {', '.join(sorted(wanted))}"
                if wanted
                else "every category"
            )

        self.push_screen(
            PromptScreen(
                f"categories, comma separated (blank for all). "
                f"This bank has: {', '.join(available)}",
                current,
            ),
            chosen,
        )

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
        why = self._marked_because(entry.bank_id, entry.program_change)
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
        # Enter reaches here through on_data_table_row_selected, because a
        # focused DataTable consumes the key for its own row selection; there
        # is no App-level Enter binding (see BINDINGS). The guard stays as
        # defence in depth: it must never play whatever row the unfocused
        # preset pane happens to remember -- an audible action from a pane
        # the user is not looking at. Enter means "the row I am looking at".
        table = self.query_one("#preset-table")
        if not table.has_focus:
            return
        entry = self._cursor_preset()
        if entry is None:
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True
        self._select_worker(entry)

    @work(thread=True)
    def _select_worker(self, entry: roms.Preset) -> None:
        """**MIDI only.**"""
        try:
            with self._lock:
                self.device.select(entry, channel=self.channel)
        except Exception as exc:
            self.call_from_thread(self.notify_status, f"select: {exc}", refused=True)
            return
        finally:
            self._busy = False
        self.call_from_thread(
            self.notify_status,
            f"selected {entry} on MIDI channel {self.channel + 1} "
            f"(PC {entry.program_change}, LSB {entry.lsb}, MSB {entry.msb})",
        )

    def action_read_names(self) -> None:
        """Read this bank's names off the unit. Makes no sound."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._read_worker(self._current_bank)

    @work(thread=True)
    def _read_worker(self, bank_id: str) -> None:
        """**MIDI only** -- everything after it happens on the main thread.

        The ``_busy`` flag is cleared on the main thread, by whatever
        handler the hand-off reaches, and never in this thread's ``finally``.
        Clearing it here let the flag flip *before* the names had made it
        onto the main thread, so a fast second press started a second read
        with the first still delivering; and with the deferred read below,
        the next read would be spawned and then have the flag cleared out
        from under it. One hand-off, one place, one order.
        """
        error: Optional[str] = None
        names: Dict[int, str] = {}
        try:

            def progress(done: int, total: int) -> None:
                self.call_from_thread(
                    self.notify_status, f"reading {bank_id}: {done}/{total} (silent)"
                )

            with self._lock:
                names = self.device.read_bank_names(bank_id, on_progress=progress)
        except Exception as exc:
            error = f"read: {exc} ({bank_id})"
        try:
            if error is not None:
                self.call_from_thread(self._read_finished, error)
            else:
                self.call_from_thread(self._adopt_names, bank_id, names)
        except Exception:
            # The app is going away, so there is no main thread to hand off
            # to. Clearing the flag here -- the very thing the docstring
            # forbids -- is the lesser evil: a flag left set refuses every
            # MIDI operation for the rest of the session, and there is no
            # session left to race.
            self._busy = False

    def _read_finished(self, error: Optional[str] = None) -> None:
        """The wire is free again: say so, and pick up any deferred read.

        Main thread. ``_adopt_names`` calls this after adopting a bank's
        names, which is what keeps the flag and the adoption in one order.
        """
        if error is not None:
            self.notify_status(error, refused=True)
        self._busy = False
        self._pump_reading()

    def _adopt_names(self, bank_id: str, names: Dict[int, str]) -> None:
        for program_change, name in names.items():
            self.catalog.set_live_name(bank_id, program_change, name)
        # The baseline: this bank as it stood the first time it was read this
        # session. Established before any comparison, so the very read that
        # creates it is never itself marked as a change.
        baseline = self._baseline.get(bank_id)
        if baseline is None:
            self._baseline[bank_id] = dict(names)
            changed: List[int] = []
        else:
            changed = [
                program_change
                for program_change, name in sorted(names.items())
                if program_change in baseline and baseline[program_change] != name
            ]
        differing = sum(1 for pc in names if self.catalog.differs(bank_id, pc))
        # A favourite made before any names were known carries a blank
        # label, and shows as one in the favourites view and in `name`
        # ordering. This is the read that supplies the real name, so it is
        # the moment to adopt it. Main thread, after the catalog is
        # updated -- the favourites store is SQLite and a worker must not
        # touch it.
        if self.favorites is not None:
            self.favorites.refresh_names(
                lambda bank, number: self.catalog.live_name(bank, number)
            )
        if bank_id == self._current_bank:
            self._fill_presets(bank_id)

        marks = []
        if changed:
            marks.append(f"{len(changed)} changed since p2ked was opened")
        if differing:
            marks.append(f"{differing} differ from the printed list")
        if marks:
            said = f"read {len(names)} names from {bank_id}: " + ", ".join(marks)
        elif baseline is None:
            said = (
                f"read {len(names)} names from {bank_id}: that is this "
                f"session's baseline for this bank"
            )
        else:
            said = f"read {len(names)} names from {bank_id}; nothing changed"
        self.notify_status(said)
        self._read_finished()

    def action_channel_down(self) -> None:
        """Previous MIDI channel. Sends nothing by itself."""
        self._step_channel(-1)

    def action_channel_up(self) -> None:
        """Next MIDI channel. Sends nothing by itself."""
        self._step_channel(1)

    def _step_channel(self, by: int) -> None:
        """Move one channel, clamped. 0-15 internally, 1-16 on screen.

        Clamped rather than wrapped: wrapping from 16 to 1 on a key held
        down a moment too long is how a selection ends up on a channel the
        user did not choose and cannot see they are on.
        """
        channel = min(15, max(0, self.channel + by))
        if channel == self.channel:
            return
        self.channel = channel
        self._remember_channel(channel)
        self.notify_status(f"channel {channel + 1}")

    def action_channels(self) -> None:
        """Show every MIDI channel. Reads one message; makes no sound."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._channels_worker()

    @work(thread=True)
    def _channels_worker(self) -> None:
        """**MIDI only** -- the screen is built on the main thread."""
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
            self.call_from_thread(self.notify_status, f"multi: {exc}", refused=True)
        else:
            self.call_from_thread(self._show_channels, dump, mode)
        finally:
            self._busy = False

    def _show_channels(self, dump, mode) -> None:
        """Open the multi screen, wired back here so `r` can re-read.

        The screen holds no device and starts no worker: a worker belongs to
        the app, and one started by a screen would outlive the screen it was
        opened from. ``on_refresh`` is the hand-off and re-runs this same
        worker -- which is also why a refresh cannot interleave with the read
        that opened the screen, since ``_busy`` is still set.
        """
        screen = MultiScreen(
            dump,
            self.catalog,
            mode,
            fitted=self.installed,
            on_edit=self.action_edit_master,
        )
        screen.on_refresh = self._refresh_multi
        self.push_screen(screen)

    def _refresh_multi(self) -> None:
        """Re-read the setup for the screen already open. Read-only."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._channels_worker()

    def action_search(self) -> None:
        def done(text) -> None:
            if not text:
                return
            hits = self.catalog.search(text)
            if not hits:
                self.notify_status(f"nothing matching {text!r}")
                return
            lines = [f"{len(hits)} match(es) for {text!r}", ""]
            notes = {"session": 0, "printed": 0}
            for bank_id, program_change, name, differs in hits[:400]:
                try:
                    entry = roms.preset(bank_id, program_change)
                except LookupError:
                    continue
                # Two reasons for the mark, and a search result comes from a
                # bank the reader has not opened -- so which one it is has
                # to be counted, not guessed at.
                changed = self._session_change(bank_id, program_change)
                notes["session" if changed else "printed"] += bool(differs or changed)
                lines.append(
                    f"{bank_id:<12} {program_change:03d}  "
                    f"{name + (' *' if differs or changed else ''):<20} "
                    f"PC {entry.program_change:>3}  LSB {entry.lsb:>2}  "
                    f"MSB {entry.msb:>3}"
                )
            if notes["session"]:
                lines += [
                    "",
                    f"* {notes['session']} of these changed since p2ked was "
                    f"opened: this session's names, not the printed catalog.",
                ]
            if notes["printed"]:
                lines += [
                    "",
                    f"* {notes['printed']} of these differ from the printed "
                    f"catalog: the unit's name is shown.",
                ]
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
            PromptScreen("MIDI channel (1-16):", str(self.channel + 1)), done
        )

    def action_device_info(self) -> None:
        """Who the unit is and which ROMs are fitted. Silent."""
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True
        self._info_worker()

    @work(thread=True)
    def _info_worker(self) -> None:
        """**MIDI only** -- the report is built on the main thread."""
        try:
            with self._lock:
                fields = self.device.identify()
                config = self.device.hardware_config()
        except Exception as exc:
            self.call_from_thread(self.notify_status, f"device: {exc}", refused=True)
        else:
            self.call_from_thread(self._show_info, fields, config)
        finally:
            self._busy = False

    def _show_info(self, fields, config) -> None:
        lines = [f"connection   {self.device.description}", ""]
        if fields:
            lines.append(
                f"manufacturer {fields['manufacturer']:#04x}"
                + ("  (E-MU)" if fields["is_emu"] else "")
            )
            lines.append(f"family       {fields['family']}")
            lines.append(f"device ID    {fields['device']}")
        lines.append("")
        lines.append(f"user presets {config.user_presets}")
        lines.append(f"SIMMs fitted {len(config.simms)}")
        for simm in config.simms:
            guess = roms.rom_for_simm_id(simm.simm_id)
            lines.append(
                f"  id {simm.simm_id:<4} {simm.presets:>4} presets  "
                + (guess.name if guess else "not in p2ked's table")
            )
        lines.append("")
        lines.append("ROM names read the SIMM ID as that ROM's Bank Select")
        lines.append("MSB. Confirmed against hardware for three ROMs on")
        lines.append("2026-09-12, which is not all twenty.")
        lines.append("")
        lines.append(
            f"catalog      {len(self.catalog)} names"
            + (f" from {self.catalog.source}" if self.catalog.source else "")
        )
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
    parser = vincli.make_parser(
        prog="p2ked", description="Browse an E-MU Proteus 2000's presets."
    )
    # --scan is asked for here too, and for the same reason p2kcli has it:
    # this unit is on a DIN cable behind an interface whose name says
    # nothing about E-MU, which is an argument that a sweep is a poor
    # *default*, not that the escape hatch should not exist. device_channel
    # =False and exclusive_channel=False: a Proteus 2000 has no base channel
    # of its own to set; --channel is the one a preset change is sent on,
    # which is what this tool sends on.
    vincli.add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        device_id=True,
        catalog=True,
        config=True,
        favorites=True,
        allow_write=True,
    )
    parser.add_argument(
        "--all-roms",
        action="store_true",
        help="list every ROM in the table, not just the ones this unit has",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    vincli.validate_common(args)
    # A flag that cannot mean anything here is refused rather than ignored.
    if args.recv_port and not args.port:
        sys.exit("error: --recv-port names the input to go with --port; give both")
    if args.scan and args.port:
        sys.exit("error: --scan searches for the port and --port names it; use one")

    from p2k import config as cfg

    config_path = getattr(args, "config", None) or cfg.DEFAULT_PATH

    if args.demo:
        from p2ked.demo import DemoDevice

        device = DemoDevice()
    else:
        from p2k import bridge as b
        from p2k import messages as msg

        b.install_clean_exit()
        #: The device ID the unit reported (or the one named), when a port was
        #: named. ``None`` means nothing worth remembering came of it.
        learned: Optional[int] = None
        try:
            if args.port:
                device = b.ProteusBridge.open(
                    args.port,
                    recv_port=args.recv_port,
                    device_id=(
                        args.device_id
                        if args.device_id is not None
                        else msg.BROADCAST_DEVICE
                    ),
                )
                if args.device_id is None:
                    # Adopt the ID the unit reports. Broadcast is not a
                    # safe default: this Proteus ignores it, so every read
                    # times out while identity still answers.
                    learned = device.learn_device_id(timeout=0.8)
                    if learned is not None:
                        print(f"  device ID {learned}", file=sys.stderr)
                    else:
                        learned = None
                        print("  no identity reply; using broadcast", file=sys.stderr)
                else:
                    learned = args.device_id
            else:
                # One Identity Request to the remembered port; the sweep
                # only when there is nothing remembered, when the
                # remembered port no longer answers, or on --scan. The unit
                # this was written for sits on a port whose name no hint
                # matches, so without a remembered port the user passes
                # --port on every launch or waits through 20 probes.
                device = b.ProteusBridge.connect(
                    config_path=config_path,
                    scan=args.scan,
                    device_id=args.device_id,
                    on_try=say_probing,
                    on_fallback=say_fallback,
                )
                if getattr(device, "port", None):
                    say_connected(device.port)
        except Exception as exc:
            sys.exit(f"error: {exc}")

        # Remember the port only when it is worth remembering: the user named
        # it AND something answered. `connect` writes the pair itself after a
        # sweep; the file is that path's input, and a fast launch must not
        # rewrite it. The old code also saved `device_id` on every launch,
        # which rewrote the file the fast path exists to trust -- and nothing
        # ever read that key back. A port the user named and that answered is
        # remembered here, and nothing else writes this path.
        try:
            if args.port and learned is not None:
                port = getattr(device, "port", None)
                recv = getattr(device, "recv_port", None)
                if port and recv:
                    cfg.save_ports(port, recv, config_path)
        except OSError:
            pass  # a read-only directory must not stop the browser
    # The channel given on the command line wins; otherwise the one used
    # last time, so `c` does not have to be pressed again every run.
    channel = (
        (args.channel - 1)
        if args.channel is not None
        else (cfg.load_channel(config_path) or 0)
    )

    catalog = cat.load(args.catalog)
    from p2k.favorites import Favorites

    try:
        store = Favorites(args.favorites)
    except Exception as exc:
        # _migrate refuses a database written by a newer p2ked, which is the
        # right refusal; every other startup failure in main() leaves by
        # sys.exit, and this one used to print a traceback instead.
        raise SystemExit(f"error: {exc}")

    # Ask the unit which ROMs it has before the interface starts. This is
    # MIDI, so it does not belong on a Textual worker or in on_mount; doing
    # it here keeps the rule that workers do MIDI and the main thread does
    # the rest. A failure is not fatal -- every bank is shown instead.
    #
    # One Configuration request, not one name request per ROM. Measured on
    # 2026-10-02 against a Proteus 2000: 16.5 ms against 370.7 ms, and the
    # worst case collapses from twenty 0.6 s timeouts -- twelve seconds of
    # silence before the first paint -- to one. `installed_roms` is still
    # used when a device does not offer the cheap way, and stays as the
    # independent cross-check it was written to be. See TODO.md item 34.
    installed = None
    if not args.all_roms:
        ask = getattr(device, "roms_from_config", None)
        if ask is None:
            ask = getattr(device, "installed_roms", None)
        if ask is not None:
            try:
                print("  asking which ROMs are fitted...", file=sys.stderr)
                installed = ask()
                have = sum(1 for present in installed.values() if present)
                print(f"  {have} of {len(installed)} ROMs fitted", file=sys.stderr)
            except Exception as exc:
                installed = None
                print(f"  could not ask ({exc}); showing every bank", file=sys.stderr)

    app = P2kedApp(
        device,
        catalog=catalog,
        favorites=store,
        installed=installed,
        config_path=config_path,
        channel=channel,
        allow_write=args.allow_write,
    )
    try:
        app.run()
    finally:
        store.close()
        device.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
