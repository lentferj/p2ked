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
the dump. The write path is separate, gated, and only offers what p2ked can
name a parameter ID for -- see :mod:`p2ked.masteredit`.

Everything the unit reports about a channel is shown, because the point of
the screen is that the reader stops guessing. What the unit does *not*
report -- a cable, an unplugged submix jack, a silent monitor -- is not
claimed. See :meth:`p2k.messages.ChannelState.silence_reasons` for which is
which and where each reason was transcribed from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Dict, List, Optional, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from p2k import messages as params
from p2k import roms
from p2ked.masteredit import (
    MASTER_BY_ID,
    MASTER_PARAMETERS,
    MasterEditor,
)
from p2ked.prompts import PromptScreen

if TYPE_CHECKING:  # pragma: no cover - importing it at runtime is a cycle
    from p2ked.app import P2kedApp

__all__ = [
    "CHANNEL_EDIT_HINT",
    "ChannelDetailScreen",
    "MasterEditScreen",
    "MultiScreen",
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


#: Shown where the per-channel editor would be. It is a sentence, not a
#: disabled control: the reason matters more than the missing feature, and a
#: disabled button with no explanation teaches nothing.
CHANNEL_EDIT_HINT = (
    "Per-channel edits are not offered. p2ked reads every channel's nine "
    "values from one dump, but setting one needs its parameter ID, and no "
    "document to hand lists them -- so p2ked will not write to a number it "
    "invented. See docs/TODO item 47 for the read-only probe that "
    "establishes them on a real unit."
)


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

    **Read-only, and silent.** One Setup Dump gets the lot; nothing is
    selected and nothing sounds. ``e`` is the door to the edit path, and it
    is the only key here that can reach one -- see
    :mod:`p2ked.masteredit`.
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
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("r", "refresh", "Re-read"),
        Binding("e", "edit", "Edit", show=False),
        # `z` / `Z` are the app's own, and this screen has to serve them
        # itself for the reason the master editor serves `w` itself: a
        # modal screen cuts the app's binding chain, so an app-level
        # binding is *dead* the moment this screen is open -- and this is
        # the screen an edit made through `e` returns to, which is
        # exactly where `z` gets pressed. The legend promises the key in
        # the browser; promising it here too is what makes that true.
        Binding("z", "undo", "Undo"),
        Binding("Z", "undo_all", "Undo all"),
    ]

    def __init__(
        self,
        dump: params.SetupDump,
        catalog=None,
        mode: Optional[int] = None,
        *,
        fitted: Optional[Dict[int, bool]] = None,
        on_edit: Optional[Callable[[], None]] = None,
        on_undo: Optional[Callable[[Optional[int]], None]] = None,
    ) -> None:
        super().__init__()
        self._dump = dump
        self._catalog = catalog
        #: ``None`` when it could not be read -- which is said, not hidden.
        self._mode = mode
        self._fitted = fitted
        self._on_edit = on_edit
        #: The app's undo, handed in for the same reason ``on_edit`` is:
        #: a screen owns no worker, and ``z`` reverses on one.
        self._on_undo = on_undo

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
            "on" if entry.receive_program_change else "OFF",
            str(entry.arp),
            f"{self._rom_name(entry.rom_id)} ({entry.rom_id})",
            "; ".join(reasons),
        )

    def _report(self) -> str:
        """What is wrong, and what p2ked cannot see.

        Every reason comes from a value the unit reported; nothing is
        inferred from a cable, a jack or a monitor, and the last line says
        so rather than leaving the reader to assume.
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
            "What this report cannot see, because the unit does not report "
            "it: the cable, an unplugged submix jack, the monitor, and "
            "anything set on the preset rather than the channel.",
        ]
        return "\n".join(lines)

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
            yield DataTable(id="multi-table", cursor_type="row", zebra_stripes=True)
            yield Static(self._report(), classes="note")
            yield Static(
                "[dim]r re-read · e edit · enter channel detail · "
                "z undo · esc / q to close[/dim]"
            )

    def on_mount(self) -> None:
        table = self.query_one("#multi-table", DataTable)
        for label, key in (
            ("ch", "ch"),
            ("plays", "plays"),
            ("vol", "vol"),
            ("pan", "pan"),
            ("out", "out"),
            ("rxPC", "rxpc"),
            ("arp", "arp"),
            ("ROM", "rom"),
            ("why not", "why"),
        ):
            table.add_column(label, key=key)
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
        """
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

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a channel row opens that channel, read-only.

        Enter arrives here rather than as a binding for the same reason
        the browser has no App-level Enter: a focused DataTable consumes
        the key for its own row selection, so the value comes back as a
        message.
        """
        if event.data_table.id != "multi-table":
            return
        row = event.cursor_row
        if 0 <= row < len(self._dump.channels):
            self.app.push_screen(self._detail(self._dump.channels[row]))

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


class MasterEditScreen(ModalScreen[None]):
    """The master parameters, one edit at a time.

    **Everything here is gated.** The gate is the family's ``--allow-write``
    / ``w`` convention, locked by default, and its state is on screen rather
    than in a keybinding manual -- "why did my edit not send?" has to be
    answerable from where the question is asked.

    What is offered is only what p2ked can name a parameter ID for: the
    master parameters, whose IDs were read back from a unit and agreed with
    the dump. Per-channel editing is refused with a reason; see
    :data:`CHANNEL_EDIT_HINT`.

    Each edit is read before, sent, and read after, on one worker. The
    read-back is not a formality: a Proteus ignores a request it cannot
    serve rather than refusing it, so a silent failure looks exactly like a
    success until something reads the value again.
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
        on_apply: Optional[Callable[[int, int], None]] = None,
        on_undo: Optional[Callable[[Optional[int]], None]] = None,
    ) -> None:
        super().__init__()
        self._dump = dump
        self._values = values
        self._editor = editor
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
            if 0 <= value < len(parameter.choices):
                return parameter.choices[value]
            return f"unknown ({value})"
        return str(value)

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
            CHANNEL_EDIT_HINT,
        ]
        return "\n".join(lines)

    # --- layout -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Multi — master parameters[/b]")
            yield DataTable(id="master-table", cursor_type="row", zebra_stripes=True)
            yield Static(self._report(), classes="note")
            # The screen's own status line. Without it everything the
            # screens in here say -- a refusal, a result, an undo report
            # -- lands on the app's `#status`, which is the dimmed
            # backdrop behind this modal. This is where the user is
            # looking, so this is where it goes.
            yield Static("", classes="status")
            yield Static(
                "[dim]w gate · enter edit · + / - nudge · z undo · "
                "Z undo all · esc / q to close[/dim]"
            )

    def on_mount(self) -> None:
        table = self.query_one("#master-table", DataTable)
        for label, key in (
            ("parameter", "param"),
            ("now", "now"),
            ("range", "range"),
        ):
            table.add_column(label, key=key)
        for parameter in MASTER_PARAMETERS:
            if parameter.choices:
                span = " / ".join(parameter.choices)
            else:
                span = f"{parameter.low} - {parameter.high}"
            table.add_row(
                parameter.label,
                self._shown(parameter),
                span,
                key=str(parameter.parameter_id),
            )

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a row offers that one edit.

        A DataTable consumes Enter for its own row selection, so the value
        arrives here rather than from a binding -- the same reason the
        browser has no App-level Enter at all.
        """
        row = event.data_table.cursor_row
        if 0 <= row < len(MASTER_PARAMETERS):
            self._offer(MASTER_PARAMETERS[row])

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
        row = self.query_one("#master-table", DataTable).cursor_row
        if not 0 <= row < len(MASTER_PARAMETERS):
            return
        parameter = MASTER_PARAMETERS[row]
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
        parameter = MASTER_BY_ID.get(parameter_id)
        if parameter is None:  # pragma: no cover - the table is fixed
            return
        try:
            self.query_one("#master-table", DataTable).update_cell(
                str(parameter_id), "now", self._shown(parameter)
            )
            self.query_one(".note", Static).update(self._report())
        except Exception:  # pragma: no cover - the screen closed underneath
            return


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
    ) -> None:
        super().__init__()
        self._label = label
        #: In the order the unit numbers them, so the index this screen
        #: answers with is the value the unit stores.
        self._choices = list(choices)
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
        if 0 <= index < len(self._choices):
            return self._choices[index]
        return f"unknown ({index})"

    def on_mount(self) -> None:
        table = self.query_one("#choices", DataTable)
        table.add_column("value", key="value")
        for index, name in enumerate(self._choices):
            table.add_row(
                f"[b]{name}[/b]" if index == self._current else name,
                key=str(index),
            )
        table.focus()
        if self._current is not None and 0 <= self._current < len(self._choices):
            table.move_cursor(row=self._current)

    def on_data_table_row_selected(self, event) -> None:
        """Enter on a row picks it -- a message, not a binding, for the
        reason every table in this tool has no App-level Enter."""
        if event.data_table.id == "choices":
            self.action_pick()

    def action_close(self) -> None:
        """``escape`` and ``q``: nothing was picked."""
        self.dismiss(None)

    def action_pick(self) -> None:
        """``enter``: dismiss with the index under the cursor."""
        table = self.query_one("#choices", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._choices):
            self.dismiss(row)


class ChannelDetailScreen(ModalScreen[None]):
    """One MIDI channel, its nine values, and nothing that writes.

    Read-only, and it says why rather than leaving a disabled control that
    teaches nothing: p2ked reads all nine values out of one Setup Dump,
    but *setting* one needs its parameter ID and no document to hand lists
    those. The hint is :data:`CHANNEL_EDIT_HINT`, and it points at
    ``docs/TODO`` item 47's read-only probe.

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
        shown = {
            "preset": f"{entry.preset}",
            "volume": f"{entry.volume} of 127",
            "pan": f"{entry.pan - 64:+d}  (64 is centre)",
            "mix_output": (
                "the preset's own output"
                if entry.mix_output < 0
                else f"send {entry.mix_output + 1}"
            ),
            "arp": f"{entry.arp}",
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
            yield Static(CHANNEL_EDIT_HINT, classes="hint")
            yield Static("[dim]esc / q to close[/dim]", classes="hint")

    def action_close(self) -> None:
        """``escape`` and ``q``. Read-only, so closing is all there is."""
        self.dismiss(None)
