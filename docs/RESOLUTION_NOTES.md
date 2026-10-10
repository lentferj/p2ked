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

**Corrected 2026-10-09.** The user-bank half of that paragraph turned out to
be wrong, and it is worth saying so here rather than deleting it: the
sentence above was carried into `Catalog.disagreement`, which then printed
it 512 times where nothing had been saved over anything. E-MU's own
instrument-definition file cannot document user memory, so its user-bank
sections hold placeholders — `usr:A0` … `usr:D127` — and a real preset name
can never equal one. The comparison was therefore guaranteed to "fail" in
every user bank, endlessly. `differs` now makes the comparison only where
the printed list has authority, which is a ROM; a user bank's `*` is gone
and so is that sentence. The ROM half of this note — all 49 Composer rows
— stands as written, and is still tested.

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
  untested and out of scope: p2ked reads. — *2026-10-11: still untested, but
  no longer out of scope. §13 writes the dump back as the per-channel route;
  the receive path there is documented and never exercised, which is the
  caveat that section's own last paragraph.*

---

## §11 — Timing, preset extents, and the startup sweep

**2026-10-02, third hardware session.** Same Proteus 2000 as §7 and §10:
device ID 0, behind a U6MIDI Pro, four SIMMs.

**No audio path.** The unit was connected by MIDI only, so nobody could hear
whether a read made a noise. Nothing in this section claims silence was
observed, because it was not observable. What *was* established is narrower
and stronger in the ways that matter: every exchange below is a read, and
**no Channel Voice message was sent at all** — 1027 messages during a full
sweep, every one System Exclusive, zero Note On/Off, Control Change, Program
Change or Pitch Bend. On a MIDI instrument that is the only route to sound,
so the read path cannot have made it, and `tests/test_no_sound.py` now
pins that mechanically rather than leaving it to an ear. Earlier wording in
this section that said "nothing sounded" was not supportable and has been
corrected.

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

### The read path emits no Channel Voice — counted, not heard

The unit had no audio connection, so silence could not be observed. What can
be observed is the *mechanism*: this instrument makes sound only by receiving
Channel Voice messages, status bytes 0x80-0xEF — Note On/Off, Control Change,
Program Change, Pitch Bend, and the two aftertouch forms.

Every byte p2ked sent during a full sweep was recorded by wrapping the output
port, and classified:

```
total messages sent   1027
  SysEx               1027
  everything else       0

  0x0c GENERIC_NAME_REQUEST   1024
  0x0a CONFIGURATION_REQUEST     1
  0x1d SETUP_DUMP_REQUEST        1
  (plus one Universal Identity Request, which is not an E-MU frame)
```

So the read path cannot have made the instrument sound — not "was probably
quiet", but: there was no message through which it could have.

The same sweep shows the rule structurally. `p2k/bridge.py` has five
`send_message` call sites: four build System Exclusive, and the remaining
three — the only non-SysEx sends in the project — are the Bank Select CCs
and Program Change inside `select()`. So the audible operation is reachable
from exactly one place, and `P2kedApp` reaches it only through Enter, or
`p2kcli select`.

`tests/test_no_sound.py` now pins both halves. It exercises every read
method against a port that records sends and never replies — every read
times out, which does not matter, because the send happens before the wait
and is what is inspected. A second test class confirms a selection *does*
emit the expected three Channel Voice messages, so the read tests cannot
pass merely because nothing ever sends anything; both halves were verified
to fail under a deliberate mutation.

**What this does not establish:** that the unit made no noise. That needs it
wired to an output and somebody listening. The claim being made is the
narrower one, which is the one the evidence supports.

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
---

## §12 — The transcription, with page cites

**2026-10-10.** `p2ked/masteredit.py` carries a table of master-parameter ranges
and labels whose docstring cites "RESOLUTION_NOTES §12" for them, and §12 did not
exist. This is it: the four things the edit path rests on, transcribed from the
manuals with a page cite on every number. None of it came from a unit and none
of it needed one — these are facts the documents state outright. Where two
documents disagree, or where a number in the code is an inference rather than a
transcription, that is said rather than smoothed over.

§1 already ranked the sources and it has not changed: the specification wins on
the wire format, the instrument-definition files are the only source for ROM
names, and the hardware outranks both. This section adds a third document, and
the first thing to say about it is that it is **not** E-MU's.

### How to re-check any cite in this section

**The specification** (`sysex.txt`, "Proteus 2000, Audity 2000, Proteus 2500,
XL-7, MP-7, PX-7, PK-6, MK-6, XK-6, Vintage Keys, Vintage Pro, Halo — System
Exclusive Specification, Version 2.2"). Every page carries its number in the
footer: odd pages end `Proteus Family MIDI SysEx Specification <n>`, even pages
end `<n> E-MU Systems`. Cited as *spec p. n*.

**The operation manual** (`p2000.txt`, "Proteus 2000 Operation Manual", FI634
Rev. D). Same arrangement: `Proteus 2000 Operation Manual   <n>` and
`<n> E-mu Systems`. Cited as *OM p. n*.

**The parameter tree** (`paramtree.txt`, "PROTEUS 2000 PARAMETER TREE version
2.26"). No pages, no footers, no table of contents — a numbered list under three
headings, `MASTER BUTTON` items 1–34, `EDIT BUTTON` 1–52, `MULTI BUTTON` 1–17.
Heading plus item number is the only stable locator. Cited as
*paramtree, MULTI BUTTON 3*.

And that third file's own line 3 reads "Compiled by Benny Skyn". It is a
third-party summary, so §1's ranking says nothing about it and it cannot
outrank anything. It is worth having because it is front-panel shaped — one
numbered item per screen, which is how the machine is actually operated — but
where it disagrees with E-MU's own two documents it is one person's reading and
it loses.

### The nine per-channel parameters

The specification lists them as individual parameter IDs (spec p. 41) and again,
positionally, in the dump's contents (spec p. 27). In ID order, which is the
order §8 confirmed from the unit's values:

| # | ID | spec p. 41 name | min | max | documented values |
|---:|---:|---|---:|---:|---|
| 1 | 130 | MULTIMODE_PRESET | 0 | 895 | — |
| 2 | 131 | MULTIMODE_VOLUME | 0 | 127 | — |
| 3 | 132 | MULTIMODE_PAN | 0 | 127 | 64L–63R displayed |
| 4 | 133 | MULTIMODE_MIX_OUTPUT | -1 | 2 | -1 = Preset, 0 = Main, 1 = Submix1, 2 = Submix2 |
| 5 | 134 | MULTIMODE_ARP | -2 | 1 | -2 = off, -1 = on, 0 = P (Preset Arp), 1 = G (Global Arp) |
| 6 | 135 | MULTIMODE_CHANNEL_ENABLE | 0 | 1 | — |
| 7 | 136 | MULTIMODE_BANK_MAP | 0 | 6 | — |
| 8 | 137 | MULTIMODE_RCV_PROG_CHANGE | 0 | 1 | — |
| 9 | 138 | ROM ID | ? | ? | — |

Reading or setting one requires `MULTIMODE_CHANNEL_SELECT` first, and that is
id **129**, min 0, max 15 (spec p. 41). Two things about it, both documented and
both awkward:

- **129's documented range does not reach the machine's channels.** The unit
  takes 01A–16A and 01B–16B, "32 channels can be used simultaneously"
  (OM p. 30, p. 34; "01A-16A, 01B-16B" OM p. 26; "channel 16B: On" OM p. 45;
  "a total of 32 MIDI channels" OM p. 80). The selector's 0–15 covers the first
  port only, so the upper sixteen channels are not addressable by the documented
  selector at all.
- It is **stateful**, which is what §8 already warned about: a value read
  without setting the channel belongs to whichever channel was selected last.

**Eight of the nine ranges are transcribed exactly where p2ked has them.**
`CHANNEL_PARAMETERS` in `p2k/messages.py` carries 0–895, 0–127, 0–127, -1–2,
-2–1, 0–1, 0–6, 0–1 and 0–127. The first eight are spec p. 41 verbatim. The
ninth is not: id 138's range is printed `min = ?; max = ?` (spec p. 41), so
0–127 is the code's inference. It is a reasonable one — a Bank Select MSB is
seven bits (§2, §3) and every SIMM ID a unit has reported is 0–127 (§7) — but it
is an inference, and it sits in a table that otherwise looks transcribed.

**And the ninth value's documented range is stale by 129.** id 130 tops out at
895 (spec p. 41); Composer holds 1024 presets (§11), so the top 129 of them
cannot be named by a per-channel preset number inside the documented range.
Nothing has written one, so whether the unit clips or accepts is unknown — but
the specification does say what happens to an out-of-range value: "Values
recieved that are outside the min/max range will be clipped to within that
range" (spec p. 41). If the spec is right the write is silently truncated,
which is a worse failure than a refusal.

**Two of the nine have the thinnest documentation, and it is worth knowing
which.** The operation manual's list of what a Multimode Map carries, per
channel, is: "Preset, Volume, & Pan", "Mix Output", "Multimode Channel Enable",
"Multimode Bank Map", "Multimode Receive Program Change" (OM p. 51). That is
seven of the nine. Missing are **MULTIMODE_ARP** (134) and **Preset ROM ID**
(138). The specification's dump prose (spec p. 27) names seven too, and a
*different* seven: it includes "Multimode Preset ROM ID" and puts ARP and
BANK_MAP where it writes `(reserved)`.

So the two *lists of the dump's contents* — the specification's prose and the
operation manual's transmit screen — name eight of the nine between them, and
their union is everything except ARP. The specification's parameter-ID table
(spec p. 41) names all nine, which is where p2ked's order comes from. The unit's
header says nine parameters per channel (§8), and all nine are present. **The
disagreement is about naming, not about layout** — the two `(reserved)` slots in
the spec's prose sit exactly where the parameter-ID list puts ARP (5th) and
BANK_MAP (7th), which is the same reading §8 confirmed from the unit's values.
What nobody has published is what ARP means on the wire beyond the four values
above, or what BANK_MAP maps between.

### The master blocks, and their counts

The dump's own header declares its layout and the specification's example spells
out what each declared count means (spec p. 28). Transcribed, with the byte
width the same example allots each block:

| field | spec p. 28's words | value given | bytes allotted |
|---|---|---:|---:|
| aa | Number of Master General Parameters | 11 | 22 (Master General) |
| bb | Number of Master MIDI Parameters | 22 | 44 (Master MIDI) |
| cc | Number of Master Effects Parameters | 16 | 32 (Master Effects) |
| dd | Number of Reserved Parameters | 0 | 40 (Reserved) |
| xx | Number of Non Channel Parameters | — | 6 |
| yy | Number of MIDI Channels | — | 576, with zz |
| zz | Number of Parameters per Channel | — | 576, with yy |

then a 16-byte ASCII setup name, then the blocks in that order. Three of the
seven counts are left blank in the example and have to be derived: 6 bytes at two
bytes per value is 3 non-channel parameters, and 576 bytes is 32 channels × 9
parameters. Both derivations agree with the prose list just above the example —
"(\*Parameters for each of 32 MIDI channels\*)" followed by nine entries
(spec p. 27).

**The example contradicts itself in two places, and §8 has already said the
first of them.** It declares 0 reserved parameters and then allots them 40 data
bytes — twenty values' worth. Its declared counts sum to 52; its own byte widths
imply 72. And the published counts give the header arithmetic §10 performs the
wrong answer entirely:

    30 + 2 x (11 + 22 + 16 + 0 + 3) = 134      <- the published counts
    30 + 2 x (20 + 22 + 16 + 21 + 3) = 194     <- what the unit declares (§10)

134 is nowhere in the dump. §8's search for the one offset at which all 288
channel values fall in range found exactly one, at 194.

**The published example totals 750 payload bytes; the unit sends 970 (§8).** The
220-byte difference is fully accounted for:

| | spec p. 28 | unit (§10) | difference |
|---|---:|---:|---:|
| master general | 22 B (11) | 40 B (20) | +18 B (+9 values) |
| master MIDI | 44 B (22) | 44 B (22) | 0 |
| master effects | 32 B (16) | 32 B (16) | 0 |
| reserved | 40 B (0 declared) | 42 B (21) | +2 B (+1 value) |
| non-channel | 6 B (3) | 6 B (3) | 0 |
| channels | 576 B | 576 B | 0 |
| the two trailing sub-blocks | not mentioned | 100 + 100 B | +200 B |
| **total** | **750 B** | **970 B** | **+220 B** |

18 + 2 + 200 = 220. Nothing is left over.

**Where the specification's prose and its example disagree about the "reserved"
block, the prose is right, and §10 says so from the unit.** The prose list of the
dump's contents puts the word "Arpeggiator" at exactly the position the example
calls reserved (spec p. 27) — between the master effects and the three
non-channel parameters, under the heading "(\*Independant of MIDI Channel\*)".
§10 read the 42 bytes there as 21 individually-verified arpeggiator parameters,
IDs 641–661. Note also that the specification's own section heading for the
message is "Setup Dump" (spec p. 26), the frame's command line calls it
"Command::Multimode Map Dump" (spec p. 28), and the operation manual calls the
same transmission "Multimode Map" (OM p. 51). Three documented names for one
message; `Command.SETUP_DUMP` is the section heading.

**The reserved-omission rule is derivable from the specification's own parameter
tables, and it predicts all five counts.** §10 found the rule on the unit: the
IDs the specification marks "(reserved)" are simply not sent. Run it forward,
from the document alone, and it gives every count the unit reports:

| block | ID span in the spec's parameter list | leading `(RESERVED)` | other `(reserved)` | span minus those | unit reports (§10) |
|---|---|---:|---|---:|---:|
| master general | 256–279 (spec pp. 43–46, 52) | 256 | 261, 262, 263 | 20 | 20 |
| master MIDI | 384–409 (spec pp. 47–48) | 384 | 387, 389, 390 | 22 | 22 |
| master effects | 512–528 (spec p. 49) | 512 | — | 16 | 16 |
| master arpeggiator | 640–661 (spec pp. 49–50) | 640 | — | 21 | 21 |
| non-channel | 139–141 (spec p. 42) | — | — | 3 | 3 |

Five for five, from a rule the document never states in as many words. That is
the licence §10 already relies on, arrived at from the other side.

Two extents are *not* derivable and should not be pretended to be:

- The general block's span is 256–279 because the spec's Master Parameters
  section runs 256–269 (spec pp. 43–46) and the BEATS "normal single items"
  271–278 sit in the same high-byte group (spec p. 52). That the block stops at
  279 rather than running on into the spec's Local Controller Parameters at 280
  (spec p. 46) is an inference — and 270 and 279 have no row in the
  specification at all, which is §10's "three IDs with no published name" for
  the general block.
- The MIDI block's span is 384–409, but the spec's Master MIDI Parameters
  section runs on to 422 (spec pp. 47–48). The unit does not send 410–422, and
  the document gives no reason. §10 records that 410 is readable on the unit and
  appears nowhere in the dump.

**The general block is the one place where the parameter tables are broader than
the dump's documented contents, and the unit sides with the tables.** The
document's eleven general parameters (spec p. 26) map to IDs 257, 258, 259, 260,
264, 265, 266, 267, 268, 269 (spec pp. 43–46) — ten of them — plus "Master Demo
Mode Enable", which has a line in the prose list and no row in any ID table. The
unit's twenty (§10) add 271–278, which the specification does document as
parameters but not as part of the dump (spec p. 52). §10's hypothesis that 270
or 279 is the unnamed "Master Demo Mode Enable" remains exactly that.

### Copy Master Setup

Command `2Ch` (spec p. 33). The frame, from the specification's own example
(spec p. 34):

    {F0h, 18h, 0Fh, dd, 55h, 2Ch, xx, xx, yy, yy, F7h}
    xx, xx = Source Master Setup Number (-1 = Setup Edit Buffer) LSB first
    yy, yy = Destination Master Setup (-1 = Setup Edit Buffer) LSB first

"Either the Source or Destination MUST be the Setup Edit Buffer."
"Copy destroys whatever Parameters existed in the Destination location."

Three things follow, all of them documented:

1. **There is no way to copy one stored setup over another.** One end must be
   -1, the edit buffer, which is not a stored location.
2. **The only way to make a stored setup current is to destroy the live one.**
   Combined with "Only the current setup can be dumped. If other setups need to
   be dumped, the "Copy Setup" command must be used first to make them
   "current"" (spec p. 26), this is the whole of multisetup browsing: dump to
   back up, copy N over the edit buffer, dump again, restore.
3. **-1 is 14-bit two's complement, and the specification spells the encoding
   out** (spec p. 79): "In the case of a 14-bit number this is equivalent to
   adding 16384 to the original negative value", then `msb = value DIV 128`,
   `lsb = value MOD 128`, transmitted lsb first. So -1 + 16384 = 16383 → lsb
   7F, msb 7F, and the edit buffer is `7F 7F` on the wire.

Worth noticing about p. 79 while transcribing it: the appendix computes the
"msb" first and transmits it *second*. Its own worked example is parameter 257 →
"2 in Hex = 02 = msb", "1 in Hex = 01 = lsb", "Parameter number would be
transmitted as 01 02" (spec p. 79). The byte order therefore agrees with
"Parameter ID (LSB first)" (spec p. 6) — but the formula's naming is exactly the
trap §2 warns about, and the example is the thing to copy rather than the
formula. The same page carries the one rule the wire format depends on and
§2's decoder relies on: "Status Bit MUST be "0" in MIDI data bytes" (spec p. 79).

**Nothing else about this command is documented.** There is no count byte in the
example, no checksum byte, and no reply. The handshaking commands — ACK `7Fh`,
NAK `7Eh`, CANCEL `7Dh`, WAIT `7Ch`, EOF `7Bh` (spec pp. 31–32) — are introduced
under "Dump Handshaking Messages" and belong to the multi-packet preset dumps,
not to a five-byte copy. And §2's point stands: the checksum is "1 Byte XOR(1's
complement) of the sum of the DATA bytes in the message. \*Only used in certain
messages. A checksum value of 7Fh means 'ignore checksum'" (spec p. 5) —
"certain" is doing a lot of work, and the copy examples carry none. A p2ked that
sends this has no documented way to learn whether it worked, which is one more
reason the read-back in `masteredit.py` is the right shape.

**How many setups there are: the E-MU documents agree and the parameter tree
does not.** "There are 128 setups numbered 0-127" (OM p. 31); "Proteus 2000
contains 128 Multisetup locations. These are all User locations which you can
use to store your own Multisetups" (OM p. 32). The parameter tree's
`RESTORE MULTISETUP` reads "0-63 or 0-127 (user programmable)" (paramtree,
MULTI BUTTON 3). The tree is hedging; the operation manual is not, twice.
p2ked's 0–127 is the documented one.

**Restoring a setup over MIDI** is `cc00 = 80, cc32 = 00` then a Program Change
(OM p. 31, p. 32) — and restoring *loads* it, replacing the live channel
configuration, which §9 already established is what makes browsing by name
destructive.

**What a setup holds, and the two documents differ by one item.** The operation
manual: "Preset/Volume/Pan assignments for each of the 32 MIDI channels", the
"Multisetup Name", and "ALL MASTER MENU PARAMETERS except…" the "MIDI Program
Change->Preset map" and the "User Key Tuning Tables" (OM p. 31). The
specification: "all settings selected by the Master Menu and settings made on the
Preset Select screen, with the exception of the program/preset map and tuning
tables (these can be dumped seperately)" (spec p. 26). The master menu's own
transmit screen names a third exception the specification does not: "Current
Multisetup — Transmits all parameters in the Master menu except Tuning Tables,
Program/Preset Map and Viewing Angle" (OM p. 51). The unit agrees with the
operation manual there: the general block contains nothing below id 257, so
`LCD_VIEW_ANGLE` (id 1, spec p. 41) is not in the dump (§10).

### Parameter Value Edit

Command `01h`. The frame, byte by byte, from the specification's own example
(spec p. 6):

    {F0h, 18h, 0Fh, dd, 55h, 01h, 02h, <xx, xx, yy, yy>, F7h}
       01h = Command::Parameter Value Edit
       02h = Byte count (number of Byte pairs)
       xx, xx = Parameter ID (LSB first)
       yy, yy = Parameter Data

"This command is used to change the value of one or more parameters." The count
is a count of *pairs*, not bytes: the example's single edit is count `02h` — one
pair for the ID, one for the value — and the count byte itself is not counted.
`p2k/messages.parameter_edit` sends `[0x02, id_lsb, id_msb, value_lsb,
value_msb]`, which is that frame exactly. Multi-parameter edits are one
`<xx, xx, yy, yy>` group per parameter, back to back (spec p. 6).

**The documented size limits.** "Please try to avoid sending messages with more
than 244 Data Bytes, or 41 Parameter Edits" (spec p. 6). The matching request
(`02h`) allows "more than 246 Data Bytes, or 123 Parameter IDs" (spec p. 6) —
note the request's higher allowance, and note that both are phrased as advice
rather than as a hard limit. 244 bytes is 122 pairs, so the 41-edit figure is
the binding one.

**Request and edit are the same message in opposite directions.** "The response
is a complete Parameter Value Edit SYSEX message for each parameter" (spec p. 6).
One frame format, one parser, and a value read by ID has no address to get
wrong. That is §9's whole point about `MIDI_MODE`, and it is why the write path
can be read back with the same command it sent.

**Three documented behaviours the edit screen has to respect:**

- **Out-of-range values are clipped, not refused.** "Values recieved that are
  outside the min/max range will be clipped to within that range" (spec p. 41).
  A client-side range check is therefore not a convenience; it is the only thing
  standing between a typo and a silently different value.
- **ROM data cannot be written.** "Preset information for ROM Presets may be
  requested, but cannot be changed. Any message trying to change ROM data will be
  ignored" (spec p. 41). Master parameters are not preset data, so this does not
  block the edit path, but it is the sentence that explains the asymmetry — and
  the reason a write's failure mode is silence.
- **There is a documented way to ask a parameter's range before writing it.**
  `Parameter Min/Max /Default Value` (`03h`) carries the minimum, maximum,
  default, and a trailing byte that is "Read Only (0 = Read/Write, 1 = Read
  Only, values above 1 reserved)", and it is the reply to `04h` (spec p. 7).
  Nothing in p2ked sends `04h`, and it is the obvious read-only companion to
  `probe_channel_ids`: an ID that does not exist should not answer, and one that
  is read-only should say so rather than accept the write and then be ignored.

**The documented error route does not work on this unit.** `Error Message`
(`70h`) is specified with `xx, xx` = "Command that failed to execute" and
`yy, yy` = "Sub-Command that failed to execute (if relevant, otherwise 0), or
Parameter ID that failed to Request or Update(invalid ID)" (spec p. 40). On the
strength of that, a bad parameter ID should come back named. §7 found the unit
ignores a request it cannot serve instead. So `probe_channel_ids` must treat
silence as ambiguous — a bad ID or a slow unit — and cannot lean on a documented
reply to tell the two apart.

**Pacing is a documented parameter, not a constant.** `MIDI_SYSEX_DELAY`
(id 405) is "min = 0; max = 8000 (milliseconds)" and is described as "Delay
between SysEx messages in multi-message dumps" (spec p. 47); the operation
manual's screen for it ranges "from 0 through 8000 milliseconds" and warns that
a value of zero "allows full speed MIDI transfer" (OM p. 51), and the parameter
tree agrees at "0-8000 milliseconds" (paramtree, MASTER BUTTON 29). A 970-byte
setup dump sent back, or forty-one parameter edits in one message, is exactly
what it is for — so the delay belongs on the wire-side of the edit gate rather
than in a sender constant.

### What is transcribed, and what the code has inferred

`p2ked/masteredit.py`'s docstring says its ranges are "transcribed from the
operator's manual's parameter tree (version 2.26) and the Master menu pages it
documents", and that "where the two disagree the manual's parameter tree wins,
because it is E-MU's own summary of what the unit stores". The first half is true
of most of the table. The second half is wrong on its own terms: the parameter
tree is not an E-MU document (paramtree, line 3), so it cannot be E-MU's own
summary, and where it disagrees with E-MU's own two documents it is a third-party
reading. The table itself, against all three documents:

| parameter | spec | OM | paramtree | p2ked |
|---|---|---|---|---|
| MIDI mode | 0–2, 0 = omni 1 = poly 2 = multi (p. 47) | Omni/Poly/Multi (p. 44) | omni, poly or multi (13) | 0–2 |
| MIDI mode change | 0–1 (p. 47) | accepted or ignored (p. 44) | ignored or accepted (13) | 0–1 |
| multimode basic channel | 0–15 (p. 42) | 01A–16A, 01B–16B (p. 26) | — | 0–32 |
| FX control channel | -1–15, -1 = Master FX, 0–15 = Channels 1–16 (p. 42) | "use master settings" for all 32 channels, or "preset on channel 1A" (p. 40) | 1-16A or 1-16B (6) | 0–32 |
| tempo control channel | 0–15, 0–15 = Channels 1–16 (p. 42) | Tempo Controller# / CHAN, 16A (p. 48) | 1-16A or 1-16B (22) | 0–32 |
| transpose | -12 to +12, with the note-name table (p. 44) | "± 24 semitones" (p. 36) | +/- 24 (1) | -24 to +24 |
| fine tune | -63 to +63 (p. 44) | "± 1 semitone in 1/64th semitone increments" (p. 36) | +/- 63 (1) | -63 to 63 |
| bend range | 0–12 (p. 44) | "±12 semitones or one octave in each direction" (p. 36) | +/- 12 semitones (2) | 0–12 |
| clock tempo | 0–500, 0 = external, 1–500 = bpm (p. 43) | "1 through 300 beats per minute" or "use MIDI clock" (p. 54) | use MIDI or 1-300 bpm (33) | 0–300 |
| FX bypass | 0–1 (p. 43) | bypassed or enabled (p. 40) | bypassed or enabled (5) | 0–1 |
| sysEx device ID | 0–126 (p. 47) | 000 (p. 44) | 0-126 (14) | 0–126 |

Six of the eleven match the specification's own min/max exactly — MIDI mode
0–2, MIDI mode change 0–1, fine tune -63 to 63, bend range 0–12, FX bypass 0–1
and the SysEx device ID 0–126 — and the parameter tree agrees with all six
(paramtree, MASTER BUTTON 13, 1, 2, 5, 14). The other five are where the
documents part company, and the disagreements are worth writing down because two
of them can silently truncate a write:

- **transpose.** The specification says -12 to +12 and prints the whole
  note-name table to prove it (spec p. 44); the operation manual says
  "± 24 semitones" (OM p. 36) and the parameter tree agrees (paramtree,
  MASTER BUTTON 1). p2ked uses ± 24. If the specification is the correct one, a
  transpose of +24 arrives as +12 (spec p. 41's clipping rule) — a write that
  looks like it worked. That is worth one cheap check on a unit: read id 259,
  write +24, read it back.
- **clock tempo.** The specification says 0–500 (spec p. 43); the operation
  manual and the parameter tree both say 1–300 (OM p. 54; paramtree, MASTER
  BUTTON 33). p2ked uses 300, siding with the two documents that agree with each
  other. The specification's 500 is the outlier here, as it was for the dump
  layout.
- **the three channel parameters.** The specification gives all three 0–15
  (spec p. 42); the operation manual documents 32 channels for all three
  (OM p. 26, p. 40, p. 48). p2ked gives 0–32, which matches neither. Given that
  basic channel 8 is the unit's channel 9 (§9), the wire numbering is 0-based and
  32 channels is 0–31, so the top value is off by one — and 32 is a number no
  document offers.
- **FX bypass's two labels.** Neither E-MU document says which number is which:
  the specification gives only min 0 max 1 (spec p. 43) and the operation manual
  shows a screen reading "enabled" (OM p. 40). The parameter tree lists
  "bypassed or enabled" (paramtree, MASTER BUTTON 5), and by that file's own
  convention — "13. MIDI MODE / omni, poly or multi" maps to 0, 1, 2 in order —
  0 is bypassed. p2ked's choices tuple reads `("on", "bypassed")`, i.e. 0 is on.
  That is the opposite of the only document that lists them in order, and it is
  an unforced guess in a table that looks transcribed.

**And one more that is not in the table at all.** `LCD_VIEW_ANGLE` is id 1,
"min = -7; max = +8" (spec p. 41); the operation manual says the angle "is
adjustable from +7 to -8" (OM p. 54) and the parameter tree says "-8 to +7"
(paramtree, MASTER BUTTON 34). The two disagree about which end owns the extra
step. Nothing is at stake — it is not in the dump and p2ked does not write it —
but it is the same shape as the transpose disagreement and it is why a range
should never be taken from one document alone.

### The master FX block: sixteen parameters, transcribed the same way

**2026-10-10.** TODO 50 was the FX half. The general table above had eleven
parameters; the dump's master effects block — sixteen values — was read and not
writeable, and the edit screen had no way to show it. It is transcribed now, and
the shape of the transcription is the general one's: an **ID** that came from a
unit (§10), a **label and range** that came from the manuals, and a page cite on
every number.

**The block is the unit's, and the words are the documents'.** Ids 513-528 are
the dump's own master effects block, which §10 established by reading each value
back from a unit and agreeing it with the dump. What no unit supplied is the name
of each value or its range: those come from the specification's parameter table
(spec p. 49), the operation manual's Master menu pages (OM pp. 41-43) and its
Effects chapter (OM pp. 145-146), and the parameter tree's `MASTER BUTTON` items
5-12 and `EDIT BUTTON` 34-38.

| id | spec p. 49 name | min | max | what the other documents say | p2ked |
|---:|---|---:|---:|---|---|
| 513 | MASTER_FX_A_ALGORITHM | 1 | 44 | "There are 44 “A” effects" (OM p. 145); the numbered list, Room 1 to DelayVerb 9 (OM p. 41, again at OM p. 121); "select effect 1-44" (paramtree, EDIT BUTTON 34) | 1-44, 44 named |
| 514 | MASTER_FX_A_DECAY | 0 | 90 | "The Decay value range is from 0 through 90" (OM p. 146); 0-90 (paramtree, MASTER BUTTON 8) | 0-90 |
| 515 | MASTER_FX_A_HFDAMP | 0 | 127 | "The value range for High Frequency Damping is from 0 through 127" (OM p. 146); 0-127 (paramtree, MASTER BUTTON 8) | 0-127 |
| 516 | MASTER_FXB_SEND_FXA | 0 | 127 | "FxB>FxA … 001" (OM p. 42); 0-127 (paramtree, MASTER BUTTON 8) | 0-127 |
| 517 | MASTER_FX_A_MIX_SEND 1 | 0 | 100 | "FXA SEND AMOUNTS 1:100% 2: 50% 3: 10% 4: 0%" (OM p. 42); 0-100% (paramtree, MASTER BUTTON 9) | 0-100 |
| 518 | MASTER_FX_A_MIX_SEND 2 | 0 | 100 | as above | 0-100 |
| 519 | MASTER_FX_A_MIX_SEND 3 | 0 | 100 | as above | 0-100 |
| 520 | MASTER_FX_B_ALGORITHM | 1 | 32 | "There are … 32 “B” effects" (OM p. 145); the numbered list, Chorus 1 to Distorted Double (OM p. 43, again at OM p. 122); "select effect 1-32" (paramtree, EDIT BUTTON 37) | 1-32, 32 named |
| 521 | MASTER_FX_B_FEEDBACK | 0 | 127 | "The Feedback value range is from 0 to 127" (OM p. 146); 0-127 (paramtree, MASTER BUTTON 11) | 0-127 |
| 522 | MASTER_FX_B_LFO_RATE | 0 | 127 | "The LFO Rate value range is from 0 to 127" (OM p. 146); 0-127 (paramtree, MASTER BUTTON 11) | 0-127 |
| 523 | MASTER_FX_B_DELAY | 0 | 127 | "The Delay value range is from 0ms to 635ms" (OM p. 146); see below | 0-127 |
| 524 | MASTER_FX_B_MIX_SEND 1 | 0 | 100 | "FXB SEND AMOUNTS 1:100% …" (OM p. 43); 0-100% (paramtree, MASTER BUTTON 12) | 0-100 |
| 525 | MASTER_FX_B_MIX_SEND 2 | 0 | 100 | as above | 0-100 |
| 526 | MASTER_FX_B_MIX_SEND 3 | 0 | 100 | as above | 0-100 |
| 527 | MASTER_FX_A_MIX_SEND 4 | 0 | 100 | the fourth FXA send (OM p. 42; paramtree, MASTER BUTTON 9) | 0-100 |
| 528 | MASTER_FX_B_MIX_SEND 4 | 0 | 100 | the fourth FXB send (OM p. 43; paramtree, MASTER BUTTON 12) | 0-100 |

**Sixteen, not seventeen.** The brief for this work called the block "the
17-value FX section". It is sixteen: 513-528 inclusive, which is the
specification's own count — "Number of Master Effects Parameters (16)" (spec
p. 48) — and the dump's declared count (§10). The seventeenth value is id 512,
which the specification prints `(RESERVED)` (spec p. 49) and §10 established the
unit does not send at all. Counting it would have produced a table with a
parameter in it that no dump carries and no page names.

**The block's order is the dump's, and the front panel's is different.**
`FX_PARAMETERS` follows 513-528, which is the specification's table order (spec
p. 49) and `MASTER_BLOCKS`'s order. The unit's own screens list each processor's
four send amounts together (OM pp. 42-43; paramtree, MASTER BUTTON 9, 12); the
dump carries sends 1-3 of each processor in the middle of the block and both
fourth sends at the end. So the two orders disagree about where the fourth send
sits, and a reader looking for "FXA send 4" beside 1, 2 and 3 on the front
panel's screen will not find it. The dump wins, because a value read by ID is a
value *of* that ID: the ID is the protocol's own name for the number, and the
front panel's grouping is a screen layout rather than a statement about the
wire.

**The two algorithms are the block's only enumerations, and they are numbered
from 1.** The specification gives both a min of 1 (spec p. 49); the operation
manual numbers its two lists from 1 — the A list on OM p. 41, the B list on
OM p. 43 — and the tree says "select effect 1-44" and "1-32" (paramtree, EDIT
BUTTON 34, 37). So `MasterParameter.base` is 1 for those two rows and 0 for
the other fourteen — an off-by-one that would have made the
picker offer a blank row and then send one value too few. The corroboration is
indirect and worth writing down: the *preset's* FXA algorithm screen carries an
extra choice, "Master Effect A", meaning "use the master setting" (OM p. 149),
which is exactly the slot a 0 would occupy in the same numbering. That is an
inference from the document's list, not a read-back: **nobody has read id 513
and compared the number with the name on the unit's display.**

**FX B delay is the one value whose units are not its own number, and the two
documents do not agree.** The operation manual says only "The Delay value range
is from 0ms to 635ms" (OM p. 146), and its own screens display a plain number of
milliseconds — "200ms" (OM p. 123), "145ms" (OM p. 149), "635ms" (OM p. 148). 127
× 5 ms is 635 ms exactly, which *fits* a 5 ms step, but no document prints a
step. The parameter tree disagrees with both readings and puts them in one line:
"(1/4d, 1/2t, 1/4, 1/8d, 1/4t, 1/8, 1/16d, 1/8t, 1/16, 1/32d, 1/16t, 1/32 or
0ms - 635ms in 5ms increments)" (paramtree, MASTER BUTTON 11; the same line at
EDIT BUTTON 38) — twelve note values *and* a millisecond range, with no rule for
where one stops and the other starts. p2ked keeps the raw 0-127 and gives the
parameter no named values: a picker built on the tree's list would send a time
nobody asked for, and a conversion built on the 5 ms step would be arithmetic
the manual does not print. It is the one range in this block a hardware session
should settle, and it costs four writes: write 0, 1, 12 and 127 to id 523,
reading each one back.

**The general block's FX bypass is not in this block.** The front panel's
"FX MODE" (paramtree, MASTER BUTTON 5) — "bypassed or enabled" — is id 258, in
the master general block, and it is already in the general table above with its
own disagreement recorded. The FX screen says so in its note, because a reader
who opened it to turn the effects off would otherwise conclude that cannot be
done.

**What the FX block does not settle that the general one does not either.**
None of these sixteen ranges has been checked against a unit. Unlike the general
block, though, the two E-MU documents *agree* on all sixteen of them, so there is
no internal disagreement to report — and no evidence either. The FX block also
carries no parameter the specification leaves unnamed, where the general block
carries three (270, 279 and 660, §10).

What §12 does **not** settle, and says so:

- The nine per-channel parameter IDs' *names* beyond spec p. 41's table. ARP and
  BANK_MAP have no front-panel screen in the operation manual and no entry in
  the parameter tree, and the specification offers no explanation of either.
- **Whether 513's value 1 is "Room 1" and 520's value 1 is "Chorus 1".** Two
  documents agree on the *count* (44 and 32, spec p. 49; OM p. 145; paramtree,
  EDIT BUTTON 34, 37) and the ordering is the manual's own list — but nobody has
  read either parameter back and compared the number with the name on the
  screen. It is one read on a unit, and the cheapest check in this section.
- **What FX B delay's 0-127 is worth in milliseconds**, and whether the
  parameter tree's twelve note values exist anywhere on the wire. See above.
- Whether any of the documented ranges is what this firmware enforces. Every
  disagreement above is between documents; the unit has not been asked. That is
  the hardware session's job, and it is the difference between a transcription
  and a fact.

### The dump is a writable message too

**2026-10-10.** p2ked has read a Setup Dump since §8 and has never written one.
`encode_setup_dump(dump, *, device)` in `p2k/messages.py` is now the inverse of
`parse_setup_dump`, byte for byte, and it exists for one reason: the next
feature is a per-channel edit, and the dump is the only route to a per-channel
value that no document numbers. Two things are worth writing down before anyone
sends one, and the first is what the specification actually licenses.

**The sentence that licenses it.** "The generic dump replaces the setup dump
(command 1Ch) as the new dump format sent by the command stations" ... "The
command stations still receive and understand the old setup dump and will
transmit one if explicitly requested to do so via sysex" (spec p. 29, under
"Generic Dump Request"). Read plainly: a command station *sends* `61h` now and
*receives* `1Ch` still. That is the whole authority for the encoder — a receive
path is documented, in the one document that describes the message, and nothing
more. The frame to send is the specification's own example,
`{F0h, 18h, 0Fh, dd, 55h, 1Ch, aa, aa, ... F7h}` (spec p. 28), which carries no
checksum byte anywhere in it.

**Caveat one: an incoming dump replaces the whole setup.** What a Setup Dump
covers is "all settings selected by the Master Menu and settings made on the
Preset Select screen, with the exception of the program/preset map and tuning
tables" (spec p. 26). So there is no such thing as sending one field: a
per-channel edit is a whole-setup write whose other bytes are the ones the unit
sent a moment ago. That is stronger than it sounds — the round trip is
byte-for-byte, so an edit moves the two bytes of the edited field and nothing
else (`TestSetupDumpEncoder.test_an_edit_changes_only_the_bytes_it_should`,
tests/test_messages.py) — and weaker than it sounds: the write carries the
setup *as p2ked decoded it*, and a dump p2ked could not fully decode is refused
rather than written back with 0 in the gaps. The two things a dump does not
carry, the program/preset map and the tuning tables, are untouched either way.

**Caveat two: no unit has received one from p2ked.** Every other claim in this
section is a transcription from a document. This one is a documented receive
path p2ked has never exercised, in a project whose documented error route does
not work on this unit (§7): a message the unit cannot serve is ignored rather
than refused, so the failure mode is silence and the only verification is the
unit's own answer. `make test-hardware` should therefore send back an
*unmodified* dump — the one `read_setup` just returned, re-encoded and nothing
else — and compare it with what came in. That is the first verification, and it
is the least that can be written and still exercise the path: it replaces the
live setup with a copy of itself. Until it has happened, `encode_setup_dump` is
a builder nothing has called on a cable.

---

## §13 — Per-channel editing, by writing the whole setup back

**2026-10-11.** p2ked read a channel's nine values out of one Setup Dump since
§8 and refused to set any of them, because setting one needed its parameter ID
and no document to hand lists those. The refusal is gone. The write goes the
other way round: the dump itself is the message, so nothing needs numbering.

**The sentence that licenses it.** "The generic dump replaces the setup dump
(command 1Ch) as the new dump format sent by the command stations" ... "The
command stations still receive and understand the old setup dump and will
transmit one if explicitly requested to do so via sysex" (spec p. 29, under
"Generic Dump Request"). Read plainly, and in the direction that matters here:
a command station *sends* `61h` and *receives* `1Ch`. That is the whole
authority — a documented receive path in the one document that describes the
message, and nothing more.

**What one write covers.** "All settings selected by the Master Menu and
settings made on the Preset Select screen, with the exception of the
program/preset map and tuning tables" (spec p. 26). There is therefore no such
thing as a one-field write: a per-channel edit is a whole-setup write whose
other bytes are the ones the unit sent a moment earlier. §12 recorded that as
caveat one and it is now the mechanism rather than a caveat — read the live
dump, change the one channel's one field, re-encode, send, read again, verify
the field.

**Why the other bytes are the unit's own.** The encoder is the byte-for-byte
inverse of the parser (§12), so a dump re-encoded unchanged is the same frame
the unit sent. An edit therefore moves the two bytes of the edited field and
nothing else, and that is asserted three times over:
`TestSetupDumpEncoder.test_an_edit_changes_only_the_bytes_it_should`
(tests/test_messages.py) at the encoder, and
`TestTheMutationIsTheOnlyThingThatMoves` (tests/test_channel_edits.py) at the
mutation, which compares whole frames and checks the offsets that moved. A
value past 127 moves both bytes of its field, which the second of those pins
so an encoder that only moved the low byte would not pass.

**The rule survives unchanged: no parameter ID is invented.** This route writes
the dump's own field positions — the nine §8's structural search found and
`_setup_dump_payload` puts back where it found them — so there is no number to
address and nothing to guess. `CHANNEL_EDIT_IDS` stays `None`,
`probe_channel_ids()` stays the read-only probe it was, and item 47 stays open
as the *alternative*: one small frame per field instead of a ~1 KB whole-setup
write, once a session with a unit has established which ID is which field.

**One frame, and no size cap in the path.** A dump is one SysEx message by
definition — splitting it would produce something the parser could not read —
and `ProteusBridge.send_setup_dump` hands the whole frame to `send_message` in
one call, as every other message here does, with `SEND_GAP` after it. The
specification's size advice ("try to avoid sending messages with more than 244
Data Bytes, or 41 Parameter Edits", spec p. 6; §12) is advice about *parameter
edits* batched into one message, and 244 bytes is 122 pairs, so the binding
figure there is the 41-edit one. Nothing in this path truncates or chunks, and
there is no limit to report: the demo's dump is a 970-byte payload in a 977-byte
frame, which is the size §8 read off a real unit in the first place — the unit
sends one of these back on request, so a 977-byte frame is not a thing this
family has never seen.

**Where each piece lives.**

- `p2ked/masteredit.py` — the rules, with no I/O in them:
  `mutate_channel(dump, channel, values)` is the pure planner that builds a new
  `SetupDump` with one channel replaced; `allow_channel_field` and
  `allow_channel_sound` are the gate and the transcribed ranges in
  `allow()`'s own refusal style; `decline_channel` refuses what needs a dump in
  hand (a channel this setup does not have, a dump that did not fully decode);
  `finish_channel` logs only what the read-back agreed with; `ChannelChange`
  is the undo record, `ChannelLog` its log, and `channel_undo_plan` /
  `channel_undo_report` the `z` half.
- `p2k/bridge.py` — `send_setup_dump(dump)`, the wire. Sent, then not
  verified, like `set_parameter`: the gate, the read-back and the log are the
  caller's.
- `p2ked/demo.py` — the same method, and it *adopts* the frame: the fake's
  next `read_setup` answers with what it was given. A fake that recorded a
  whole-setup write and carried on answering its original dump would make
  every read-back agree, including the ones that should fail.
- `p2ked/app.py` — `action_edit_channel(channel, field, value)` and
  `action_channel_sound(channel, rom_id, preset, bank_map)`, the two callbacks
  the UI calls. Gate and range on the main thread, MIDI on a worker, and the
  read-back decides whether the edit is logged and whether it joins the one
  timeline `z` reverses. A channel undo re-reads the dump and restores
  `before` — the unit may have been touched by hand in between, and the old
  value belongs in the channel the unit reports now.

**One entry for a sound.** `rom_id`, `preset` and `bank_map` are what aims a
channel at a sound, and the unit takes them together, so
`action_channel_sound` writes all three in one dump, verifies all three, and
records **one** `ChannelChange` under `SOUND_FIELD`. Three `z` presses that
each restored a third of a sound would not put back the sound anybody had.

**Caveat: no unit has received one from p2ked.** Everything above is a
transcription plus a synthetic test suite. The receive path is documented and
has never been exercised on a cable, the documented error route does not work
on this unit (§7), so a dump the unit cannot serve is *ignored* and the only
evidence either way is the read-back. `make test-hardware` should therefore
start where §12 said it should: send back an unmodified dump — the one
`read_setup` just returned, re-encoded and nothing else — and compare what the
unit reports afterwards with what came in. Until that has run,
`send_setup_dump` is a builder nothing has called on hardware, and every
sentence in this section is about p2ked rather than about a Proteus.
