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

## Support this project

p2ked is free software and always will be. Nothing is behind a paywall, no
feature is withheld, and none of what follows changes that.

(These paragraphs describe the family's bench, which is shared between the
sibling tools. p2ked's own share of it is the Proteus 2000 and the ROMs read
from it in the hardware sessions recorded in `docs/RESOLUTION_NOTES.md`.)

But if it has been useful — if it saved you reading a ROM's worth of preset
names off the front panel one slot at a time, or told you which ROMs are
fitted without you touching the unit, or **best of all, if it has your
vintage instrument switched on and in use more often than it was, and you
are having more fun with it** — then please consider supporting the work.

**Because here is what it has actually cost:**

- **Real machines on a real bench.** Much of what these tools know about these
  formats was measured on hardware rather than read anywhere, because for most
  of it there is nowhere to read it. That needs the machines — the instruments
  themselves — and it puts hours of wear on hardware that has been locked up and
  recovered more than once in the course of it. Some of these instruments were
  bought specifically to add and verify a format; the others were already here,
  because the person doing this is a vintage instrument enthusiast first and the
  projects exist because the instruments were in the room.
- **Dozens — realistically hundreds — of hours of human time.** Format
  reverse-engineering is slow: measure, be wrong, measure again. A single
  parameter law in this README can represent an evening at the bench.
- **AI assistance, which is a paid service**, used heavily throughout and not
  cheap at this volume.

**This is support, not a donation — and the distinction is a legal one, not a
turn of phrase.** The maintainer is based in Germany, where payments like these
are *not* `Spenden` in the tax sense: they count as **taxable income** for the
recipient and are **not tax-deductible** for the giver. So this section is
titled *Support*, deliberately, and no receipt for tax purposes can be issued.
(That is a statement of how it is handled here, not tax advice.)

If the project saved you the work, you can support it through
**[GitHub Sponsors](https://github.com/sponsors/lentferj)** — the *Sponsor*
button at the top of the repository. Payment is handled entirely by GitHub and
Stripe, so bank and tax details are never handed to the person paying.

**Support is not expected, and it is not the only currency.**

- **Bug reports** — ideally with the bank and preset numbers involved, the
  exact command line, and what the unit did. A failure is usually specific
  to one ROM or one unit rather than general, and without that detail it is
  very hard to reproduce.
- **Confirmations from hardware that is not on this bench**, which matters more
  here than for a single-machine tool. These tools write for whole *families*
  of instruments, and the bench holds only a subset. Whether a variant accepts
  what we write is genuinely unknown, and several notes say "on this unit" for
  that reason. A "loads fine here too", or a "no, mine refuses it", is worth a
  great deal.
- **Corrections to the reverse-engineering notes.** The wrong turns are
  recorded next to the findings in `docs/RESOLUTION_NOTES.md` — retractions
  included, because a finding that was withdrawn is as useful as one that
  stood. If any of it is wrong in a way that is still costing someone time,
  saying so improves the record.

---

## AI assistance & human authorship

p2ked was built by its human author together with AI assistance. The
**ideas, the project vision, and every feature** came from the human author;
AI assisted with **writing the code and analyzing the binary formats**.
Crucially, the **reverse engineering rests on hands-on human work** — all testing
and verification on real hardware, creating the reference images/banks on those
instruments (disk saves, SysEx probes), and aural A/B comparison of presets —
which is what makes the results correct.
Full account in [DISCLAIMER.md](DISCLAIMER.md).

---

## ⚠️ Use at your own risk — back up first

p2ked is provided **as is, with absolutely no warranty and no liability**
for data loss or **hardware damage**. You assume all risk. Full terms:
[DISCLAIMER.md](DISCLAIMER.md).

p2ked **reads** the unit, can **select** a preset, which makes sound, and can
**write master parameters** — behind a write gate that is locked by default.
Preset memory is never written: a Proteus ignores any message that would
change ROM data, and p2ked does not try. Other tools in the family do write
to hardware and storage media, and this warning is the family's. Even so:
**make good, current backups of all your files** — and of any existing
banks on your instrument and storage media — before you start. A mistake, a
bug, or untested output could overwrite or corrupt data, or be rejected by
hardware. Always test on a spare unit or emulator **before** connecting
irreplaceable equipment.

---

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
- **Edits the master parameters, and the 32 channels, behind a write gate
  that is locked by default.** `w` arms the gate, `--allow-write` starts it
  armed, every edit is read back to check it landed, and `z` / `Z` send the
  previous value back. Only parameters whose IDs were established by reading
  them off a unit are offered; the per-channel fields are written by the
  dump route instead, with no ID invented — see Editing below.
- **A CLI** (`p2kcli`), most of which needs no unit at all.

### Channels (`m`)

One Setup Dump request returns the whole multi configuration, so `m` shows
all **32** channels — this family has two MIDI interfaces. The dump carries
nine parameters for each one: preset, volume, pan, mix output, arpeggiator,
enable, bank map, whether it receives Program Change, and the ROM ID. The
table is channel, what that preset is — resolved to a ROM, a preset number
and a name — volume, pan, output, Program Change receive, arpeggiator and
ROM, plus a **why not** column: the reasons a channel would make no sound,
every one of them a value the unit reported rather than an inference about a
cable.

Above them sits the master panel: clock tempo, transpose, bend range, the
basic, FX and tempo control channels and the SysEx device ID — the settings
those channels are played through.

It says which **MIDI mode** the unit is in, because that decides whether any
of it means anything. In Omni or Poly a Proteus is not multitimbral: it plays
one preset and ignores every channel setting on this screen, so the screen
says so rather than letting somebody debug a channel that was never in play.
The mode is read as parameter 385 directly — one request, no layout, no way
to be wrong (see RESOLUTION_NOTES §9).

What it still does not claim: **"channel 20 is enabled" says nothing about
whether anything is plugged into the second interface**, and none of the
reasons mention the cable, an unplugged submix jack or the monitor, because
the unit does not report them.

`r` re-reads the setup from inside the screen. `enter` on a row opens that
channel's **detail** — all nine parameters, the why-not reasons, and what an
edit would send. The **editing** lives on the table itself: the cursor is a
cell cursor, so the arrows walk over the nine values and a gesture changes
the one under it — see Editing below. `e` is the door to the master
parameters and `x` to the master FX block. The MIDI channel selections go
out on sits in the window's subtitle for as long as the window is open, not
only for the moment it changes.

Note the word: **"multi" means two things on this machine.** Multi is one of
three MIDI *modes* (Omni / Poly / Multi). A *Multisetup* is something else —
a stored snapshot of all 32 channels, 128 of them, selected with MSB 80 /
LSB 0 and a Program Change. This screen shows the live channel state, which
is the first of those. Browsing Multisetups is not built yet.

### Editing (`w`, `z`, `Z`)

`e` on the multi screen opens the **master parameters** — the eleven settings
a channel map is played through: MIDI mode and whether an external one is
accepted, the basic, FX and tempo control channels, transpose, fine tune,
bend range, clock tempo, FX bypass and the SysEx device ID. `enter` on a row
offers that edit: a parameter with named values — the MIDI mode is omni /
poly / multi — opens the picker and ⏎ picks; a plain range gets a prompt
that names the range with it. `+` and `-` nudge the row under the cursor by
one, clamped to the range, and go through the same gate as an edit.

`x` on the multi screen opens the **master FX** — the sixteen FX parameters
the dump carries (513–528: the two algorithms, their decays, damping,
feedback, LFO, delay and the eight sends). Same gate, same read-back, same
undo, and the algorithms are *named* lists — 44 and 32 names — picked
rather than typed. The value is checked before anything is sent, because a
Proteus **clips** an out-of-range value rather than refusing it — a typo
would otherwise land as a plausible, silent change.

Everything here is behind a write gate, the family's editor shape rather
than something this tool invented:

- **The gate is locked by default.** `w` toggles it, and its state is on the
  screen and in the legend, so "why did my edit not send?" is answered where
  the question is asked rather than in a keybinding manual. `--allow-write`
  starts it armed, for a session that is going to edit anyway. Nothing is
  sent while it is locked, and a refusal says which of the two it was: the
  gate, or the range.
- **Every edit is read back.** A Proteus *ignores* a request it cannot serve
  rather than refusing it, so a write that did not land looks exactly like
  one that did until something reads the value again. p2ked reads the
  parameter, sends the edit, reads it once more, and reports a disagreement
  instead of trusting the wire.
- **Only a verified edit is undoable.** `z` sends the previous value back and
  `Z` all of them, newest first. An edit the read-back did not confirm is not
  in the log, because nothing landed to restore — and that is the reason
  "undid 2 edits" can be fewer than the number of edits attempted. A
  favourite toggle is a change too: it sits in the same timeline, and `z`
  flips the slot back in the local database — no frame goes out for it.

Both undo keys work from the browser as well, not only from the edit screen:
an edit is made *through* the screen and undone *after* it closes, so the app
holds the log and the undo worker.

**The per-channel route is a whole-setup write, and it says so.** A
Proteus "receive[s] and understand[s] the old setup dump" (spec p. 29), so
p2ked reads the live dump, changes one channel's one field and sends the
dump back — every other byte is the one the unit just sent
(`tests/test_messages.py`'s `TestSetupDumpEncoder` proves the round trip is
byte-exact). The gate applies and the field is read back, exactly as a
master edit is. **No parameter ID is invented**: this writes the dump's own
field positions. No unit has received one yet — the first check is `make
test-hardware`'s unmodified-dump round trip — and the ID-based alternative
still needs `docs/TODO` item 47's probe, which would cost one small frame
per field instead of a ~1 KB whole-setup write.

**The channels screen is editable cell by cell** (`m`, then any of the
gestures below). The cursor is a *cell* cursor: the arrows walk over a row's
nine values and the gesture changes the one under them. This is the shape
rxved's multi table uses, and the reason is the same one — a row-wide cursor
cannot say which of nine values a keystroke was aimed at.

| gesture | what it does |
|---|---|
| `⏎` on `ch`, `why not` | that channel's detail — read-only |
| `⏎` on `vol` or `pan` | a prompt with the range and the current value |
| `⏎` on `out` or `arp` | the list of names, because a document names the values |
| `⏎` on `plays` or `ROM` | the sound picker — the same as `s` |
| `+` / `-` (and `=`) | step the number under the cursor, clamped |
| `space` | flip `on` or `rxPC` |
| a digit | type a number in place: the digits sit on the screen's own status line, `⏎` writes, `esc` cancels |
| `s` | pick a sound for the channel — writes `rom_id`, `preset` **and** `bank_map` together |
| `w` | the write gate, on this screen too, because a modal cuts the app's binding chain |

`out` is the mix output, and its four values are the ones spec p. 41
documents: -1 "use preset", 0 "send 1", 1 "send 2", 2 "send 3". The
parameter tree prints "use preset or send 1-4" — five names against a
four-value field — and the code shows the four the field holds.
`arp` gets its four names from the same table (-2 off, -1 on, 0 P (preset
arp), 1 G (global arp)); that is the whole of what any document to hand says
about the field, so the list stops there. Every other field is a number.

A nudge that cannot move — `+` at the top of a range — says the range and
sends nothing, because a per-channel edit is a whole-dump write and
re-sending a value the unit already holds would put an entry on the undo
timeline that restores something that was never changed.

**The sound picker's filters, against rxved's.** `s` opens a bank pane, that
bank's presets with their names, the favourites cycle on `v` (the same three
views the browser has, and a sentence rather than an empty list when there is
no store), and a name filter — the one rxved's multi picker does not have,
because its `/` search lives on the browser and the picker scrolls. Its bank
list and favourites views match. The **ROM ID** the pick writes is that ROM's
Bank Select MSB, which is what `rom_for_simm_id` reads a reported SIMM ID
as: confirmed against hardware for three ROMs on 2026-09-12, which is not all
twenty, and the picker says so rather than leaving a column of numbers
looking transcribed.

**What a pick writes.** `rom_id`, `preset` and `bank_map` together, as one
change — the unit takes the three together, and three `z` presses that each
restored a third of a sound would not put back the sound anybody had.
`bank_map` is carried over from the channel rather than set: no document to
hand says what the Multimode Bank Map maps between (RESOLUTION_NOTES §12), so
the picker changes the sound and leaves the channel's own mapping alone.

**No write has been sent to a Proteus from this editor yet.** The IDs were
established by reading them back off a unit and comparing them with the dump
— 82 values, all agreeing (RESOLUTION_NOTES §10) — but the *ranges* are
transcribed from documents that disagree with each other in five of the
eleven places (§12), and no unit has been asked which range its firmware
enforces. Every write so far has been verified against `DemoDevice`. Treat
the first real edit as a hardware session: back the setup up somewhere you
can restore it from, and read the value back after.

### The two numbers that identify a ROM

- the **Bank Select MSB**, used to select a preset;
- the **SIMM ID**, which the unit reports and which System Exclusive uses as
  the "ROM ID" when asking *about* a preset.

**No E-MU document to hand maps one to the other.** p2ked assumed they were
the same number, and a unit confirmed it on 2026-09-12: three fitted ROMs
each named the presets p2ked's catalog holds for the ROM at that MSB,
character for character. Three of twenty, so `p2kcli hardware` still states
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

Needs Python 3.11+, `python-rtmidi` and `textual`, plus **vinsynlib** — the
shared base of this family of terminal instrument tools: the settings cache,
the favourites database, the keymap and legend, the command line and the port
listing. It comes from PyPI with the rest. To develop against a *working copy*
of it instead of the published one, install that alongside — it shadows the
published version in this environment only:
`.venv/bin/pip install --no-deps -e ../vinsynlib`.

`--system-site-packages` here is deliberate: ALSA's sequencer and the
system `python-rtmidi` are used rather than a fresh build.

## Run

The install puts both commands in the venv, so put that on `PATH` first —
otherwise the shell answers `p2ked: command not found`:

```sh
source .venv/bin/activate          # PowerShell: .venv\Scripts\Activate.ps1
```

Or skip activation and spell out the path, which works whatever you did
above: `.venv/bin/p2ked`.

```sh
p2ked --demo           # built-in demo device; opens no MIDI ports
p2ked                  # ask the remembered port, sweep if there is none
p2ked --scan           # probe every port again (after the unit moves)
p2ked --port "E-MU Proteus 2000 MIDI 1"
p2ked --allow-write    # start with the write gate armed (default: locked)
```

`--allow-write` is the only one of these that can lead to a write: it makes
the gate `w` toggles start armed instead of locked. See Editing above.

The first launch finds the unit by broadcasting a Universal Identity Request
and reading the reply. The reply carries the device ID the unit is set to,
so discovery ends knowing what to address — no sweep over 127 IDs. The port
that answered is remembered in `config.toml` (in the working directory,
gitignored, safe to delete), and every later launch asks *only that port*:
one round trip instead of one probe per MIDI port on the machine. `--scan`
ignores the remembered port and sweeps again, which is what is needed after
the unit moves — USB re-enumeration renumbers ALSA clients out from under a
saved name. A remembered port that stops answering falls back to the sweep
and says so on stderr, so a launch that took the slow path never looks like
a fast one.

`config.toml` is shared, by name, with the other tools in the family, so it
is **not** a place to keep anything of your own. Its first line records
which tool wrote it; another tool reads and writes its own file, and leaves
this one alone. `--config PATH` names a different file entirely.

### Keys

| | |
|---|---|
| arrows, `tab` | move; `tab` switches pane |
| `enter` | select this preset **on the unit** — it will sound |
| `r` | read this bank's names from the unit — **silent** |
| `m` | every MIDI channel: what it plays and why it might not — **silent** |
| `x` | the master FX editor, from the multi screen |
| `/` | search names |
| `c` | set the MIDI channel selections go out on |
| `f` | mark or unmark the preset under the cursor — **this writes the favourites database** |
| `v` | step the favourites view: all presets → this bank's favourites → every favourite (reads only) |
| `w` | write gate — **locked by default**; nothing is sent while it is |
| `z` | undo the last change: the last master edit, or the last favourite toggle |
| `Z` | undo every change made this session |
| `i` | device identity and which ROMs are fitted |
| `?` / `q` | help / quit |

On the multi screen, editing the channel under the cursor: `⏎` opens the
value (or the channel's detail, on the columns that are not values), `+` and
`-` nudge it, `space` flips a switch, a digit types a number in place, and
`s` picks a sound. `w` is there too — a modal cuts the app's binding chain,
so the gate has to be armable from the screen that says it is locked. `r`
re-reads the setup, `e` opens the master parameters and `x` the FX block, and
`z` / `Z` undo from here as they do from the browser.

`f` writes and `v` reads, which is why they are not a shift-pair. The family
puts the favourites view on `F`, one slip of the shift key from the key that
writes; rxved moved it to `v` and p2ked follows. Every other key is where the
family puts it.

`w`, `z` and `Z` are the family's editor keys, spelled the same way here so a
reader who has used rxved already knows them. `enter` changes what the unit is
playing and `f` writes your own database; these three are the only keys that
change what the unit *stores*, which is why they are in the legend rather than
left to a keybinding manual. And `z` / `Z` reach the app's own actions rather
than a screen's — an edit is made through the edit screen and undone after it
closes, so both have to work from the browser with no screen open.

**Moving the cursor never sends anything.** That is enforced by a test, not
just by intent: it is the property that decides whether you can leave this
open next to a running sequencer.

### Command line

`p2kcli` is the same information in a pipe, from the same venv, so the
commands below work however you chose to reach it above.

```sh
p2kcli banks                 # the bank table (no unit needed)
p2kcli list XLEAD-1          # one bank's presets (no unit needed)
p2kcli find "bell"           # search names (no unit needed)
p2kcli resolve 7 1 5         # what does this MSB/LSB/PC select?
p2kcli ports                 # MIDI ports on this host
p2kcli --demo hardware       # what the unit reports about itself
p2kcli --demo channels       # every MIDI channel (silent)
p2kcli --demo channels --json  # the same, as one JSON object
p2kcli --demo names XLEAD-1  # read a bank's names (silent)
p2kcli select XLEAD-1 5      # select a preset ON THE UNIT
```

`p2kcli channels` has no aliases and needs the unit: one Setup Dump and one
mode read, neither of which a catalog can answer. Its default output is the
same table the `m` screen draws — the setup's name, the MIDI mode, the master
panel on one line, then a row per channel with its volume, pan, output,
Program Change receive, arpeggiator and ROM, a `why not` column of the
reasons it would not sound, and a closing line listing the channels that
would.

`--json` prints **one** object instead, for another program to read rather
than for a person to scan: `setup`, `mode`, `multitimbral`, a `master` object
of the seven master values, and `channels` — one object per channel with the
raw numbers (`volume`, `pan` as the wire's 0-127, `mix_output` as -1..2
rather than "use preset" / "send 2", `enable`, `bank_map`,
`receive_program_change`, `rom_id`, `preset`) plus `plays` and a
`silent_reasons` list. The table has no column for `enable` — it reaches the
screen only as the "channel is disabled" reason in `why not` — and none for
`bank_map`; here both are fields in their own right.

Two commands are named differently from earlier p2kcli, with the old
spelling still accepted, because they collided with something:

- `roms` is now `banks`. The family calls that table banks everywhere else
  and p2ked's own browser already did; the CLI was the odd one out.
- `config` is now `hardware`. `config` meant *which ROMs are fitted* while
  the `--config` flag beside it meant *the settings file* — one program, one
  word, two meanings, in one line of help output.

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

## Development checks

Static analysis, type checking, tests and dependency audits, all runnable
from the Makefile. Nothing here is AI-generated and nothing here writes to
a Proteus.

```sh
make install          # create .venv, install pinned dev dependencies
make install-hooks    # pre-commit install
make check            # everything below; fails on the first error
```

`make help` lists every target.

| target | what it runs |
|---|---|
| `make lint` | `ruff check` — E, F, I, B, S, SIM, UP, C4, PL, RUF, C901 |
| `make format` | `ruff format` (rewrites files in place) |
| `make format-check` | `ruff format --check --diff` |
| `make typecheck` | `mypy` |
| `make test` | `pytest -q` (fast, no coverage) |
| `make coverage` | `pytest` with a term-missing report, enforcing `fail_under` |
| `make test-hardware` | the same pytest against a real Proteus 2000 — opens MIDI ports, so **not** part of `check` |
| `make audit` | `pip-audit`, `vulture`, `deptry`, `detect-secrets` |
| `make check` | lint → format-check → typecheck → coverage → audit |

`pip-audit` audits the runtime dependency list it renders from
`pyproject.toml`, including `vinsynlib` now that it comes from PyPI. It used
to filter `vinsynlib` out, when it was a sibling checkout pip could not
resolve and the audit would fail resolving rather than audit anything. The
pinned toolchain is audited in full.

### The hardware suite

Everything above runs against `p2ked/demo.py`, which is the point — fast,
and it passes on a machine with no MIDI stack at all. Its limit is the one
CLAUDE.md names: a demo agrees with whatever p2ked believes, so every offset
below the API surface was only ever checked against p2ked's own
transcription of E-MU's documents. `make test-hardware` is the other half,
and it needs a real Proteus 2000 on a MIDI port:

- **structural reads** — the dump's declared counts against the block table
  p2ked builds; every master value agreed between the dump and its own
  parameter read (RESOLUTION_NOTES §10's hand measurement, now repeatable);
  the channel block's shape and the channel ranges both documents print.
- **the probe** — `probe_channel_ids()`, read-only: TODO 47's answer, printed
  for a human to record rather than asserted by a test.
- **one write** — FX bypass, sent, read back and put back. Audible for about
  a second (the effects drop out and come back); the apparatus around it —
  gate, undo, read-back — is the app's and is tested in the ordinary suite.

Not part of `make check`, and CI never passes the flag: only one session may
drive the unit at a time. `--hardware`, or `P2KED_HARDWARE=1`, opens the
ports; without them the file skips with the reason, and `-rs` shows it.
`-o addopts=""` keeps the ordinary coverage gate from failing a run that
only executes this file. Nothing in the suite asserts on a preset name —
E-MU's ROM contents are not this project's to redistribute — and nothing
selects a preset, which is the operation that stays behind its own
confirmation in the app.

### Before pushing

`make check` is the gate. It is also what a CI job would run, and what
`pre-commit run --all-files` covers between commits. If the two ever
disagree, `make check` is the answer — the Makefile is the source of
truth and every tool reads its configuration from `pyproject.toml`.

### Versions

`requirements-dev.txt` is the lockfile: every tool and every transitive
dependency, pinned to an exact version, so a check means the same thing on
every machine. To regenerate it after adding a tool:

```sh
python3 -m venv /tmp/p2k-lock && /tmp/p2k-lock/bin/pip install -U pip
/tmp/p2k-lock/bin/pip install -r requirements-dev.txt
/tmp/p2k-lock/bin/pip freeze | sort
```

### What is suppressed, and why

`make check` passes on the tree as it stands. That is not the same as the
tree being clean, and the difference is worth being explicit about.

`pyproject.toml` holds every rule, every baseline and the reason for each.
Nothing in the source was rewritten to satisfy a linter.

- **~400 of 499 pre-existing ruff findings** are five rules ignored
  project-wide: `UP006`/`UP035`/`UP045` (`typing.Dict` rather than PEP 585
  spellings), `PLR2004` (magic values — the protocol constants must stay
  literal, per CLAUDE.md) and `PLC0415` (function-local imports, which is
  what lets the offline CLI work without a MIDI backend).
- **The remaining ~99** are per-file, per-rule ignores, each with a comment
  naming the finding. They are per *rule*, not per file, so a new finding
  of an unlisted rule in one of those files is still reported.
- **mypy** silences 36 pre-existing errors by error code per module, so
  every other check stays live there. `p2k/roms.py` and `p2k/catalog.py`
  pass with none of the below enabled and are checked strictly — that is
  the bar for new modules.
- **One ruff F821 and one mypy `name-defined` were a real bug, not a style
  finding.** `p2kcli find` raised on every non-empty search. Both are fixed
  and **their baselines are removed**, so an undefined name in that file is
  reported again. It survived because `p2ked/cli.py` had no test at all;
  `tests/test_cli.py` now drives every command through `main()`.
- **Coverage is gated** at `fail_under = 68`. The suite reports **69.60%**
  with branch coverage on; the gate sits just below so ordinary fluctuation
  does not turn `make check` red. Two figures are low for a reason no
  synthetic test can fix, and neither is a reason to lower the bar:
  `p2k/bridge.py` **24%** (the transport needs a cable — it was exercised
  against a real unit instead, see RESOLUTION_NOTES §11) and `p2ked/app.py`
  **57%** (layout and event plumbing that would want a snapshot to pin).

### The formatter

`ruff format` is enabled, in `make check` and as a pre-commit hook. It was
held back while the tree was unformatted, because 17 of 19 files would have
been rewritten by the first commit after `pre-commit install` — a mass change
smuggled into an unrelated commit. The reformat was applied as its own commit
instead, so the hook now only ever touches code you are already editing.

`make format` applies it; `make format-check` verifies it. Both are in
`make check`.

### Checking against the instrument

`make check` is entirely synthetic — it opens no MIDI port, and every test
runs against `DemoDevice`. Two tools are the exception, because they need a
unit and so cannot be part of an automated gate:

```sh
python3 tools/measure_send_gap.py --port "U6MIDI Pro:U6MIDI Pro MIDI 1 40:0"
python3 tools/measure_send_gap.py --demo     # synthetic; proves nothing
```

`measure_send_gap.py` reads names and compares each read against a reference,
which is how `bridge.SEND_GAP` was measured rather than guessed — see
RESOLUTION_NOTES §11. It never selects anything and never writes.

### Shell scripts

There are none — no `*.sh`, and no file with a bash or sh shebang — so
`shellcheck` and `shfmt` are not wired in. `.pre-commit-config.yaml`
carries both, commented out with the revisions to use, for whenever the
first script arrives.

### What these checks cannot tell you

A green `make check` says the encoder and the decoder agree, that the
ranges are enforced, that a signed value survives a round trip, and that
the cursor still never sends MIDI. It does not say the protocol is right.
That remains what DISCLAIMER.md is for, and no amount of static analysis
changes it.

## Licence

GPL-2.0-or-later. See [LICENSE](LICENSE) for the project's copyright notice
and third-party attributions, and [COPYING](COPYING) for the licence text.

Not affiliated with E-MU Systems or Creative Technology.
