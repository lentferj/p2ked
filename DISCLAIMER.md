<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# Disclaimer

## Some of this is verified against hardware. Most of it is not.

**Read which is which before trusting a byte.**

Verified on **2026-09-12** against a real Proteus 2000 (device ID 0, reached
over a DIN cable behind a U6MIDI Pro interface):

- **Port discovery and the Universal Identity Request.** The unit answered a
  broadcast request with manufacturer `18h`, and the reply carried the
  device ID it is set to.
- **The System Exclusive frame layout** -- `F0 18 0F <dev> 55 …` -- and the
  14-bit LSB-first encoding, confirmed together by every exchange below
  working at all.
- **Hardware Configuration (`0Ah`/`09h`).** Parsed as written: 512 user
  presets and four SIMMs with their IDs, preset counts and instrument
  counts.
- **Generic Name (`0Ch`/`0Bh`).** Preset names came back for the user banks
  and every fitted ROM, and matched the catalog character for character.
- **That a SIMM ID is the ROM's Bank Select MSB** -- p2ked's one guess, now
  confirmed for three ROMs. See below.

**Not verified.** Everything else, including:

- **Parameter edit and request**, and the whole preset-dump family. The
  encoders exist and are tested against the demo device; nothing has been
  sent to a unit.
- **The checksum rule.** Still ambiguous, still worked around by sending
  `7Fh`. No checksummed message has been captured from a unit.
- **`SEND_GAP`.** Still a guess. It has not failed at 10 ms across a few
  thousand name requests, which is evidence it is not too *short* and none
  at all that it is near right.
- **Every ROM but the four fitted here.** The table's other fifteen rows are
  transcribed, not confirmed.

That still makes this a **prototype**. What changed on 2026-09-12 is that
the read path is now known to work against one unit, not merely to be
self-consistent.

### Why the test suite is still not evidence

p2ked has a test suite that passes, and `p2ked/demo.py` — a stand-in device
that answers its messages. **For anything in the unverified list above,
neither is evidence that the protocol is right.** The demo device was written from the same document, by the same
reader, at the same time as the code it answers. Two things that share a
misreading agree with each other perfectly.

This is not a hypothetical concern. The sibling rxved project shipped a
device-ID conversion that was wrong for every value it was ever given, with
a green suite, for as long as it took to plug in a synthesizer — because
every synthetic test agreed with the same wrong convention, and because the
XV-2020 answers a wrong device ID with **silence**, which is
indistinguishable from a cable fault.

What the tests *do* establish is internal consistency: that the encoder and
decoder agree, that ranges are enforced, that a signed value survives a
round trip, that the cursor never sends MIDI. Those are worth having. They
are a different claim from "this works".

### The specific things most likely to be wrong

- **The SIMM ID to ROM mapping — RESOLVED 2026-09-12.** p2ked assumed a
  reported SIMM ID is that ROM's Bank Select MSB. A unit reporting IDs 4, 65
  and 67 returned, for each, the preset names this project's catalog holds
  for the ROM at that MSB. Three of nineteen ROMs, so a mismatch elsewhere
  is still possible — but it is no longer a guess.
- **The checksum rule.** The specification says "1 Byte XOR(1's complement)
  of the sum of the DATA bytes", which describes two different operations.
  p2ked implements the plain XOR reading and sends `7Fh` — "ignore
  checksum", which the specification explicitly permits — rather than guess
  on the messages that carry the field.
- **`SEND_GAP`.** A guess, not a measurement. E-MU gives no inter-message
  timing at all. A name sweep of a 1024-preset ROM spends a thousand of
  these.
- **Preset counts per ROM.** Taken from the instrument-definition files,
  which describe *banks*, not populated presets. For the four ROMs fitted
  here the unit's own counts agree; for the rest they are unconfirmed. A
  unit answers a request past the end of a ROM with the name
  `(not installed)` rather than ignoring it, so p2ked can now tell an
  absent preset from a dead cable — see `p2k.roms.is_absent`.
- **Everything else.** The list above is what is known to be uncertain, not
  the extent of the uncertainty.

## What p2ked does to the instrument

**It does not write to the unit's memory.** There is no code in `p2k/` that
stores a preset, renames anything, or erases anything.

It plays the instrument in exactly one place, and that place says so:
`Enter` in the TUI and `p2kcli select` send Bank Select and a Program
Change, which changes the sound immediately and audibly.

**Reading names makes no sound**, and that is a real property of this
machine rather than a claim about care taken. A Proteus answers a Generic
Name Request for any preset in any fitted ROM without selecting it. The
sibling rxved has no such message and must select each patch in turn to
learn its name — which is why that project has confirmation prompts around
an operation p2ked performs silently and without asking.

## AI assistance and human authorship

p2ked was created by its **human author, Jan Lentfer
(<jan.lentfer@web.de>)**, working with Anthropic's **Claude**, and follows
the pattern of the author's sibling **rxved**, **eosed**, **s3ked**,
**k2kremote** and **mpc2emu** projects.

**The ideas and the direction are human.** Targeting the Proteus 2000,
building a browser rather than an editor, modelling it on the sibling
projects, and every source that made the data possible — E-MU's System
Exclusive specification, the operation manual and the instrument-definition
files — came from the human author.

**Claude assisted with the execution:** transcribing the System Exclusive
frame layout and command set into `p2k/messages.py`, deriving the ROM and
bank table from the instrument-definition files, writing the transport, the
demo device, the CLI, the Textual browser, the tests and this
documentation.

## No warranty

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
more details.
