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

"""The write path over the multi setup: a gate, a log, and what is known.

p2ked was read-only until the maintainer decided editing was in. The
apparatus that makes that safe is here, and it follows the family's shape
rather than a new invention:

**A write gate, locked by default.** ``w`` arms it, ``--allow-write`` starts
it armed, and every key that can reach the unit refuses while it is locked.
This is ``EDITOR_KEYS``' ``w write gate`` in vinsynlib, so it is the same key
in rxved and here.

**A log, so an edit is undoable.** ``z`` reverses the last edit and ``Z`` all
of them, by sending the *previous* value back. Every entry records the
parameter, the old value and the new one, so an undo is a known thing rather
than a guess.

**Verify by reading back.** After every edit p2ked reads the parameter again
and reports a disagreement rather than trusting the wire.

**Nothing is sent that p2ked cannot name a parameter ID for.** The master
parameters below have IDs that were read back from a real unit and agreed
with the dump, value for value (RESOLUTION_NOTES §10). The *per-channel*
multimode parameters do not: their IDs are not in any document to hand, and
inventing one would be a write to a number nobody knows. The UI says so, and
:func:`probe_channel_ids` is the read-only way to establish them on a real
unit -- see ``docs/TODO`` item 47.

**Two tables, one write path.** :data:`MASTER_PARAMETERS` is the general
set and :data:`FX_PARAMETERS` is the master FX block, and the app sends
whichever of them names the parameter: one gate, one log, one read-back.
The FX block's sixteen IDs are unit-agreed master-block IDs -- §10's table
of the dump's blocks came from a unit, and its sixteen master-effects
values were among the eighty-two read back one at a time and agreed with
the dump. What is *not* from a unit is the label and range side of that
table: those are transcribed from the manuals with a page cite on each one,
the way §12 transcribed the general block's, and the two algorithms' named
values are the operation manual's own numbering rather than anything read
back off a screen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from p2k import messages as params

__all__ = [
    "CHANNEL_EDIT_IDS",
    "FX_PARAMETERS",
    "MASTER_BY_ID",
    "MASTER_PARAMETERS",
    "EditGate",
    "EditLog",
    "MasterEditor",
    "MasterParameter",
    "probe_channel_ids",
]


@dataclass(frozen=True)
class MasterParameter:
    """One master parameter p2ked can set, with the range it may be set to.

    ``low`` and ``high`` are inclusive, in the **signed** values the wire
    uses -- a parameter that runs 0-127 reads the same either way, and one
    that runs -12..+12 does not. ``choices`` is for the enumerations, in the
    unit's own order, so a picker can name them without p2ked pretending to
    know the firmware's spelling.

    ``base`` is the value the unit numbers the first of those names by, and
    it is 0 for every enumeration in the general block. The two FX
    algorithms are the ones where it is not: their ranges start at 1, so
    the first name is the value at ``low`` and there is no name at 0. A
    picker built on the assumption that names start at zero would offer a
    blank row and then send one too few.
    """

    parameter_id: int
    label: str
    low: int
    high: int
    #: Named values, in the order the unit numbers them. Empty means a
    #: plain integer range.
    choices: Tuple[str, ...] = ()
    #: What the manual says about it, for the edit screen.
    note: str = ""
    #: The value the first of :attr:`choices` is numbered by. See above.
    base: int = 0


def _p(
    parameter_id: int,
    label: str,
    low: int,
    high: int,
    choices: Tuple[str, ...] = (),
    note: str = "",
    base: int = 0,
) -> MasterParameter:
    # Seven positional values, one per row of the tables this builds. The
    # family allows this where each argument says one thing (PLR0913/
    # PLR0917), as vinsynlib does for the same shape.
    return MasterParameter(parameter_id, label, low, high, choices, note, base)


#: The master parameters the multi setup is built from, in the order an edit
#: screen shows them. Every ID here is one p2ked already reads, which is why
#: these are the ones it can also write: the ID was established by reading
#: the value back from a unit and comparing it with the dump
#: (RESOLUTION_NOTES §10), not by reading a number off a page.
#:
#: Ranges and labels are transcribed from the operator's manual's parameter
#: tree (version 2.26) and the Master menu pages it documents; see
#: RESOLUTION_NOTES §12. Where the two disagree the manual's parameter tree
#: wins, because it is E-MU's own summary of what the unit stores.
MASTER_PARAMETERS: Tuple[MasterParameter, ...] = (
    _p(
        params.Parameter.MIDI_MODE,
        "MIDI mode",
        0,
        2,
        ("omni", "poly", "multi"),
        "The switch that decides whether any of the channel settings mean "
        "anything. Multi is the multitimbral one.",
    ),
    _p(
        params.Parameter.MIDI_MODE_CHANGE,
        "MIDI mode change",
        0,
        1,
        ("ignored", "accepted"),
        "Whether a mode change from an external controller is honoured.",
    ),
    _p(
        params.Parameter.MULTIMODE_BASIC_CHANNEL,
        "multimode basic channel",
        0,
        32,
        note="The channel the front panel's preset selection applies to.",
    ),
    _p(
        params.Parameter.MULTIMODE_FX_CTRL_CHANNEL,
        "FX control channel",
        0,
        32,
        note="Whose preset's effects the master FX settings come from.",
    ),
    _p(
        params.Parameter.MULTIMODE_TEMPO_CTRL_CHAN,
        "tempo control channel",
        0,
        32,
        note="Whose arpeggiator's tempo the master tempo follows.",
    ),
    _p(
        params.Parameter.MASTER_TRANSPOSE,
        "transpose",
        -24,
        24,
        note="Semitones, all presets.",
    ),
    _p(
        params.Parameter.MASTER_TUNE,
        "fine tune",
        -63,
        63,
        note="1/64 semitone increments. p2ked sends the raw value; the "
        "specification's cent table has not been checked.",
    ),
    _p(
        params.Parameter.MASTER_BEND_RANGE,
        "bend range",
        0,
        12,
        note="Semitones, either direction.",
    ),
    _p(
        params.Parameter.MASTER_CLOCK_TEMPO,
        "clock tempo",
        0,
        300,
        note="0 follows an external clock, 1-300 is bpm.",
    ),
    _p(
        params.Parameter.MASTER_FX_BYPASS,
        "FX bypass",
        0,
        1,
        ("on", "bypassed"),
        note="Whether the master effects processors are in circuit.",
    ),
    _p(
        params.Parameter.MIDI_ID,
        "sysEx device ID",
        0,
        126,
        note="What distinguishes two units on one editor. Changing it "
        "mid-session changes how p2ked must address this unit from the next "
        "message on.",
    ),
)

#: The "A" effect types, in the operation manual's own order and spelling.
#: Forty-four of them, which is the specification's max for id 513
#: (spec p. 49) and the count the parameter tree gives ("select effect
#: 1-44", paramtree, EDIT BUTTON 34).
#:
#: The numbering is the document's: the manual lists them 1-44 (OM p. 41,
#: repeated for the Edit menu at OM p. 121) and the specification's min for
#: this parameter is 1, so value 1 is the first name rather than the second.
#: Nothing here was read back off a unit -- the *IDs* are unit-agreed
#: (§10), the *names* are transcribed.
FX_A_ALGORITHMS: Tuple[str, ...] = (
    "Room 1",
    "Room 2",
    "Room 3",
    "Hall 1",
    "Hall 2",
    "Plate",
    "Delay",
    "Panning Delay",
    "Multitap 1",
    "Multitap Pan",
    "3 Tap",
    "3 Tap Pan",
    "Soft Room",
    "Warm Room",
    "Perfect Room",
    "Tiled Room",
    "Hard Plate",
    "Warm Hall",
    "Spacious Hall",
    "Bright Hall",
    "Bright Hall Pan",
    "Bright Plate",
    "BBall Court",
    "Gymnasium",
    "Cavern",
    "Concert 9",
    "Concert 10 Pan",
    "Reverse Gate",
    "Gate 2",
    "Gate Pan",
    "Concert 11",
    "Medium Concert",
    "Large Concert",
    "Large Concert Pan",
    "Canyon",
    "DelayVerb 1",
    "DelayVerb 2",
    "DelayVerb 3",
    "DelayVerb 4 Pan",
    "DelayVerb 5 Pan",
    "DelayVerb 6",
    "DelayVerb 7",
    "DelayVerb 8",
    "DelayVerb 9",
)

#: The "B" effect types, same arrangement: thirty-two of them, which is the
#: specification's max for id 520 (spec p. 49) and the parameter tree's
#: "select effect 1-32" (paramtree, EDIT BUTTON 37).
#:
#: Spelled from the master menu's page (OM p. 43). The Edit menu repeats the
#: list (OM p. 122) and closes up two of the spaces -- "PanDelay Chorus 1"
#: and "PanDelay Chorus 2" for what p. 43 calls "Pan Delay Chorus 1" and
#: "Pan Delay Chorus 2". Same two documents, same list, two spellings;
#: p2ked follows the Master menu's because that is where the master
#: parameters live.
FX_B_ALGORITHMS: Tuple[str, ...] = (
    "Chorus 1",
    "Chorus 2",
    "Chorus 3",
    "Chorus 4",
    "Chorus 5",
    "Doubling",
    "Slapback",
    "Flange 1",
    "Flange 2",
    "Flange 3",
    "Flange 4",
    "Flange 5",
    "Flange 6",
    "Flange 7",
    "Big Chorus",
    "Symphonic",
    "Ensemble",
    "Delay",
    "Delay Stereo",
    "Delay Stereo 2",
    "Panning Delay",
    "Delay Chorus",
    "Pan Delay Chorus 1",
    "Pan Delay Chorus 2",
    "Dual Tap 1/3",
    "Dual Tap 1/4",
    "Vibrato",
    "Distortion 1",
    "Distortion 2",
    "Distorted Flange",
    "Distorted Chorus",
    "Distorted Double",
)

#: The master FX block, in the dump's own order -- which is the order the
#: specification lists these sixteen parameters in (spec p. 49) and the
#: order :data:`p2k.messages.MASTER_BLOCKS` carries them in. Follow the
#: block, not the front panel: the unit's own screens list each processor's
#: four send amounts together (OM pp. 42-43; paramtree, MASTER BUTTON 9, 12),
#: while the dump carries sends 1-3 of each in the middle of the block and
#: both fourth sends at the end -- 517-519, then 520-523, then 524-526,
#: then 527 = FX A send 4 and 528 = FX B send 4. A reader looking for "FXA
#: send 4" on the front panel's screen will not find it beside 1, 2 and 3.
#:
#: The IDs are unit-agreed master-block IDs: the master effects block the
#: dump carries is 513-528, and §10 established that table by reading each
#: value back from a unit and agreeing it with the dump. The **labels,
#: ranges and named values** are not from a unit -- they are transcribed
#: from the operator's manual's Master menu pages and parameter tree, with
#: a page cite on each one, the way RESOLUTION_NOTES §12 transcribed the
#: general block. Where the two disagree the E-MU documents win, because
#: the parameter tree is one person's summary (paramtree, line 3) and
#: nothing more.
#:
#: Two things about this block that the general one does not have to say:
#:
#: - **The algorithms start at 1, not 0.** The specification gives both a
#:   min of 1 (spec p. 49) and the manual numbers its effect types from 1
#:   (OM p. 41 for the A list, p. 43 for the B one -- they sit on facing
#:   pages of the same spread), so ``base`` is 1 for those two rows and
#:   there is no name at 0.
#: - **FX B delay is the one value whose units are not its own number.** The
#:   parameter tree lists it as note values "or 0ms - 635ms in 5ms
#:   increments" (paramtree, MASTER BUTTON 11); the operation manual says
#:   only "The Delay value range is from 0ms to 635ms" (OM p. 146) and its
#:   screens show a plain number of milliseconds. p2ked keeps the raw 0-127
#:   and does not invent the 5 ms step or the note-value table, because the
#:   two documents do not agree on either -- see RESOLUTION_NOTES §12.
FX_PARAMETERS: Tuple[MasterParameter, ...] = (
    _p(
        513,
        "FX A algorithm",
        1,
        44,
        FX_A_ALGORITHMS,
        note="The “A” effect type: 44 of them, Room 1 to DelayVerb 9, "
        "numbered 1-44 (spec p. 49; OM p. 41).",
        base=1,
    ),
    _p(
        514,
        "FX A decay",
        0,
        90,
        note="How long the A effect takes to fade out (spec p. 49; "
        "paramtree, MASTER BUTTON 8; OM p. 146).",
    ),
    _p(
        515,
        "FX A HF damping",
        0,
        127,
        note="How fast the highs go first in the decay (spec p. 49; "
        "paramtree, MASTER BUTTON 8; OM p. 146).",
    ),
    _p(
        516,
        "FX B into FX A",
        0,
        127,
        note="Routes FX B through FX A, so the two sit in series "
        "(spec p. 49; OM p. 122; paramtree, MASTER BUTTON 8).",
    ),
    _p(
        517,
        "FX A send 1",
        0,
        100,
        note="Percent of the first stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 9; OM p. 42).",
    ),
    _p(
        518,
        "FX A send 2",
        0,
        100,
        note="Percent of the second stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 9).",
    ),
    _p(
        519,
        "FX A send 3",
        0,
        100,
        note="Percent of the third stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 9).",
    ),
    _p(
        520,
        "FX B algorithm",
        1,
        32,
        FX_B_ALGORITHMS,
        note="The “B” effect type: 32 of them, Chorus 1 to Distorted "
        "Double, numbered 1-32 (spec p. 49; OM p. 43).",
        base=1,
    ),
    _p(
        521,
        "FX B feedback",
        0,
        127,
        note="How much of FX B's output goes back into its input "
        "(spec p. 49; OM p. 146).",
    ),
    _p(
        522,
        "FX B LFO rate",
        0,
        127,
        note="The speed of FX B's modulation oscillator (spec p. 49; OM p. 146).",
    ),
    _p(
        523,
        "FX B delay",
        0,
        127,
        note="The unit's display reads it in milliseconds, 0 to 635 "
        "(OM p. 146); the parameter tree adds a table of note values "
        "and a 5 ms step that the manual does not (paramtree, MASTER "
        "BUTTON 11). p2ked sends the raw number.",
    ),
    _p(
        524,
        "FX B send 1",
        0,
        100,
        note="Percent of the first stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 12; OM p. 43).",
    ),
    _p(
        525,
        "FX B send 2",
        0,
        100,
        note="Percent of the second stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 12; OM p. 43).",
    ),
    _p(
        526,
        "FX B send 3",
        0,
        100,
        note="Percent of the third stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 12; OM p. 43).",
    ),
    _p(
        527,
        "FX A send 4",
        0,
        100,
        note="Percent of the fourth stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 9).",
    ),
    _p(
        528,
        "FX B send 4",
        0,
        100,
        note="Percent of the fourth stereo effects bus (spec p. 49; "
        "paramtree, MASTER BUTTON 12; OM p. 43).",
    ),
)

#: Every master parameter p2ked can write, by parameter ID: the general
#: table above and the FX block, together.
#:
#: It is the one lookup the app's edit path checks, and the sentence about
#: it needs the parameter's name and range rather than a bare number --
#: an edit is verified by reading the parameter it wrote, so the report
#: off a read-back is written from here. Holding both tables is what makes
#: a parameter offered by a screen and a parameter the app will send the
#: same set: adding a row to either table puts it on the edit path, and
#: taking one out refuses it, with nothing else to change.
MASTER_BY_ID: Dict[int, MasterParameter] = {
    **{parameter.parameter_id: parameter for parameter in MASTER_PARAMETERS},
    **{parameter.parameter_id: parameter for parameter in FX_PARAMETERS},
}

#: Parameter IDs for the per-channel multimode parameters, or ``None``.
#:
#: **Not established, and deliberately not guessed.** The Setup Dump carries
#: all nine per channel positionally, so reading them is solved; setting one
#: needs its parameter ID, and no document to hand lists them. p2ked refuses
#: the edit rather than sending to a number it invented, and
#: :func:`probe_channel_ids` is the read-only way to find them on a real
#: unit. Until then the edit screen offers only :data:`MASTER_PARAMETERS`.
CHANNEL_EDIT_IDS: Optional[Dict[str, int]] = None


class EditGate:
    """Whether writes to the unit are allowed, and what to say about it.

    Locked by default. The family's ``--allow-write`` starts it armed, and
    ``w`` toggles it in the browser; either way the legend shows the state
    so the answer to "why did my edit not send?" is on screen rather than in
    a keybinding manual.
    """

    def __init__(self, *, armed: bool = False) -> None:
        self.armed = armed

    def toggle(self) -> bool:
        self.armed = not self.armed
        return self.armed

    def describe(self) -> str:
        return "write gate ARMED" if self.armed else "write gate locked"

    def refuse(self, what: str) -> str:
        """The message for an edit refused because the gate is locked."""
        return (
            f"{what} not sent: the write gate is locked. Press w to arm it, "
            f"or start with --allow-write."
        )


@dataclass
class EditLog:
    """What was sent, in order, so an edit can be reversed.

    Undo sends the *previous* value back, which needs the old value recorded
    before the new one goes out -- not read back afterwards, because a write
    that failed to land has nothing to read.
    """

    changes: List[Tuple[int, int, int]] = field(default_factory=list)

    def record(self, parameter_id: int, old: int, new: int) -> None:
        self.changes.append((parameter_id, old, new))

    @property
    def pending(self) -> int:
        return len(self.changes)

    def take(self, count: int) -> List[Tuple[int, int, int]]:
        """The last ``count`` changes, newest first, and drop them."""
        if count <= 0:
            return []
        taken = list(reversed(self.changes[-count:]))
        del self.changes[-count:]
        return taken

    def clear(self) -> None:
        self.changes.clear()


class MasterEditor:
    """The rules around a master edit, with no I/O in them.

    Deliberately pure: the gate, the range check, the log and the sentences
    are what p2ked has to get right, and they are testable without a unit on
    the desk. The wire itself is the app's, on a worker, in the shape every
    other MIDI operation in p2ked uses -- see
    ``P2kedApp._apply_master_edit``.

    The verify step is not politeness. A Proteus ignores a request it cannot
    serve rather than refusing it, so a silent failure looks exactly like a
    success until something reads the value back -- which is why
    :meth:`finish` takes the value read *after* the write and reports a
    disagreement rather than assuming the write landed.
    """

    def __init__(
        self,
        gate: Optional[EditGate] = None,
        log: Optional[EditLog] = None,
    ) -> None:
        self.gate = gate if gate is not None else EditGate()
        self.log = log if log is not None else EditLog()

    def allow(self, parameter: MasterParameter, value: int) -> Optional[str]:
        """Why this edit must not be sent, or ``None`` if it may be.

        A locked gate and an out-of-range value are both things a reader
        does, not failures of the program, so both come back as a sentence
        rather than an exception.
        """
        if not self.gate.armed:
            return self.gate.refuse(f"{parameter.label}")
        if not parameter.low <= value <= parameter.high:
            return (
                f"{parameter.label} must be {parameter.low}-{parameter.high}, "
                f"and {value} is not"
            )
        return None

    def finish(
        self,
        parameter: MasterParameter,
        value: int,
        *,
        before: Optional[int],
        after: Optional[int],
    ) -> Tuple[bool, str]:
        """Record a sent edit, and say what the read-back found.

        ``after`` is what the unit reported *after* the write. ``None``
        means the read failed, which is said rather than rounded to a
        success or a failure.
        """
        if after is None:
            return False, (
                f"{parameter.label} = {value} was sent, but the read-back "
                f"failed; nothing is logged, so undo cannot restore it"
            )
        if after != value:
            # A unit that ignores a request rather than refusing it is
            # exactly this case, and it is indistinguishable from a slow
            # reply without reading back.
            return False, (
                f"{parameter.label} did not take {value}: the unit still "
                f"reports {after!r}. It ignores a request it cannot serve "
                f"rather than refusing it -- check the mode, the device ID "
                f"and the channel."
            )
        self.log.record(
            parameter.parameter_id, value if before is None else before, value
        )
        return True, f"{parameter.label} = {value}"

    def undo_plan(self, count: int) -> List[Tuple[int, int]]:
        """Which ``(parameter id, value to send)`` to reverse, newest first.

        The plans are taken off the log as they are made, so an undo that
        fails halfway cannot be replayed twice on the next press.
        """
        return [(parameter_id, old) for parameter_id, old, _new in self.log.take(count)]

    def undo_report(self, results: List[Tuple[int, bool]]) -> str:
        """One sentence over several undo attempts."""
        failed = [parameter_id for parameter_id, ok in results if not ok]
        undone = len(results) - len(failed)
        if not undone and not failed:
            return "nothing to undo"
        if failed:
            return (
                f"undid {undone}; the unit rejected {len(failed)} "
                f"(parameters {', '.join(str(f) for f in sorted(failed))})"
            )
        return f"undid {undone} edit{'s' if undone != 1 else ''}"


def probe_channel_ids(
    read: Callable[[int], Optional[int]],
    *,
    low: int = 662,
    high: int = 1024,
) -> Dict[str, object]:
    """Look for the per-channel multimode parameter IDs, read-only.

    **This does not write anything.** It reads a range of parameter IDs and
    reports which ones answer, so a human on a session with a unit can
    establish what p2ked refuses to guess. It does not try to match them to
    the dump's fields on its own: a value that happens to agree once is not
    a mapping, and this is a finding to be recorded, not an assignment to be
    made automatically.

    The default range is the first block after the master parameters p2ked
    already knows (641-661 is the master arpeggiator), which is where the
    family's numbering would put them -- that is a *hint about where to
    look*, and the hint is labelled as one.
    """
    answered: List[int] = []
    for parameter_id in range(low, high):
        if read(parameter_id) is not None:
            answered.append(parameter_id)
    return {
        "low": low,
        "high": high,
        "answered": answered,
    }
