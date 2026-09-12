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

## 1. The read path — DONE 2026-09-12

**Status:** done. First hardware session; see RESOLUTION_NOTES §7.

Identity, Hardware Configuration and Generic Name all worked as written
against a real Proteus 2000. Nothing was selected and nothing made a sound.
What remains unverified is listed in DISCLAIMER.md: parameter edits, preset
dumps, the checksum rule and `SEND_GAP`.

**Superseded plan, kept because the order was right:**

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

## 2. SIMM ID versus Bank Select MSB — RESOLVED 2026-09-12

**Status:** confirmed. A SIMM ID **is** the ROM's Bank Select MSB.

A unit reporting SIMM IDs 4, 65 and 67 returned, for each, preset names
matching p2ked's catalog for the ROM at that MSB — character for character.
Three of nineteen ROMs, so a mismatch on some other board remains possible,
but this is no longer a guess and the interface no longer calls it one.

A second, independent check agrees: `ProteusBridge.installed_roms()` asks
each ROM ID for preset 0 and reads the reply, and its answer matches the
Configuration response exactly.

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

**Status:** open, and now fixable. A unit answers past the end of a ROM with
the name `(not installed)` rather than going silent, so the real extent of
every fitted ROM can be found by asking — silently, and without a timeout.
`roms.is_absent` recognises it and `read_bank_names` drops those rows; using
it to *correct* the table at runtime is the remaining work.

The instrument-definition files describe *banks*, not populated presets, so
`roms.ROMS` gives every ROM `banks * 128`. A ROM whose last bank is partly
empty will show rows that name nothing. Deliberate: an over-long bank shows
empty rows, a short one hides presets, and a hidden preset is not
discoverable by the person looking for it.

A unit's Configuration response reports the real per-SIMM preset count and
could correct this at runtime.

## 5b. ROM 14 has no name

**Status:** open, needs the front panel.

A unit reported SIMM ID 14 with 640 presets, and it answers name requests
for all 640. No instrument-definition file to hand covers MSB 14, so p2ked
has the numbers but not the ROM's own name, and System Exclusive has no
object type to ask for one. It is in the table as "ROM 14 (unidentified)".

The unit's own display knows. Whoever has the unit can say.

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
