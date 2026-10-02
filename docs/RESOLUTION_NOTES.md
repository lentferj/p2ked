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
exactly one: **194**, leaving 194 bytes before and 200 after. (Both of those
are decoded now, by a different method entirely -- see §10, which also
confirms this offset from the header's own arithmetic.)

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


---

## §9 — The MIDI Mode, and why the Multisetups are not browsable

**2026-09-12.** Both were the remaining halves of the channel screen, and
they turned out very differently. Neither needed anybody at the unit.

### MIDI Mode: readable, and not from the dump

`MIDI_MODE` is **parameter id 385**, documented, `0 = omni, 1 = poly,
2 = multi`. A Parameter Value Request returns it directly.

That is worth noting because the obvious plan was to decode it out of the
setup dump's master block -- work that was still undone at the time (TODO
10, done since, §10) and was never necessary. A flat parameter ID needs no layout at all. The lesson is
the cheap one: before reverse-engineering a structure, check whether the
thing wanted has its own name in the protocol.

The unit read `2`, multi, which is consistent with it being played
multitimbrally on two channels. `MIDI_ID` read `0`, matching the device ID
discovery found, and `MULTIMODE_BASIC_CHANNEL` read `8` -- channel 9, one
of the two in use.

The channel screen now shows the mode above the table, and in omni or poly
it shows *only* the mode and a sentence saying the settings below are stored
but not in effect. Listing per-channel faults in a mode where they do not
apply would send somebody to fix a channel when the mode is the answer --
which is precisely the wrong turn the sibling rxved nearly took on an
XV-2020 before the sound mode was checked.

### Multisetup names: not readable, and the evidence is clean

`Generic Name Request` takes an object type, and type 4 is Setup. Asking for
setups 0, 1, 2, 3 and 127 returns the same name every time.

That on its own would be ambiguous -- 128 setups all named alike is
plausible on a machine nobody has renamed. What settles it is asking for
setup **128**, which does not exist: it returns that same name too, where an
out-of-range *preset* returns `(not installed)`. The unit is ignoring the
number and answering with the current setup's name.

So Multisetups cannot be browsed by name on this firmware. They could be
listed by number, and selected with MSB 80 / LSB 0 / PC -- but selecting one
*loads* it, replacing the live channel configuration, which is a destructive
act against somebody's working setup and not something p2ked should do to
find out what a setup is called.

Recorded rather than retried.

---

## §10 — The Setup Dump's master blocks, decoded by asking the unit

**2026-09-12, second hardware session.** TODO 10 wanted the 194 bytes before
the channel block and the 200 after. Both are now mapped. The method matters
more than the table, because it generalises: **do not decode a structure
when you can ask the device what each value is.**

### The method

Every parameter on this machine has a flat 14-bit ID, and every one can be
read on its own with a Parameter Value Request — silently, with nothing
selected and nothing sounding. So the dump was not decoded from a layout at
all. Each documented master parameter was **read individually**, and the
dump was searched for where that value sat.

Eighty-two values in the master region; eighty-two individual reads; every
one agreed. Nothing here rests on a byte offset somebody inferred, and
anybody with a unit can re-derive the whole table without trusting this
note. `p2k/messages.MASTER_BLOCKS` is the result.

### The layout, on this unit and this firmware

| offset | bytes | contents |
|-------:|------:|----------|
| 0 | 14 | seven 14-bit counts: 20, 22, 16, 21, 3, 32, 9 |
| 14 | 16 | setup name, 16 ASCII characters |
| 30 | 40 | **master general** — parameter IDs 257-260, 264-279 |
| 70 | 44 | **master MIDI** — IDs 385, 386, 388, 391-409 |
| 114 | 32 | **master effects** — IDs 513-528 |
| 146 | 42 | **master arpeggiator** — IDs 641-661 (the header calls this "reserved") |
| 188 | 6 | **non-channel** — IDs 139, 140, 141 |
| 194 | 576 | 32 channels x 9 parameters, IDs 130-138 (§8) |
| 770 | 100 | sub-block: 24 BEATS triggers x 2 values, IDs 160, 161 |
| 870 | 100 | sub-block: 16 BEATS parts x 3 values, IDs 164, 165, 166 |

Total 970 payload bytes, exactly what the unit sends.

### Two things no document says

**1. IDs the specification marks "(reserved)" are omitted from the dump.**
That is the whole reason the general block holds twenty values across an ID
span of twenty-three: 261, 262 and 263 are simply not sent. Likewise the
MIDI block's twenty-two values span 385-409, with the reserved 387, 389 and
390 missing. Every block's leading `(RESERVED)` ID — 256, 384, 512, 640 — is
absent too.

This is the kind of detail that cannot be guessed and is fatal to guess
wrong: put one reserved slot back and every value after it lands on its
neighbour's ID, all of them in range, none of them right.

**2. The block the header calls "reserved" is the Master Arpeggiator.**
Twenty-one values, parameter IDs 641-661 in order, matching twenty-one
individually-read arpeggiator parameters. The specification's *prose* list
of the dump's contents does say "Arpeggiator" at exactly that position — it
is only the example layout that calls those bytes reserved. The prose was
right and the example was wrong, which is the same verdict §8 reached from
the other direction.

### The header's own arithmetic agrees with §8's structural search

    30 + 2 x (20 + 22 + 16 + 21 + 3) = 194

which is precisely the offset §8 found by searching for the one window where
all 288 channel values fall in range. Two independent methods, one answer.

That agreement is not decoration, it is the licence to read the master
blocks positionally at all, so `parse_setup_dump` now checks it: if the
counts do not land on the offset the search found, `SetupDump.master` stays
**empty** and the disagreement is reported. A master value read at the wrong
offset is a plausible number that nothing downstream could reject.

### The 200 bytes after the channel block

The seven-value header does not mention them. They are two further
**self-describing** sub-blocks, each a row count and a row width followed by
that many rows:

- at 770: `24, 2` then 24 rows — trigger keys 36 to 59 ascending, latch 0;
- at 870: `16, 3` then 16 rows — `-1, 0, g` with `g` running 1,1,1,1,
  2,2,2,2, 3,3,3,3, 4,4,4,4.

Identified from the specification's prose rather than its tables: the BEATS
trigger parameters are documented as "per **24 triggers**" and there are
**two** of them (`BEATS_TRIGGER_KEY` 160, `BEATS_TRIGGER_LATCH` 161); the
BEATS part parameters are "per **16 parts**" and there are **three**
(`BEATS_VELOCITY` 164, `BEATS_XPOSE` 165, `BEATS_GROUP` 166). Those are
exactly the two shapes the unit sends, and the values fit: velocity -1 is
documented as "use trigger velocity", and group has range 0-4.

Cross-checked directly: reading IDs 160 and 161 returned `36, 0` and reading
164, 165, 166 returned `-1, 0, 1` — one row of each block, in that field
order. Which trigger and part those belong to is not known, because
selecting one needs a parameter *edit* (`LAYER_SELECT`, id 898) and nothing
was written to this unit. So the field order is confirmed for one row of
each block, not for all forty.

### Small confirmations worth keeping

- `MASTER_RIFF_ROM_ID` (277) reads **4** in both the dump and the individual
  read — a ROM this unit actually has fitted. The general block landing a
  real ROM ID on the parameter named for one is the same kind of evidence
  §8 used for the channel block's ninth field.
- `MIDI_MODE` (385) reads 2 in the dump, matching what §9 read directly.
  The dump now carries it, and the bridge should still ask for it by ID:
  one request, no layout, no way to be wrong.
- IDs 261 and 410 answer a request (with -1 and 127) but appear **nowhere**
  in the dump. Readable and un-dumped are different things; do not go
  hunting for them.

### What is established, and what is not

**Established**, against one unit on 2026-09-12: the table above, value for
value, by two independent readings of every master parameter.

**Not established**:

- **Three IDs in the dump have no published name**: 270 and 279 in the
  general block, 660 in the arpeggiator block. They are decoded — a value at
  a known ID is a fact — and deliberately left unnamed. The specification's
  prose lists a "Master Demo Mode Enable" that appears in no ID table, so
  270 or 279 *could* be it; that is a hypothesis, not a reading, and p2ked
  does not print it.
- **Other firmware.** This is one unit's answer. The parser therefore obeys
  the declared counts rather than these byte offsets, skips any single block
  whose count it does not recognise, and keeps the structural search as the
  authority for where the channels are.
- **Writing.** Nothing was written. Whether the unit accepts a Setup Dump
  back, and what it does with the two undocumented trailing blocks, is
  untested and out of scope: p2ked reads.

---

## §11 — Timing, preset extents, and the startup sweep

**2026-10-02, third hardware session.** Same Proteus 2000 as §7 and §10:
device ID 0, behind a U6MIDI Pro, four SIMMs. Nothing was selected, nothing
wrote to the unit, and nothing sounded — every exchange below is a read.

Three open items were aimed at this session (TODO 4, TODO 5, TODO 34), and a
fourth question turned up that nobody had asked.

### The unit's answer to a name request is ~18 ms, and that is the whole cost

`bridge.SEND_GAP` had been a guess since the first commit. Measured, over a
128-preset bank, on this unit and this cable:

| gap after each send | per preset | notes |
|---|---:|---|
| 10.00 ms (the default) | 18.72 ms | 3/3 clean |
| 0.00 ms | 18.94 ms | 3/3 clean |

And the round trip on its own, with no gap and no drain: **17.91 ms**.

So the gap is entirely hidden inside the unit's response time. Removing it
outright changes nothing — 18.94 ms against 18.72 ms, which is noise. The
cost of a name sweep is the instrument taking eighteen milliseconds to think,
and no sender-side constant can improve that.

**`SEND_GAP` stays at 10 ms.** Two reasons, and the second is the one that
matters:

1. It is not a performance lever. Cutting it to zero buys nothing
   measurable, so there is no performance argument for changing it.
2. The sweep found **no failures at any gap down to 0.05 ms** — 3/3 clean at
   every step. The unit tolerates a far faster rate than p2ked sends at.
   That is evidence the current value is *conservative*, not evidence it is
   needed. Lowering it would trade a margin nobody has measured the need
   for, for nothing.

`tools/measure_send_gap.py` is the tool that produced this, and it is the
answer to "re-derive it rather than trust this note". It compares each read
against a reference read, not merely counting successes, because the failure
a too-small gap causes is a reply belonging to the *previous* request — every
name shifted by one preset — which a success count cannot see.

One unit, one firmware, one interface. The sibling projects' 10 ms default is
untouched here, and nothing above generalises to another unit.

### The preset counts in `roms.py` are right for all four fitted ROMs

TODO 5 said the table's counts come from the instrument-definition files,
which describe banks rather than populated presets, and asked whether
`banks * 128` might therefore overstate a ROM.

The unit reports its own per-SIMM count, and all four agree exactly:

| SIMM | p2ked `count` | unit reports | agree |
|---|---:|---:|---|
| 4 Composer | 1024 | 1024 | yes |
| 14 X-Lead v2 | 640 | 640 | yes |
| 65 Techno Synth | 512 | 512 | yes |
| 67 Beat Garden | 512 | 512 | yes |

User memory: 512, against 512 in the table. The next section reads two of
these ROMs slot by slot, which is what turned "the counts agree" into "the
counts are right, and here is the one empty slot".

### Preset extents, read whole: two ROMs, 1664 names

§7 compared 640 X-Lead v2 names against the document. Done again on
2026-10-02 at more scale, and extended to a second ROM, this is the
clearest result of the session.

Every preset of two fitted ROMs was read off the unit and counted:

| ROM | slots read | named | empty | absent | table says |
|---|---:|---:|---:|---:|---:|
| Composer | 1024 | 1023 | **1** | 0 | 1024 |
| X-Lead v2 | 640 | 640 | 0 | 0 | 640 |

**The `banks * 128` policy is exactly right** for every ROM this unit has:
not one slot over, not one under. TODO 5 asked whether it would overstate a
ROM, and it does not.

**And the partly-empty last bank is not hypothetical.** COMPOSER-7 pc 127
is an empty slot -- the last preset of the last bank holds nothing. The
catalog records it as `:default` too, so table, catalog and unit all agree,
and `read_bank_names` keeps the slot for the reason its comment gives:
"default" is what the unit says, and a blank row would leave the user
wondering whether the read failed or the slot is genuinely empty.

Composer is also the ROM that will not answer `(not installed)` past its
end, discussed next. The two findings are one fact seen twice: this ROM
answers `:default` rather than reporting absence, so its extent has to come
from the table and the catalog -- which is exactly the arrangement TODO 5
was worried about. It works.

### Fifty slots where the printed list is wrong and the unit is right

Diffing those 1664 names against the generated catalog:

| ROM | differences | kind |
|---|---:|---|
| X-Lead v2 | 11 | whitespace, every one a double space on the instrument |
| Composer | **49** | typos, lost characters, truncation, case, 2 wrong prefixes |

**X-Lead v2's 11 reproduce §7 exactly** -- an independent re-derivation of a
finding recorded three weeks earlier, on a different sample:

    XLEAD2-0 pc 25  printed='kit:K-1 HPF'  unit='kit:K-1  HPF'
    XLEAD2-0 pc 90  printed='hit:Dance 1'  unit='hit:Dance  1'

**Composer's 49 are something else** -- real errors in the published patch
list, not transcription artefacts of ours:

    COMPOSER-0 pc 19  printed='brs:TrumpetMure2'  unit='brs:TrumpetMute2'
    COMPOSER-1 pc 47  printed='syn:808 Synthax'   unit='syn:8O8 Synthax'
    COMPOSER-3 pc 85  printed='kit:Clean RsrB'    unit='kit:Clean R&B'
    COMPOSER-0 pc 16  printed='brr:Trumpet FX 7'  unit='brs:Trumpet FX 7'
    COMPOSER-4 pc  9  printed='kb3:DX Organ'      unit='kit:Kit 1'

Broken down: 28 typos and garbled text (`Mure`/`Mute`, `808`/`8O8`,
`Voxwav`/`VS Vox`), 12 whitespace, 4 case, 3 truncated, 2 with the wrong
category prefix. One of those two is not a typo but a different instrument
altogether -- `kb3:DX Organ` where the unit holds `kit:Kit 1`.

**All 49 are what `Catalog.disagreement` was written for.** A ROM cannot be
saved over, so a difference in a ROM bank cannot mean "somebody stored their
own sound here". It means the printed list is wrong and the unit is right,
which is what the screen will say on all 49.

**The cost, measured at the same time:** 1664 names in 31.0 s, or
**18.6 ms per name** -- three orders of magnitude more sample than the
SEND_GAP measurement above, and agreeing with it. It is also the honest
price of the feature: reading one whole fitted ROM takes the better part of
half a minute, which is why startup asks the Configuration response instead.

### The absent-preset sentinel is not returned by every ROM

Expected, on the strength of §7: X-Lead v2 answers preset 639 and says
`(not installed)` at 640. Confirmed, and so were two more:

| ROM | last preset | one past the end |
|---|---|---|
| X-Lead v2 | #639 `bts:Magic Air` | `(not installed)` |
| Techno Synth | #511 `   :TemplateV2.0` | `(not installed)` |
| Beat Garden | #511 `   :TemplateV1.0` | `(not installed)` |
| **Composer** | #1022 `brs:SforzadoEnsb` | **`   :default`** |

Composer does not, and pushing the probe further only makes it worse: it
returns `   :default` for **every representable preset number** up to #16382,
the largest but one. There is no point at which it admits the preset does not
exist, so **a name request cannot discover this ROM's extent at all**.

The other three are exact and deterministic — six repeats of each boundary
slot, six out of six identical every time.

That matters because `(not installed)` is load-bearing in two places, so both
were checked against the unit rather than reasoned about:

- **`installed_roms` is sound.** It asks preset 0 of every ROM in the table.
  All **15 unfitted** ROMs answer `(not installed)`; all four fitted ones
  answer with a name. The sentinel is reliable for the only question p2ked
  ever asks of it.
- **`read_bank_names` is safe.** It only asks about slots the table says
  exist, and drops what comes back absent.

And it retroactively justifies a decision. Runtime correction of the ROM
table was **dropped** rather than deferred in item 5, on the grounds that the
counts already agree everywhere they can be checked. Composer's behaviour is
the hard reason: a scheme that worked out each ROM's extent by probing would
have worked for three ROMs and silently over-reported Composer — the exact
failure item 5 existed to prevent.

**The sentinel is a courtesy, not a guarantee.** The ROM table and the
Configuration response's per-SIMM count are what p2ked actually relies on,
and neither is a name request.

### Two smaller things, found by looking

**Preset number 16383 is silent on every ROM tested**, fitted or not. It is
the largest 14-bit value, so this reads as a reserved edge in the firmware
rather than an extent boundary. Nothing in p2ked asks for it.

**The unit can go briefly unresponsive.** Once, right after a sweep of 1664
names, three consecutive requests timed out at 2 s each; the unit then
recovered and answered normally, and six repeats of every boundary slot
afterwards were identical. So it is not boundary nondeterminism. p2ked
degrades safely — `read_bank_names` catches the timeout per slot — and
`tools/measure_send_gap.py` exists to catch exactly this, which is why it
compares each read against a reference rather than counting successes.

Not investigated: *why* Composer differs, and whether its true extent really
is 1024. The catalog, the table and the Configuration response all say 1024,
and the unit holds 1023 populated presets plus one empty slot. The likeliest
reading is that this ROM answers "empty" rather than "absent", but that is a
hypothesis about firmware behaviour and is not recorded as a fact.

### The startup sweep was asking twenty questions where one would do

TODO 34: `p2ked` asked the unit which ROMs it had by sending one name request
per ROM at startup — twenty requests, up to 12 s of silence before the first
paint if the unit went quiet.

The Configuration response already lists every fitted SIMM. Timed, on this
unit:

| method | requests | wall clock |
|---|---:|---:|
| `installed_roms` | 20 | 370.7 ms |
| `roms_from_config` (new) | 1 | **16.5 ms** |

23x, and the two agree exactly — identical dicts, verified. `installed_roms`
is kept, because it asks the question the name reader will actually ask rather
than believing the configuration block, and two independent readings of the
same fact are worth more than 350 ms. The cheap one is for startup, where
there is no second reading yet to compare against.

The trap worth naming: **user memory is not a SIMM.** The Configuration
response reports it as `user_presets`, separately, so `config.simms` alone
says the unit has no user banks — and a bank pane built from it would start
on a ROM and never show USER-0 at all. `roms_from_config` adds that entry
itself.

### What this session did not settle

- The other fifteen ROM rows. Unreachable without the boards.
- **Why Composer answers `:default` where three other ROMs answer
  `(not installed)`, and whether its true extent is 1024.** Three
  independent sources agree on 1024 and the unit holds 1023 populated
  presets plus one empty slot, so nothing is at stake — but the question
  is about firmware behaviour and is not answered by guessing.
- Whether a different unit, firmware or interface has the same 18 ms answer,
  or returns the sentinel everywhere, or can go briefly unresponsive.
- Writing. Still nothing was written, still out of scope.
