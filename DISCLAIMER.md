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
- **Setup Dump (`1Dh`/`1Ch`).** All 32 channels decoded, and the result
  matches the owner's sequencer template — which was written from neither.
  The channel block is found by structural search, because the published
  layout is both self-contradictory and older than this unit's firmware.
- **The Setup Dump's master blocks.** All 82 master parameter values, and
  the two undocumented blocks after the channels. Not read from a layout:
  every value was read a second time as an individual parameter and
  compared. See RESOLUTION_NOTES §10 for what is established and what is
  not.
- **Parameter Value Request (`02h` with sub-command `01h`).** Around 120
  IDs asked for; the ones that exist answer, the ones that do not are
  silent, and signed values come back signed.
- **That a SIMM ID is the ROM's Bank Select MSB** -- p2ked's one guess, now
  confirmed for three ROMs. See below.

Verified again on **2026-10-02** against the same unit, adding:

- **Timing.** A Generic Name Request takes ~18 ms to answer, which is what
  a name sweep costs. `SEND_GAP` is hidden inside it, and no gap down to
  0.05 ms produced a single wrong or missing name. See below and
  RESOLUTION_NOTES §11.
- **Preset extents.** All four fitted ROMs' preset counts match `roms.py`
  exactly, as does user memory.
- **That `roms_from_config` and `installed_roms` agree.** Two independent
  readings of which ROMs are fitted -- one Configuration request against
  twenty name probes -- return identical answers, 16.5 ms against 370.7 ms.

**Not verified.** Everything else, including:

- **Parameter edit**, and the whole preset-dump family. The encoders exist
  and are tested against the demo device; nothing that changes a unit has
  been sent to one. (The parameter *request* is verified — see above. The
  edit is the half that writes, and stays untested on purpose.)
- **The checksum rule.** Still ambiguous, still worked around by sending
  `7Fh`. No checksummed message has been captured from a unit.
- **`SEND_GAP`.** **Measured 2026-10-02**, and deliberately left at 10 ms.
  The unit takes ~18 ms to answer a name request, and the gap is hidden
  inside that: setting it to zero changes nothing measurable. No failures
  at any gap down to 0.05 ms, so 10 ms is conservative rather than
  necessary — kept because there is no measured reason to spend the
  margin. One unit, one firmware, one interface; see RESOLUTION_NOTES §11
  and `tools/measure_send_gap.py`.
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
- **`SEND_GAP`.** RESOLVED 2026-10-02. E-MU gives no inter-message timing at
  all, and it turns out not to matter: the unit's ~18 ms response time
  dominates, so the gap is neither a bottleneck nor a risk at any value
  tried. Left at 10 ms, measured, and re-derivable with
  `tools/measure_send_gap.py`.
- **Preset counts per ROM.** RESOLVED for the four fitted, 2026-10-02: the
  unit's own per-SIMM counts match `roms.py` exactly for all of them and for
  user memory. The other fifteen rows still come from the
  instrument-definition files, which describe *banks*, not populated
  presets.
- **`(not installed)` is not universal.** Three of the four fitted ROMs
  answer a request past their last preset with that name; **Composer does
  not** — it returns `   :default` indefinitely (measured 2026-10-02).
  p2ked is unaffected, because it only ever asks about slots its own table
  says exist, but the sentinel is a courtesy and not a guarantee. See
  TODO.md item 41.
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
