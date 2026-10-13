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

"""The multi screen: every MIDI channel, the master settings that govern them,
and -- when the unit supports it -- the edit path over both.

The counterpart to the sibling rxved's multi-mode screen. Two differences
shape it, and neither is a limitation of p2ked's:

**Thirty-two channels, not sixteen.** A Proteus 2000 has two MIDI
interfaces, and channels 17-32 are the second one. A channel answering on an
unwired interface is exactly the kind of thing somebody opens this screen to
find, so both halves are shown.

**Read before write.** The read path is one Setup Dump and needs nothing but
the dump. The write path is separate, gated, and it has two shapes: the master
parameters, whose IDs were read back off a unit, and the nine per-channel
fields, written by sending the dump back with one of them changed -- a route
that needed no ID to be invented. See :mod:`p2ked.masteredit`.

Everything the unit reports about a channel is shown, because the point of
the screen is that the reader stops guessing. What the unit does *not*
report -- a cable, an unplugged submix jack, a silent monitor -- is not
claimed. See :meth:`p2k.messages.ChannelState.silence_reasons` for which is
which and where each reason was transcribed from.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence, Tuple, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static

from p2k import literal as _p2k_literal
from p2k import messages as params
from p2k import roms
from p2ked.masteredit import (
    CHANNEL_EDIT_HINT,
    CHANNEL_FIELDS,
    FX_PARAMETERS,
    MASTER_PARAMETERS,
    ChannelChange,
    MasterEditor,
    MasterParameter,
)
from p2ked.prompts import PromptScreen

if TYPE_CHECKING:  # pragma: no cover - importing it at runtime is a cycle
    from p2ked.app import P2kedApp

__all__ = [
    "ARP_NAMES",
    "CHANNEL_EDIT_HINT",
    "FX_EDIT_HINT",
    "MIX_OUTPUT_NAMES",
    "ChannelDetailScreen",
    "FXEditScreen",
    "MasterEditScreen",
    "MultiScreen",
    "SoundPickerScreen",
    "ValuePickerScreen",
]


def _say(app, message: str, *, refused: bool = False) -> None:
    """One sentence on the app's status line, from a screen.

    The cast rather than a plain call: :class:`textual.app.App` has no
    ``notify_status``, and importing the app to say what ``app`` is would
    be a real cycle -- ``app.py`` imports this module to build its screens.
    The name in the string is resolved by the type checker only.

    It is :meth:`P2kedApp._say_edit` rather than ``notify_status``
    directly, because a modal is where an edit happens and the app's own
    status line is the dimmed backdrop behind one -- a refusal written
    there is written where nobody is looking. The app's line still gets
    the sentence; that method is what decides. See it.
    """
    cast("P2kedApp", app)._say_edit(message, refused=refused)


#: What the mix output's four values are called, in the order the field
#: numbers them.
#:
#: The names are the ones this screen and ``p2kcli channels`` already print,
#: and they follow the manual's reading of the field: "you can select Send
#: 1-4, or Preset" (OM p. 38, quoted in
#: :meth:`p2k.messages.ChannelState.silence_reasons`). The parameter tree
#: prints the same thing as "use preset or send 1-4" (paramtree) -- five
#: names against a field whose documented range is **four** values (spec
#: p. 41: -1 to 2). So the fourth send has no value to attach to, and the
#: code gives "send 3" the top of the range: the list below is the four the
#: field actually holds, not the five a document prints. Which of the two is
#: ahead of the other is not something any document to hand settles, and the
#: field's range is what p2ked writes.
MIX_OUTPUT_NAMES: Tuple[str, ...] = ("use preset", "send 1", "send 2", "send 3")

#: The value the first of :data:`MIX_OUTPUT_NAMES` is numbered by. -1, so a
#: pick of "use preset" answers -1 and not 0.
MIX_OUTPUT_BASE = -1

#: What the arpeggiator field's four values are called, in the order the
#: field numbers them.
#:
#: spec p. 41's own "documented values" column, transcribed in
#: ``docs/RESOLUTION_NOTES.md`` §12's table of the nine per-channel
#: parameters: "-2 = off, -1 = on, 0 = P (Preset Arp), 1 = G (Global Arp)".
#: That is the whole of what any document to hand says about the field,
#: which is why the list stops there rather than naming what "P" switches.
ARP_NAMES: Tuple[str, ...] = ("off", "on", "P (preset arp)", "G (global arp)")

#: The value the first of :data:`ARP_NAMES` is numbered by.
ARP_BASE = -2

#: What sits under the FX table instead of :data:`CHANNEL_EDIT_HINT`,
#: because the questions a reader has here are different ones: where the FX
#: *bypass* went, and what the two enumerations are.
#:
#: The bypass is the sharp edge. It is called "FX MODE" on the front panel
#: (paramtree, MASTER BUTTON 5) and it is **not** in this block -- the dump
#: carries it in the general block at id 258 -- so somebody who came here to
#: turn the effects off has to be told which screen that is on, or they
#: will conclude it cannot be done.
FX_EDIT_HINT = (
    "The master FX block: ids 513-528, the dump's own "
    "(RESOLUTION_NOTES §10).\n"
    "\n"
    "The two algorithms are enumerations: 44 and 32 named values, numbered "
    "from 1 in the manual's own order (OM p. 41, p. 43) -- a transcription, "
    "not a reading from this unit. Enter opens the list.\n"
    "\n"
    "FX B delay reads 0-127 on the wire and 0 ms to 635 ms on the unit's "
    "own display (OM p. 146). FX bypass is not here: the dump puts it in the "
    "general block at id 258, on the master-parameter screen."
)


@dataclass(frozen=True)
class _Cell:
    """One column of the multi table, and what an edit on it would write.

    ``kind`` is the whole of the editing decision, and it is declared per
    column rather than derived from a range, because the derivations would be
    wrong in the one place it matters: ``enable`` and
    ``receive_program_change`` are 0-1 like a two-value enumeration, but they
    are switches -- ``space`` flips them and a list of two would be a dialog
    where a keystroke belongs.

    ``field`` is the dump field the column writes, empty for the columns that
    are not one of the nine: ``ch`` is the row's own index, ``plays`` and
    ``ROM`` are the *sound* -- three fields the unit takes together -- and
    ``why not`` is a reading of the other eight.
    """

    key: str
    label: str
    kind: str  # "read" | "number" | "named" | "switch" | "sound"
    field: str = ""
    names: Tuple[str, ...] = ()
    base: int = 0

    @property
    def editable(self) -> bool:
        """Whether a value can be typed, picked or nudged into this cell."""
        return self.kind in ("number", "named", "switch")


#: The table's columns, in the order they are drawn, with the range of each
#: one available from :data:`p2ked.masteredit.CHANNEL_FIELDS`.
#:
#: Nine of the dump's per-channel fields become cells. The other three --
#: ``preset``, ``bank_map`` and ``rom_id`` -- do not get a cell each, because
#: the unit takes the three *together* as one sound: aiming a channel at a
#: sound is one write and one entry on the undo timeline
#: (:data:`p2ked.masteredit.SOUND_FIELD`), so they belong behind the one
#: gesture that changes all three -- ``s`` -- rather than behind three cells
#: that could each be moved into a channel that plays nothing.
CELLS: Tuple[_Cell, ...] = (
    _Cell("ch", "ch", "read"),
    _Cell("plays", "plays", "sound"),
    _Cell("vol", "vol", "number", field="volume"),
    _Cell("pan", "pan", "number", field="pan"),
    _Cell(
        "out",
        "out",
        "named",
        field="mix_output",
        names=MIX_OUTPUT_NAMES,
        base=MIX_OUTPUT_BASE,
    ),
    _Cell("on", "on", "switch", field="enable"),
    _Cell("rxpc", "rxPC", "switch", field="receive_program_change"),
    _Cell("arp", "arp", "named", field="arp", names=ARP_NAMES, base=ARP_BASE),
    _Cell("rom", "ROM", "sound"),
    _Cell("why", "why not", "read"),
)

#: The columns by their DataTable key, because a cell arrives as a key and
#: not as an object.
CELLS_BY_KEY: Dict[str, _Cell] = {cell.key: cell for cell in CELLS}


def _literal(text: str) -> str:
    """``text`` as markup that renders as exactly itself.

    Kept as a local name because the calls in this module read better with
    it; the implementation is shared. See :func:`p2k.literal`.
    """
    return _p2k_literal(text)


def mode_summary(mode: Optional[int]) -> str:
    """One line about the MIDI Mode, which decides whether the table means
    anything. ``None`` when it could not be read -- said, not hidden."""
    if mode is None:
        return "[dim]MIDI mode could not be read[/dim]"
    name = params.MidiMode.name(mode)
    if params.MidiMode.is_multitimbral(mode):
        return f"MIDI mode [b]{name}[/b]"
    return (
        f"[b]MIDI mode {name}[/b] — NOT multitimbral; the unit ignores every "
        f"channel setting below and plays [b]one[/b] preset"
    )


def master_summary(dump: params.SetupDump) -> List[str]:
    """The master parameters a channel map is played through, as lines.

    Every value is the raw decoded one. Where the manual gives a unit p2ked
    has not verified, the raw number is shown rather than a conversion --
    see p2k/messages.py's ``SetupDump.tune`` for the standing example.
    """
    lines: List[str] = []

    def present(label: str, value: Optional[int], fmt: str) -> None:
        lines.append(
            f"{label} {fmt.format(value)}" if value is not None else f"{label} ?"
        )

    present("clock", dump.clock_tempo, "{} bpm")
    present("transpose", dump.transpose, "{:+d} st")
    present("bend", dump.bend_range, "±{} st")
    present("basic ch", dump.basic_channel, "{}")
    present("FX ctrl ch", dump.fx_control_channel, "{}")
    present("tempo ctrl ch", dump.tempo_control_channel, "{}")
    present("sysEx id", dump.midi_id, "{}")
    return lines


class MultiScreen(ModalScreen[None]):
    """Every MIDI channel, and the master settings they are played through.

    **Silent.** One Setup Dump gets the lot; nothing is selected and nothing
    sounds. ``e`` is the door to the edit path over the general master
    parameters and ``x`` to the one over the master FX block -- see
    :mod:`p2ked.masteredit`.

    **And editable, cell by cell.** The table moves between *cells* rather
    than rows, the way the sibling rxved's multi table does, because nine of
    the columns are values with ranges and a row-wide cursor could say
    nothing about which of them a keystroke was aimed at. ``enter`` opens the
    focused value: a number to type, or the list of names for a field whose
    values a document names. ``+`` and ``-`` nudge it, ``space`` flips a
    switch, a digit starts typing a number in place, and ``s`` picks a sound
    for the channel -- which is the one gesture that writes three fields,
    because the unit takes them together.

    Every one of those is a write, and none of them is a shortcut around the
    apparatus: they all call the app's own
    :meth:`P2kedApp.action_edit_channel`, so the write gate, the range check,
    the undo log and the read-back are the ones a master edit goes through.
    The screen holds no device and starts no worker -- the app owns both.

    A burst of nudges on one cell is what that apparatus was extended for,
    and the extension is the app's: the row is drawn with each value as it
    is pressed, and the worker already writing sends the next one when its
    read-back agrees. Still one write in flight, still gate-checked, still
    read back, and one entry on the undo timeline per value the unit
    actually received. :meth:`channel_target` and :meth:`channel_reported`
    are the two seams that draw a row before and after that.
    """

    DEFAULT_CSS = """
    MultiScreen { align: center middle; }
    MultiScreen > Vertical {
        width: 110; height: 90%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    MultiScreen DataTable { height: 1fr; }
    MultiScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    MultiScreen .master { height: auto; color: $text-muted; }
    MultiScreen .status { height: auto; color: $text; padding-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("r", "refresh", "Re-read"),
        Binding("e", "edit", "Edit", show=False),
        # `w` is here as well as on the app, and both are needed. A modal
        # screen's bindings take precedence over the app's -- the whole
        # point of a modal -- so the app's `w` never arrives on this
        # screen. Without this one the gate could only be armed by closing
        # the very screen whose cells are refused until it is armed.
        #
        # The gate itself is the editor's, which the app handed in: the
        # same object the app's own key toggles and the same one its edits
        # are checked against, so the two cannot disagree about which is
        # open.
        Binding("w", "toggle_write_gate", "Write gate"),
        # `x` is the FX block, for the same reason `e` is the general one:
        # they are two different tables in the dump (spec p. 49 puts the
        # master effects right after the master general parameters), and a
        # reader looking for a reverb should not have to find it in a list
        # of MIDI modes. Shown in the legend and in this screen's footer,
        # because a key that changes the unit and is documented nowhere is
        # a key that gets pressed by accident.
        Binding("x", "edit_fx", "Master FX", show=False),
        # `z` / `Z` are the app's own, and this screen has to serve them
        # itself for the reason the master editor serves `w` itself: a
        # modal screen cuts the app's binding chain, so an app-level
        # binding is *dead* the moment this screen is open -- and this is
        # the screen an edit made through `e` returns to, which is
        # exactly where `z` gets pressed. The legend promises the key in
        # the browser; promising it here too is what makes that true.
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
        # The four editing gestures, and `s`. Not a second edit path: each
        # one calls the same `on_edit_channel` a typed number does, so the
        # gate, the range check, the log and the read-back are the ones an
        # edit has always gone through. rxved binds the same three on its
        # part table for the same reason -- a value with a clear range
        # should not be changed one way here and another way one screen
        # over.
        Binding("space", "toggle_cell", "Toggle"),
        Binding("plus", "bump(1)", "Value +"),
        # `=` as well as `+`, because `+` is a shift on most layouts and a
        # nudge is a one-handed gesture.
        Binding("equals_sign", "bump(1)", "Value +"),
        Binding("minus", "bump(-1)", "Value -"),
        Binding("s", "pick_sound", "Pick a sound"),
        # Typing a digit on a numeric cell starts entering a number, the way
        # a spreadsheet does -- pressing Enter first to open an empty-ish
        # prompt is a step nobody wants for a three-keystroke value. The
        # digits go on this screen's own status line, `enter` confirms and
        # `escape` cancels, so there is no modal to leave.
        *[
            Binding(str(digit), f"type_digit('{digit}')", "Type", show=False)
            for digit in range(10)
        ],
    ]

    def __init__(
        self,
        dump: params.SetupDump,
        catalog=None,
        mode: Optional[int] = None,
        *,
        fitted: Optional[Dict[int, bool]] = None,
        bank_ids: Optional[Sequence[str]] = None,
        favorites=None,
        editor: Optional[MasterEditor] = None,
        on_edit: Optional[Callable[[], None]] = None,
        on_edit_fx: Optional[Callable[[], None]] = None,
        on_undo: Optional[Callable[[Optional[int]], None]] = None,
        on_edit_channel: Optional[Callable[[int, str, int], None]] = None,
        on_channel_sound: Optional[Callable[[int, int, int, int], None]] = None,
    ) -> None:
        super().__init__()
        self._dump = dump
        self._catalog = catalog
        #: ``None`` when it could not be read -- which is said, not hidden.
        self._mode = mode
        self._fitted = fitted
        #: The banks the sound picker lists: the app's own visible set, so a
        #: picker and a browser cannot disagree about which ROMs exist.
        #: ``None`` means every bank in the table.
        every_bank = list(roms.bank_ids())
        self._bank_ids = list(bank_ids) if bank_ids is not None else every_bank
        #: The favourites store, for the picker's ``v`` view. ``None`` when
        #: the app was started without one -- the cycle then has "all" only,
        #: rather than promising a view it cannot fill.
        self._favorites = favorites
        #: The app's editor, for the same reason the master edit screen
        #: takes one: this screen offers per-channel edits, so it has to
        #: serve `w` -- a modal cuts the app's binding chain -- and it has
        #: to be able to say which state that left the gate in. ``None``
        #: for a screen built with no edit path at all, which is what the
        #: read-only tests do.
        self._editor = editor
        self._on_edit = on_edit
        #: The app's FX editor, handed in for the reason ``on_edit`` is:
        #: a screen owns no worker, and the FX screen needs values read off
        #: one before it can show them.
        self._on_edit_fx = on_edit_fx
        #: The app's undo, handed in for the same reason ``on_edit`` is:
        # a screen owns no worker, and ``z`` reverses on one.
        self._on_undo = on_undo
        #: The two write paths, both the app's own. A screen offers an edit
        # and never sends one: the gate, the range check, the worker and the
        # read-back are the app's, which is what makes them the same ones a
        # master edit goes through.
        self._on_edit_channel = on_edit_channel
        self._on_channel_sound = on_channel_sound
        #: The number being typed on this screen's status line:
        #: ``(channel, field, digits)``, or ``None``. Held here rather than
        #: in a modal, because a three-keystroke value should not cost a
        #: dialog -- the spreadsheet gesture, not the form.
        self._typing: Optional[Tuple[int, str, str]] = None

    # --- reading ----------------------------------------------------------

    @property
    def _multitimbral(self) -> bool:
        return self._mode is None or params.MidiMode.is_multitimbral(self._mode)

    def _plays(self, entry: params.ChannelState) -> str:
        """What sounds: the preset's name where a name is known, else ids.

        The name comes from the catalog only when the catalog knows the
        bank, so a channel aimed at a ROM with no catalog entry still says
        which ROM and preset it wants.

        The dump's ``preset`` is a **ROM-relative** number and the catalog
        is keyed by **bank-relative** program change, so the two are split
        with :func:`divmod` rather than used as if they were one number.
        Without that split nothing past 128 could be named: every bank is
        128 presets wide and the fourth digit of a 512-preset ROM is a
        different bank. ``p2kcli channels`` answers the same question the
        same way, in :func:`p2ked.cli._plays`.
        """
        rom = (
            roms.USER
            if entry.rom_id == roms.USER_ROM_ID
            else roms.rom_for_simm_id(entry.rom_id)
        )
        plays = f"ROM {entry.rom_id} preset {entry.preset}"
        if rom is None:
            # No ROM in p2ked's table answers on that ID.
            return plays
        index, program_change = divmod(entry.preset, roms.PRESETS_PER_BANK)
        if index >= len(rom.lsbs):
            return f"{rom.name} {entry.preset} (past the last bank)"
        if self._catalog is not None:
            bank_id = f"{rom.id}-{rom.lsbs[index]}"
            name = self._catalog.display_name(bank_id, program_change)
            if name:
                plays = f"{rom.name} {entry.preset} {name}".rstrip()
        return plays

    def _rom_name(self, rom_id: int) -> str:
        for entry in roms.ROMS:
            if entry.msb == rom_id:
                return entry.name
        return f"ROM {rom_id}"

    def _row(self, entry: params.ChannelState) -> tuple:
        reasons = entry.silence_reasons(
            multitimbral=self._multitimbral,
            fitted=self._fitted,
        )
        mix = "use preset" if entry.mix_output < 0 else f"send {entry.mix_output + 1}"
        return (
            str(entry.channel_display),
            self._plays(entry),
            str(entry.volume),
            str(entry.pan - 64),
            mix,
            "on" if entry.enable else "OFF",
            "on" if entry.receive_program_change else "OFF",
            str(entry.arp),
            f"{self._rom_name(entry.rom_id)} ({entry.rom_id})",
            "; ".join(reasons),
        )

    def _report(self) -> str:
        """What is wrong, what p2ked cannot see, and what an edit will do.

        Every reason comes from a value the unit reported; nothing is
        inferred from a cable, a jack or a monitor, and the last line says
        so rather than leaving the reader to assume.

        The closing paragraphs are about the *writing*, because this screen
        writes: what the gate is, what a per-channel edit actually sends, and
        how it is verified. A reader who has just changed a channel deserves
        to be told which of those happened, and a reader who has not deserves
        to know the gate was locked rather than to guess.
        """
        if not self._multitimbral:
            return (
                "The unit is in a single-preset mode, so no channel setting "
                "is in effect: it plays the preset on the front panel on "
                "every channel. Nothing below is a fault."
            )
        silent = []
        for entry in self._dump.channels:
            reasons = entry.silence_reasons(multitimbral=True, fitted=self._fitted)
            if reasons:
                silent.append((entry, reasons))
        if not silent:
            first = f"Every one of the {len(self._dump.channels)} channels would sound."
        else:
            first = (
                f"{len(silent)} of {len(self._dump.channels)} channels would not sound:"
            )
        lines = [first, ""]
        for entry, reasons in silent:
            lines.append(f"  ch {entry.channel_display:>2}  " + "; ".join(reasons))
        deaf = [c for c in self._dump.channels if not c.receive_program_change]
        if deaf:
            lines.append("")
            lines.append(
                "Ignores Program Change on channel "
                + ", ".join(str(c.channel_display) for c in deaf)
                + " — a select aimed there does nothing."
            )
        lines += [
            "",
            "This unit has two MIDI interfaces, so channels 17-32 are the "
            "second one. They are real channels whether or not anything is "
            "plugged into it.",
            "",
            self._edit_note(),
            "",
            # The ROM column's own caveat, on the screen whose column it is.
            # CLAUDE.md's rule is that a guess is labelled in the interface
            # and not only in a comment, and this column names a ROM from a
            # SIMM ID -- see p2k/roms.py's `rom_for_simm_id` and the test in
            # tests/test_roms.py that keeps its wording.
            "The ROM column reads the SIMM ID as that ROM's Bank Select MSB. "
            "No E-MU document to hand says they are the same number; it was "
            "confirmed against hardware for three ROMs on 2026-09-12, which "
            "is not all twenty.",
            "",
            "What this report cannot see, because the unit does not report "
            "it: the cable, an unplugged submix jack, the monitor, and "
            "anything set on the preset rather than the channel.",
        ]
        return "\n".join(lines)

    def _edit_note(self) -> str:
        """What editing a channel here does, in the fewest honest words.

        Four facts, in the order a reader asks for them: the gate, the
        write, the verification, the undo. It is here rather than in the
        footer because the footer has to name keys and this has to explain
        consequences -- and because the gate's *state* is a fact about right
        now, not a key.
        """
        # ``describe()`` spells both states -- "write gate locked" and
        # "write gate ARMED" -- so the sentence carries the editor's own
        # words rather than a second phrasing of them, and a screen that
        # ever says what state the gate is in says the same thing the
        # browser's ``w`` says.
        gate = (
            "write gate locked"
            if self._editor is None
            else self._editor.gate.describe()
        )
        return (
            f"{gate[0].upper()}{gate[1:]}: editing a cell — ⏎, + and -, "
            "space, or s — writes the whole setup dump. p2ked reads the live "
            "dump, changes this one field and sends the dump back (spec p. "
            "29), so every other byte is the one the unit just sent. The "
            "field is read back to verify it, and z — here or in the "
            "browser — puts the previous value back. A burst of nudges on "
            "one cell is not refused and not lost: the row moves as each "
            "one is pressed, the writes still go out one at a time and are "
            "still read back, and z steps back through the values that "
            "were actually sent."
        )

    # --- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        title = (
            f"[b]Multi — setup “{self._dump.name}”[/b]"
            if self._dump.name
            else "[b]Multi[/b]"
        )
        with Vertical():
            yield Label(f"{title}  {mode_summary(self._mode)}")
            yield Static(" · ".join(master_summary(self._dump)), classes="master")
            # `cell`, not `row`: nine of these columns are values with
            # ranges, and a row-wide cursor cannot say which of them a
            # keystroke was aimed at. Textual then hands back arrow-key
            # movement between cells and Enter as CellSelected.
            yield DataTable(id="multi-table", cursor_type="cell", zebra_stripes=True)
            yield Static(self._report(), classes="note")
            # The screen's own status line, for the same reason the master
            # editor has one: everything an edit says -- a refusal, a
            # result, a number half-typed -- lands here, where the user is
            # looking, and not on the app's `#status` behind the modal.
            yield Static("", classes="status")
            yield Static(
                "[dim]arrows move · enter channel detail, or edit the value "
                "under it · a digit types a number · + / - nudge · space "
                "toggles · s picks a sound · r re-read · e master edit · x "
                "master FX · z undo · esc / q to close[/dim]"
            )

    def on_mount(self) -> None:
        table = self.query_one("#multi-table", DataTable)
        for cell in CELLS:
            table.add_column(cell.label, key=cell.key)
        for entry in self._dump.channels:
            table.add_row(*self._row(entry), key=str(entry.channel))

    # --- actions ----------------------------------------------------------

    def action_close(self) -> None:
        """``escape`` and ``q``.

        The binding alone is not enough, and for a reason worth writing
        down: a binding whose action method does not exist is not an
        error. Textual logs it to its console log and presses on, so the
        keys look dead and the reason is invisible unless
        ``TEXTUAL_LOG`` is set. ``q`` works despite the modal binding
        chain stopping at this screen because this is a *screen*
        binding serving itself -- the app's own ``q`` is ``quit`` and is
        never reached from here, which is the point of a modal.

        The same shape as :meth:`p2ked.app.ReportScreen.action_close`.

        ``escape`` first drops a half-typed number, because a key that both
        cancels an entry and closes the screen would close the screen the
        first time it was pressed for the entry -- and the status line
        promises the other thing.
        """
        if self._typing is not None:
            self._forget_typing()
            return
        self.dismiss(None)

    def action_refresh(self) -> None:
        """Re-read the setup. Read-only, and remote-controlled by the app.

        The screen has no device of its own -- the app hands one in through
        ``on_refresh``, because a worker belongs to the app and a screen is
        not allowed to start one that outlives the screen it was opened
        from.
        """
        refresher = getattr(self, "on_refresh", None)
        if refresher is not None:
            refresher()

    def action_edit(self) -> None:
        if self._on_edit is not None:
            self._on_edit()

    def action_toggle_write_gate(self) -> None:
        """``w`` on this screen: the app's own key, and why this one exists.

        A modal screen's bindings win over the app's, so ``w`` pressed here
        never reaches :meth:`P2kedApp.action_toggle_write_gate`. The gate it
        arms is still the app's -- the editor was handed in with it -- so
        what is toggled is the one the edits are checked against, and the
        note under the table is redrawn rather than left describing the
        state the gate was in before the keypress.
        """
        if self._editor is None:
            _say(self.app, "this screen has no write gate to toggle", refused=True)
            return
        self._editor.gate.toggle()
        self.query_one(".note", Static).update(self._report())
        _say(self.app, self._editor.gate.describe())

    def action_edit_fx(self) -> None:
        """``x``: the master FX block, the other half of the edit path.

        ``e`` opens the general parameters and this opens the sixteen FX
        ones, and both go through the same gate, the same undo log and the
        same read-back -- the app is handed the call, because a screen owns
        no worker and this screen opens nothing else either.
        """
        if self._on_edit_fx is not None:
            self._on_edit_fx()

    def action_undo(self) -> None:
        """``z``: the app's own undo, from the screen an edit returns to.

        One change, of either kind -- a master edit sent back over the
        worker the app owns, or a favourite toggle flipped back in the
        local store. The timeline is the app's (see
        :class:`p2ked.app.EditChange`), so all this does is ask; this
        screen holds no log and starts no worker.
        """
        if self._on_undo is not None:
            self._on_undo(1)

    def action_undo_all(self) -> None:
        """``Z``: every change there is, newest first. ``None`` because the
        app is the one that knows the total, favourites included."""
        if self._on_undo is not None:
            self._on_undo(None)

    def on_data_table_cell_selected(self, event) -> None:
        """Enter on a cell: edit the value, or open the channel's detail.

        Enter arrives here rather than as a binding for the same reason the
        browser has no App-level Enter: a focused DataTable consumes the key
        for its own selection, so the value comes back as a message -- and
        with ``cursor_type="cell"`` it comes back as a *cell*, which is the
        only way to know which of a row's nine values the key was aimed at.

        The read-only columns still answer, because a reader who presses
        Enter on ``ch`` or ``why not`` is asking about the channel and not
        fumbling: the detail screen is what they get. The two sound columns
        get the picker, because they are the columns ``s`` writes and the
        gesture a reader will try first.
        """
        if event.data_table.id != "multi-table":
            return
        cell = CELLS_BY_KEY.get(event.cell_key.column_key.value)
        if cell is None:  # pragma: no cover - the table is built from CELLS
            return
        channel = self._channel_of(event.cell_key.row_key.value)
        if channel is None:
            return
        if self._typing is not None and self._typing[:2] == (channel, cell.field):
            # A number was being typed on this very cell: Enter confirms it.
            self._commit_typing()
            return
        entry = self._dump.channel(channel)
        if entry is None:  # pragma: no cover - _channel_of checked it
            return
        if cell.kind == "number":
            self._offer_number(channel, cell, entry)
        elif cell.kind == "named":
            self._offer_named(channel, cell, entry)
        elif cell.kind == "switch":
            self._toggle(channel, cell.field, getattr(entry, cell.field))
        elif cell.kind == "sound":
            self._pick_sound(channel)
        else:
            self.app.push_screen(self._detail(entry))

    def on_data_table_cell_highlighted(self, event) -> None:
        """The cursor moved, so a number being typed is abandoned.

        Not left on the status line, where it would look live: the next
        digit would append to a value meant for the cell the cursor has
        left. ``enter`` and ``escape`` still work on the cell it is now on,
        which is the cell the status line is describing by then.
        """
        if event.data_table.id != "multi-table":
            return
        self._forget_typing()

    def _channel_of(self, row_key: str) -> Optional[int]:
        """The channel a table row key names, or ``None``.

        Row keys are the wire's own 0-based channel numbers as strings, which
        is what makes the row index and
        :meth:`p2ked.app.P2kedApp.action_edit_channel`'s ``channel`` the same
        number.
        """
        try:
            channel = int(row_key)
        except ValueError:  # pragma: no cover - the keys are ours
            return None
        return channel if self._dump.channel(channel) is not None else None

    def _focused(
        self, *, forget: bool = True
    ) -> Tuple[Optional[_Cell], Optional[int], Optional[int]]:
        """``(cell, channel, value)`` under the cursor, or ``(None, ...)``.

        Every editing gesture starts here, so this is also where a
        half-typed number is dropped: a gesture that is not a digit is a
        different gesture, and leaving the digits on the status line would
        make the next ``4`` append to a ``4`` nobody meant to keep.

        ``forget=False`` is for the digit gesture itself, which has to read
        the buffer *before* deciding what to do with it.
        """
        if forget:
            self._forget_typing()
        table = self.query_one("#multi-table", DataTable)
        if not table.row_count:
            return None, None, None
        try:
            row_key, column_key = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:  # pragma: no cover - a table with no cursor yet
            return None, None, None
        # Every row and every column here was added with a key of our own,
        # so a missing one means the table moved underneath us rather than
        # that a channel has no name.
        cell = CELLS_BY_KEY.get(column_key.value or "")
        channel = self._channel_of(row_key.value or "")
        entry = self._dump.channel(channel) if channel is not None else None
        if cell is None or entry is None:
            return None, None, None
        return cell, channel, getattr(entry, cell.field) if cell.field else None

    # --- offering an edit -------------------------------------------------

    def _offer_number(
        self, channel: int, cell: _Cell, entry: params.ChannelState
    ) -> None:
        """A number to type, with the range and the current value on it.

        The question names the range because the specification clips an
        out-of-range value rather than refusing it (spec p. 41) -- so the
        reader has to be able to see what the field takes before sending
        one. The check itself is the app's, on the main thread, before
        anything is spawned; see :meth:`MasterEditor.allow_channel_field`.
        """
        field = CHANNEL_FIELDS[cell.field]
        question = (
            f"channel {channel + 1} {cell.field} "
            f"({field.low}-{field.high}), now {getattr(entry, cell.field)}"
        )

        def apply(text) -> None:
            if not text or not text.strip():
                return
            try:
                value = int(text.strip())
            except ValueError:
                _say(self.app, f"{text!r} is not a number", refused=True)
                return
            self._edit_channel(channel, cell.field, value)

        self.app.push_screen(PromptScreen(question), apply)

    def _offer_named(
        self, channel: int, cell: _Cell, entry: params.ChannelState
    ) -> None:
        """A field whose values a document names is a list to pick from.

        Not a number to type: ``use preset`` is what the screen prints and
        what the front panel shows, so asking for ``-1`` and then spelling
        it back as words on the next render is a round trip through a
        vocabulary the unit does not use. The answer is the value the field
        is numbered by -- the same integer a typed ``-1`` would produce --
        so the gate, the range check and the undo log downstream cannot tell
        which door the edit came through.
        """

        def picked(value: Optional[int]) -> None:
            if value is not None:
                self._edit_channel(channel, cell.field, value)

        self.app.push_screen(
            ValuePickerScreen(
                f"channel {channel + 1} {cell.field}",
                list(cell.names),
                getattr(entry, cell.field),
                base=cell.base,
            ),
            picked,
        )

    def _edit_channel(self, channel: int, field: str, value: int) -> None:
        """One per-channel edit, handed to the app to send.

        The gate and the range are the app's to check -- see
        :meth:`p2ked.app.P2kedApp.action_edit_channel` -- and this screen
        never sends anything itself. The only thing it does when there is no
        path to hand is say so, rather than accept a keystroke and do
        nothing with it.
        """
        on_edit = self._on_edit_channel
        if on_edit is None:
            _say(self.app, "this screen has no per-channel edit path", refused=True)
            return
        on_edit(channel, field, value)

    # --- the gestures -----------------------------------------------------

    def action_type_digit(self, digit: str) -> None:
        """A digit starts a number on the focused cell, in place.

        The spreadsheet gesture: the value a reader wants is three
        keystrokes, and a modal for each of them is a step nobody wants.
        The digits accumulate on this screen's own status line, ``enter``
        confirms and ``escape`` cancels -- the two keys the status line
        names while it holds them.

        There is nothing to type into a switch or a named field, and saying
        so is more use than ignoring the key: ``space`` is the one that
        toggles.
        """
        cell, channel, _value = self._focused(forget=False)
        if cell is None or channel is None:
            return
        if cell.kind == "switch":
            _say(
                self.app,
                f"{cell.field} is on or off — space toggles it",
                refused=True,
            )
            return
        if cell.kind != "number":
            _say(
                self.app, f"there is no number to type into {cell.field}", refused=True
            )
            return
        started = self._typing
        if started is not None and started[:2] == (channel, cell.field):
            digits = started[2] + digit
        else:
            # A number started on another cell is abandoned rather than
            # appended to: the cursor has moved, so what was being built
            # was for a different channel.
            self._forget_typing()
            digits = digit
        self._typing = (channel, cell.field, digits)
        field = CHANNEL_FIELDS[cell.field]
        self.say(
            f"channel {channel + 1} {cell.field}: {digits} "
            f"({field.low}-{field.high}) — ⏎ writes · esc cancels"
        )

    def action_bump(self, by: int) -> None:
        """``+`` / ``-``: one step the focused numeric value, clamped.

        Not a shortcut around the edit path but another way into it: the
        clamped value goes to the same ``on_edit_channel`` a typed number
        goes to, so the gate refuses it, the range check sees it, the log
        records it and the read-back verifies it. A screen that moved the
        cell itself would be a screen that could show a value the unit never
        accepted.

        A step that cannot move is said, not sent. A per-channel edit is a
        whole-dump write, and re-sending a value the unit already holds would
        put an entry on the undo timeline that restores something that was
        never changed -- so ``+`` at the top of a range answers with the range
        and sends nothing.
        """
        cell, channel, value = self._focused()
        if cell is None or channel is None:
            return
        if cell.kind != "number":
            field = CHANNEL_FIELDS.get(cell.field)
            span = f"{field.low}-{field.high}" if field else cell.field
            _say(self.app, f"+ / - step a number; {cell.field} is {span}", refused=True)
            return
        if value is None:  # pragma: no cover - every field on a read channel
            return
        field = CHANNEL_FIELDS[cell.field]
        stepped = min(field.high, max(field.low, value + by))
        if stepped == value:
            _say(
                self.app,
                f"channel {channel + 1} {cell.field} is already {value}, "
                f"and the range is {field.low}-{field.high}",
                refused=True,
            )
            return
        self._edit_channel(channel, cell.field, stepped)

    def action_toggle_cell(self) -> None:
        """``space``: flip the switch under the cursor.

        The one-bit fields are a switch rather than a range because there is
        nothing to step: ``enable`` and ``receive_program_change`` are the
        two, and rxved bound ``space`` to the same gesture on its part table.
        """
        cell, channel, value = self._focused()
        if cell is None or channel is None:
            return
        if cell.kind != "switch":
            _say(
                self.app,
                f"space toggles a switch; {cell.field} is not one",
                refused=True,
            )
            return
        self._toggle(channel, cell.field, value)

    def _toggle(self, channel: int, field: str, value: Optional[int]) -> None:
        """Flip a one-bit field and hand the new value to the app.

        ``value`` is what the field holds now, read from the screen's own
        copy of the dump -- which is the same object the read-back just
        verified, so a toggle cannot act on a stale value.
        """
        self._edit_channel(channel, field, 0 if value else 1)

    def action_pick_sound(self) -> None:
        """``s``: pick a sound for the focused channel, by name.

        The three fields the unit takes together -- ``rom_id``, ``preset``
        and ``bank_map`` -- are one write and one entry on the undo
        timeline, so they belong behind one gesture rather than three cells.
        See :meth:`_pick_sound`.
        """
        _cell, channel, _value = self._focused()
        if channel is None:
            return
        self._pick_sound(channel)

    def _pick_sound(self, channel: int) -> None:
        """The picker, and what a pick writes.

        ``bank_map`` is carried over from the channel rather than set: no
        document to hand says what the Multimode Bank Map maps between
        (RESOLUTION_NOTES §12), so the picker changes the sound and leaves
        the channel's own mapping alone. Inventing a value for it would be
        exactly the guess the rest of this file refuses to make.
        """
        entry = self._dump.channel(channel)
        on_sound = self._on_channel_sound
        if entry is None or on_sound is None:
            _say(self.app, "this screen has no sound picker path", refused=True)
            return

        def picked(preset: Optional[roms.Preset]) -> None:
            if preset is None:
                return
            rom = preset.bank.rom
            rom_id = roms.USER_ROM_ID if rom is roms.USER else rom.msb
            on_sound(channel, rom_id, preset.number, entry.bank_map)

        self.app.push_screen(
            SoundPickerScreen(
                self._catalog,
                self._bank_ids,
                favorites=self._favorites,
                current=self._preset_of(entry),
            ),
            picked,
        )

    def _preset_of(self, entry: params.ChannelState) -> Optional[roms.Preset]:
        """The preset this channel is on, when p2ked can name its slot.

        The same split :meth:`_plays` makes: the dump's ``preset`` is
        ROM-relative and the catalog is keyed bank-relative, so a preset
        past 128 belongs to a different bank than the first. ``None`` when
        the ROM is not in the table or the number is past its last bank --
        said as unknown rather than rounded into a slot that plays something
        else.
        """
        rom = (
            roms.USER
            if entry.rom_id == roms.USER_ROM_ID
            else roms.rom_for_simm_id(entry.rom_id)
        )
        if rom is None:
            return None
        index, program_change = divmod(entry.preset, roms.PRESETS_PER_BANK)
        if index >= len(rom.lsbs):
            return None
        try:
            return roms.preset(f"{rom.id}-{rom.lsbs[index]}", program_change)
        except LookupError:
            return None  # a ROM whose last bank is partly empty

    # --- the number being typed -------------------------------------------

    def _forget_typing(self) -> None:
        """Drop a half-typed number, and clear the line it was on."""
        if self._typing is not None:
            self._typing = None
            self._clear_status()

    def _commit_typing(self) -> None:
        """``enter``: write the number that was typed, or refuse it."""
        typing = self._typing
        self._typing = None
        if typing is None:  # pragma: no cover - the caller checked
            return
        channel, field, digits = typing
        self._clear_status()
        try:
            self._edit_channel(channel, field, int(digits))
        except ValueError:  # pragma: no cover - digits are digits
            _say(self.app, f"{digits!r} is not a number", refused=True)

    def _clear_status(self) -> None:
        try:
            self.query_one(".status", Static).update("")
        except Exception:  # pragma: no cover - the screen closed under us
            return

    # --- the seams the app looks for --------------------------------------

    def say(self, message: str, *, refused: bool = False) -> None:
        """One sentence on this screen's own status line.

        The same shape :meth:`MasterEditScreen.say` has, and for the same
        reason: the app's ``#status`` is the dimmed backdrop behind this
        modal, so a refusal written there is written where nobody is
        looking. ``[b]refused[/b] · `` in front of a refusal, because the
        difference between a "no" and news is carried by the words and the
        weight, not by the colour alone.
        """
        try:
            status = self.query_one(".status", Static)
        except Exception:  # pragma: no cover - the screen closed under us
            return
        prefix = "[b]refused[/b] · " if refused else ""
        status.update(prefix + message)

    # --- the master-edit seams -------------------------------------------
    #
    # The app looks for a screen that answers `say` and then hands it the
    # master editor's own two seams, because that is the shape it learned
    # them in: `MasterEditScreen` answers all three. A screen that grew a
    # `say` and not these would be a screen the app calls a missing method
    # on, which in Python is an AttributeError out of a worker.
    #
    # This screen is the honest case for it. An edit made through `e` comes
    # back here, and `z` is pressed here -- so the sentence belongs on this
    # screen's line and not on the editor's, which is closed. What cannot
    # happen here is the master editor's *redraw*: those rows are on that
    # screen's table, and there are none of them on this one.

    def result(
        self,
        ok: bool,
        message: str,
        parameter_id: Optional[int] = None,
        value: Optional[int] = None,
    ) -> None:
        """A master edit's answer, when this screen is the live one.

        The row is the editor's to redraw and it is not here, so this says
        the sentence and stops. ``_edit_applied`` calls this instead of
        ``_say_edit``, which is why the sentence is written here rather than
        left for the app.
        """
        self.say(message, refused=not ok)

    def undone(self, plan, results) -> None:
        """``z`` put master values back, and this screen has no master rows.

        Nothing is redrawn, and the sentence is not repeated: the app's own
        ``_say_edit`` follows this call with the same one, and a status line
        written twice in one pass is a flicker.
        """
        return

    def channel_result(self, ok: bool, message: str, change: ChannelChange) -> None:
        """What a per-channel edit did, from the app's read-back.

        A success is drawn where it happened, not just said: the row is
        redrawn from the values the read-back verified. What is shown is
        what the *unit reported*, not what was sent -- the two differ
        exactly when an edit did not land, which is the whole point of
        reading back.

        The screen's own copy of the dump is updated too, so a channel
        detail opened afterwards says the same thing the row does. A screen
        whose two views of one channel could disagree would be a screen
        nobody could trust.

        The sentence is not repeated here: the app says it on every path --
        ``_channel_edited`` ends with ``_say_edit`` -- and a sentence
        written twice is a status line that flickers.
        """
        if ok:
            self._adopt(change, change.sent_values)

    def channel_undone(self, changes: Sequence[Tuple[ChannelChange, bool]]) -> None:
        """``z`` put values back, so the rows say what the unit has now.

        The same redraw :meth:`channel_result` does, for the same reason. A
        ``z`` whose send failed leaves the row alone, because nothing was
        put back: the row still says what the unit has.
        """
        for change, ok in changes:
            if ok:
                self._adopt(change, change.restore_values)

    def channel_target(self, channel: int, values: Dict[str, int]) -> None:
        """A value on its way to the unit, drawn on the row now.

        The app calls this the moment a key is accepted, and there are
        two reasons it has to. The first is the complaint that started
        it: a row that waits for a whole-dump round trip to move looks
        broken for as long as the write takes, which on a cable is
        longer than anybody is willing to believe. The second is
        arithmetic -- the next ``+`` of a burst steps from *this* value,
        so the screen's own copy of the dump, the one every gesture
        reads, has to hold the target and not the value the last
        read-back confirmed.

        An offer and not a claim, and the screen is not asked to believe
        it: :meth:`channel_result` confirms it from the read-back, and
        :meth:`channel_reported` puts back what the unit holds if the
        write does not land.
        """
        self._put_values(channel, values)

    def channel_reported(self, channel: int, values: Dict[str, int]) -> None:
        """What the unit reports for this channel, put back on the row.

        The correction to :meth:`channel_target`, and the reason an
        optimistic row cannot lie: it was drawn with a target nothing
        had verified, so a refusal or a read-back that disagreed hands
        back the values that were read and the row says those instead.
        """
        self._put_values(channel, values)

    def _put_values(self, channel: int, values: Dict[str, int]) -> None:
        """``values`` into this screen's copy of the dump, and redraw.

        One place that writes the dump copy, for the reason
        :meth:`_draw_row` is one place that redraws a row: a channel
        detail opened afterwards has to say the same thing the row says.
        Three things can move a row now -- a read-back, a target on its
        way to the unit, and a correction after a write that did not
        land -- and they all come through here so they cannot drift.
        """
        entry = self._dump.channel(channel)
        if entry is None:  # pragma: no cover - the edit was on a real channel
            return
        for name, value in values.items():
            setattr(entry, name, value)
        self._draw_row(channel)

    def _adopt(self, change: ChannelChange, values: Tuple[int, ...]) -> None:
        """Show one channel's new values, in the row and in the dump copy.

        ``values`` is ``change.sent_values`` after a write and
        ``change.restore_values`` after an undo; both have already been
        verified by a read-back, which is what makes writing them here
        honest. The record's own field order, so the two cannot drift
        apart.
        """
        self._put_values(change.channel, dict(zip(change.fields, values, strict=True)))

    def _draw_row(self, channel: int) -> None:
        """Redraw one row's cells.

        ``DataTable.update_cell`` rather than ``refresh()``, which would
        repaint the cells the table already has and never recompute them --
        an edit that appears to do nothing. Guarded, because a worker can
        finish after the screen it was started from has closed.
        """
        entry = self._dump.channel(channel)
        if entry is None:  # pragma: no cover - the caller checked
            return
        try:
            table = self.query_one("#multi-table", DataTable)
            for cell, value in zip(CELLS, self._row(entry), strict=True):
                table.update_cell(str(channel), cell.key, value)
        except Exception:  # pragma: no cover - the screen closed underneath
            return

    def _detail(self, entry: params.ChannelState) -> ChannelDetailScreen:
        """One channel, everything the dump says about it, and nothing that
        writes. The reasons are the same ones the row and the report carry,
        so the screen cannot disagree with itself about a channel."""
        return ChannelDetailScreen(
            entry,
            plays=self._plays(entry),
            reasons=entry.silence_reasons(
                multitimbral=self._multitimbral, fitted=self._fitted
            ),
            rom_name=self._rom_name(entry.rom_id),
            mode_note="" if self._multitimbral else mode_summary(self._mode),
        )


class SoundPickerScreen(ModalScreen[Optional[roms.Preset]]):
    """Pick a sound for a channel by name, not by a preset number.

    The ``plays`` column is the resolved name, and nobody knows which
    preset number "Velvet Bell" is. So `s` opens this: every bank the app
    lists on the left, that bank's presets on the right with their names
    from the catalog, and the three numbers that select one -- Program
    Change, Bank Select LSB, Bank Select MSB -- on every row, in the order
    a sequencer's MIDI track asks for them.

    The shape is the sibling rxved's ``PatchPickerScreen``, and it is worth
    saying which parts of it p2ked can be given and which it cannot:

    * **The bank pane** matches. p2ked's bank table is ``roms.bank_ids()``
      -- 74 banks, and the app hands in the same visible set its own browser
      shows, so a picker and a browser cannot disagree about what exists.
    * **The favourites cycle** matches, on ``v``, for the same three views
      the browser steps through. A picker with no store to read -- the app
      started without ``--favorites`` -- has the one view only, rather than
      promising two it cannot fill.
    * **A name search** is *not* in rxved's multi picker; its ``/`` search
      lives on the browser, and the picker scrolls. p2ked's catalog can
      search, and a 128-preset bank is a long scroll, so this screen adds
      the filter box. That is the one filter here rxved does not have.

    What a pick writes is one operation: ``rom_id``, ``preset`` and
    ``bank_map`` together, because the unit takes the three together (see
    :meth:`p2ked.app.P2kedApp.action_channel_sound`). The ROM ID is the
    ROM's Bank Select MSB, which is the number ``roms.rom_for_simm_id``
    reads a reported SIMM ID as -- confirmed against hardware for three
    ROMs, which is not all nineteen, and the sentence below the table says
    so rather than leaving a column of numbers looking transcribed.
    """

    DEFAULT_CSS = """
    SoundPickerScreen { align: center middle; }
    SoundPickerScreen > Vertical {
        width: 104; height: 90%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    SoundPickerScreen DataTable { height: 1fr; width: 1fr; }
    SoundPickerScreen #banks { width: 34; height: 1fr; }
    SoundPickerScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        # `v` is the favourites view, on the family's own key -- the same
        # one the browser uses, for the same three views.
        Binding("v", "cycle_view", "Favourites view"),
        Binding("tab", "switch_pane", "Switch pane"),
    ]

    #: The three views ``v`` steps through, named after the app's own.
    VIEW_ALL = "all"
    VIEW_BANK_FAVOURITES = "bank-favourites"
    VIEW_ALL_FAVOURITES = "all-favourites"
    VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)
    VIEW_LABELS = {
        VIEW_ALL: "all presets in this bank",
        VIEW_BANK_FAVOURITES: "this bank's favourites",
        VIEW_ALL_FAVOURITES: "every favourite, all banks",
    }

    #: What the ROM column reads the SIMM ID as, in the app's own words.
    #: Reused rather than reworded: it is the sentence ``p2kcli hardware``
    #: prints and the device screen shows, and a second phrasing of the same
    #: caveat is a caveat that drifts.
    ROM_NOTE = (
        "The ROM ID is that ROM's Bank Select MSB. No E-MU document to hand "
        "says a SIMM ID and an MSB are the same number; it was confirmed "
        "against hardware for three ROMs on 2026-09-12, which is not all "
        "twenty."
    )

    def __init__(
        self,
        catalog,
        bank_ids: Sequence[str],
        *,
        favorites=None,
        current: Optional[roms.Preset] = None,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._bank_ids = list(bank_ids)
        #: The favourites store, or ``None`` when the app has none.
        self._favorites = favorites
        #: The preset the channel is on now, marked in the list and put
        #: under the cursor. ``None`` when p2ked cannot name the slot.
        self._current = current
        #: Index into VIEW_CYCLE, cycled by `v`.
        self._view = 0
        #: What is typed in the filter box. Empty means "the bank's own
        #: presets"; anything else searches every bank, the way the
        #: browser's `/` does.
        self._filter = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title(), id="picker-title")
            yield Input(
                placeholder="filter names — empty shows this bank",
                id="filter",
            )
            with Horizontal():
                yield DataTable(id="sound-banks", cursor_type="row", zebra_stripes=True)
                yield DataTable(id="sound-slots", cursor_type="row", zebra_stripes=True)
            yield Static(self.ROM_NOTE, classes="note")
            yield Static(
                "[dim]tab pane · type to filter names · v favourites view · "
                "⏎ picks · esc cancels[/dim]",
                classes="note",
            )

    def on_mount(self) -> None:
        banks = self.query_one("#sound-banks", DataTable)
        banks.add_column("bank", key="bank")
        for bank_id in self._bank_ids:
            entry = roms.bank(bank_id)
            banks.add_row(f"{entry.label} ({entry.id})", key=bank_id)
        banks.focus()
        self._fill_slots()

    # --- the two panes -----------------------------------------------------

    def _title(self) -> str:
        view = self.VIEW_CYCLE[self._view]
        if self._filter.strip():
            which = f"matching “{self._filter.strip()}”"
        else:
            which = self.VIEW_LABELS[view]
        return f"[b]Pick a sound[/b]  [dim]· {which}[/dim]"

    def _bank_id(self) -> Optional[str]:
        table = self.query_one("#sound-banks", DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate)[0].value

    def _slot_name(self, entry: roms.Preset) -> str:
        """What the catalog calls this slot. Empty when it cannot.

        An empty string rather than a placeholder: a row reading "unknown"
        claims something the catalog did not say, and a user bank has no
        printed name to fall back on at all.
        """
        return self._catalog.display_name(entry.bank_id, entry.program_change)

    def _visible_slots(self) -> List[roms.Preset]:
        """The rows the slot pane shows, for the view and the filter.

        A filter searches every bank, because that is the question being
        asked: "which bank is Velvet Bell in" is what somebody types a name
        for. With no filter the pane shows the bank the left-hand cursor is
        on, exactly as the browser does.
        """
        needle = self._filter.strip().lower()
        if needle:
            hits = []
            # The hit carries its name and whether the printed list disagrees
            # about that slot; the slot is all a picker needs, because the
            # name is fetched again from the same catalog when the row is
            # drawn -- one source, not two answers to the same question.
            for bank_id, program_change, *_rest in self._catalog.search(needle):
                try:
                    hits.append(roms.preset(bank_id, program_change))
                except LookupError:
                    # A hit in a bank this build no longer defines.
                    continue
            return hits
        view = self.VIEW_CYCLE[self._view]
        if view == self.VIEW_ALL:
            bank_id = self._bank_id()
            return roms.presets(bank_id) if bank_id is not None else []
        if self._favorites is None:
            return []
        if view == self.VIEW_BANK_FAVOURITES:
            bank_id = self._bank_id()
            if bank_id is None:
                return []
            marked = self._favorites.keys_for_bank(bank_id)
            return [e for e in roms.presets(bank_id) if e.program_change in marked]
        rows = []
        for favourite in self._favorites.all(order="bank"):
            try:
                rows.append(roms.preset(favourite.bank_id, favourite.number))
            except LookupError:
                continue
        return rows

    def _fill_slots(self) -> None:
        table = self.query_one("#sound-slots", DataTable)
        table.clear(columns=True)
        for label, key in (
            ("♥", "fav"),
            ("bank / #", "number"),
            ("name", "name"),
            ("PC", "pc"),
            ("LSB", "lsb"),
            ("MSB", "msb"),
        ):
            table.add_column(label, key=key)
        for entry in self._visible_slots():
            name = self._slot_name(entry)
            if self._favorites is not None and self._favorites.get(
                entry.bank_id, entry.program_change
            ):
                mark = "[b]♥[/b]"
            else:
                mark = ""
            if self._matches(entry):
                name += "  [b]← current[/b]"
            table.add_row(
                mark,
                f"{entry.bank_id} {entry.number:03d}",
                name,
                str(entry.program_change),
                str(entry.lsb),
                str(entry.msb),
                key=entry.key,
            )
        self.query_one("#picker-title", Label).update(self._title())

    def _matches(self, entry: roms.Preset) -> bool:
        if self._current is None:
            return False
        return (self._current.bank_id, self._current.number) == (
            entry.bank_id,
            entry.number,
        )

    def _slot(self) -> Optional[roms.Preset]:
        table = self.query_one("#sound-slots", DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate)[0].value
        if not key:  # pragma: no cover - a row always has a key
            return None
        bank_id, _, number = key.rpartition(":")
        try:
            return roms.preset(bank_id, int(number))
        except (LookupError, ValueError):
            return None

    # --- messages ----------------------------------------------------------

    def on_data_table_row_highlighted(self, event) -> None:
        if event.data_table.id != "sound-banks":
            return
        # The bank pane only chooses rows while the pane is showing a bank;
        # in the all-favourites view every bank is already listed, and in a
        # name search the bank is irrelevant.
        if (
            self._filter.strip()
            or self.VIEW_CYCLE[self._view] == self.VIEW_ALL_FAVOURITES
        ):
            return
        self._fill_slots()

    def on_data_table_row_selected(self, event) -> None:
        if event.data_table.id == "sound-slots":
            picked = self._slot()
            if picked is not None:
                self.dismiss(picked)
            return
        if event.data_table.id == "sound-banks":
            # Enter on a bank is "show me its presets", which the highlight
            # has already done -- so it moves the cursor into them.
            self.query_one("#sound-slots", DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "filter":
            return
        self._filter = event.value
        self._fill_slots()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the filter box goes to the first match."""
        if event.input.id != "filter":
            return
        self.query_one("#sound-slots", DataTable).focus()

    # --- actions -----------------------------------------------------------

    def action_cancel(self) -> None:
        """``escape`` and ``q``: nothing was picked."""
        self.dismiss(None)

    def action_switch_pane(self) -> None:
        """``tab``: filter box, banks, presets -- round again.

        Three stops rather than rxved's two, because the filter box is a
        third thing to be in and a two-stop cycle would leave it reachable
        only by mouse.
        """
        focused = self.focused
        if isinstance(focused, Input):
            self.query_one("#sound-banks", DataTable).focus()
        elif isinstance(focused, DataTable) and focused.id == "sound-banks":
            self.query_one("#sound-slots", DataTable).focus()
        else:
            self.query_one("#filter", Input).focus()

    def action_cycle_view(self) -> None:
        """``v``: every preset in this bank, its favourites, all favourites.

        The same three views the browser's own table has, so the favourites
        marked there can be picked from here too. With no store the cycle
        does not move, and says why rather than showing an empty list.
        """
        if self._favorites is None:
            self.query_one("#picker-title", Label).update(
                "[b]Pick a sound[/b]  [dim]· no favourites store: "
                "start with --favorites[/dim]"
            )
            return
        self._view = (self._view + 1) % len(self.VIEW_CYCLE)
        self._fill_slots()


class MasterEditScreen(ModalScreen[None]):
    """The master parameters, one edit at a time.

    **Everything here is gated.** The gate is the family's ``--allow-write``
    / ``w`` convention, locked by default, and its state is on screen rather
    than in a keybinding manual -- "why did my edit not send?" has to be
    answerable from where the question is asked.

    What is offered is only what p2ked can name a parameter ID for: the
    general master parameters, whose IDs were read back from a unit and
    agreed with the dump. Per-channel editing is refused with a reason; see
    :data:`CHANNEL_EDIT_HINT`.

    Each edit is read before, sent, and read after, on one worker. The
    read-back is not a formality: a Proteus ignores a request it cannot
    serve rather than refusing it, so a silent failure looks exactly like a
    success until something reads the value again.

    **It is parameterised over the table it shows**, rather than written
    twice for the two master blocks the dump carries. The FX block is
    sixteen more parameters behind the *same* gate, the same undo log and
    the same read-back, and a second copy of this screen would be a second
    place for ``_draw`` to forget to redraw a cell and a second place for
    the range check to drift. See :class:`FXEditScreen`, which is those
    arguments fixed for the FX block.
    """

    DEFAULT_CSS = """
    MasterEditScreen { align: center middle; }
    MasterEditScreen > Vertical {
        width: 90; height: 80%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    MasterEditScreen DataTable { height: 1fr; }
    MasterEditScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    MasterEditScreen .status { height: auto; color: $text; padding-top: 1; }
    """

    #: The footer line inside the panel, one per screen: the FX screen has
    #: no ``x`` to advertise, for the reason its BINDINGS drop the key.
    HINTS = (
        "[dim]w gate · x FX · enter edit · + / - nudge · z undo · "
        "Z undo all · esc / q to close[/dim]"
    )

    #: The table's DOM id, one per screen class: a CSS rule or a query that
    #: names ``#master-table`` must not reach the FX screen's table, and the
    #: two are on screen at different times anyway.
    TABLE_ID = "master-table"

    #: How many named values the ``range`` cell spells out before it says
    #: how many there are instead. The general block's enumerations are two
    #: or three names and read fine in a row; the FX algorithms are
    #: forty-four and thirty-two, and a row holding them would widen the
    #: table past the screen for the sake of a list the picker already
    #: shows. The row names them when they fit and counts them when they do
    #: not, rather than dropping the fact that they exist.
    NAMED_IN_A_ROW = 4

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        # `w` is here as well as on the app, and both are needed. A modal
        # screen's bindings take precedence over the app's -- the whole
        # point of a modal -- so the app's `w` never arrives on this
        # screen; without this one the gate could only be armed by closing
        # the very screen that is saying "edits are refused until it is
        # armed" and "press w".
        #
        # The gate itself is the editor's, which the app handed in: the
        # same object the app's own key toggles and the same one its edits
        # go through, so the two cannot disagree about which is open.
        Binding("w", "toggle_write_gate", "Write gate"),
        # `x` opens the FX block, for the same reason `w` is bound here: a
        # modal cuts the app's binding chain, so the app's own `x` -- the
        # one the legend promises -- is dead the moment this screen is up.
        # Without this one, the only way from here to the FX block would be
        # to close the screen that is one key away from it.
        Binding("x", "edit_fx", "Master FX"),
        # `+` / `-` step the value under the cursor. Not a second edit
        # path: they call the same `on_apply`, so the gate, the range
        # check, the undo log and the read-back are the ones an edit
        # typed in has always gone through.
        Binding("plus", "nudge_up", "Value +"),
        Binding("minus", "nudge_down", "Value -"),
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
    ]

    def __init__(
        self,
        dump: params.SetupDump,
        values: Dict[int, Optional[int]],
        editor: MasterEditor,
        *,
        parameters: Tuple[MasterParameter, ...] = MASTER_PARAMETERS,
        title: str = "Multi — master parameters",
        note: str = CHANNEL_EDIT_HINT,
        on_edit_fx: Optional[Callable[[], None]] = None,
        on_apply: Optional[Callable[[int, int], None]] = None,
        on_undo: Optional[Callable[[Optional[int]], None]] = None,
    ) -> None:
        super().__init__()
        self._dump = dump
        self._values = values
        self._editor = editor
        #: The table this screen shows, and the same one by ID. A redraw
        #: looks a row up in the set the screen was *built* from rather
        #: than in whichever set the app happens to have handy, so a screen
        #: cannot end up drawing a parameter it was not showing.
        self._parameters = parameters
        self._by_id = {p.parameter_id: p for p in parameters}
        self._title = title
        #: The paragraph under the table: the general screen says why the
        #: per-channel parameters are not offered, and the FX one says
        #: where the FX bypass went. Both answer the question the reader
        #: has at that table.
        self._note = note
        #: The app's FX editor, for the reason ``on_apply`` is: a screen
        #: owns no worker and no device.
        self._on_edit_fx = on_edit_fx
        self._on_apply = on_apply
        self._on_undo = on_undo

    # --- reading ----------------------------------------------------------

    def _current(self, parameter_id: int) -> str:
        value = self._values.get(parameter_id)
        return "?" if value is None else str(value)

    def _shown(self, parameter) -> str:
        value = self._values.get(parameter.parameter_id)
        if value is None:
            return "?"
        if parameter.choices:
            # Counted from ``base``, not from zero: the two FX algorithms
            # run 1-44 and 1-32, so the first name is the value 1 and there
            # is nothing at 0 to spell.
            offset = value - parameter.base
            if 0 <= offset < len(parameter.choices):
                return parameter.choices[offset]
            return f"unknown ({value})"
        return str(value)

    def _span(self, parameter) -> str:
        """What the ``range`` cell says."""
        if parameter.choices:
            if len(parameter.choices) <= self.NAMED_IN_A_ROW:
                return " / ".join(parameter.choices)
            return (
                f"{parameter.low} - {parameter.high} ({len(parameter.choices)} named)"
            )
        return f"{parameter.low} - {parameter.high}"

    def _report(self) -> str:
        lines = [
            f"{self._editor.gate.describe()} — "
            + (
                "every edit below will be sent"
                if self._editor.gate.armed
                else "edits are refused until it is armed"
            ),
            "",
            f"{self._editor.log.pending} edit(s) undoable with z.",
            "",
            self._note,
        ]
        return "\n".join(lines)

    # --- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]{self._title}[/b]")
            yield DataTable(id=self.TABLE_ID, cursor_type="row", zebra_stripes=True)
            # `_literal`, because the note quotes the specification and its
            # own sentence carries `[s]` in it -- see the helper.
            yield Static(_literal(self._report()), classes="note")
            # The screen's own status line. Without it everything the
            # screens in here say -- a refusal, a result, an undo report
            # -- lands on the app's `#status`, which is the dimmed
            # backdrop behind this modal. This is where the user is
            # looking, so this is where it goes.
            yield Static("", classes="status")
            yield Static(self.HINTS)

    def on_mount(self) -> None:
        table = self.query_one(f"#{self.TABLE_ID}", DataTable)
        for label, key in (
            ("parameter", "param"),
            ("now", "now"),
            ("range", "range"),
        ):
            table.add_column(label, key=key)
        for parameter in self._parameters:
            table.add_row(
                parameter.label,
                self._shown(parameter),
                self._span(parameter),
                key=str(parameter.parameter_id),
            )

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a row offers that one edit.

        A DataTable consumes Enter for its own row selection, so the value
        arrives here rather than from a binding -- the same reason the
        browser has no App-level Enter at all.
        """
        row = event.data_table.cursor_row
        if 0 <= row < len(self._parameters):
            self._offer(self._parameters[row])

    def _offer(self, parameter) -> None:
        """Offer one edit, in the shape the parameter asks for.

        An enumeration is not a number to type. ``poly`` is what the manual
        prints and what the unit's own display shows, so a parameter with
        :attr:`MasterParameter.choices` opens the list of them and ``enter``
        picks one; a plain range still gets the typed prompt it always
        had. Either way the answer arrives at ``on_apply``, so the gate,
        the range check and the undo log cannot tell the two apart.
        """
        on_apply = self._on_apply
        if on_apply is None:
            return
        if parameter.choices:
            self.app.push_screen(
                ValuePickerScreen(
                    parameter.label,
                    list(parameter.choices),
                    self._values.get(parameter.parameter_id),
                    base=parameter.base,
                ),
                self._picked(on_apply, parameter),
            )
            return
        question = (
            f"{parameter.label} "
            f"({parameter.low}-{parameter.high}), now "
            f"{self._current(parameter.parameter_id)}"
        )

        def apply(text) -> None:
            if not text:
                return
            try:
                value = int(text.strip())
            except ValueError:
                _say(self.app, f"{text!r} is not a number", refused=True)
                return
            on_apply(parameter.parameter_id, value)

        self.app.push_screen(PromptScreen(question), apply)

    @staticmethod
    def _picked(on_apply, parameter):
        """The picker's answer, as the one the typed prompt would have
        given: a value for ``on_apply``, and nothing at all when the pick
        was cancelled."""

        def picked(index: Optional[int]) -> None:
            if index is not None:
                on_apply(parameter.parameter_id, index)

        return picked

    # --- actions ----------------------------------------------------------

    def action_close(self) -> None:
        """``escape`` and ``q``.

        A binding with no action method to serve it is not an error --
        Textual logs it and presses on -- so the two keys this screen has
        advertised since it was written did nothing at all, invisibly.
        ``q`` works despite the modal binding chain stopping here because
        this is a *screen* binding serving itself; the app's own ``q`` is
        ``quit`` and is never reached from a modal, which is the point of
        one. Same shape as
        :meth:`p2ked.app.ReportScreen.action_close`.
        """
        self.dismiss(None)

    def action_toggle_write_gate(self) -> None:
        """``w`` on this screen: the app's own key, and why this one exists.

        A modal screen's bindings win over the app's, so ``w`` pressed here
        never reaches :meth:`P2kedApp.action_toggle_write_gate`. The gate it
        arms is still the app's -- the editor was handed in with it -- so
        what is toggled is the one the app's edits are checked against, and
        the report below it is redrawn rather than left describing the state
        the gate was in before the keypress.
        """
        self._editor.gate.toggle()
        self.query_one(".note", Static).update(self._report())
        _say(self.app, self._editor.gate.describe())

    def action_nudge_up(self) -> None:
        """``+``: one more than the value under the cursor."""
        self._nudge(1)

    def action_nudge_down(self) -> None:
        """``-``: one less."""
        self._nudge(-1)

    def action_edit_fx(self) -> None:
        """``x``: the master FX block, on this screen's own key.

        Same reason ``w`` is bound here: a modal screen's bindings win over
        the app's, so the app's own ``x`` -- the one the legend promises --
        never arrives while this screen is up. The FX editor it opens reads
        its values on the app's worker, which is why the call is handed in
        rather than made here: a screen owns no device.
        """
        if self._on_edit_fx is not None:
            self._on_edit_fx()

    def _nudge(self, by: int) -> None:
        """Step the cursor row's value by ``by``, clamped to its range.

        Not a shortcut around the edit path but another way into it: the
        clamped value goes to the same ``on_apply`` a typed number goes
        to, so the gate refuses it, the range check sees it, the log
        records it and the read-back verifies it. A screen that moved the
        cell itself would be a screen that could show a value the unit
        never accepted.
        """
        on_apply = self._on_apply
        if on_apply is None:
            return
        row = self.query_one(f"#{self.TABLE_ID}", DataTable).cursor_row
        if not 0 <= row < len(self._parameters):
            return
        parameter = self._parameters[row]
        current = self._values.get(parameter.parameter_id)
        if current is None:
            _say(
                self.app,
                f"{parameter.label} could not be read, so there is "
                f"nothing to nudge from",
                refused=True,
            )
            return
        value = min(parameter.high, max(parameter.low, current + by))
        on_apply(parameter.parameter_id, value)

    def action_undo(self) -> None:
        if self._on_undo is not None:
            self._on_undo(1)

    def action_undo_all(self) -> None:
        """``Z``: every change there is, of either kind.

        ``None`` rather than a number because the count now spans the
        favourites toggles as well as the master edits -- the app's own
        ``Z`` passes the same, and it is the one that knows the total.
        """
        if self._on_undo is not None:
            self._on_undo(None)

    def say(self, message: str, *, refused: bool = False) -> None:
        """One sentence on this screen's own status line.

        ``[b]refused[/b] · `` in front of a refusal, exactly as the app's
        status line prefixes one -- the difference between a "no" and news
        is carried by the words and the weight, not by the colour alone.

        The app keeps writing to its own ``#status`` too; see
        :meth:`P2kedApp._say_edit`. This line is the copy the user can
        actually read while the modal is up.
        """
        try:
            status = self.query_one(".status", Static)
        except Exception:  # pragma: no cover - the screen closed under us
            return
        prefix = "[b]refused[/b] · " if refused else ""
        status.update(prefix + message)

    def result(
        self,
        ok: bool,
        message: str,
        parameter_id: Optional[int] = None,
        value: Optional[int] = None,
    ) -> None:
        """What an edit did, from the app's worker and its read-back.

        A success is drawn where it happened, not just said: ``_values``
        and the ``now`` cell are both replaced. ``DataTable.refresh()``
        alone would repaint the cells it already has and never recompute
        them, so the row would keep reading what the parameter was before
        the edit -- an edit that appears to do nothing. The note is redrawn
        for the same reason ``w`` redraws it: it counts what ``z`` could
        undo, and that count just changed.
        """
        if ok and parameter_id is not None:
            self._values[parameter_id] = value
            self._draw(parameter_id)
        _say(self.app, message, refused=not ok)

    def undone(self, plan, results) -> None:
        """``z`` sent values back, so the rows that showed the edited ones
        say what the unit reports now.

        The same redraw :meth:`result` does, for the same reason: a row
        left reading a value ``z`` has just sent away is the same lie a
        stale edit cell was. The plan and the results are in one order --
        one worker, one list each -- so they are read together.

        A ``z`` whose send failed leaves the cell alone, because nothing
        was put back: the row still says what the unit has.
        """
        # One worker, one list each, in the same order -- so the pairs
        # line up by construction, and `strict` is a second opinion.
        for (parameter_id, value), (answered, ok) in zip(plan, results, strict=True):
            if answered != parameter_id or not ok:
                continue
            self._values[parameter_id] = value
            self._draw(parameter_id)

    def _draw(self, parameter_id: int) -> None:
        """Redraw one row's ``now`` cell, and the note under the table.

        ``DataTable.update_cell`` rather than ``refresh()``, which is the
        whole of the first half of this bug: a refresh repaints the cells a
        table already has and never recomputes them, so an edit that left
        the row alone looked exactly like an edit that did nothing. The
        note is redrawn because it counts what ``z`` could undo, and that
        count just changed -- the same redraw ``w`` does.

        Guarded, because a worker can finish after the screen it was
        started from has closed, and ``_edit_screen`` is kept precisely so
        that such a worker still has somewhere to report.
        """
        parameter = self._by_id.get(parameter_id)
        if parameter is None:  # pragma: no cover - the table is fixed
            return
        try:
            self.query_one(f"#{self.TABLE_ID}", DataTable).update_cell(
                str(parameter_id), "now", self._shown(parameter)
            )
            self.query_one(".note", Static).update(self._report())
        except Exception:  # pragma: no cover - the screen closed underneath
            return


class FXEditScreen(MasterEditScreen):
    """The master FX block: the two algorithms, their parameters, the sends.

    Its own screen rather than sixteen more rows on the general one,
    because they are two different tables in the dump and because a reader
    who has come to ask "why is there no reverb" wants the effects, not a
    longer list to scroll -- and because the front panel keeps them on
    separate screens too (OM pp. 40-43).

    Nothing behind it is new. One write gate, one undo log, one read-back,
    the same gate's state on screen, the same in-modal status line, the
    same picker for an enumeration -- the apparatus is the general editor's
    and only the table and the title are arguments to it. ``x`` opens this
    screen, from the browser, from the multi screen and from the general
    editor, for the reason ``w`` is bound on all three.

    What the IDs are: the dump's own master effects block, 513-528, which
    RESOLUTION_NOTES §10 established by reading each value back from a unit
    and agreeing it with the dump. What the labels, ranges and named values
    are: transcribed from the manuals with a page cite on each one
    (RESOLUTION_NOTES §12) -- the same split the general table makes, said
    here because the FX block is the newer of the two and the algorithm
    names are the part with the most words in it.
    """

    DEFAULT_CSS = """
    FXEditScreen { align: center middle; }
    FXEditScreen > Vertical {
        width: 96; height: 80%; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    FXEditScreen DataTable { height: 1fr; }
    FXEditScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    FXEditScreen .status { height: auto; color: $text; padding-top: 1; }
    """

    #: Its own id, so a rule or a query naming the general editor's table
    #: cannot reach this one.
    TABLE_ID = "fx-table"

    #: No ``x`` in the footer either, for the reason it is not in the
    #: bindings: there is no FX screen to open from here.
    HINTS = (
        "[dim]w gate · enter edit · + / - nudge · z undo · "
        "Z undo all · esc / q to close[/dim]"
    )

    #: No ``x`` here: this screen *is* the FX view, so the key that opens
    #: it has nothing left to open. A binding that reopened the screen it
    #: is already on would be a key that looks live and does nothing --
    #: which is the failure ``action_close``'s docstring describes from the
    #: other side. The rest of the parent's bindings stand as they are.
    BINDINGS = [b for b in MasterEditScreen.BINDINGS if getattr(b, "key", "") != "x"]

    def __init__(
        self,
        dump: params.SetupDump,
        values: Dict[int, Optional[int]],
        editor: MasterEditor,
        *,
        on_apply: Optional[Callable[[int, int], None]] = None,
        on_undo: Optional[Callable[[Optional[int]], None]] = None,
    ) -> None:
        super().__init__(
            dump,
            values,
            editor,
            parameters=FX_PARAMETERS,
            title="Multi — master FX",
            note=FX_EDIT_HINT,
            on_apply=on_apply,
            on_undo=on_undo,
        )


class ValuePickerScreen(ModalScreen[Optional[int]]):
    """Pick one of a parameter's named values.

    An enumeration is not a number to type. ``poly`` is what the manual
    prints, what the unit's own display shows, and what a reader is
    looking for; asking for ``1`` and then spelling it back as a word on
    the next render is a round trip through a vocabulary the unit does not
    use. So ``enter`` on such a parameter opens this list instead of the
    numeric prompt, with the current value on the cursor already.

    ``enter`` picks, ``escape`` and ``q`` close with nothing. The answer
    is the **index** the unit numbers the value by -- the same integer a
    typed ``1`` would have produced -- so the gate, the range check and
    the undo log downstream cannot tell which door the edit came through.

    The shape is the sibling rxved's choice screen (``ChoiceScreen`` in
    rxved/screens.py), with one deliberate difference: the pick arrives
    through the DataTable's own ``RowSelected`` rather than a
    ``priority=True`` ``enter`` binding. A focused DataTable consumes
    Enter for its own row selection -- which is why p2ked's browser has
    no App-level Enter either -- so the value comes back as a message,
    the same way every other table in this tool answers one.
    """

    DEFAULT_CSS = """
    ValuePickerScreen { align: center middle; }
    ValuePickerScreen > Vertical {
        width: 60; height: auto; max-height: 80%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    ValuePickerScreen DataTable { height: auto; max-height: 16; }
    ValuePickerScreen .hint { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(
        self,
        label: str,
        choices: List[str],
        current: Optional[int] = None,
        *,
        base: int = 0,
    ) -> None:
        super().__init__()
        self._label = label
        #: In the order the unit numbers them, so the index this screen
        #: answers with is the value the unit stores.
        self._choices = list(choices)
        #: The value the first of :attr:`_choices` is numbered by, from
        #: :attr:`MasterParameter.base`. 0 for every enumeration in the
        #: general block; 1 for the two FX algorithms, whose ranges start
        #: at 1 (spec p. 49) -- so ``Room 1`` is the value 1 and a picker
        #: that assumed otherwise would answer one too few.
        self._base = base
        #: The index now showing, marked in the list and put under the
        #: cursor. ``None`` when it could not be read.
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"[b]{self._label}[/b]  [dim]now {self._named(self._current)}[/dim]"
            )
            yield DataTable(id="choices", cursor_type="row", zebra_stripes=True)
            yield Static("[dim]⏎ picks · esc / q to close[/dim]", classes="hint")

    def _named(self, index: Optional[int]) -> str:
        if index is None:
            return "?"
        # Counted from ``base``, because the FX algorithms' names start at
        # the value 1 and there is no name at 0 to give back.
        offset = index - self._base
        if 0 <= offset < len(self._choices):
            return self._choices[offset]
        return f"unknown ({index})"

    def _row_of(self, value: int) -> int:
        """The list row a value sits on."""
        return value - self._base

    def _value_of(self, row: int) -> int:
        """The value a list row answers with: what the unit stores."""
        return self._base + row

    def on_mount(self) -> None:
        table = self.query_one("#choices", DataTable)
        table.add_column("value", key="value")
        for row, name in enumerate(self._choices):
            table.add_row(
                f"[b]{name}[/b]" if self._value_of(row) == self._current else name,
                key=str(self._value_of(row)),
            )
        table.focus()
        if self._current is not None:
            row = self._row_of(self._current)
            if 0 <= row < len(self._choices):
                table.move_cursor(row=row)

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a row picks it -- a message, not a binding, for the
        reason every table in this tool has no App-level Enter."""
        if event.data_table.id == "choices":
            self.action_pick()

    def action_close(self) -> None:
        """``escape`` and ``q``: nothing was picked."""
        self.dismiss(None)

    def action_pick(self) -> None:
        """``enter``: dismiss with the value under the cursor."""
        table = self.query_one("#choices", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._choices):
            self.dismiss(self._value_of(row))


class ChannelDetailScreen(ModalScreen[None]):
    """One MIDI channel, its nine values, and nothing that writes.

    Read-only, and it says where the writing is rather than leaving a
    reader to conclude it cannot be done: the editing gestures live on the
    multi screen's table, one cell at a time, and this screen is the same
    nine values in the words the manual uses. :data:`CHANNEL_EDIT_HINT`
    explains what a per-channel edit actually sends, and it points at
    ``docs/TODO`` item 47's read-only probe -- the ID-based alternative
    that would cost one small frame per field instead of a whole-setup
    write.

    The nine values are spelled the way the manual spells them -- ``use
    preset`` for a mix output of -1, ``on``/``OFF`` for the two flags --
    each with the documented range beside it, because a bare ``bank map 3``
    tells a reader nothing and ``arp -2`` less. What p2ked cannot name a
    meaning for is shown as the unit reported it, inside the range the
    manual documents, and not converted into a guess.
    """

    DEFAULT_CSS = """
    ChannelDetailScreen { align: center middle; }
    ChannelDetailScreen > Vertical {
        width: 84; height: auto; max-height: 80%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    ChannelDetailScreen .body { height: auto; }
    ChannelDetailScreen .hint { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(
        self,
        entry: params.ChannelState,
        *,
        plays: str,
        reasons: List[str],
        rom_name: str,
        mode_note: str = "",
    ) -> None:
        super().__init__()
        self._entry = entry
        self._plays = plays
        self._reasons = reasons
        self._rom_name = rom_name
        #: Set when the MIDI Mode says none of the channel map is in
        #: effect, so the reasons are not listed as faults that are not
        #: faults -- the same thing the multi screen's report does.
        self._mode_note = mode_note

    def _value_lines(self) -> List[str]:
        entry = self._entry
        # The four names spec p. 41 gives the arpeggiator field, where the
        # value is one of the four; the bare number where it is not, rather
        # than the nearest word.
        arp = entry.arp - ARP_BASE
        shown = {
            "preset": f"{entry.preset}",
            "volume": f"{entry.volume} of 127",
            "pan": f"{entry.pan - 64:+d}  (64 is centre)",
            "mix_output": (
                "the preset's own output"
                if entry.mix_output < 0
                else f"send {entry.mix_output + 1}"
            ),
            "arp": ARP_NAMES[arp] if 0 <= arp < len(ARP_NAMES) else f"{entry.arp}",
            "enable": "on" if entry.enable else "OFF",
            "bank_map": f"{entry.bank_map}",
            "receive_program_change": "on" if entry.receive_program_change else "OFF",
            "rom_id": f"{self._rom_name} ({entry.rom_id})",
        }
        return [
            f"  {name:<24} {shown[name]:<26} [dim]{low} - {high}[/dim]"
            for name, low, high in params.CHANNEL_PARAMETERS
        ]

    def _why_lines(self) -> List[str]:
        if self._mode_note:
            return [
                "",
                self._mode_note,
                "",
                "[dim]No per-channel reason is in effect in this mode.[/dim]",
            ]
        if not self._reasons:
            return ["", "[b]this channel would sound[/b]"]
        return ["", "[b]why it would not sound[/b]"] + [
            f"  · {reason}" for reason in self._reasons
        ]

    def compose(self) -> ComposeResult:
        body = [
            f"[b]channel {self._entry.channel_display}[/b]  {self._plays}",
            "",
            *self._value_lines(),
            *self._why_lines(),
        ]
        with Vertical():
            yield Label("[b]Multi — channel detail[/b]")
            yield Static("\n".join(body), classes="body")
            # Where the editing is, because a reader who has just read nine
            # values will want to change one and this screen will not do it.
            yield Static(
                "Editing is on the table, one cell at a time: ⏎ on a value, "
                "+ and -, space on a switch, s for a sound.",
                classes="hint",
            )
            # `_literal`, because the sentence quotes the specification and
            # carries `[s]` in it -- see the helper.
            yield Static(_literal(CHANNEL_EDIT_HINT), classes="hint")
            yield Static("[dim]esc / q to close[/dim]", classes="hint")

    def action_close(self) -> None:
        """``escape`` and ``q``. Read-only, so closing is all there is."""
        self.dismiss(None)
