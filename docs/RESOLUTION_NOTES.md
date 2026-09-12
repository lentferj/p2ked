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

---

## §7 — The first hardware session

**2026-09-12.** A Proteus 2000 was powered up and scanned. Nothing was
selected and nothing made a sound: every exchange below is a read.

The unit is **not** on a port that names it — it reaches the host over a DIN
cable behind a U6MIDI Pro interface, exactly the case `likely_proteus_ports`
warns about. It was found by broadcasting a Universal Identity Request on
every bidirectional port and reading the replies; it answered with
manufacturer `18h` and device ID `0`.

### What worked as written

- The frame layout, `F0 18 0F <dev> 55 …`, and the 14-bit LSB-first
  encoding. Confirmed by everything below working at all.
- **Hardware Configuration.** Parsed first time: 512 user presets, four
  SIMMs, each with an ID, a preset count and an instrument count. The
  declared-length reading paid for itself — the general block really is two
  bytes and the per-SIMM block really is six, but the parser did not have to
  assume it.
- **Generic Name.** Names came back for the user banks and every fitted ROM.

### The guess, resolved

p2ked assumed a reported **SIMM ID is the ROM's Bank Select MSB**. The unit
reported IDs 4, 65 and 67; asking each for its first three presets returned
names matching this project's catalog for the ROMs at MSB 4, 65 and 67 —
character for character. Three of twenty ROMs, so the docstring still
records the limit, but the assumption is no longer a guess.

A second, independent check agrees. `ProteusBridge.installed_roms()` asks
every ROM ID for preset 0 and reads the reply; its answer matches the
Configuration response exactly. The owner confirms the unit has four slots,
all filled, including the factory Composer ROM.

### Two sentinels, neither documented

The specification says a request the unit cannot serve is ignored. It is
not:

- **`(not installed)`** is returned for a preset that does not exist —
  past the end of a ROM, or in a ROM that is not fitted. This is *better*
  than silence and worth relying on: it turns "is this ROM present?" from a
  timeout into an answer, and a timeout would equally mean the cable is out.
- **`default`**, with the usual blank category prefix, is returned for a
  real but unprogrammed slot.

`roms.is_absent` and `roms.is_empty` recognise them, and `read_bank_names`
drops the absent ones rather than inventing 128 presets called
"(not installed)".

### A ROM no document covered

The unit reported SIMM ID **14** with 640 presets, and p2ked's table had no
row for it: the Cakewalk instrument-definition files simply do not cover
MSB 14. It answered names for 0–639 and `(not installed)` at 640.

It was identified from E-MU's own patch list for **X-Lead v2** — 640
presets in five banks, and every preset sampled off the unit (0, 5, 100,
200, 400, 638, 639) matching that list exactly. `tools/extract_catalog.py`
now reads OpenDocument patch lists as well, so those 640 names are in the
catalog; they were unobtainable from any other file to hand.

Not useful, and worth recording so nobody tries it twice: the SIMM "code
numbers" published on enthusiast sites are a **third** numbering, unrelated
to either the Bank Select MSB or the reported SIMM ID. Techno Synth is code
`04` and answers on MSB 65.

### What comparing 640 names against the document found

Reading all five X-Lead v2 banks off the unit and diffing them against the
patch list left **629 of 640** matching. The eleven that did not came in
three kinds, and only the last is a real difference:

1. **Typographic apostrophes.** The document uses `’`; a preset name is 16
   bytes of ASCII and cannot contain one.
2. **XML entities and space runs.** An `.odt` stores `&` as `&amp;` and a
   run of spaces as `<text:s text:c="2"/>`. Stripping tags naively loses
   both — and the second is invisible, turning two spaces into one.
3. **Genuinely different names.** Eleven presets carry two spaces on the
   instrument where the document prints one. The document is wrong.

The first two were p2ked's bugs, found only because a real unit disagreed
with it. **A parser checked against nothing but its own output is a parser
checked against nothing.**

The third changes what the `*` flag means. In a *user* bank a difference
means somebody saved over the factory preset, which is worth pointing out.
In a *ROM* bank it cannot mean that — so it means the printed list is wrong
and the unit is right. `Catalog.disagreement` says which.

---

## §8 — "Multi" means two different things on this machine

**Read 2026-09-12**, prompted by the owner warning that the word is
overloaded. It is, and confusing the two would build the wrong screen.

**1. Multi is a MIDI *mode*.** The Master menu's MIDI Mode parameter selects
Omni, Poly or **Multi** (OM p. 2715 region). Only in Multi does the unit
respond multitimbrally, one preset per channel. This is the direct analogue
of the XV-2020's PATCH-versus-PERFORM sound mode, and of the same
diagnostic importance: in Omni or Poly, "only one channel sounds" is not a
fault and nothing about the channels is wrong.

**2. A Multisetup is a stored *snapshot*.** 128 user locations, reached by
the front panel's Multi button. The manual is explicit about what one
holds: preset, volume and pan for each of the **32 MIDI channels**, the
setup's name, and all Master menu parameters except the program-change map
and the user tuning tables. Selectable over MIDI with **MSB 80, LSB 0** and
a Program Change. That is closer to an XV-2020 *performance* than to its
multi-mode screen.

So rxved's multi-mode screen splits into two features here, and they are not
the same feature.

### What the wire offers

Per channel, as individual parameters (ids 130-138): preset, volume, pan,
mix output, arp, channel enable, bank map, receive program change, and
preset ROM ID. Reading one requires first setting `MULTIMODE_CHANNEL_SELECT`
(id 129) -- **stateful**, unlike the XV-2020's per-part addressed blocks,
and a trap: a value read without setting the channel belongs to whichever
channel was selected last.

Better, and what p2ked should use: **Setup Dump Request** (`1Dh`) returns
the whole thing in one message (`1Ch`), with no channel selector and no
state.

### The dump's documented layout does not match the firmware

Read from a unit, the dump is 970 payload bytes and its self-describing
header says: 20 master general parameters, 22 master MIDI, 16 master
effects, 21 reserved, 3 non-channel, **32 MIDI channels, 9 parameters per
channel**, then a 16-character setup name.

The specification's example says 11 master general and 0 reserved -- and
then, in the same example, allots the 0 reserved parameters 40 data bytes.
Its own numbers are inconsistent, so the byte layout cannot be derived from
them.

Nor is the channel block simply the last 576 bytes: decoding it that way
produces ROM IDs of 256 and values that drift upward like indices. It was
located **structurally** instead, the same way the sibling rxved finds
tables in Roland's editor binary -- by searching for the one offset at which
all 32 channels' 9 values fall inside their documented ranges. There is
exactly one: **194**, leaving 194 bytes before and 200 after.

At that offset every value is plausible: presets 0-31 across the 32
channels, volume 127, pan 64 (centre), receive-program-change 1, ROM ID 0.

### The field order, and a lesson about sampling

An earlier note here said the Enable/Bank Map order was unresolved, because
the first field "reads 0 for channels 1-16 and 1 for 17-32", which would
have meant the working channels were the disabled ones.

**That was wrong, and wrong in an avoidable way**: it generalised from a
printed sample of eight channels out of thirty-two. Printing all 32 shows
the field is 1 for channels 9, 10 and 17-32, and 0 for the rest -- not a
clean split at 16 at all. A pattern inferred from the rows that happened to
be on screen is not a pattern.

With the full table the order is confirmed, by evidence rather than by
trusting the parameter-ID list:

- Exactly three channels are not at factory defaults, and for exactly those
  three the ninth field reads **14** -- the Bank Select MSB of a ROM this
  unit actually has fitted. Every other channel reads 0. A misaligned field
  would have no reason to land on a real ROM ID precisely where the real
  customisation is.
- Their preset numbers resolve, inside that ROM, to real presets with
  sensible names.
- All three are on channels 1-16, and the owner confirms using only a few
  channels and only on the first of the unit's two MIDI interfaces.

So the parameter-ID order holds: preset, volume, pan, mix output, arp,
**channel enable**, bank map, receive program change, preset ROM ID. Enable
is 1 on the channels in use.

Two things remain merely plausible rather than shown: that channels 17-32
reading enable=1 at factory defaults is simply the second interface's
default state, and that the one configured-but-disabled channel was set up
and then switched off.

### The firmware outranks the specification here

The owner confirms this unit runs the latest firmware, which is newer than
any documentation to hand. That reframes every mismatch in this section:
the specification's inconsistent counts are not evidence of a misreading,
they are a stale document. **Where the unit and the specification disagree
about this dump, the unit is right**, and p2ked should read the
self-describing header rather than any published layout.

### Confirmed a third time, from outside both projects

The owner's sequencer template — written years before any of this and
derived from neither the unit nor p2ked — drives this Proteus on **channels
9 and 10**, both addressed at **MSB 14 / LSB 2**.

That is an independent confirmation of two separate readings: the Channel
Enable field (1 on exactly those two channels) and the SIMM-ID-is-the-MSB
mapping (ROM 14, the board the unit reports on exactly those channels). The
one configured-but-disabled channel targets the same bank, which the owner
confirms is a leftover from an older setup.

The same template drives the XV-2020 at MSB 87 — the patch bank in the
sibling rxved's table — which confirms that table from outside rxved too.

Worth the note because it is the only confirmation here that could not have
inherited a mistake: the unit, the documents and p2ked could in principle
all be read wrong in the same way; a sequencer that has been playing these
machines correctly for years could not.
