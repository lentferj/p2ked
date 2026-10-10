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

**Two routes, one gate.** A master parameter is written by its own
parameter ID; a per-channel value is written by *writing the setup dump
back*, which the specification licenses: the unit "receive[s] and
understand[s] the old setup dump" (spec p. 29). See
:data:`CHANNEL_EDIT_HINT` for the sentence that says so to a user, and
:func:`mutate_channel` for the mutation the route is built on.

The second route is not a way around the project's rule that
**a parameter ID is never invented**. It writes the dump's own field
positions -- the nine the parser found by structural search (§8) and the
encoder puts back where it found them -- so no ID is invented and no number
nobody knows is addressed. :data:`CHANNEL_EDIT_IDS` stays ``None`` and
:func:`probe_channel_ids` stays the read-only probe it was, because the
ID-based route remains an *alternative* worth having on a real unit: one
frame per field instead of a ~1 KB whole-setup write. Establishing those IDs
needs a unit on the desk -- ``docs/TODO`` item 47.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from p2k import messages as params

__all__ = [
    "CHANNEL_EDIT_HINT",
    "CHANNEL_EDIT_IDS",
    "CHANNEL_FIELDS",
    "FX_PARAMETERS",
    "MASTER_BY_ID",
    "MASTER_PARAMETERS",
    "SOUND_FIELD",
    "ChannelChange",
    "ChannelField",
    "ChannelLog",
    "EditGate",
    "EditLog",
    "MasterEditor",
    "MasterParameter",
    "channel_label",
    "channel_values",
    "fields_of",
    "mutate_channel",
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

#: What a per-channel *edit* writes, and the sentence that says so.
#:
#: It is a sentence rather than a disabled control because the reason
#: matters more than the missing feature, and it used to say the opposite
#: thing -- that per-channel edits were not offered at all. They are now,
#: and by a route no document needed to number:
#:
#: * **The write is a whole Setup Dump.** The specification's own words for
#:   what a command station does with the old format are that it
#:   "receive[s] and understand[s] the old setup dump" (spec p. 29), so the
#:   unit takes ``1Ch`` back. Every other byte is the one the unit just
#:   sent, because the dump is read live first and re-encoded unchanged
#:   except for the edited field -- the round trip is byte-exact and
#:   ``tests/test_messages.py``'s ``TestSetupDumpEncoder`` proves it.
#: * **The gate applies, and the read-back verifies.** A per-channel edit
#:   goes through the same :class:`EditGate` and the same read-the-field-
#:   back-again check any other edit does.
#: * **What it does not do is invent a parameter ID.** This route writes
#:   the dump's own field positions, not an ID, so the rule survives
#:   unchanged; the ID-based alternative is still what
#:   ``docs/TODO`` item 47's read-only probe is for.
CHANNEL_EDIT_HINT = (
    "A per-channel edit writes the whole setup dump: the unit “receive[s] "
    "and understand[s] the old setup dump” (spec p. 29), so p2ked reads the "
    "live dump, changes the one field and sends the dump back. The write "
    "gate applies and the field is read back to verify it -- every other "
    "byte is the one the unit just sent (tests/test_messages.py's "
    "TestSetupDumpEncoder). No parameter ID is invented: this writes the "
    "dump's own field positions. The first unit contact is `make "
    "test-hardware`'s unmodified-dump round trip, and until it has run no "
    "unit has received one. The ID-based alternative still needs "
    "docs/TODO item 47's probe."
)

#: **Where this sentence is shown.** It lives here because the write path
#: lives here, but the screen that draws it is ``p2ked/multi.py`` -- and that
#: file held a copy of its own until the UI agent's pass, one that says the
#: now-false thing ("Per-channel edits are not offered"). Until the import
#: there is swapped for this one, a reader of *this* sentence is reading the
#: truth about the mechanism and not the sentence on the screen. The swap is
#: one line -- ``from p2ked.masteredit import CHANNEL_EDIT_HINT`` -- and it
#: keeps both strings that the tests assert on, so nothing else moves.

#: The field a sound selection is written as. One entry on the undo timeline
#: for one dump write, because the unit takes ``rom_id``, ``preset`` and
#: ``bank_map`` together: aiming a channel at a sound is one operation, and
#: three ``z`` presses that each restore a third of a sound would not put
#: back the sound anybody had.
SOUND_FIELD = "sound"

#: The dump's nine per-channel fields, in the order the dump carries them,
#: with the range each is documented to take.
#:
#: Transcribed, not read: the field *order* is confirmed against hardware
#: (§8) and the *ranges* are the specification's own (RESOLUTION_NOTES §12,
#: "The nine per-channel parameters"). The range check that uses them is
#: :meth:`MasterEditor.allow_channel_field`, and it is the same style of
#: refusal :meth:`MasterEditor.allow` gives a master parameter.
CHANNEL_FIELDS: Dict[str, ChannelField] = {}


@dataclass(frozen=True)
class ChannelField:
    """One of the nine, with the range it may be set to.

    ``low`` and ``high`` are inclusive and in the **signed** values the wire
    uses: ``mix_output`` runs -1 to 2 and ``arp`` -2 to 1, so an unsigned
    reading of either turns -1 into 16383, which no range check catches.
    """

    name: str
    low: int
    high: int

    def holds(self, value: int) -> bool:
        """Whether ``value`` is inside the inclusive range, signed."""
        return self.low <= value <= self.high


for _name, _low, _high in params.CHANNEL_PARAMETERS:
    CHANNEL_FIELDS[_name] = ChannelField(_name, _low, _high)
del _name, _low, _high


def fields_of(field: str) -> Tuple[str, ...]:
    """The dump's own field names one edit touches, in dump order.

    ``"sound"`` is the one that is not a field: it is ``preset``,
    ``bank_map`` and ``rom_id`` together, ordered as the dump carries them
    rather than in the order a caller named them, because the values in a
    :class:`ChannelChange` are held in this order.
    """
    if field == SOUND_FIELD:
        return (
            "preset",
            "bank_map",
            "rom_id",
        )
    return (field,)


def channel_label(channel: int, field: str) -> str:
    """What to call the thing being edited, 1-based like the unit's display.

    ``channel`` is the wire's own 0-based number -- the same one
    :attr:`p2k.messages.ChannelState.channel_display` adds one to -- so a
    sentence here names the channel the front panel shows.
    """
    return f"channel {channel + 1} {field}"


def channel_values(
    dump: params.SetupDump, channel: int, names: Sequence[str]
) -> Optional[Tuple[int, ...]]:
    """The values ``names`` hold on ``channel``, or ``None`` if it is absent.

    ``None`` rather than a tuple of zeros: a dump that does not carry the
    channel says so, and a read-back of zeros would look like a write that
    landed on an empty slot.
    """
    entry = dump.channel(channel)
    if entry is None:
        return None
    return tuple(getattr(entry, name) for name in names)


def mutate_channel(
    dump: params.SetupDump, channel: int, values: Mapping[str, int]
) -> params.SetupDump:
    """The same setup with ``values`` written into one channel. Pure.

    A **new** :class:`p2k.messages.SetupDump`, with every other byte the one
    that came in. That is the whole mechanism, and it is worth being exact
    about why: the dump is the only route to a per-channel value no document
    numbers, and the specification licenses it -- the unit "receive[s] and
    understand[s] the old setup dump" (spec p. 29). So a per-channel edit is
    *read the live dump, change the one field, send the dump back*, and the
    other 96-and-count bytes are the ones the unit sent a moment earlier.

    It is built by replacing the one :class:`p2k.messages.ChannelState`
    rather than by editing the original, because a caller that mutated the
    dump in place would have to re-read it to know what it used to hold --
    which is the whole value of the operation. ``ChannelState`` has no
    ``__eq__`` (it is a ``__slots__`` value object), so "every other channel
    is unchanged" is a statement about values and not about identity, and
    this rebuilds every field from the original's own rather than relying on
    a copy anyway.

    Raises :class:`p2k.messages.ProtocolError` -- does not guess -- for a
    channel the dump does not have and for a field name that is not one of
    the nine. The *range* of a value is not checked here; that is
    :meth:`MasterEditor.allow_channel_field`'s, and it has to be a refusal a
    reader sees rather than an exception.
    """
    entry = dump.channel(channel)
    if entry is None:
        raise params.ProtocolError(
            f"this setup carries {len(dump.channels)} channels "
            f"(0-{len(dump.channels) - 1}) and channel {channel} is not one "
            f"of them"
        )
    unknown = [name for name in values if name not in CHANNEL_FIELDS]
    if unknown:
        raise params.ProtocolError(
            f"p2ked writes nine per-channel fields and "
            f"{', '.join(sorted(unknown))} is not one of them"
        )
    replaced = params.ChannelState(entry.channel)
    for name, _low, _high in params.CHANNEL_PARAMETERS:
        # Rebuilt from the original's own value: a copy of the object would
        # do, but then a later edit of the copy would be an edit of the
        # channel the dump says the unit has.
        setattr(
            replaced,
            name,
            values[name] if name in values else getattr(entry, name),
        )
    channels = tuple(
        replaced if entry.channel == other.channel else other for other in dump.channels
    )
    return params.SetupDump(
        dump.name,
        channels,
        channel_count=dump.channel_count,
        parameters_per_channel=dump.parameters_per_channel,
        offset=dump.offset,
        payload_size=dump.payload_size,
        master=dump.master,
        trailing=dump.trailing,
        header_counts=dump.header_counts,
        undecoded=dump.undecoded,
    )


@dataclass(frozen=True)
class ChannelChange:
    """One per-channel edit, as the undo timeline sees it.

    It carries its data, which is the difference between it and
    :class:`p2ked.app.EditChange`: an undo of one of these is a *whole setup
    dump* write putting ``before`` back, not one parameter ID and value, so
    the entry has to hold the channel, the field and the value rather than
    look a second one up in a log.

    ``before`` and ``after`` are the value the field held and now holds --
    and are the tuple ``(preset, bank_map, rom_id)`` when :attr:`field` is
    :data:`SOUND_FIELD`, in the order :attr:`fields` gives. One entry for a
    sound rather than three: the unit takes the three fields together, so
    three entries would let ``z`` restore a third of a sound and call it
    undone.
    """

    channel: int
    field: str
    before: int | Tuple[int, ...]
    after: int | Tuple[int, ...]

    @property
    def fields(self) -> Tuple[str, ...]:
        """The dump's field names this change touched, in dump order."""
        return fields_of(self.field)

    @property
    def restore_values(self) -> Tuple[int, ...]:
        """The values an undo sends back, in :attr:`fields` order."""
        before = self.before
        return before if isinstance(before, tuple) else (before,)

    @property
    def sent_values(self) -> Tuple[int, ...]:
        """The values that were written, in :attr:`fields` order."""
        after = self.after
        return after if isinstance(after, tuple) else (after,)

    @property
    def restore(self) -> Dict[str, int]:
        """The mutation an undo makes: ``{field name: previous value}``."""
        return dict(zip(self.fields, self.restore_values, strict=True))

    @property
    def label(self) -> str:
        """ "channel 6 volume", 1-based like the unit's own display."""
        return channel_label(self.channel, self.field)

    @property
    def spelled(self) -> str:
        """The value as a sentence spells it, so a report reads as words."""
        if isinstance(self.after, tuple):
            return ", ".join(
                f"{name} {value}"
                for name, value in zip(self.fields, self.after, strict=True)
            )
        return str(self.after)


@dataclass
class ChannelLog:
    """The per-channel edits, newest last, so ``z`` can put one back.

    Its own log rather than a widened :class:`EditLog`, because the plan the
    two produce are different shapes: the master one answers
    ``(parameter id, value)`` and this one answers a whole-dump write of one
    channel's previous value. Two logs that answer two questions are two
    logs; one that answered both would have to be tagged, and every caller
    would have to check the tag.

    The app keeps a single timeline over both, because ``z`` reverses
    whichever came last -- see :class:`p2ked.app.EditChange`.
    """

    changes: List[ChannelChange] = field(default_factory=list)

    def record(self, change: ChannelChange) -> None:
        self.changes.append(change)

    @property
    def pending(self) -> int:
        return len(self.changes)

    def take(self, count: int) -> List[ChannelChange]:
        """The last ``count`` changes, newest first, and drop them."""
        if count <= 0:
            return []
        taken = list(reversed(self.changes[-count:]))
        del self.changes[-count:]
        return taken

    def clear(self) -> None:
        self.changes.clear()


#: Parameter IDs for the per-channel multimode parameters, or ``None``.
#:
#: **Not established, and still deliberately not guessed.** The Setup Dump
#: carries all nine per channel positionally, so reading them is solved;
#: setting one *by ID* needs its parameter ID, and no document to hand lists
#: them. Per-channel values are written now by the dump route above -- see
#: :data:`CHANNEL_EDIT_HINT` -- so this is no longer what blocks the feature;
#: it is the alternative that would cost one small frame per field instead
#: of a ~1 KB whole-setup write, and :func:`probe_channel_ids` is the
#: read-only way to establish them on a real unit. Item 47.
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
    """The rules around an edit, with no I/O in them.

    Deliberately pure: the gate, the range check, the log and the sentences
    are what p2ked has to get right, and they are testable without a unit on
    the desk. The wire itself is the app's, on a worker, in the shape every
    other MIDI operation in p2ked uses -- see ``P2kedApp._apply_master_edit``
    for a master parameter and ``P2kedApp.action_edit_channel`` for a
    per-channel one.

    The verify step is not politeness. A Proteus ignores a request it cannot
    serve rather than refusing it, so a silent failure looks exactly like a
    success until something reads the value back -- which is why
    :meth:`finish` takes the value read *after* the write and reports a
    disagreement rather than assuming the write landed.

    **Two kinds of edit, one gate.** A master parameter is one ID and one
    value on the wire; a per-channel field is a whole setup dump write (see
    :func:`mutate_channel`). They share the gate, the read-back discipline
    and the undo timeline, and they differ only in the shape of the write
    and of the plan ``z`` makes -- which is why they are two logs here and
    one timeline in the app.
    """

    def __init__(
        self,
        gate: Optional[EditGate] = None,
        log: Optional[EditLog] = None,
        channel_log: Optional[ChannelLog] = None,
    ) -> None:
        self.gate = gate if gate is not None else EditGate()
        self.log = log if log is not None else EditLog()
        self.channel_log = channel_log if channel_log is not None else ChannelLog()

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

        Master edits only: the plan for a per-channel one is a
        :class:`ChannelChange` and a whole-dump write, and it is
        :meth:`channel_undo_plan` that hands that out. Mixing the two in one
        list would mean an entry type every caller had to test for.
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

    # --- the per-channel route -------------------------------------------

    def allow_channel_field(
        self, channel: int, field: str, value: int
    ) -> Optional[str]:
        """Why this per-channel edit must not be sent, or ``None`` if it may.

        The per-channel half of :meth:`allow`, in the same style: a locked
        gate and a value outside the field's transcribed range are both
        things a reader does, so both are a sentence and not an exception.

        The gate comes first for the reason it does there -- an armed gate
        must not be the difference between a refusal and a write -- and the
        channel itself is *not* checked here: whether this setup has that
        many channels is a fact about the dump, which is the worker's to
        read. :meth:`decline_channel` refuses it there, before anything is
        sent.
        """
        if not self.gate.armed:
            return self.gate.refuse(channel_label(channel, field))
        entry = CHANNEL_FIELDS.get(field)
        if entry is None:
            return (
                f"{field!r} is not one of the nine per-channel fields p2ked "
                f"writes: {', '.join(CHANNEL_FIELDS)}"
            )
        if not entry.holds(value):
            return (
                f"channel {channel + 1} {field} must be {entry.low}-{entry.high}, "
                f"and {value} is not"
            )
        return None

    def allow_channel_sound(
        self,
        channel: int,
        *,
        rom_id: int,
        preset: int,
        bank_map: int,
    ) -> Optional[str]:
        """Why this sound selection must not be sent, or ``None`` if it may.

        Three fields in one operation, one refusal at the first that is out
        of range: the unit takes ``rom_id``, ``preset`` and ``bank_map``
        together, so a channel aimed at a sound is aimed at all three or at
        none. The order is the dump's own, so the field named is the one a
        reader would find first in the channel detail screen.
        """
        for name, value in (
            ("preset", preset),
            ("bank_map", bank_map),
            ("rom_id", rom_id),
        ):
            refusal = self.allow_channel_field(channel, name, value)
            if refusal is not None:
                return refusal
        return None

    def decline_channel(
        self, dump: params.SetupDump, channel: int, values: Mapping[str, int]
    ) -> Optional[str]:
        """Why this per-channel edit must not be sent *given this dump*.

        Called from the worker, once a dump is in hand, and it checks the
        two things :meth:`allow_channel_field` could not: whether the setup
        has that many channels, and whether the setup can be written back at
        all -- a dump p2ked could not fully decode is refused rather than
        rebuilt with the unread parts as zeros.

        No gate check: the caller has already made one, on the main thread,
        where a refusal is a sentence a reader sees rather than a result a
        worker hands back.
        """
        if dump.channel(channel) is None:
            return (
                f"channel {channel + 1} is not one of the "
                f"{len(dump.channels)} this setup has"
            )
        if dump.undecoded:
            return (
                "this setup was not fully decoded, so writing it back would "
                "drop what p2ked could not read: " + "; ".join(dump.undecoded)
            )
        unknown = [name for name in values if name not in CHANNEL_FIELDS]
        if unknown:  # pragma: no cover - the caller's tables are fixed
            return (
                f"{', '.join(sorted(unknown))} is not one of the nine "
                f"per-channel fields p2ked writes"
            )
        return None

    def finish_channel(
        self, change: ChannelChange, read_back: Optional[Tuple[int, ...]]
    ) -> Tuple[bool, str]:
        """Log a per-channel edit, and say what the read-back found.

        The per-channel half of :meth:`finish`, and the same discipline: the
        edit is logged only when the field reads back as the value that was
        sent, because an unverified one must not become undoable -- undoing
        it would send a dump nobody saw the unit accept.

        ``change`` is the record that *would* be logged, carrying the values
        read before the write; ``read_back`` is what the unit reported after
        it. ``None`` means the read failed, which is said rather than rounded
        to either answer.
        """
        sent = change.sent_values
        if read_back is None:
            return False, (
                f"{change.label} = {change.spelled} was sent, but the "
                f"read-back failed; nothing is logged, so undo cannot "
                f"restore it"
            )
        if tuple(read_back) != tuple(sent):
            # The unit ignores a request it cannot serve rather than
            # refusing it, which is exactly this case -- and here it is a
            # whole dump the unit took or disregarded.
            reported = ", ".join(
                f"{name} {value}"
                for name, value in zip(change.fields, read_back, strict=True)
            )
            return False, (
                f"{change.label} did not take {change.spelled}: the unit "
                f"still reports {reported}. It ignores a request it cannot "
                f"serve rather than refusing it -- check the mode and the "
                f"device ID."
            )
        self.channel_log.record(change)
        return True, f"{change.label} = {change.spelled}"

    def channel_undo_plan(self, count: int) -> List[ChannelChange]:
        """Which per-channel edits to reverse, newest first.

        The per-channel half of :meth:`undo_plan`, and it is a list of
        records rather than ``(id, value)`` pairs because the undo is a
        whole-dump write putting ``before`` back -- the entry carries the
        value and the field, so the plan is simply "these, newest first".
        """
        return self.channel_log.take(count)

    def channel_undo_report(self, results: Sequence[Tuple[ChannelChange, bool]]) -> str:
        """One sentence over several per-channel undo attempts.

        ``""`` when there is nothing to say, which is how a combined undo
        report leaves it out rather than saying "nothing to undo" beside a
        master edit it did undo.
        """
        undone = [change.label for change, ok in results if ok]
        rejected = [change.label for change, ok in results if not ok]
        if not undone and not rejected:
            return ""
        if not rejected:
            if len(undone) == 1:
                return f"undid {undone[0]}"
            return f"undid {len(undone)} channel edits: {', '.join(undone)}"
        return (
            f"undid {len(undone)} channel edit(s); the unit rejected "
            f"{len(rejected)} ({', '.join(rejected)})"
        )

    @property
    def channel_pending(self) -> int:
        """How many per-channel edits are undoable. Both counts, both kinds:
        this one and :attr:`log`'s :attr:`EditLog.pending`."""
        return self.channel_log.pending


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
