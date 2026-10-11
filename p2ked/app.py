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
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, cast

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Header, Label, Static

from p2k import catalog as cat
from p2k import roms
from p2k.favorites import rating_cell
from p2ked._report import say_connected, say_fallback, say_probing
from p2ked.masteredit import (
    FX_PARAMETERS,
    MASTER_BY_ID,
    MASTER_PARAMETERS,
    SOUND_FIELD,
    ChannelChange,
    EditGate,
    EditLog,
    MasterEditor,
    channel_values,
    fields_of,
    mutate_channel,
)
from p2ked.multi import (
    FXEditScreen,
    MasterEditScreen,
    MultiScreen,
    ValuePickerScreen,
)
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


@dataclass(frozen=True)
class RatingFilter:
    """``stars``, and whether that many is a floor or an exact match.

    Two widths rather than one because "show me the 3s" and "show me 3 and
    up" are both real questions and neither implies the other. Absence --
    no filter -- is ``None`` rather than a value, since at least one of the
    rows below is genuinely "no rating".

    The sibling rxved's shape, kept because it is the family's answer to
    the same question and a rating filter that behaved differently there
    would be a worse thing than a copy.
    """

    #: 0 means "no rating" as a category, not "no filter".
    stars: int = 0
    #: ``True`` for equal-or-greater, ``False`` for exactly.
    at_least: bool = False

    def matches(self, rating: int) -> bool:
        return rating >= self.stars if self.at_least else rating == self.stars

    @property
    def label(self) -> str:
        """For the subtitle and the sentence, said as one glance."""
        return f"rating {'≥' if self.at_least else '='}{self.stars}"


#: Every state ``V`` can leave the list in: the six exact thresholds and
#: the five floors that are real.
#:
#: ``≥0`` is deliberately absent, and this tuple is where that decision
#: lives -- so the picker's ``≥`` cell on the "no rating" row is blank
#: because the state does not exist, rather than because a second copy of
#: the rule said so. At least *nothing* matches everything, which is not a
#: filter; exactly-nothing is a real one, and the question it answers --
#: which of my favourites have I not rated yet -- is the one this filter
#: gets asked most. No filter at all is ``None``, not a twelfth state, for
#: the reason :class:`RatingFilter` says.
RATING_FILTER_STATES: Tuple[RatingFilter, ...] = tuple(
    [RatingFilter(stars=stars) for stars in range(6)]
    + [RatingFilter(stars=stars, at_least=True) for stars in range(1, 6)]
)


def _has_floor_at(stars: int) -> bool:
    """Whether a filter at this many stars has a floor at all.

    Reads :data:`RATING_FILTER_STATES` rather than repeating "not at
    nothing" a third time: a rule with three copies is a rule with three
    chances to disagree with itself.
    """
    return RatingFilter(stars=stars, at_least=True) in RATING_FILTER_STATES


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
    # The rating pair, in the gap the family leaves for this tool's own
    # keys and beside the annotations it belongs to: a rating hangs off a
    # favourite exactly as tags and a note do. `*` writes and `V` narrows,
    # which is the distinction `f` and `v` draw -- a read must not sit one
    # shift away from a write, and `V` is as far from `v` as a shift gets
    # while still reading as the same word. Declared to the family in
    # tests/test_conformance.py's EXTRAS, the way `v` and `x` are.
    "* rating",
    "V rating filter",
    # `m` means channels in a browser everywhere in this family. Here that
    # was already true: the multi screen shows what every MIDI channel plays.
    "m channels",
    # p2ked's own, plus the one key it borrows from rxved rather than the
    # family.
    "v favourites view",
    "C category",
    "a all ROMs",
    # The FX block, on `x`. It is in the legend because it is a key that
    # changes the unit: `m` then `e` edits the general master parameters
    # and `x` -- here, on the multi screen, or on the general editor --
    # edits the sixteen FX ones. Declared to the family in
    # tests/test_conformance.py's EXTRAS, the same way `m` and `v` are.
    "x master FX",
    # The write path, in the family's own words: these three are the
    # `EDITOR_KEYS` entries p2ked now binds, spelled as the family spells
    # them so a reader who has used rxved already knows what they do. They
    # are in the legend because a write must be findable from the legend --
    # a key that changes the unit and is documented nowhere is a key that
    # gets pressed by accident.
    "w write gate",
    # The per-channel editing gestures. All four are the multi screen's
    # own, bound on the screen for the reason `w` and `x` are bound on the
    # edit screens -- a modal cuts the app's binding chain, so a legend
    # entry served only by the app would be dead the moment the screen they
    # belong to was open. They are in the legend anyway, because each of
    # them changes the unit and the footer of a modal is not where a reader
    # looks to find out that a key exists. Declared to the family in
    # tests/test_conformance.py's EXTRAS with the rest.
    "+ - nudge",
    "space toggle",
    "s pick sound",
    "z undo",
    "Z undo all",
    "i device",
    "? help",
    "q quit",
)


@dataclass(frozen=True)
class EditChange:
    """One master edit, as the undo timeline sees it.

    It carries no data of its own, and that is the point: the value an
    undo has to send back is the one :meth:`MasterEditor.finish` recorded
    *before* the edit went out, and :meth:`MasterEditor.undo_plan` is still
    where ``z`` reads it from. What this entry adds is the **position**.

    ``z`` reverses the most recent change of either kind, and a favourite
    toggle can land between two edits. Two logs would each have to be
    asked which of them happened last; one list cannot disagree with
    itself about that, so the two kinds share this one.
    """


@dataclass(frozen=True)
class FavouriteChange:
    """One ``f`` press, so ``z`` can put it back.

    ``was_favourite`` is what the slot held *before* the keypress, which
    is the state an undo restores -- not the complement of whatever the
    store happens to say when ``z`` is pressed, because something else
    could have toggled the same slot in between.

    The undo is a write to the local favourites database and nothing
    else: no frame goes out, and no MIDI operation is in it.
    """

    bank_id: str
    number: int
    was_favourite: bool


@dataclass(frozen=True)
class RatingChange:
    """One ``*`` press, so ``z`` can put the rating back.

    A separate entry from :class:`FavouriteChange` rather than a field on
    it, because the two are different questions: ``f`` asks *whether* a
    slot is a favourite and ``*`` asks *how much* it is one, and the
    answer an undo owes is the number that was there before. Folding the
    rating into the toggle's entry would make an undo of one have to know
    whether the other had ever been pressed.

    Like it, and unlike every other kind on the timeline, the undo is a
    write to the local favourites database and nothing else: no frame goes
    out, and no MIDI operation is in it.
    """

    bank_id: str
    number: int
    was_rating: int


class _Sayer(Protocol):
    """What a screen that can carry an edit sentence looks like.

    Structural rather than a class name, because the sentence has more than
    one place it can land: the master editor is a modal with its own status
    line, and a per-channel edit is offered on the multi screen, which will
    grow one when the UI does. Both answer the same two arguments, so both
    match, and neither has to be imported here to be found.
    """

    def say(self, message: str, *, refused: bool = False) -> None:
        """One sentence on this screen's own status line."""
        ...


#: What ``z`` can reverse. See :class:`EditChange` for why it is one list --
#: and :class:`p2ked.masteredit.ChannelChange` for the entry that carries its
#: own data, because undoing one of those is a whole-dump write rather than
#: one parameter ID and value. The two favourites-store entries are here for
#: the reason the edits are: ``z`` reverses whichever came last.
Change = EditChange | FavouriteChange | RatingChange | ChannelChange


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


class RatingFilterScreen(ModalScreen[Optional[RatingFilter]]):
    """Pick a rating to narrow the list to, and how strictly.

    A radio, not a checklist: at most one cell is on, because a row either
    matches a rating or does not and there is nothing to accumulate. Two
    columns for the same reason :class:`RatingFilter` has two widths --
    "the 3s" and "3 and up" are different questions, and a key that flipped
    between them would hide the one the reader did not pick.

    The ``≥`` cell is missing from the "no rating" row on purpose. At least
    *nothing* matches everything, which is not a filter; exactly-nothing is
    a real one, and the question it answers -- which of my favourites have I
    not rated yet -- is the one this filter gets asked most.

    The cursor is a **cell** cursor, not a row cursor: the two radio columns
    *are* the choice, so right steps between ``=`` and ``≥`` and the
    highlighted cell itself says which one ``space`` is about to toggle. The
    stars label to the right is read-only, and ``space`` on it goes to
    whichever column was last actually toggled in rather than being a key
    that does nothing.

    The one difference from the picker on the master editor's enumerations:
    ``enter`` is a ``priority`` binding rather than the table's own
    ``RowSelected``, because the answer is a *cell* and that message carries
    no column.
    """

    DEFAULT_CSS = """
    RatingFilterScreen { align: center middle; }
    RatingFilterScreen > Vertical {
        width: 62; height: auto; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    RatingFilterScreen DataTable { height: auto; }
    """

    BINDINGS = [
        # `toggle_cell` and not `action_toggle`: Textual's own DOMNode has
        # one of those, for a CSS class, with a different signature -- the
        # same clash the multi screen's own space binding names its way
        # out of.
        Binding("space", "toggle_cell", "Toggle"),
        # `priority`, for the same reason the browser's Enter is not bound
        # at all: a focused DataTable consumes Enter for its own row
        # selection, so without this the key would do nothing and the only
        # way out would be escape -- which throws the choice away.
        Binding("enter", "accept", "Apply", priority=True),
        Binding("x", "clear", "Clear"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    def __init__(self, current: Optional[RatingFilter] = None) -> None:
        super().__init__()
        # What the app is showing, for a cancel to put back unchanged. Kept
        # apart from `_current`, which the cursor edits: escape has to mean
        # "leave it alone", and "cleared" is a *choice* made with `x` and
        # then applied with enter.
        self._opened_with = current
        self._current = current
        #: The radio column the cursor last toggled in, 0 for ``=`` and 1
        #: for ``≥``. The stars label is read-only, and `space` on it would
        #: otherwise be a key that does nothing at all.
        self._radio_column = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Rating[/b] -- narrows whatever is already shown")
            # `cell`, not `row`: with a row cursor `right` scrolls the table
            # instead of moving the cursor, so the ≥ column would be
            # unreachable and half the filter would be dead code.
            yield DataTable(id="ratings", cursor_type="cell")
            yield Static("[dim]space toggle   x clear   ⏎ apply   esc / q cancel[/dim]")

    def on_mount(self) -> None:
        table = self.query_one("#ratings", DataTable)
        for label, key in (("=", "exact"), ("≥", "at_least"), ("rating", "stars")):
            table.add_column(label, key=key)
        self._fill()
        table.focus()

    def _stars(self, stars: int) -> str:
        """The threshold as it reads on the row: five cells, not three."""
        if not stars:
            return "no rating"
        return rating_cell(stars)

    def _fill(self) -> None:
        table = self.query_one("#ratings", DataTable)
        # `clear()` resets the cursor to (0, 0), which on a cell cursor also
        # throws the user back to the `=` column -- so a toggle spent in `≥`
        # would have to be paid for with another press of right. Save the
        # whole coordinate, not just the row, and put it back afterwards.
        where = table.cursor_coordinate
        first = not table.row_count
        table.clear()
        for stars in range(6):
            exact = (
                self._current is not None
                and not self._current.at_least
                and self._current.stars == stars
            )
            # Nothing has no "at least": see the class docstring. Blank in
            # the table as well as dead under the cursor, because a cell
            # that looks empty and toggles anyway is the worst of both.
            at_least = (
                _has_floor_at(stars)
                and self._current is not None
                and self._current.at_least
                and self._current.stars == stars
            )
            table.add_row(
                "[b]x[/b]" if exact else " ",
                "[b]x[/b]" if at_least else " ",
                self._stars(stars),
                key=str(stars),
            )
        # Not on the first fill: there is nothing to return to yet, and the
        # table starts where it should anyway.
        if table.row_count and not first:
            table.cursor_coordinate = where

    def _cell_under_cursor(self):
        """``(row, which)``, or ``None`` if the cursor is nowhere useful."""
        table = self.query_one("#ratings", DataTable)
        row = table.cursor_row
        if not 0 <= row < 6:
            return None
        column = table.cursor_column
        if column not in (0, 1):
            # The stars label: read-only, and a cell a reader passes over on
            # the way to choosing a row. `space` here does nothing at all,
            # which reads as a dead key -- so it toggles whichever radio
            # column was last actually toggled in.
            column = self._radio_column
        return row, column

    def action_toggle_cell(self) -> None:
        cell = self._cell_under_cursor()
        if cell is None:
            return
        row, which = cell
        # The column the user is choosing in, whether it came from the
        # cursor itself or from the fallback above.
        self._radio_column = which
        at_least = which == 1
        if at_least and not _has_floor_at(row):
            # At least *nothing*: not a state, so not a cell. The table
            # leaves it blank as well, which is why the check is asked of
            # the states rather than of the row number.
            return
        # Toggling the cell that is already on clears the filter; toggling
        # any other one moves it. Either way exactly one cell is on
        # afterwards, or none is.
        on = (
            self._current is not None
            and self._current.stars == row
            and self._current.at_least == at_least
        )
        self._current = None if on else RatingFilter(stars=row, at_least=at_least)
        self._fill()

    def action_clear(self) -> None:
        self._current = None
        self._fill()

    def action_accept(self) -> None:
        self.dismiss(self._current)

    def action_cancel(self) -> None:
        # The filter as it was when the screen opened, not as the cursor has
        # left it: escape discards what was picked *in this screen* and
        # changes nothing on the table behind it. Clearing is `x` and then
        # enter -- a choice, not the same as walking away from one.
        self.dismiss(self._opened_with)


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
        Binding("asterisk", "edit_rating", "Rating"),
        Binding("V", "rating_filter", "Rating filter"),
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
        # The master FX block. Its own key rather than another row on the
        # master editor: the two are different tables in the dump (spec
        # p. 49) and the front panel keeps them on different screens too.
        # Bound here as well as on the two edit screens, because a modal
        # cuts the app's binding chain -- see the `x` binding on
        # MasterEditScreen for the same problem `w` has there.
        Binding("x", "edit_fx", "Master FX"),
    ]

    #: True while a worker owns the wire. Declared here, above the methods
    #: that read it, because mypy infers an attribute's type from the first
    #: assignment it has seen and this one is made at the end of
    #: ``__init__``. See there for what the flag is for.
    _busy: bool

    #: The per-channel write in flight, and the target a press made while
    #: it was. Declared here for the reason ``_busy`` is, and for one more:
    #: they are the coalescing, they are read from a worker on another
    #: thread, and their whole contract is worth naming where a reader
    #: finds ``_busy``. See ``__init__``.
    _channel_inflight: Optional[Tuple[int, str]]
    _channel_target: Optional[Dict[str, int]]

    #: What ``--allow-write`` was given on the command line: the state the
    #: gate below starts in, recorded because the gate itself is created on
    #: first use. Declared here for the same reason ``_busy`` is.
    _allow_write: bool

    #: The MIDI channel selections go out on, 0-based. A reactive rather
    #: than a plain attribute so the header's line cannot go stale: three
    #: places set it -- ``--channel`` at startup, ``[`` / ``]``, and the
    #: ``c`` prompt -- and one of them being missed is exactly how a
    #: display ends up naming a channel the app is not sending on.
    channel: int = reactive(0, init=False)

    def watch_channel(self, channel: int) -> None:
        """Say it on the line that persists, wherever it was set."""
        self._update_subtitle()

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
        """``z`` in the browser: reverse the last change, either kind.

        The edit screen binds the same key to the same name -- a modal
        screen's bindings take precedence over the app's, so there is no
        double handling -- but a change is made *through* the screen and
        undone *from* the browser after it closes, so the key has to work
        with no screen open. It is the app's because the worker is: see
        :meth:`_undo_master_edits`.

        One change, not one edit: a favourite toggle made with ``f`` and a
        rating made with ``*`` are undoable here too, and ``z`` reverses
        whichever came last. See :class:`EditChange`.
        """
        self._undo_master_edits(1)

    def action_undo_all(self) -> None:
        """``Z``: every change there is, of any kind, newest first."""
        self._undo_master_edits(None)

    def _saying_screen(self) -> Optional[_Sayer]:
        """The screen an edit sentence belongs to, if one is open.

        Two ways to be the right screen, and the live one wins. A worker
        that finishes after its screen closed still reports to the screen
        the app recorded when *it* opened one -- ``_edit_screen`` -- and
        ``say`` on a screen that is gone is a no-op, so it has to be
        asked for. But a screen underneath a PromptScreen, or one a
        caller pushed by hand, is not recorded there, and it is the one
        the user is looking at all the same.

        That last case is the per-channel one: a channel edit is offered on
        the multi screen, which owns no status line yet and is not an edit
        screen. A screen that grows a ``say`` of its own --
        :meth:`p2ked.multi.MasterEditScreen.say` is the shape to copy -- is
        the live one and is answered first, so the sentence lands where the
        user is looking. Until then the fallback is unchanged.
        """
        top = self.screen
        if isinstance(top, MasterEditScreen):
            return top
        if callable(getattr(top, "say", None)):
            return cast(_Sayer, top)
        return getattr(self, "_edit_screen", None)

    def _hook_screen(self, name: str):
        """The live screen to call a channel hook on, or ``None``.

        The same question :meth:`_saying_screen` answers, asked for a second
        reason: a screen that only redraws a row might carry no ``say`` of its
        own -- so it would not be the screen a sentence belongs to and it is
        still the one the user is looking at. The recorded edit screen is
        deliberately absent here, because a hook that outlives its screen is
        a redraw into a table nobody is showing.
        """
        top = self.screen
        return top if callable(getattr(top, name, None)) else None

    def _say_edit(self, message: str, *, refused: bool = False) -> None:
        """One sentence about an edit, where the user is looking.

        The master-parameter editor is a modal. While it is open the app's
        own ``#status`` line is the dimmed backdrop behind it -- a refusal
        written there is written where the user cannot read it, which is
        how "edits made through ``e`` appear to do nothing" looked. So the
        sentence also goes to the open screen's own status line
        (:meth:`p2ked.multi.MasterEditScreen.say`).

        The app's line is written either way, and that is deliberate: it
        is the record, it is what a test can assert on with no screen
        open, and it is what is left on screen once the modal closes.
        """
        screen = self._saying_screen()
        if screen is not None:
            screen.say(message, refused=refused)
        self.notify_status(message, refused=refused)

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

    def action_edit_fx(self) -> None:
        """Open the master FX editor: the two algorithms and their
        parameters.

        The same path as :meth:`action_edit_master` -- read first, for the
        same two reasons -- over the FX block rather than the general one.
        ``x`` here, on the multi screen and on the general editor, because a
        modal screen cuts the app's binding chain and the legend promises
        the key in the browser; see the ``x`` binding on
        :class:`p2ked.multi.MasterEditScreen` for the same reasoning that
        puts ``w`` there.
        """
        if self.device is None:
            return
        if self._busy:
            self.notify_status("busy", refused=True)
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._edit_fx_worker()

    def _read_master_values(self, parameters):
        """Read the setup, and one value per parameter in ``parameters``.

        Extracted from the two edit workers rather than duplicated in them:
        both screens need the same three things -- the dump, the current
        value of every parameter they are about to offer, and one refusal
        sentence when the read fails -- and two copies of that would be two
        places to get the wrong ``_busy`` hand-off. Called *from* a worker,
        so the wire is still touched on the worker's thread only.

        ``None`` means the read failed, which is said on the app's own line
        and leaves nothing to build a screen from.
        """
        values: Dict[int, Optional[int]] = {}
        try:
            with self._lock:
                dump = self.device.read_setup()
                for parameter in parameters:
                    try:
                        values[parameter.parameter_id] = self.device.read_parameter(
                            parameter.parameter_id
                        )
                    except Exception:
                        values[parameter.parameter_id] = None
        except Exception as exc:
            self.call_from_thread(self.notify_status, f"multi: {exc}", refused=True)
            self._busy = False
            return None
        return dump, values

    @work(thread=True)
    def _edit_master_worker(self) -> None:
        """**MIDI only** -- every value is read here, the screen is built on
        the main thread."""
        read = self._read_master_values(MASTER_PARAMETERS)
        if read is None:
            return
        dump, values = read
        self.call_from_thread(self._show_master_edit, dump, values)

    @work(thread=True)
    def _edit_fx_worker(self) -> None:
        """**MIDI only** -- every FX value is read here, the screen is built
        on the main thread."""
        read = self._read_master_values(FX_PARAMETERS)
        if read is None:
            return
        dump, values = read
        self.call_from_thread(self._show_fx_edit, dump, values)

    def _show_master_edit(self, dump, values) -> None:
        self._busy = False
        screen = MasterEditScreen(
            dump,
            values,
            self._editor,
            on_apply=self._apply_master_edit,
            on_undo=self._undo_master_edits,
            on_edit_fx=self.action_edit_fx,
        )
        # Kept, so a worker that finishes after the screen closed still has
        # somewhere to report -- and so the gate's state, which the screen
        # shows, is the same one the edits went through.
        self._edit_screen = screen
        self.push_screen(screen)

    def _show_fx_edit(self, dump, values) -> None:
        """The FX block, behind the same gate and the same undo log.

        ``on_edit_fx`` is not handed in: this screen *is* the FX view, so
        the key that opens one has nothing to open.
        """
        self._busy = False
        screen = FXEditScreen(
            dump,
            values,
            self._editor,
            on_apply=self._apply_master_edit,
            on_undo=self._undo_master_edits,
        )
        # Kept for the reason the general editor's is kept, and it is the
        # same attribute: whichever edit screen the app opened last is
        # where a worker that outlives its screen reports, and ``say`` on a
        # screen that is gone writes nowhere.
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

        The lookup is :data:`p2ked.masteredit.MASTER_BY_ID`, which holds the
        general table and the FX block together -- so a screen cannot offer
        a parameter this method refuses, and the two cannot drift. An ID in
        neither table is a number p2ked cannot name, and it is refused
        rather than sent.

        A refusal says so and sends nothing. :meth:`MasterEditor.allow`
        answers both cases -- a locked gate and a value outside the
        parameter's range -- because both are a reader's question rather
        than a failure of the program. The sentence goes through
        :meth:`_say_edit`, because this is called from inside the edit
        screen and its own status line is where the answer belongs.
        """
        parameter = MASTER_BY_ID.get(parameter_id)
        if parameter is None:
            self.notify_status(
                f"parameter {parameter_id} is not one p2ked edits", refused=True
            )
            return
        refusal = self._editor.allow(parameter, value)
        if refusal is not None:
            self._say_edit(refusal, refused=True)
            return
        if self._busy:
            self._say_edit("busy", refused=True)
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
        if ok:
            # The edit is now undoable, and `z` has to know that *after*
            # any favourite toggle -- so it goes on the shared timeline
            # rather than only on the editor's own log. See EditChange.
            self._changes.append(EditChange())
        screen = self._saying_screen()
        if screen is not None:
            # The screen says it as well as the status line, because it is
            # the one showing the row that just changed -- and it is a
            # modal, so the app's line is behind it. A screen that closed
            # underneath the worker is drawn nowhere and still reports:
            # see MasterEditScreen._draw.
            screen.result(ok, message, parameter_id=parameter_id, value=value)
        else:
            self._say_edit(message, refused=not ok)

    # --- the per-channel write path ---------------------------------------

    def action_edit_channel(self, channel: int, field: str, value: int) -> None:
        """Set one of a channel's nine values. **This changes the unit.**

        The UI's door into the per-channel write path. Deliberately tiny:
        the gate and the range are checked here, on the main thread and
        before anything is spawned -- the same shape as
        :meth:`_apply_master_edit`, and for the same reason. This is the
        last place an edit can be stopped before it reaches the wire, so a
        check that lived on the screen would be a check the next caller of
        this method could simply not make.

        **No parameter ID is involved, and none is invented.** The write is
        the whole Setup Dump: the unit "receive[s] and understand[s] the old
        setup dump" (spec p. 29), so p2ked reads the live dump, changes this
        one field and sends the dump back -- which means every other byte on
        the frame is the byte the unit just sent. Then it reads again and
        verifies this one field. See
        :func:`p2ked.masteredit.mutate_channel` for the mutation, and
        :data:`p2ked.masteredit.CHANNEL_EDIT_HINT` for the sentence the
        screen shows about all of this.

        ``field`` is one of the nine the dump carries -- ``preset``,
        ``volume``, ``pan``, ``mix_output``, ``arp``, ``enable``,
        ``bank_map``, ``receive_program_change``, ``rom_id`` -- and ``value``
        is the signed value the wire uses, so a mix output of -1 is ``-1``
        and not 3. A field outside that set, or a value outside its
        transcribed range, is refused and sends nothing.

        ``channel`` is 0-based, the wire's own numbering -- the one
        :attr:`p2k.messages.ChannelState.channel` and
        :meth:`p2k.messages.SetupDump.channel` use, so the multi screen's row
        index is the same number. Whether this setup has that many channels
        is a fact about the dump, which is the worker's to read; a channel it
        does not have is refused there, before anything is sent.

        **A press that arrives while this one is still on the wire is not
        lost and not refused.** It becomes the value the same worker sends
        next, and the row is drawn with it at once; the write, the gate
        check and the read-back are one per *sent* value, so the undo log
        holds what the unit actually received. See
        :meth:`_start_channel_edit` for the slot and
        :meth:`_channel_edit_worker` for the loop.
        """
        if self.device is None:
            return
        refusal = self._editor.allow_channel_field(channel, field, value)
        if refusal is not None:
            self._say_edit(refusal, refused=True)
            return
        self._start_channel_edit(channel, field, {field: value})

    def action_channel_sound(
        self, channel: int, rom_id: int, preset: int, bank_map: int
    ) -> None:
        """Aim a channel at a sound. **This changes the unit.**

        One operation, not three: the unit takes ``rom_id``, ``preset`` and
        ``bank_map`` together, so they are ranged together
        (:meth:`p2ked.masteredit.MasterEditor.allow_channel_sound`), written
        together in one dump, verified together, and undone together as one
        entry. Three ``z`` presses that each restored a third of a sound
        would not put back the sound anybody had.

        Everything else is :meth:`action_edit_channel`'s: one dump write, the
        gate, the read-back, the undo timeline.
        """
        if self.device is None:
            return
        refusal = self._editor.allow_channel_sound(
            channel, rom_id=rom_id, preset=preset, bank_map=bank_map
        )
        if refusal is not None:
            self._say_edit(refusal, refused=True)
            return
        self._start_channel_edit(
            channel,
            SOUND_FIELD,
            {"rom_id": rom_id, "preset": preset, "bank_map": bank_map},
        )

    def _start_channel_edit(
        self, channel: int, field: str, values: Dict[str, int]
    ) -> None:
        """Refuse because the wire is busy, or put the edit on a worker.

        No MIDI in here: the gate and the range have already been answered
        on the main thread, and ``_busy`` is the last thing to say before a
        worker is spawned.

        **Unless the wire is busy with this very cell.** A nudge that
        arrives while a write to the same ``(channel, field)`` is in
        flight is not refused and not queued either: it becomes the target
        in :attr:`_channel_target`, the row is drawn with it at once, and
        the worker that is already running sends it next. That is the
        whole of the coalescing -- one slot, not a queue, because the
        burst is on one cell and the value that matters is the last one
        pressed. See :meth:`_channel_edit_worker` for the loop that
        drains it.

        Every *other* cell still finds ``_busy`` set and is refused with
        the one sentence: the slot holds one cell, and a second one is
        the old refusal.
        """
        if self._channel_inflight == (channel, field):
            self._channel_target = values
            self._show_channel_target(channel, values)
            return
        if self._busy:
            self._say_edit("busy", refused=True)
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._channel_inflight = (channel, field)
        self._show_channel_target(channel, values)
        self._channel_edit_worker(channel, field, values)

    def _allow_channel_values(
        self, channel: int, field: str, values: Dict[str, int]
    ) -> Optional[str]:
        """Why these values must not be sent, or ``None`` if they may be.

        The press path's gate-and-range check, made again on the thread
        that sends, and field by field in the dump's own order so a
        refusal names the one a reader would find first -- the order
        :meth:`p2ked.masteredit.MasterEditor.allow_channel_sound` checks
        a sound's three in.

        It is repeated because a burst's later writes have no keypress of
        their own to be checked at, and because the gate can be locked
        between two presses: ``w`` is not refused while a write is in
        flight, so the second write of a burst has to ask again rather
        than rely on the answer the first one was given. A refusal here
        stops the burst and is not queued across the lock.
        """
        for name in fields_of(field):
            refusal = self._editor.allow_channel_field(channel, name, values[name])
            if refusal is not None:
                return refusal
        return None

    def _show_channel_target(self, channel: int, values: Dict[str, int]) -> None:
        """Show the values this edit is sending, now, before they land.

        The row moves when the key is accepted rather than when a
        whole-dump round trip comes back -- the "incredibly slow" half of
        the complaint, and on a cable a read, a write and a read-back is
        longer than anybody is willing to believe. The next ``+`` of a
        burst steps from *this* value too, so the screen's own copy of
        the dump has to hold the target and not what the last read-back
        confirmed.

        An offer, not a claim: :meth:`_channel_edited` confirms it from
        the read-back, or puts back what the unit reports.
        """
        screen = self._hook_screen("channel_target")
        if screen is not None:
            screen.channel_target(channel, values)

    def _restore_channel_row(
        self, channel: int, field: str, values: Optional[Tuple[int, ...]]
    ) -> None:
        """Put one channel's row back to what the unit reports.

        The correction to :meth:`_show_channel_target`, and the reason an
        optimistic row cannot lie: it was drawn with a target nothing had
        verified, so a refusal or a read-back that disagreed hands back
        the values that *were* read and the row says those.

        ``None`` means nothing was read -- a wire that broke before the
        read-back -- and then the row is left alone, because the unit may
        well have taken the dump and only the answer was lost. The
        sentence says as much.
        """
        if values is None:
            return
        screen = self._hook_screen("channel_reported")
        if screen is not None:
            screen.channel_reported(
                channel, dict(zip(fields_of(field), values, strict=True))
            )

    @work(thread=True)
    def _channel_edit_worker(
        self, channel: int, field: str, values: Dict[str, int]
    ) -> None:
        """Read the dump, change one channel, send the dump, read it back.

        **MIDI only** -- one operation on one thread, for the reason
        :meth:`_apply_worker` is: a write and its verification must not be
        split across threads, because another read landing between them
        would be read back as this write's result.

        **And it loops.** A press that arrives while the round trip is in
        flight is neither refused nor queued: it leaves the value it wants
        in :attr:`_channel_target`, and when this read-back agrees with
        what was sent the loop looks there, finds a value that differs,
        and sends that one next -- one write in flight, gate-checked, read
        back, exactly like the first. Five presses in the time one write
        takes are therefore two writes, at the first value and at the
        last; the three in between cost a redraw and no frame, because
        the burst is on one cell and the newest target is the only one
        worth sending.

        The gate and the range are re-checked per write, here, for the
        reason :meth:`_allow_channel_values` gives: ``w`` stays live while
        a write is in flight, so a burst's second write cannot rely on
        the answer its first one was given.

        The dump is the whole mechanism. It is read live, so the frame sent
        back carries the unit's own bytes for everything but this one field;
        :meth:`p2k.bridge.ProteusBridge.send_setup_dump` encodes it with
        :func:`p2k.messages.encode_setup_dump`, which refuses a dump it
        cannot reproduce rather than inventing what it could not read; and it
        is read again afterwards, so what is verified is the field the unit
        now holds rather than the field that was sent.

        ``refusal`` comes back rather than being raised, because the checks
        that need a dump in hand -- has the setup that many channels, can it
        be written back at all -- are a reader's question, not a failure of
        the program. ``after`` is read for a refusal too, because a row
        drawn with the target has to be put back to what the unit holds.
        """
        while True:
            failure: Optional[BaseException] = None
            refusal: Optional[str] = None
            before: Optional[Tuple[int, ...]] = None
            after: Optional[Tuple[int, ...]] = None
            sent = tuple(values[name] for name in fields_of(field))
            try:
                with self._lock:
                    dump = self.device.read_setup()
                    refusal = self._editor.decline_channel(dump, channel, values)
                    if refusal is None:
                        refusal = self._allow_channel_values(channel, field, values)
                    if refusal is not None:
                        after = channel_values(dump, channel, fields_of(field))
                    else:
                        before = channel_values(dump, channel, fields_of(field))
                        written = mutate_channel(dump, channel, values)
                        self.device.send_setup_dump(written)
                        after = channel_values(
                            self.device.read_setup(), channel, fields_of(field)
                        )
            except Exception as exc:
                failure = exc
            # What to send next, and only a write the read-back agreed
            # with earns one -- the loop's whole bargain, and the reason
            # a refusal counts as refusing to send: a unit that has just
            # not taken this value is unlikely to take the next, and one
            # disagreement sentence is worth more than one per value in
            # the burst. Looked at *after* the write rather than before
            # it, so a press that landed during the round trip is in the
            # slot by the time it is read.
            target = self._channel_target
            landed = (
                failure is None
                and refusal is None
                and after is not None
                and after == sent
            )
            pending = (
                target if landed and target is not None and target != values else None
            )
            self.call_from_thread(
                self._channel_edited,
                channel=channel,
                field=field,
                values=values,
                sent=sent,
                refusal=refusal,
                failure=failure,
                before=before,
                after=after,
                pending=pending,
            )
            if pending is None:
                return
            values = pending

    def _channel_edited(
        self,
        *,
        channel: int,
        field: str,
        values: Dict[str, int],
        sent: Tuple[int, ...],
        refusal: Optional[str],
        failure: Optional[BaseException],
        before: Optional[Tuple[int, ...]],
        after: Optional[Tuple[int, ...]],
        pending: Optional[Dict[str, int]],
    ) -> None:
        """Report a per-channel edit, and log it only if it read back.

        The same three outcomes :meth:`_edit_applied` has -- a refusal, an
        operation that could not be carried out, and a success -- said
        differently, because "the field did not change" and "the wire broke"
        are different things to act on.

        **One entry per value sent, not per key pressed.** A burst that
        coalesced five presses into two writes logs two changes, for the
        two values the unit actually received -- which is what makes
        ``z`` honest: it steps back through values the unit held, and an
        intermediate value nobody sent must not appear on the timeline.

        ``values`` is the dict that was just written, and ``pending`` is
        the target the worker is already sending next, or ``None`` when
        the burst is over. Together they are the hand-off this method
        makes on the main thread, and they are why it is the only place
        the wire is marked free again: with a ``pending`` there is
        nothing to do, because spawning a worker here would put a
        *second* write beside the one the loop is sending; without one
        there is a last look at the slot, for the press that landed
        between the worker's final read of it and this callback -- a
        press that could only have been seen on this thread, so this is
        the only place its loss could be caught.
        """
        if refusal is not None:
            # Nothing was sent, so the wire is free -- and the row goes
            # back to what the unit holds, because it was drawn with the
            # target the moment the key was accepted. The target is
            # dropped with it: no write goes out on the strength of a
            # gate the burst's earlier ones passed, and one left in the
            # slot would be sent by the next edit to any cell.
            self._busy = False
            self._channel_inflight = None
            self._channel_target = None
            self._restore_channel_row(channel, field, after)
            self._say_edit(refusal, refused=True)
            return
        if before is None:  # pragma: no cover - decline_channel checks it
            before = sent
        change = self._as_change(channel, field, before, sent)
        if failure is not None:
            ok, message = False, f"{change.label} = {change.spelled}: {failure}"
        else:
            ok, message = self._editor.finish_channel(change, after)
        if ok:
            # Now undoable, and on the shared timeline so `z` knows it came
            # *after* any favourite toggle and *before* any other edit. The
            # ChannelChange *is* the entry: it carries the channel, the
            # field and the previous value, which is what an undo of a
            # whole-dump write needs and what an empty EditChange could not
            # hold. See EditChange.
            self._changes.append(change)
        screen = self._hook_screen("channel_result")
        if screen is not None:
            # The screen's own hook for a screen that shows a channel row --
            # the multi screen's is the UI's to write, and until it exists
            # the sentence below is the whole of the answer. The signature:
            # channel_result(ok, message, change).
            screen.channel_result(ok, message, change)
        if not ok:
            # The row is showing a value the unit did not take, so it goes
            # back to the one the read-back reported.
            self._restore_channel_row(channel, field, after)
        self._say_edit(message, refused=not ok)
        more = pending
        if more is None:
            # Read and cleared in one piece, on the one thread nothing
            # can interrupt between the two, and only here: a target
            # left in the slot would be sent by the next edit to any
            # cell -- a write nobody pressed a key for. And a target the
            # write below did not verify goes out with the clearing,
            # because no further write goes out on behalf of a unit that
            # has just not taken one.
            target = self._channel_target
            self._channel_target = None
            if ok and target is not None and target != values:
                more = target
        if more is None:
            self._busy = False
            self._channel_inflight = None
            return
        self._busy = True  # main thread, before the spawn; see _busy
        self._channel_inflight = (channel, field)
        if pending is None:
            # The press the worker never saw: its loop is finished, so
            # this thread starts the write it asked for.
            self._channel_edit_worker(channel, field, more)

    @staticmethod
    def _as_change(
        channel: int, field: str, before: Tuple[int, ...], after: Tuple[int, ...]
    ) -> ChannelChange:
        """The record: a bare value for one field, a triple for a sound.

        The shape :class:`p2ked.masteredit.ChannelChange` documents, and the
        reason it is not always a tuple is that a ``z`` report has to read
        as words -- "channel 6 volume = 90" -- while a sound is three values
        the unit takes together and a report has to say so.
        """
        if len(before) == 1:
            return ChannelChange(channel, field, before[0], after[0])
        return ChannelChange(channel, field, tuple(before), tuple(after))

    def _undo_master_edits(self, count: Optional[int] = None) -> None:
        """Reverse the last ``count`` changes. Nothing read-only about it.

        ``None`` means every change there is, which is what ``Z`` asks for.

        **Four kinds, one timeline.** A master edit is reversed by sending
        the value it replaced back over the wire, on a worker; a per-channel
        edit is reversed by re-reading the dump, putting that one field back
        and sending the *dump* back; and a favourite toggle and a rating are
        reversed in the local favourites store and **go nowhere near the
        device**. ``z`` reverses whichever came last, so the entries are
        kept in the order they happened rather than one log per kind -- see
        :class:`EditChange` and :class:`ChannelChange`.

        Each entry leaves the timeline as it is undone, so an undo that
        fails halfway cannot be replayed by the next press. The editor's own
        logs lose the same entries at the same time, which is what keeps
        "N undoable with z" on the edit screen true.
        """
        if self._busy:
            self._say_edit("busy", refused=True)
            return
        if not self._changes:
            self._say_edit("nothing to undo")
            return
        wanted = len(self._changes) if count is None else count
        if wanted <= 0:
            return
        taken = self._changes[-wanted:]
        del self._changes[-wanted:]
        # The two local kinds first, and with no wire involved at all: a
        # favourite and its rating live in SQLite, and undoing one is a
        # write there. New ones are undone before old ones, like the edits
        # after them.
        local = [
            c for c in reversed(taken) if isinstance(c, (FavouriteChange, RatingChange))
        ]
        for change in local:
            if isinstance(change, RatingChange):
                self._undo_rating(change)
            else:
                self._undo_favourite(change)
        favourites = sum(1 for c in taken if isinstance(c, FavouriteChange))
        ratings = sum(1 for c in taken if isinstance(c, RatingChange))
        edits = sum(1 for c in taken if isinstance(c, EditChange))
        # Off the timeline, which is the authority: a ChannelChange carries
        # its own channel, field and previous value, so undoing one needs
        # nothing looked up. The editor's channel log loses the same count,
        # so the two cannot disagree about what is left to undo.
        channels = [c for c in reversed(taken) if isinstance(c, ChannelChange)]
        if channels:
            self._editor.channel_undo_plan(len(channels))
        if edits or channels:
            # Still off the editor's log: undo_plan is what `z` has always
            # read the value to send from, and taking them off there as
            # well as off the timeline is what leaves the two agreeing.
            plan = self._editor.undo_plan(edits)
            self._busy = True  # main thread, before the spawn; see _busy
            self._undo_worker(plan, channels, favourites, ratings)
        elif favourites or ratings:
            # No wire, so no worker and nothing to hand off: the local
            # kinds were undone above and are already done, so the
            # sentence is all that is left. Without it a `z` over nothing
            # but a favourite toggle or a rating was indistinguishable
            # from a dead key -- the work happened and nothing said so.
            self._say_edit(self._undo_sentence([], favourites, ratings))

    def _undo_favourite(self, change: FavouriteChange) -> None:
        """Put one ``f`` press back. **Sends nothing: no MIDI here.**

        ``Favorites.toggle`` rather than a remove-then-add, for the reason
        ``f`` itself uses it: un-favouriting keeps the row, so a rating,
        tags, a note and the original date survive being toggled off and
        on. A delete followed by a fresh add destroyed all four, and ``z``
        is one keystroke from ``f``.
        """
        if self.favorites is None:  # pragma: no cover - recorded only when not
            return
        name = self.catalog.display_name(change.bank_id, change.number)
        self.favorites.toggle(change.bank_id, change.number, name=name)
        self._refill_bank_count(change.bank_id)
        if change.bank_id == self._current_bank:
            self._refill_keeping_place()

    def _undo_rating(self, change: RatingChange) -> None:
        """Put one ``*`` press back. **Sends nothing: no MIDI here.**

        ``set_rating`` and not a remove-then-add, which is the same reason
        ``f`` gives for ``toggle``: the row holds a rating, tags, a note and
        the date it was made, and an undo is one keystroke from the press
        that made the change. It writes straight to the store, so it also
        works on a slot that is no longer a favourite -- the row survives
        being toggled off, and putting a rating back on it has to too.

        The table is rebuilt rather than one cell updated, because a rating
        is the one change that can take a row *out* of the list: rate a
        3-star down to nothing under a ``≥2`` filter and it no longer
        belongs there. A row the filter does not describe is worse than a
        stale cell -- it is the row that makes the list a lie.
        """
        if self.favorites is None:  # pragma: no cover - recorded only when not
            return
        self.favorites.set_rating(change.bank_id, change.number, change.was_rating)
        self._refill_keeping_place()

    @work(thread=True)
    def _undo_worker(
        self, plan, channels=(), favourites: int = 0, ratings: int = 0
    ) -> None:
        """Send everything ``z`` asked for back. **MIDI only.**

        Two verbs because the two kinds of edit are two shapes of write: a
        master parameter is one ID and one value, a per-channel one is a
        whole dump with the previous field put back. Each kind is newest
        first, and each is verified on its own before it is claimed.

        A channel undo reads the dump again rather than reusing the one from
        when the edit was made: the unit may have been edited by hand in
        between, and the old value belongs in the channel the unit reports
        now. Anything that fails -- a read, an encode, a send, or a read-back
        that disagrees -- is a ``False`` for that one entry and does not stop
        the rest.
        """
        results: List[Tuple[int, bool]] = []
        undone: List[Tuple[ChannelChange, bool]] = []
        try:
            with self._lock:
                for parameter_id, value in plan:
                    try:
                        self.device.set_parameter(parameter_id, value)
                        results.append((parameter_id, True))
                    except Exception:
                        results.append((parameter_id, False))
                for change in channels:
                    undone.append((change, self._restore_channel(change)))
        finally:
            self.call_from_thread(
                self._edit_undone, results, favourites, ratings, plan, undone
            )

    def _restore_channel(self, change: ChannelChange) -> bool:
        """Put one per-channel edit back. True only if the unit took it.

        The caller holds ``self._lock`` (an RLock, so taking it again would
        be harmless) -- the whole undo is one operation on one thread.

        ``False`` for a send that raised **and** for a read-back that
        disagrees. The entry has already left the timeline, so an undo that
        did not land must not be reported as one that did: the report names
        it, and ``z`` pressed again will not silently try the same thing a
        second time.
        """
        try:
            dump = self.device.read_setup()
            written = mutate_channel(dump, change.channel, change.restore)
            self.device.send_setup_dump(written)
            after = channel_values(
                self.device.read_setup(), change.channel, change.fields
            )
        except Exception:
            return False
        return after is not None and tuple(after) == change.restore_values

    def _edit_undone(
        self, results, favourites: int = 0, ratings: int = 0, plan=(), undone=()
    ) -> None:
        self._busy = False
        screen = self._saying_screen()
        if screen is not None:
            # The undo put values back, so the rows that showed the edited
            # ones have to say what the unit reports now -- a row left
            # reading a value `z` just sent away is the same lie a stale
            # edit cell was.
            screen.undone(plan, results)
        screen = self._hook_screen("channel_undone")
        if screen is not None:
            # The per-channel half of the same redraw: a screen showing a
            # channel row answers channel_undone([(change, ok), ...]). The
            # multi screen's is the UI's to write; until it exists the
            # sentence below is the whole of the answer.
            screen.channel_undone(undone)
        self._say_edit(self._undo_sentence(results, favourites, ratings, undone))

    def _undo_sentence(
        self,
        results,
        favourites: int,
        ratings: int,
        undone: Sequence[Tuple[ChannelChange, bool]] = (),
    ) -> str:
        """One sentence over the four kinds of undo.

        The local kinds are named first because they were undone first and
        needed no wire -- one clause for both, because "undid 1 favourite
        and 1 rating" is one thing the user did even though it is two
        entries on the timeline. With no per-channel undo at all this is
        the editor's own report, verbatim -- "undid 1 edit", "undid 1; the
        unit rejected 1 (parameters 259)" -- because that wording is what
        the MIDI half is pinned to; the per-channel half adds its own,
        naming the channel and the field rather than a parameter ID.
        """
        parts = []
        if favourites or ratings:
            local = []
            if favourites:
                local.append(f"{favourites} favourite{'s' if favourites != 1 else ''}")
            if ratings:
                local.append(f"{ratings} rating{'s' if ratings != 1 else ''}")
            parts.append("undid " + " and ".join(local))
        # The editor's own report, verbatim, when there is anything to
        # report -- and when nothing else was undone, because then it is
        # the sentence that says so. A local kind is a whole clause of its
        # own, so "nothing to undo" belongs to neither half of a sentence
        # that already said what it did.
        if results or not (parts or undone):
            parts.append(self._editor.undo_report(results))
        channels = self._editor.channel_undo_report(list(undone)) if undone else ""
        if channels:
            parts.append(channels)
        return "; ".join(parts)

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
        #: The rating filter, or ``None`` for none. Stacks on the view and
        #: on the categories the same way the categories stack on the view
        #: -- see :meth:`_visible`, which applies it last and over all
        #: three.
        #:
        #: Above the ``channel`` assignment below and not beside the view
        #: mode, because that assignment fires :meth:`watch_channel` while
        #: the constructor is still running, and the watcher writes the
        #: subtitle. It does not matter for the *channel*; it matters for
        #: anything the subtitle says as well.
        self.rating_filter: Optional[RatingFilter] = None
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
        #:
        #: A coalesced per-channel burst is the one thing that keeps it
        #: set past a single write: the worker drains the target a later
        #: press left in :attr:`_channel_target` before it hands the wire
        #: back, so the flag covers the whole burst rather than flickering
        #: free between two of its writes. See
        #: :meth:`_channel_edit_worker`.
        self._busy = False
        self._filling = False
        #: The per-channel write on the wire right now, as
        #: ``(channel, field)``, or ``None``. One slot and not a queue,
        #: because a burst of nudges lands on one cell -- so "which write
        #: is in flight" is one pair, and the value it is being nudged
        #: *towards* lives in :attr:`_channel_target` beside it. Set on
        #: the main thread when the worker is spawned, kept while the
        #: worker drains, and cleared where the write is reported.
        self._channel_inflight: Optional[Tuple[int, str]] = None
        #: The values a press made while that write was in flight wants
        #: the unit to hold, or ``None``. One slot for the reason the
        #: in-flight one is one slot: the burst is on a single cell, so
        #: the value that matters is the last one pressed and an
        #: intermediate one is not worth a frame.
        #:
        #: Overwritten freely on the main thread, read on the worker's,
        #: and **read and cleared in one piece** where the burst is
        #: reported over -- see :meth:`_channel_edited`. Both halves of
        #: that matter. A worker that cleared the slot as it read it
        #: would drop a press landing between its read and its write,
        #: which is the lost-press bug wearing a different coat; and a
        #: slot left standing after a burst would be sent by the next
        #: edit to any cell, which is a write nobody pressed a key for.
        #: One attribute under the GIL, so a reader sees either the old
        #: target or the new one and never half a dict.
        self._channel_target: Optional[Dict[str, int]] = None
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
        #: Everything ``z`` can reverse, in the order it happened. Two kinds
        #: share it -- a master edit and a favourite toggle -- because ``z``
        #: reverses whichever came last; see :class:`EditChange`.
        self._changes: List[Change] = []
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
        # The header's sub-title, so the channel is on screen all the time
        # rather than only for as long as the sentence that announced a
        # change. rxved shows its send channel the same way -- a suffix on
        # the sub-title line -- and the family agrees on where to look.
        self._update_subtitle()
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
        for label, key, width in (
            ("♥", "fav", None),
            # The rating, beside the marker it belongs to: both are the
            # favourites store's own, both are narrow, and a rating means
            # nothing without a favourite -- one glance down the gutter
            # answers "is this one of mine" and "how much" together. rxved
            # puts its ★ column after the name instead; p2ked puts it here
            # because its name column is the widest thing in the table and
            # a five-wide block wedged between the name and the numbers
            # pushes PC/LSB/MSB off a narrow terminal.
            #
            # Pinned to five rather than fitted to its content, for rxved's
            # reason: fitted, it is five wide in a bank you have rated and
            # one wide in a bank you have not, so the same column changes
            # shape depending on data that has nothing to do with it -- and
            # the row you just rated would jump sideways as it appeared.
            ("★", "rating", 5),
            ("#", "pc", None),
            ("name", "name", None),
            ("PC", "pcn", None),
            ("LSB", "lsb", None),
            ("MSB", "msb", None),
            ("ROM#", "rom", None),
        ):
            presets.add_column(label, key=key, width=width)
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

    def _rating_map(self) -> Dict[str, Dict[int, int]]:
        """Every rating in the store, as ``{bank id: {number: rating}}``.

        One query for the whole set rather than a ``get`` per row, for the
        reason the favourite marker's comment in :meth:`_fill_presets`
        gives: a bank is over a hundred rows redrawn on every cursor move,
        and the store is behind a lock.

        A rating of 0 is left out rather than stored as a zero, because 0
        is what :func:`p2k.favorites.rating_cell` renders as a blank and
        what a lookup of a slot with no row has to fall back to. Keeping
        them apart in the map would be one more thing to be right about.
        """
        if self.favorites is None:
            return {}
        out: Dict[str, Dict[int, int]] = {}
        for favourite in self.favorites.all():
            if favourite.rating:
                out.setdefault(favourite.bank_id, {})[favourite.number] = (
                    favourite.rating
                )
        return out

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
        return self._by_rating(entries)

    def _by_rating(self, entries: List[roms.Preset]) -> List[roms.Preset]:
        """Narrow to the rating filter. A no-op when there is none.

        Last of the three narrowings, and over all of them, for rxved's
        reason: a rating filter applied only to the favourites views would
        be a different filter depending on which view is showing, which is
        how a keypress ends up doing something the user cannot predict.
        ``v`` steps through three views and ``V`` is a filter over whichever
        one is showing, so the order has to be the same in all three.
        """
        if self.rating_filter is None or self.favorites is None:
            return entries
        ratings = self._rating_map()
        return [
            e
            for e in entries
            if self.rating_filter.matches(
                ratings.get(e.bank_id, {}).get(e.program_change, 0)
            )
        ]

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
        # One query for the whole store, for the reason the marker below
        # takes one per bank: a bank is over a hundred rows redrawn on every
        # cursor move, and the store is behind a lock.
        ratings = self._rating_map()
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
                rating = ratings.get(entry.bank_id, {}).get(entry.program_change, 0)
                number = (
                    f"{roms.bank(entry.bank_id).label} {entry.program_change:03d}"
                    if across
                    else f"{entry.program_change:03d}"
                )
                table.add_row(
                    star,
                    rating_cell(rating),
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
        was = self.favorites.get(entry.bank_id, entry.program_change) is not None
        now = self.favorites.toggle(entry.bank_id, entry.program_change, name=name)
        # Recorded so `z` can put it back, in the same timeline as the
        # master edits: `z` reverses whichever of the two came last. The
        # state *before* the keypress is what an undo restores, because
        # that is the only thing this keypress can be held to.
        self._changes.append(FavouriteChange(entry.bank_id, entry.program_change, was))
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

    def action_edit_rating(self) -> None:
        """Rate the favourite under the cursor, 0 to 5.

        The one favourite field with no key until now. The store has held a
        rating since it was a store and ``z`` could put one back, but
        nothing in this interface could produce the change -- which made
        the store's own promise of "slots, ratings, tags" half true of the
        front end. ``*`` writes it and ``V`` narrows by it.

        The picker is the same one an enumerated master parameter opens,
        and that is deliberate: a rating is six named things rather than a
        number to type -- ``no rating`` is one of them -- and the answer is
        the number of stars the slot is worth, so the store and the undo
        log downstream cannot tell which door the value came through. Six
        rows rather than a range to remember, because a rating that has to
        be recalled is a rating nobody sets.
        """
        if self.favorites is None:
            self.notify_status(
                "no favourites database: pass --favorites, or let it use the "
                "default path"
            )
            return
        where, existing = self._favourite_under_cursor()
        if where is None:
            self.notify_status("no preset under the cursor to rate", refused=True)
            return
        if existing is None:
            self.notify_status("not a favourite yet -- press f first", refused=True)
            return
        name = self.catalog.display_name(where[0], where[1])
        # `rating_cell` for rows 1-5 rather than a row of bare stars, so
        # the picker, the column it fills and the filter's own third
        # column all spell a rating the same way. The first row is the
        # words: a rating of nothing renders as a blank, and a blank row
        # in a list of choices is not a choice.
        choices = ["no rating"] + [rating_cell(stars) for stars in range(1, 6)]
        self.push_screen(
            ValuePickerScreen(f"Rating for {name}", choices, existing.rating),
            lambda value: self._apply_rating(where, existing, value),
        )

    def _apply_rating(self, where, existing, value) -> None:
        """Write one rating, and record it beside the favourite toggle."""
        if value is None or self.favorites is None:
            return
        bank_id, number = where
        self.favorites.set_rating(bank_id, number, value)
        # Recorded so `z` can put the number back, in the same timeline as
        # the toggle and the master edits: `z` reverses whichever came
        # last. The rating *before* the keypress is what an undo restores,
        # because that is the only thing this keypress can be held to.
        self._changes.append(RatingChange(bank_id, number, existing.rating))
        name = self.catalog.display_name(bank_id, number)
        said = f"rated {value} {name}" if value else f"rating cleared {name}"
        # The row can leave the list: rate a 3-star down to nothing under a
        # `>= 2` filter and it no longer belongs there. A list that shrank
        # and a slot that vanished are two different things to act on, so
        # the sentence says which.
        if not any(
            e.bank_id == bank_id and e.program_change == number
            for e in self._visible(bank_id)
        ):
            said += " -- no longer matches the rating filter"
        self.notify_status(said)
        self._refill_keeping_place()

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

    def action_rating_filter(self) -> None:
        """Narrow the list by rating, exactly or at least.

        The shift pair of ``*``, and it narrows rather than writes, which is
        the distinction ``f`` and ``v`` draw. Offered with no counts,
        because six thresholds is not a bank of categories and every one of
        them is a question worth asking.
        """
        if self.favorites is None:
            self.notify_status("no favourites database")
            return

        def apply(chosen) -> None:
            # Escape comes back as the filter unchanged, so "nothing
            # changed" and "cleared" are different answers and only one of
            # them rebuilds.
            if chosen == self.rating_filter:
                return
            self.rating_filter = chosen
            self._refill_keeping_place()
            self.query_one("#preset-table", DataTable).focus()
            shown = len(self._current)
            if chosen is None:
                self.notify_status(f"rating filter cleared -- {shown} rows")
            else:
                self.notify_status(f"{chosen.label} -- {shown} rows")
            # Never a silent narrowing: the filter stays on the header line
            # after the sentence is gone. See :meth:`_update_subtitle`.
            self._update_subtitle()

        self.push_screen(RatingFilterScreen(self.rating_filter), apply)

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

    def _channel_line(self) -> str:
        """What the header says about the send channel.

        1-16, not 0-15: the channel a sequencer is set to is the one on the
        unit's display and in its manual, and ``self.channel`` is the wire
        value. Both halves are said, because a reader who has only ever
        seen the number in a config file has seen the 0-based one.
        """
        return f"sending on MIDI channel {self.channel + 1}"

    def _update_subtitle(self) -> None:
        """The header's line: the send channel, and any rating filter.

        A rating filter is the one narrowing that has to be on this line.
        The category filter only ever cuts down a view the user asked for,
        and the status line that announced it is enough; a rating filter
        narrows **all three** views, including the full list of a bank you
        were reading straight down. Rows that are not there and no word
        about why is the failure this exists to prevent -- the same reason
        rxved puts the filter on its own sub-title first.

        Main thread only, like every other thing that touches a widget.
        """
        filters = ""
        if self.rating_filter is not None:
            filters = f"   ·   {self.rating_filter.label}"
        self.sub_title = self._channel_line() + filters

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

        ``on_undo`` is handed in for the same reason: a modal screen cuts
        the app's binding chain, so ``z`` pressed here would otherwise be
        dead -- and this is the screen an edit made through ``e`` comes
        back to, which is where ``z`` gets pressed.

        ``on_edit_fx`` is handed in for the same reason again: ``x`` here
        opens the FX editor, which is the app's worker and the app's screen
        to build.

        ``editor``, ``on_edit_channel`` and ``on_channel_sound`` are the
        per-channel write path's: the screen offers an edit on a cell, and
        the gate, the range check, the worker and the read-back are all
        here. ``bank_ids`` and ``favorites`` are the sound picker's, handed
        in so a picker cannot disagree with the browser about which banks
        there are or which presets are marked.
        """
        screen = MultiScreen(
            dump,
            self.catalog,
            mode,
            fitted=self.installed,
            bank_ids=self._bank_ids,
            favorites=self.favorites,
            editor=self._editor,
            on_edit=self.action_edit_master,
            on_edit_fx=self.action_edit_fx,
            on_undo=self._undo_master_edits,
            on_edit_channel=self.action_edit_channel,
            on_channel_sound=self.action_channel_sound,
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
