<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# Disclaimer

## Nothing here has been tested against hardware

**Read this before trusting a single byte.**

There is no Proteus 2000 attached to the machine p2ked was written on. Every
message it builds, every offset, every assumption about how the instrument
answers, comes from reading E-MU's *Proteus Family MIDI System Exclusive
Specification* v2.2 and the Proteus 2000 Operation Manual. Not one of them
has been sent to a unit.

That makes this a **prototype**, and the word is meant literally: it is a
careful reading of a document, expressed as code that runs. It is not a
program known to work.

### Why the test suite is not evidence

p2ked has a test suite that passes, and `p2ked/demo.py` — a stand-in device
that answers its messages. **Neither is evidence that the protocol is
right.** The demo device was written from the same document, by the same
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

- **The SIMM ID to ROM mapping.** p2ked assumes a SIMM ID reported in the
  Configuration response is that ROM's Bank Select MSB. Nothing in E-MU's
  specification says so; no document here lists SIMM IDs at all. Every
  screen that shows a ROM name derived this way labels it a guess, and
  `p2k.roms.rom_for_simm_id` says so in its docstring, with a test that the
  wording stays. **If one thing here is wrong, it is probably this.**
- **The checksum rule.** The specification says "1 Byte XOR(1's complement)
  of the sum of the DATA bytes", which describes two different operations.
  p2ked implements the plain XOR reading and sends `7Fh` — "ignore
  checksum", which the specification explicitly permits — rather than guess
  on the messages that carry the field.
- **`SEND_GAP`.** A guess, not a measurement. E-MU gives no inter-message
  timing at all. A name sweep of a 1024-preset ROM spends a thousand of
  these.
- **Preset counts per ROM.** Taken from the instrument-definition files,
  which describe *banks*, not populated presets. A ROM whose last bank is
  partly empty will show rows that name nothing.
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
