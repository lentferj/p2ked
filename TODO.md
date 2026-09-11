<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# TODO

## Status, 2026-09-11 (first session)

A prototype exists and runs: protocol codec, ROM/bank table, transport,
demo device, CLI, Textual browser, 70 tests, 8832 catalogued names.

**Nothing has been tested against hardware, because there is none.** Every
item below that says "unverified" means exactly that, and the list is not
exhaustive — see DISCLAIMER.md.

---

## 1. Everything is unverified

**Status:** open, and blocked on a Proteus 2000.

The first session with a unit should, in this order:

1. `p2kcli ports`, then `p2kcli status` — does it answer an Identity
   Request at all, and with what?
2. `p2kcli config` — does the Configuration response parse, and are the
   SIMM IDs what item 2 assumes?
3. `p2kcli --port ... names USER-0` — do names come back, and do they
   match what the unit's display shows?
4. Only then anything that makes a sound.

Until step 1 succeeds nothing else is worth attempting: silence is this
protocol's answer to every kind of mistake.

## 2. SIMM ID versus Bank Select MSB

**Status:** open. **The likeliest thing to be wrong.**

p2ked assumes a SIMM ID reported in the Configuration response is that
ROM's Bank Select MSB. Nothing in E-MU's specification says so, and no
document to hand lists SIMM IDs at all.

Resolved by one `p2kcli config` against a unit with a known ROM fitted: if
the reported ID is the ROM's documented MSB, the assumption holds.

If it does not, `roms.rom_for_simm_id` becomes a transcribed table and
`bridge.rom_id_for` needs the real mapping. Everything else survives.

## 3. The checksum rule is ambiguous

**Status:** open, worked around.

The specification says "1 Byte XOR(1's complement) of the sum of the DATA
bytes", which describes two different operations: an XOR *of* the bytes, or
the one's complement *of their sum*. `messages.checksum` implements the
plain XOR reading; p2ked sends `7Fh` ("ignore checksum", explicitly
permitted) on messages that carry the field rather than guess.

Resolved by capturing a checksummed message *from* a unit and testing both
readings against it.

## 4. `SEND_GAP` is a guess

**Status:** open, blocked on hardware.

E-MU gives no inter-message timing at all; the only guidance is to keep a
message under 244 data bytes. `SEND_GAP` is the sibling projects'
conservative default. A name sweep of a 1024-preset ROM spends a thousand
of them, so this is worth measuring early.

## 5. Preset counts are bank counts

**Status:** open, cosmetic.

The instrument-definition files describe *banks*, not populated presets, so
`roms.ROMS` gives every ROM `banks * 128`. A ROM whose last bank is partly
empty will show rows that name nothing. Deliberate: an over-long bank shows
empty rows, a short one hides presets, and a hidden preset is not
discoverable by the person looking for it.

A unit's Configuration response reports the real per-SIMM preset count and
could correct this at runtime.

## 6. Only presets are browsable

**Status:** open. A feature, not a defect.

`Generic Name Request` also names instruments, arps, setups, demos and
riffs (`messages.ObjectType`). p2ked asks only about presets. Instruments
in particular would be worth browsing — they are the raw material presets
are built from.

## 7. No editing, and no plan to add it casually

**Status:** deliberate.

p2ked reads. The specification documents parameter edits and preset dumps,
and `messages.parameter_edit` exists and is tested, but nothing calls it.
If editing is added, CLAUDE.md's hardware rules apply: arm-then-fire, never
key-bound, back up first, verify by reading back.

## 8. The other documents in the source folder are unread

**Status:** open.

`~/Dokumente/SYNTHS/Proteus 2000` also holds the Operation Manual, a
parameter tree PDF, riff and drum-map text files, ROM and SIMM images, a
flash-analysis archive, and `prodatum` (an existing open-source editor).
Only the System Exclusive specification and the instrument-definition files
have been read. The parameter tree is the obvious next source if p2ked ever
grows an editor, and prodatum is an independent reading of the same
protocol — the best available cross-check short of hardware.
