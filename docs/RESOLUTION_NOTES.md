<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# Resolution notes

*How* things were decided, and where every transcribed number came from.
`TODO.md` tracks *what* is still open.

---

## §1 — Sources, and which one wins

**1. E-MU, "Proteus Family Sound Modules MIDI System Exclusive
Specification", v2.2.** The authority for the wire format: frame layout,
manufacturer and product IDs, the editor designator byte, the command set,
the 14-bit LSB-first encoding, and the Configuration and Generic Name
messages. Everything in `p2k/messages.py` comes from here.

**2. The Cakewalk instrument-definition files** shipped for the family
(`P2k_All.ins`, `p2000.ins`, `E-mu.ins`). The only source to hand for ROM
names, their Bank Select allocation and preset names. `p2k/roms.py` and the
catalog come from here.

**3. The Proteus 2000 Operation Manual.** Cross-read for the bank model.

**The hardware outranks all three** for anything it can be asked. It has not
been asked anything: there is none. See DISCLAIMER.md.

---

## §2 — The wire format

```
F0 18 0F <dev> 55 <command> [<sub>] [data ...] [checksum] F7
```

- `18h` E-MU (a single-byte manufacturer ID), `0Fh` Proteus.
- `dev` 00h–7Eh, `7Fh` broadcast.
- `55h` the "Special Editor designator byte" — present in every editor
  message and no other, which is what lets `messages.parse` ignore E-MU's
  own non-editor traffic rather than misreading it.

Three differences from the Roland protocol the sibling rxved speaks, each a
place to be careful:

- **Values are 14 bits, two 7-bit bytes, least significant first.** Roland's
  addresses are big-endian base 128. A pair read the wrong way round here is
  a valid, plausible number that nothing downstream rejects.
- **Values are signed** (two's complement in 14 bits). Read unsigned, −1
  becomes 16383 and passes every range check.
- **The checksum is an XOR**, not a two's-complement sum over address and
  data — and `7Fh` means "ignore it". See TODO 3 on the wording's ambiguity.

**Addressing is by flat parameter ID**, not by a four-byte address into a
memory map. No base-128 carry to get wrong, and no structure either: an ID
means nothing except against the specification's list.

---

## §3 — The ROM and bank model

Selection is Bank Select MSB, Bank Select LSB, then Program Change:

- **MSB identifies the ROM**, fixed and unique across the family.
- **LSB is the bank within it**, up to 128 presets.
- **Program Change picks one of the 128.**

Derived from the instrument-definition files, whose `Patch[N]` keys encode
`N = MSB * 128 + LSB`. 19 ROMs, 69 banks, 8832 presets.

This is a far kinder arrangement than the XV-2020's expansion boards, where
every board shares one MSB and is given a *running* allocation of LSBs — a
list with a hole in it that must be transcribed and cannot be derived.

### The split that had to be got right

`N = MSB * 128 + LSB`. Doing it the other way round yields an MSB of 0–127
and an LSB of 0–1 for every ROM in the file: numbers that look like data
rather than like a mistake. Done once, in `extract_catalog.split_bank`,
with a test.

---

## §4 — A defect in the instrument-definition file

**Found 2026-09-11**, by a conflict check written before it was needed.

Orchestral Sessions Vol. 1 has three banks. The file's section headings say
so — `Bank 0 (1280)`, `Bank 1 (1281)`, `Bank 2 (1282)`, each with its own
128 names. But the `Patch[]` index at the other end of the file reads:

```
Patch[1280]=... Bank 0 (1280)
Patch[1281]=... Bank 1 (1281)
Patch[1281]=... Bank 2 (1282)      <- should be 1282
```

Taken at face value, bank 2's names land under bank 1's numbers and bank 2
disappears. Wrong names under right numbers, which nothing downstream can
detect.

**The section's own label wins**, and that choice is checkable rather than
a preference: 69 of the 70 sections carry a parenthesised bank number, no
two agree, and the index disagrees with exactly one of them. The label sits
next to the 128 names it describes; the index is a separate hand-maintained
list. The extractor reports the correction on stderr, and `p2k/roms.py`
carries the third bank the index would have hidden.

The general lesson, and the reason the check existed at all: **when two
parts of a document state the same fact, compare them.** The cost is a
dictionary and a printed note; the alternative is 128 presets silently
misnamed.

---

## §5 — Why `p2ked/demo.py` builds real frames

The demo device could have returned canned objects. It encodes and parses
actual System Exclusive instead, through `p2k.messages`.

The reason is that this project has no hardware, so the demo device is the
*only* thing the code is ever exercised against — and a fake that shares the
production code's assumptions proves nothing about them. Building real
frames at least establishes that the encoder produces what the decoder
expects, which is a real property. It establishes nothing about whether a
Proteus agrees, and DISCLAIMER.md says so.

---

## §6 — What p2ked can do that rxved cannot

`Generic Name Request` (`0Ch`) returns any preset's name in any fitted ROM
without selecting it. So:

- reading a bank's names makes **no sound** and needs no prompt;
- there is no equivalent of rxved's `scan_bank`, its confirmation screen, or
  its `--yes`;
- `Configuration Request` (`0Ah`) reports the fitted SIMMs, so which ROMs
  are present is asked rather than guessed.

rxved has to select each patch in turn and read the temporary area, audibly,
because an XV-2020's preset banks have no addresses in its parameter map.
The two programs look alike and differ most in exactly this.

The cost of E-MU's design shows up elsewhere: a reply carries no address to
match against, only an object type, number and ROM ID. So every request
drains the input first and checks that the reply describes the object asked
about — without that, a late reply to an abandoned request shifts every name
in a bank by one preset.
