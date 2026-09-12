<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# p2ked

A terminal browser for the **E-MU Proteus 2000** family's presets.

> **Prototype. Its read path works; most of it is still unverified.**
> Identity, hardware configuration, preset names and the setup dump were
> exercised against a real Proteus 2000 on 2026-09-12. Parameter edits,
> preset dumps and the checksum rule were not, and 16 of its 20 ROM rows
> have never been seen on hardware. **Read [DISCLAIMER.md](DISCLAIMER.md)
> for which is which.**

Two panes: every bank the unit can be sent to on the left, that bank's
presets on the right, and on every row the three numbers that actually
select a sound — Program Change, Bank Select LSB and Bank Select MSB, in the
order a sequencer's MIDI track asks for them.

```
 bank                    MSB LSB   n     #    name            PC   LSB  MSB  ROM#
 User bank 0             0   0     128   003  Velvet Bell      3   0    0    3
 User bank 1             0   1     128   004  Rusted Pad       4   0    0    4
▸Xtreme Lead bank 1      7   1     128  ▸005  Woven Bell       5   1    7    133
 Xtreme Lead bank 2      7   2     128   …

 Xtreme Lead bank 1 005  Woven Bell
 Program Change 5   Bank Select LSB 1 (CC#32)   MSB 7 (CC#0)   preset 133 within Xtreme Lead
```

## What it does

- **Every ROM the family addresses** — the four user banks plus 19 ROM
  SIMMs, 74 banks and 9472 addressable presets. MSB identifies the ROM, LSB
  the bank within it, Program Change the preset.
- **Reads preset names off the unit, silently.** A Proteus answers a Generic
  Name Request for any preset in any fitted ROM *without selecting it*, so
  `r` reads a whole bank while the instrument keeps playing whatever it was
  playing. There is no prompt and no `--yes`, because there is nothing to
  warn about. (The sibling rxved cannot do this at all: an XV-2020's preset
  banks have no addresses, so learning their names means playing them.)
- **Asks the unit what ROMs are fitted.** `Configuration Request` reports
  the installed SIMMs with their IDs and preset counts, so nothing has to be
  guessed — with one caveat below.
- **Names from two sources, kept distinct.** The printed catalog and what
  the unit says. A name read from hardware is shown in bold; one that
  *disagrees* with the catalog gets a `*`. On a user bank somebody has saved
  into, that mark is the most useful thing on the screen.
- **A CLI** (`p2kcli`), most of which needs no unit at all.

### Channels (`m`)

One Setup Dump request returns the whole multi configuration, so `m` shows
all **32** channels — this family has two MIDI interfaces — with what each
one plays, resolved to a ROM, a preset number and a name, plus why a channel
would make no sound.

Two things it deliberately does not claim. It does not say the unit is in
**Multi** mode: in Omni or Poly a Proteus is not multitimbral and none of
these settings apply, and that byte is in the part of the dump p2ked cannot
yet decode. And "channel 20 is enabled" says nothing about whether anything
is plugged into the second interface.

Note the word: **"multi" means two things on this machine.** Multi is one of
three MIDI *modes* (Omni / Poly / Multi). A *Multisetup* is something else —
a stored snapshot of all 32 channels, 128 of them, selected with MSB 80 /
LSB 0 and a Program Change. This screen shows the live channel state, which
is the first of those. Browsing Multisetups is not built yet.

### The two numbers that identify a ROM

- the **Bank Select MSB**, used to select a preset;
- the **SIMM ID**, which the unit reports and which System Exclusive uses as
  the "ROM ID" when asking *about* a preset.

**No E-MU document to hand maps one to the other.** p2ked assumed they were
the same number, and a unit confirmed it on 2026-09-12: three fitted ROMs
each named the presets p2ked's catalog holds for the ROM at that MSB,
character for character. Three of twenty, so `p2kcli config` still states
what was checked. The one ROM ID that is also *documented* is `0`, meaning
user memory.

One ROM in the table got there the other way round. A unit reported SIMM ID
14 with 640 presets and no file to hand covered MSB 14 at all; it was
identified as **X-Lead v2** from E-MU's own patch list for that ROM, and
`tools/extract_catalog.py` now reads those OpenDocument lists so its names
are catalogued too.

## Install

```sh
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e .
```

Needs Python 3.11+, `python-rtmidi` and `textual`.

## Run

```sh
p2ked --demo           # built-in demo device; opens no MIDI ports
p2ked                  # autodetect a Proteus-family unit
p2ked --port "E-MU Proteus 2000 MIDI 1"
```

Autodetect broadcasts a Universal Identity Request on every bidirectional
port and matches the reply's manufacturer byte. The reply carries the device
ID the unit is set to, so discovery ends knowing what to address — no sweep
over 127 IDs.

### Keys

| | |
|---|---|
| arrows, `tab` | move; `tab` switches pane |
| `enter` | select this preset **on the unit** — it will sound |
| `r` | read this bank's names from the unit — **silent** |
| `m` | every MIDI channel: what it plays and why it might not — **silent** |
| `/` | search names |
| `c` | set the MIDI channel selections go out on |
| `i` | device identity and which ROMs are fitted |
| `?` / `q` | help / quit |

**Moving the cursor never sends anything.** That is enforced by a test, not
just by intent: it is the property that decides whether you can leave this
open next to a running sequencer.

### Command line

```sh
p2kcli roms                     # the ROM table (no unit needed)
p2kcli list XLEAD-1             # one bank's presets (no unit needed)
p2kcli find "bell"              # search names (no unit needed)
p2kcli resolve 7 1 5            # what does this MSB/LSB/PC select?
p2kcli ports                    # MIDI ports on this host
p2kcli --demo config            # which ROMs are fitted
p2kcli --demo channels          # every MIDI channel (silent)
p2kcli --demo names XLEAD-1     # read a bank's names (silent)
p2kcli select XLEAD-1 5         # select a preset ON THE UNIT
```

## Preset names are not included

p2ked ships **no** E-MU content. The ROM table, the bank arithmetic and the
three numbers are its own; only the names are E-MU's, and those you generate
locally:

```sh
python3 tools/extract_catalog.py --ins ~/path/to/P2k_All.ins \
    --odt "XLEAD2=~/path/to/X-Lead v2 patch list.odt"
```

That reads your own copy of the Cakewalk instrument-definition files and
writes `p2k/data/catalog.json`, which is gitignored. It currently produces
**9472 names across 74 banks**. p2ked works without it, showing numbers
only — and a connected unit can supply every name itself.

The extractor checks its input rather than trusting it. The file shipped for
this family indexes one ROM's third bank as `Patch[1281]` while the section
itself is labelled `(1282)`; taken at face value that puts bank 2's 128
names under bank 1's numbers and loses bank 2 entirely. The section's own
label wins, the correction is reported on stderr, and `p2k/roms.py` carries
the third bank the index would have hidden.

## Licence

GPL-2.0-or-later. See [LICENSE](LICENSE) for the project's copyright notice
and third-party attributions, and [COPYING](COPYING) for the licence text.

Not affiliated with E-MU Systems or Creative Technology.
