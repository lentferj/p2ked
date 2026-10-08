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

p2ked **reads** the unit and can **select** a preset, which makes sound; it
does not write to the unit's memory. Other tools in the family do write to
hardware and storage media, and this warning is the family's. Even so:
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
character for character. Three of twenty, so `p2kcli hardware` still states
what was checked. The one ROM ID that is also *documented* is `0`, meaning
user memory.

One ROM in the table got there the other way round. A unit reported SIMM ID
14 with 640 presets and no file to hand covered MSB 14 at all; it was
identified as **X-Lead v2** from E-MU's own patch list for that ROM, and
`tools/extract_catalog.py` now reads those OpenDocument lists so its names
are catalogued too.

## Install

Two checkouts, side by side — this project and the shared library it uses:

```sh
git clone https://github.com/lentferj/vinsynlib.git ../vinsynlib
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --no-deps -e ../vinsynlib
.venv/bin/pip install -e .
```

Needs Python 3.11+, `python-rtmidi` and `textual`, plus **vinsynlib** — the
shared base of this family of terminal instrument tools: the settings cache,
the favourites database, the keymap and legend, the command line and the port
listing. It is **not on PyPI**, so it is installed from the sibling checkout
above, and installed *first* so that the second command finds the requirement
already satisfied.

`--no-deps` on the first install because vinsynlib's dependencies are this
project's too, and a second copy of `textual` in the same venv is a version
skew to diagnose somewhere else. With `uv`, `uv sync` takes the path from
`[tool.uv.sources]` in `pyproject.toml`, so the checkout only has to exist
and neither `pip` line is needed.

`--system-site-packages` here is deliberate: ALSA's sequencer and the
system `python-rtmidi` are used rather than a fresh build.

## Run

```sh
p2ked --demo           # built-in demo device; opens no MIDI ports
p2ked                  # ask the remembered port, sweep if there is none
p2ked --scan           # probe every port again (after the unit moves)
p2ked --port "E-MU Proteus 2000 MIDI 1"
```

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
| `/` | search names |
| `c` | set the MIDI channel selections go out on |
| `i` | device identity and which ROMs are fitted |
| `?` / `q` | help / quit |

**Moving the cursor never sends anything.** That is enforced by a test, not
just by intent: it is the property that decides whether you can leave this
open next to a running sequencer.

### Command line

```sh
p2kcli banks                 # the bank table (no unit needed)
p2kcli list XLEAD-1          # one bank's presets (no unit needed)
p2kcli find "bell"           # search names (no unit needed)
p2kcli resolve 7 1 5         # what does this MSB/LSB/PC select?
p2kcli ports                 # MIDI ports on this host
p2kcli --demo hardware       # what the unit reports about itself
p2kcli --demo channels       # every MIDI channel (silent)
p2kcli --demo names XLEAD-1  # read a bank's names (silent)
p2kcli select XLEAD-1 5      # select a preset ON THE UNIT
```

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
| `make audit` | `pip-audit`, `vulture`, `deptry`, `detect-secrets` |
| `make check` | lint → format-check → typecheck → coverage → audit |

`pip-audit` filters `vinsynlib` out of the runtime dependency list it audits.
It is a sibling checkout rather than a package on an index, so `pip` cannot
resolve it and the audit would fail resolving rather than audit anything;
it is this family's own source, reviewed in this repository, and it carries
no third-party dependency of its own at this layer. The pinned toolchain is
audited in full.

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
