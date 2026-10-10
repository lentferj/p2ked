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
    MASTER_PARAMETERS,
    MasterEditor,
)
from p2ked.prompts import PromptScreen

if TYPE_CHECKING:  # pragma: no cover - importing it at runtime is a cycle
    from p2ked.app import P2kedApp

__all__ = ["CHANNEL_EDIT_HINT", "MasterEditScreen", "MultiScreen"]


def _say(app, message: str, *, refused: bool = False) -> None:
    """One sentence on the app's status line, from a screen.

    The cast rather than a plain call: :class:`textual.app.App` has no
    ``notify_status``, and importing the app to say what ``app`` is would
    be a real cycle -- ``app.py`` imports this module to build its screens.
    The name in the string is resolved by the type checker only.
    """
    cast("P2kedApp", app).notify_status(message, refused=refused)


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
    ]

    def __init__(
        self,
        dump: params.SetupDump,
        catalog=None,
        mode: Optional[int] = None,
        *,
        fitted: Optional[Dict[int, bool]] = None,
        on_edit: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__()
        self._dump = dump
        self._catalog = catalog
        #: ``None`` when it could not be read -- which is said, not hidden.
        self._mode = mode
        self._fitted = fitted
        self._on_edit = on_edit

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
            yield Static("[dim]r re-read · e edit · esc / q to close[/dim]")

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
        on_undo: Optional[Callable[[int], None]] = None,
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
            yield Static(
                "[dim]w gate · enter edit · z undo · Z undo all · "
                "esc / q to close[/dim]"
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
        on_apply = self._on_apply
        if on_apply is None:
            return
        if parameter.choices:
            shown = ", ".join(
                f"{index}={name}" for index, name in enumerate(parameter.choices)
            )
            question = f"{parameter.label} ({shown})"
        else:
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

    # --- actions ----------------------------------------------------------

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

    def action_undo(self) -> None:
        if self._on_undo is not None:
            self._on_undo(1)

    def action_undo_all(self) -> None:
        if self._on_undo is not None:
            self._on_undo(self._editor.log.pending)

    def result(self, ok: bool, message: str) -> None:
        """What an edit did, from the app's worker and its read-back."""
        try:
            self.query_one("#master-table", DataTable).refresh()
        except Exception:  # pragma: no cover - screen closed underneath us
            pass
        _say(self.app, message, refused=not ok)
