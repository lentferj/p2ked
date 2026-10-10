<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# TODO

## Status, 2026-09-11 (first session)

A prototype exists and runs: protocol codec, ROM/bank table, transport,
demo device, CLI, Textual browser, 70 tests, 8832 catalogued names.

**Nothing has been tested against hardware, because there is none.** Every
item below that says "unverified" means exactly that, and the list is not
exhaustive — see DISCLAIMER.md.

---

## 1. The read path — DONE 2026-09-12

**Status:** done. First hardware session; see RESOLUTION_NOTES §7.

Identity, Hardware Configuration and Generic Name all worked as written
against a real Proteus 2000. Nothing was selected and nothing made a sound.
What remains unverified is listed in DISCLAIMER.md: parameter edits, preset
dumps, the checksum rule and `SEND_GAP`.

**Superseded plan, kept because the order was right:**

The first session with a unit should, in this order:

1. `p2kcli ports`, then `p2kcli status` — does it answer an Identity
   Request at all, and with what?
2. `p2kcli config` — does the Configuration response parse, and are the
   SIMM IDs what item 2 assumes?
3. `p2kcli --port ... names USER-0` — do names come back, and do they
   match what the unit's display shows?
4. Only then anything that makes a sound.

Until step 1 succeeds nothing else is worth attempting: silence is this
protocol's answer to every kind of mistake.

## 2. SIMM ID versus Bank Select MSB — RESOLVED 2026-09-12

**Status:** confirmed. A SIMM ID **is** the ROM's Bank Select MSB.

A unit reporting SIMM IDs 4, 65 and 67 returned, for each, preset names
matching p2ked's catalog for the ROM at that MSB — character for character.
Three of nineteen ROMs, so a mismatch on some other board remains possible,
but this is no longer a guess and the interface no longer calls it one.

A second, independent check agrees: `ProteusBridge.installed_roms()` asks
each ROM ID for preset 0 and reads the reply, and its answer matches the
Configuration response exactly.

## 3. The checksum rule is ambiguous

**Status:** open, worked around.

The specification says "1 Byte XOR(1's complement) of the sum of the DATA
bytes", which describes two different operations: an XOR *of* the bytes, or
the one's complement *of their sum*. `messages.checksum` implements the
plain XOR reading; p2ked sends `7Fh` ("ignore checksum", explicitly
permitted) on messages that carry the field rather than guess.

Resolved by capturing a checksummed message *from* a unit and testing both
readings against it.

## 4. `SEND_GAP` is a guess — MEASURED 2026-10-02, and deliberately left alone

**Status:** answered, and the answer is "do not change it".

Measured on a Proteus 2000 over a 128-preset bank:

    gap 10.00 ms (the default)   18.72 ms per preset   3/3 clean
    gap  0.00 ms                 18.94 ms per preset   3/3 clean
    round trip, no gap, no drain 17.91 ms

**The gap is entirely hidden inside the unit's response time.** Removing it
outright changes nothing measurable — 18.94 against 18.72 is noise — so
there is no performance argument for lowering it. A sweep costs what the
instrument costs to think, and no sender-side constant improves that.

The sweep also found **no failures at any gap down to 0.05 ms**. That says
the current value is conservative, not that it is needed: there is no
measured reason to spend the margin, so the margin stays.

`SEND_GAP` remains 10 ms, the sibling projects' default, untouched.
`tools/measure_send_gap.py` re-derives all of it against any unit, comparing
each read with a reference read rather than counting successes — the failure
a too-small gap causes is a reply belonging to the *previous* request, which
a success count cannot see.

One unit, one firmware, one interface; none of this generalises. See
RESOLUTION_NOTES §11.

## 5. Preset counts are bank counts — RESOLVED for the fitted ROMs, 2026-10-02

**Status:** the policy is right, and it is now right *with evidence* rather
than by argument. What remains is only the fifteen ROMs not fitted here,
which cannot be reached without the boards.

This item asked whether giving every ROM `banks * 128` -- taken from
instrument-definition files that describe **banks**, not populated presets --
overstates the ROM. It was defended on a trade-off: an over-long bank shows
rows that name nothing, a short one *hides* presets, and a hidden preset is
not discoverable by the person looking for it. That is now measured, at
scale, on two whole ROMs.

### 1. The slot counts are exactly right

Every preset of every fitted ROM was read off the unit and counted:

| ROM | slots read | named | empty | absent | `roms.py` says | unit reports |
|---|---:|---:|---:|---:|---:|---:|
| Composer | 1024 | 1023 | 1 | 0 | 1024 | 1024 |
| X-Lead v2 | 640 | 640 | 0 | 0 | 640 | 640 |
| Techno Synth | 512 | 512 | 0 | 0 | 512 | 512 |
| Beat Garden | 512 | 512 | 0 | 0 | 512 | 512 |
| user memory | 512 | -- | -- | -- | 512 | 512 |

Not one slot over, not one under, on any of the five. `banks * 128` is the
right answer for every ROM this unit has, and the Configuration response
agrees with the table on all of them.

### 2. The partly-empty last bank is real -- and it is Composer

The trade-off above was hypothetical. It is not: **COMPOSER-7 pc 127 is an
empty slot.** The last preset of the last bank holds nothing.

```
COMPOSER  #1021  'brs:Section'
          #1022  'brs:SforzadoEnsb'
          #1023  '   :default'      <- empty slot
          #1024  '   :default'      <- past the end: still :default
```

And the **catalog records it as `:default` too** -- the instrument-definition
files say the same thing the unit says. So the table, the catalog and the
unit agree on all three, and `read_bank_names` keeps the slot for exactly the
reason its comment gives: "default" is what the unit says, and a blank row
would leave the user wondering whether the read failed or the slot is
genuinely empty.

Note also that Composer is the ROM that **does not** answer `(not
installed)` past its end -- TODO 41. The two findings are the same fact seen
twice: this ROM answers `:default` rather than reporting absence, so its
extent has to come from the table and the catalog, which is precisely the
arrangement this item was worried about. It works.

### 3. Fifty slots where the printed list is wrong and the unit is right

Diffing Composer's 1024 names and X-Lead v2's 640 against the generated
catalog:

| ROM | differences |
|---|---:|
| X-Lead v2 | 11 |
| Composer | 49 |

**X-Lead v2's 11 reproduce RESOLUTION_NOTES §7 exactly** -- every one a
double space on the instrument where the document prints one:

```
XLEAD2-0 pc  25  printed='kit:K-1 HPF'    unit='kit:K-1  HPF'
XLEAD2-0 pc  90  printed='hit:Dance 1'    unit='hit:Dance  1'
```

That is an independent re-derivation of a finding recorded three weeks
earlier, on a different sample.

**Composer's 49 are a different and more interesting kind.** Not whitespace
-- real errors in the published patch list:

```
COMPOSER-0 pc  19  printed='brs:TrumpetMure2'   unit='brs:TrumpetMute2'
COMPOSER-1 pc  47  printed='syn:808 Synthax'    unit='syn:8O8 Synthax'
COMPOSER-3 pc  85  printed='kit:Clean RsrB'     unit='kit:Clean R&B'
COMPOSER-0 pc  16  printed='brr:Trumpet FX 7'   unit='brs:Trumpet FX 7'
COMPOSER-4 pc   9  printed='kb3:DX Organ'       unit='kit:Kit 1'
```

Broken by kind: 28 typos and garbled text (`Mure`/`Mute`, `808`/`8O8`,
`Voxwav`/`VS Vox`), 12 whitespace, 4 case, 3 truncated, and 2 with the
wrong category prefix -- one of which is not a typo at all but a
different instrument entirely (`kb3:DX Organ` against `kit:Kit 1`).

**All 49 are the case `Catalog.disagreement` was written for.** A ROM cannot
be saved over, so a difference in a ROM bank cannot mean "somebody stored
their own sound here"; it means the printed list is wrong and the unit is
right. That is what the screen will say, on all 49, and it is correct.

This item is ROM-only and stands. The *user*-bank half of the same idea did
not: see item 45, which removed it.

### 4. The cost, measured at the same time

1664 names in 31.0 seconds: **18.6 ms per name**, from a sample three
orders of magnitude larger than the SEND_GAP measurement in §11, and
agreeing with it. It is also the honest cost of the feature: reading a whole
fitted ROM takes the better part of half a minute, which is why startup
asks the Configuration response instead (TODO 34).

### What is left

- **The fifteen unfitted ROM rows.** Unreachable without the boards, and
  the same reasoning that leaves §7's SIMM-ID mapping confirmed for three
  ROMs rather than nineteen.
- **Correcting the table at runtime from the Configuration response.** Not
  done, and **no longer worth doing**: the counts agree on every ROM that
  can be checked, so there is nothing for it to correct. It would only
  ever fire on a unit whose ROMs are laid out differently, and the
  Configuration response is a whole-unit statement rather than a per-ROM
  one -- it would suppress a ROM p2ked can address. Item closed.

See RESOLUTION_NOTES §11.

## 5b. ROM 14 has no name — DONE 2026-09-21

**Status:** done. This entry was stale; it was not reopened, just not
closed when the work happened.

The ROM is named **X-Lead v2**, with its real extent -- five banks, 640
presets -- in `p2k/roms.py`:

    _rom("XLEAD2", "X-Lead v2", 14, (0, 1, 2, 3, 4), 640),

Identified from E-MU's own X-Lead v2 patch list: 640 presets in five banks,
and every preset sampled off the unit (0, 5, 100, 200, 400, 638, 639)
matching that list character for character. `tools/extract_catalog.py`
now reads those OpenDocument lists, so its 640 names are catalogued too --
they were unobtainable from any instrument-definition file, which do not
cover MSB 14 at all. See RESOLUTION_NOTES §7.

## 6. Only presets are browsable

**Status:** open. A feature, not a defect.

`Generic Name Request` also names instruments, arps, setups, demos and
riffs (`messages.ObjectType`). p2ked asks only about presets. Instruments
in particular would be worth browsing — they are the raw material presets
are built from.

## 7. No editing, and no plan to add it casually

**Status:** deliberate.

p2ked reads. The specification documents parameter edits and preset dumps,
and `messages.parameter_edit` exists and is tested, but nothing calls it.
If editing is added, CLAUDE.md's hardware rules apply: arm-then-fire, never
key-bound, back up first, verify by reading back.

## 8. The other documents in the source folder are unread

**Status:** open.

`~/Dokumente/SYNTHS/Proteus 2000` also holds the Operation Manual, a
parameter tree PDF, riff and drum-map text files, ROM and SIMM images, a
flash-analysis archive, and `prodatum` (an existing open-source editor).
Only the System Exclusive specification and the instrument-definition files
have been read. The parameter tree is the obvious next source if p2ked ever
grows an editor, and prodatum is an independent reading of the same
protocol — the best available cross-check short of hardware.

## 9. Multi functionality — channel view DONE 2026-09-12

**Status:** the channel screen is built (`m`, and `p2kcli channels`), reads
one Setup Dump, shows all 32 channels with what each plays and why it would
be silent, and was verified against hardware. See RESOLUTION_NOTES §8.

**Still open from this item:**

- ~~The MIDI Mode is not shown~~ **DONE.** It is parameter id 385, read
  directly -- no dump layout needed. Shown above the table, and in omni or
  poly the screen shows only the mode and says the settings below are not in
  effect. See §9.
- **Multisetups are not browsable, and cannot be by name.** The Generic Name
  request ignores the object number for setups and returns the current
  setup's name -- proved by asking for setup 128, which does not exist and
  answers anyway. They could be listed by number; selecting one to learn its
  name would *load* it over the user's live configuration, which p2ked will
  not do. See §9.

**Superseded plan:**

rxved has a multi-mode screen: 16 parts, their channels, levels, receive
switches and routing, plus a report on why a channel is silent.
~~p2ked has nothing equivalent.~~ **DONE 2026-10-10.** `m` (and `p2kcli
channels`) reads one Setup Dump and shows all 32 channels, their nine
parameters, the master panel and the why-not column, with the documented
reason set for every channel that would be silent. The edit half of the
same parity is item 48; multisetup browsing is still deferred -- the
primitive is built and documented, the UI is not.

"Multi" is two things on this machine and they need two features:

- **MIDI Mode** (Omni / Poly / Multi), the analogue of the XV-2020's
  PATCH/PERFORM. Worth surfacing first: in Omni or Poly, "only one channel
  sounds" is the mode, not a fault.
- **Multisetups**: 128 stored snapshots of all 32 channels, selectable with
  MSB 80 / LSB 0 / PC. Closer to an XV-2020 performance. Browsable the same
  way presets are.

The data is readable in one silent message -- Setup Dump Request `1Dh` --
the channel block is at payload offset 194 (32 channels x 9 parameters x 2
bytes), and the field order is confirmed: preset, volume, pan, mix output,
arp, channel enable, bank map, receive program change, preset ROM ID. See
§8 for the evidence.

The offset itself was found by structural search against one firmware, so
it should be re-derived rather than hardcoded -- the dump's header declares
the channel count and parameters per channel, and a future firmware may
change what precedes them.

## 10. The Setup Dump layout — DONE 2026-09-12

**Status:** done, and honestly bounded. See RESOLUTION_NOTES §10.

The whole 970-byte payload is mapped: the 194 bytes before the channel block
are the master general, MIDI, effects and arpeggiator blocks plus the three
non-channel parameters, and the 200 after are two further self-describing
sub-blocks holding the BEATS triggers and parts. `SetupDump.master` now
carries all 82 master values, keyed by parameter ID.

It was not decoded from the layout. Every value was **read a second time as
an individual parameter** and matched against the dump — 82 for 82. The
published example was never used and is still wrong.

Two findings that no document states: the dump **omits every ID the
specification marks reserved**, and the block the header calls "reserved"
is the **Master Arpeggiator**.

**What is still not established**, and is recorded rather than papered over:

- Three IDs in the dump (270, 279, 660) have no published name. They are
  decoded and left unnamed; the prose's "Master Demo Mode Enable" may be one
  of them, which is a hypothesis and is not printed as a fact.
- The BEATS field order is confirmed for one row of each block, not all 40:
  selecting a trigger or part needs a parameter *edit*, and nothing was
  written to the unit.
- This is one unit and one firmware. The parser obeys the declared counts
  rather than these offsets, skips any one block whose count it does not
  recognise, and still finds the channels by structural search.

---

*Items 11 onward came from a code review by MiMo V2.5 Free on 2026-09-19.
Each has since been checked against the code; the verdict line says what
that check found. Two do not reproduce and one is right about a third of
what it cites.*

## 11. Nothing enforces that config writes stay on the main thread

**Status:** open, hypothetical today. **Verified, and worth restating.**

The review frames this as `_update` rewriting the whole file, so two
concurrent calls could interleave. Checked: no `@work` method in
`p2ked/app.py` touches `config` at all, so there is no race now.

But the reason there is no race is the project rule -- workers do MIDI and
hand off -- and that rule is only enforced for two things. `tests/test_legend.py`
has AST checks that no worker reaches `self.catalog` or queries widgets.
A worker calling `config.save_channel` would pass every test in the suite.

So the useful fix is not a file lock, which would make a worker doing this
*work* and leave the rule unenforced. It is a third AST check of the same
shape, so that the first worker to touch config fails the suite instead of
the disk.

**Status since 2026-10-02: still open, and the reason has shifted.** Item
37 made the `_busy` flag live, which is what a config-writing worker would
have had to contend with, and the natural place to write a channel is
already the main thread (`_step_channel`, `action_pick_channel`). So there
is no path to the race today and slightly less temptation for one.

The AST check is still the right fix and is still worth doing, and it is
still cheap: `_workers()` in `tests/test_legend.py` already yields every
decorated function, so the check is one more loop over an existing list,
and the guard-that-the-guard-has-something-to-check pattern is already
written twice in that file.

**Fixed 2026-10-10.** The check is `test_no_worker_writes_the_settings_cache`,
one more loop over that same `_workers()` generator. It catches any
`*.save_*` call in a worker and reports the worker and the method.

`test_a_worker_writing_config_is_caught` proves it can fail, by parsing a
synthetic worker from `textwrap.dedent`. That second test matters more than
it looks: the refactor which would make the check vacuous is exactly the one
an edit feature tempts somebody into -- moving a settings write behind a
worker so the interface does not pause on it.

## 12. `catalog.search` dropped the disagreement it knows about — FIXED

**Status:** **fixed 2026-09-20.** Was the most useful item on this list.

`Catalog.search` (`p2k/catalog.py:146`) returns `(bank_id, program_change,
name)`, merging printed and live names into one dict and keeping whichever
sorted last. The browser marks a slot whose live name differs from the
printed one, via `Catalog.differs` / `Catalog.disagreement`; search shows
the name flat, with nothing to say which source it came from or that the
two disagree.

That is the wrong way round. In the browser the user is already looking at
the slot. In search they are looking at a list of names from banks they
have not opened, which is exactly where "this one is not what the printed
catalog says" is worth knowing -- it is how a user bank that somebody
overwrote gets noticed at all.

Fixed by returning the flag alongside, as item 23 spells out, and having
both callers -- `p2ked find` and the TUI search report -- render the same
marker the browser does.

## 13. `bridge.identify` does not drain before sending

**Status:** **rejected -- does not reproduce.**

`ProteusBridge.identify` calls `self._drain()` as its first statement,
`p2k/bridge.py:272`, and has since the initial commit `d003569`. The
finding states the opposite. Every bridge method that sends a request
drains first; there is no exception to align.

## 14. `DemoDevice.preset_name` and the bridge's differ in return type — FIXED

**Status:** **fixed 2026-10-02**, together with item 22, which is the same
finding with the hazard checked. `DemoDevice.preset_name` returns `str` and
raises `TimeoutError` for silence, exactly as
`ProteusBridge.preset_name` does. Both annotations are now `str`, and a
test asserts the two signatures match rather than trusting a comment.

`DemoDevice.read_bank_names` was brought into line with the bridge's at the
same time: it catches `TimeoutError` per slot and drops absent names, so
the demo exercises the loop the real thing runs rather than a simpler one
that happens to pass.

The demo remains a second implementation rather than a mock, which is the
point of it -- but it is a second implementation of the *same contract*.

**Blocked on:** nothing.

## 15. The `tomllib` fallback in `config.py` cannot execute — FIXED

**Status:** **fixed 2026-10-02.** Removed.

`pyproject.toml:10` declares `requires-python = ">=3.11"` and `tomllib`
entered the standard library in 3.11, so the `except ModuleNotFoundError`
branch was unreachable and `tomllib is None` never true. `import tomllib`
is now unconditional, and the `or tomllib is None` guard in `_read` went
with it rather than becoming the dead code instead.

A comment is left in place saying why, because "a fallback that looks like
it degrades but cannot" is the sort of thing the next reader re-adds.

**Blocked on:** nothing.

## 16. A tool reads a file without closing it — FIXED

**Status:** **fixed.** This entry was stale: the code had already been
fixed and the entry never closed.

`tools/import_favourites.py` reads through a `with` block:

    with open(path, encoding="utf-8") as handle:
        lines = handle.readlines()

The other two the review named were already correct when it was written:
`tools/extract_catalog.py` uses `with open(...) as handle` in all three
places.

**Blocked on:** nothing; one line.

## 17. `wrap_blocks` did not guard against `width <= 0` — FIXED

**Status:** **fixed 2026-10-02.** `width = max(width, 1)`, and the
`if width and ...` test became `if ...`, since it is now always true.

Worth recording what the guard was for, per the function's own docstring:
the legend wraps rather than truncates, because a footer that silently
drops its last few keys teaches the user those keys do not exist. A width
of 0 was the degenerate version of exactly that failure — every candidate
looks too wide, the break is never taken, and the legend comes out as one
very long line: the same outcome, reached by the other route.

The only caller clamps with `max(self.size.width - 2, 20)`, so nothing ever
passed 0 and no user could have seen this. It is fixed because a function
that silently degrades on an argument its own docstring does not mention
is worth less than one that cannot.

**Blocked on:** nothing.

## 18. `roms.presets` recomputes its base offset on every call

**Status:** open, cosmetic. **Verified** -- `p2k/roms.py:332-337` walks
`entry.rom.lsbs` to find the bank's base each time, and `_fill_presets`
calls it on every cursor move.

At 128 presets across 74 banks this is not measurable. The reason to leave
it alone is stronger than the reason to cache it: `lsbs` is the installed
ROM set, which the app can change at runtime when the fitted-ROM filter is
toggled, so a cache keyed on `bank_id` would need invalidating on exactly
the event most likely to be forgotten.

**Status:** **fixed 2026-10-10 -- and the stated reason not to do it was
wrong.** The concern recorded below was that `lsbs` is the installed ROM set,
which "the app can change at runtime when the fitted-ROM filter is toggled".
That is the app's *list of bank ids*, `P2kedApp._bank_ids`, which decides
what is **shown**; `roms.ROMS` is a tuple built at import and nothing writes
to it. A preset's number within its ROM cannot therefore change under a
cache, and there was never a cache to invalidate.

`Bank` carries `base` now, filled in once by `banks()` where it already
walked the LSBs, and `presets()` reads it. No behaviour change: three tests
in `tests/test_roms.py::TestTheBankBaseOffset` assert the field equals
`PRESETS_PER_BANK * index`, that the first and last preset numbers bracket a
bank exactly, and that a later bank does not restart its numbering. The one
case where the old walk and the new field could have diverged -- a *trailing*
bank that is partly full -- cannot, because truncation only ever happens to
the last bank of a ROM, so every bank before it is a whole 128 wide.

## 19. A test wrote `config.toml` into the working directory — FIXED

**Status:** **fixed.** Real, and it had actually happened.

`tests/test_favorites.py` called `config.save_last_port("some port")` with
no path on the line *above* the correct call that passes one -- a leftover
from adding the path argument. `config.DEFAULT_PATH` is the relative string
`"config.toml"`, so the pathless call wrote into whatever directory pytest
was started from. A `config.toml` dated during a test run was sitting in
the repository root when this was checked.

It is gitignored in all four sibling projects, which is why it never
appeared in `git status` and why the review could only infer it.

The relative default is **not** itself a bug: it is the same in rxved,
kwsed and x5ded, and deliberate -- `config.toml` is a disposable
per-checkout cache of which port answered last, as distinct from the
favourites store, which is the user's own work and lives in the platform
data directory.

The duplicated line is gone, and `tests/test_legend.py` now carries an AST
check that every `config.save_*` in the suite names its file, plus the
usual guard that the check has something to match.

---

*Items 20 onward come from a code review by **Nemotron 3 Ultra (free)** on
2026-09-20. All code-level findings (items 11–19) were already tracked by the
prior MiMo V2.5 Free review; this review independently confirmed them and
adds the following process/tooling items.*


## 20. No static type checking in CI

**Status:** **fixed 2026-10-10 -- as the whole gate, not just mypy.**

`.github/workflows/ci.yml` runs `make install && make check` on
ubuntu/macOS/windows × Python 3.11/3.12/3.13 -- ruff, format, mypy, the
suite with its coverage gate, and all four audits. The gate is not a
reimplementation: CI runs the same commands a new contributor does, because
a gate that diverges from the documented one is a gate nobody trusts.

The "all four together or not at all" half is still true and deliberately
not attempted: this runs p2ked's **own** mypy configuration, not
`--strict`. One project with a much stricter gate than its siblings buys a
week of fixing the backlog and no family consistency.

It earned its keep before it first ran. `make install` had been installing
the project with `--no-deps`, which was correct while vinsynlib was a sibling
checkout and silently wrong after the library moved to PyPI: the runtime
dependency p2ked cannot start without was never installed at all, so
`make install && make check` failed on the first import. The Makefile now
installs plainly, and the clean-venv path has been run end to end to prove
it -- which is the first time anybody ran that sequence since 3d27bbe
documented it.

Unverified until it runs on GitHub: whether python-rtmidi 1.5.8 builds from
sdist on 3.13 for Windows and macOS. It publishes no cp313 wheel, so Linux
gets `libasound2-dev` (already in the workflow) and the other two link
against WinMM and CoreMIDI. If a build fails there, the fix is a Python
version floor for the matrix or an unpinned `python-rtmidi` -- not a change
to the project.

## 21. Test suite not parallelised

**Status:** open, cosmetic. Not acted on.

`pytest-xdist` is not installed and no sibling uses it. The ~24 s is almost
entirely Textual pilot tests waiting on their own event loop, which xdist
would genuinely help. Against that: it is a new dependency for a suite that
runs in under half a minute, and it distributes across *processes*, so the
relevant property is not the thread-safety the finding cites but whether
two workers can collide on a shared path -- which item 19 showed they could
until this week.

**Blocked on:** wanting it.

## 22. `DemoDevice.preset_name` silence behaviour differs from bridge — FIXED

**Status:** **fixed 2026-10-02.** See item 14.

The hazard it claimed did not exist: `preset_name` has three callers and
each is inside the class that defines it, so nothing a caller could
mistake the return for ever saw a `None`. The inconsistency was real and
the fix is still worth having -- the demo now raises `TimeoutError` and
both annotations read `str`, so the divergence is gone rather than
explained away.

Worth noting what the fix is *not*: the demo was not made to wrap the
bridge, and the bridge was not relaxed to suit the demo. Silence is
`TimeoutError` in both, because that is what silence is on a MIDI cable,
and the demo's job is to be the same contract over a fake transport.

## 23. `catalog.search` return type should include `differs` flag — FIXED

**Status:** **fixed 2026-09-20**, together with item 12, which is the same
finding.

`search` now returns `(bank_id, program_change, name, differs)`. Both
callers render the `*`: `p2ked find` prints it with a footnote, and the TUI
search report marks each row and says how many of the results differ.

---

*Items 24 onward came from a second, independent code review by
**GLM-5.3-Flash** on 2026-09-20, which said it had reproduced each finding
by executing the code. Each has now been reproduced or refuted here
independently; the verdict line says which. Eleven hold. One does not.*

## 24. The `[` and `]` channel keys were dead — FIXED

**Status:** **fixed 2026-09-20.** Real and user-visible. **Reproduced**
before fixing: a pilot set the channel to 4, pressed `]` then `[`, and the
channel was still 4 both times.

`app.py` bound `left_square_bracket` to `channel_down` and
`right_square_bracket` to `channel_up`; neither action existed. The legend
advertised them and `test_the_keys_are_all_in_the_legend` asserted the
legend was complete -- so the suite verified the documentation of keys that
did nothing.

`action_channel_down`, `action_channel_up` and `_step_channel` now exist.
Clamped at 1 and 16 rather than wrapped: wrapping from 16 to 1 on a key
held a moment too long puts a selection on a channel the user did not
choose and cannot see they are on. Three tests, including one that the
keys send no MIDI.

## 25. Toggling a favourite off and on destroyed its annotations — FIXED

**Status:** **fixed 2026-09-20.** The one finding on either list that lost
data. **Reproduced**: a favourite with `rating=4, tags='a, b',
note='hello'` came back as `0, '', ''` -- and, unremarked by the review,
with its `added` date reset too, which `add`'s own docstring calls "the one
ordering the user cannot reconstruct".

**It was in all four sibling projects, and live in rxved.** The review
noted that `Favorites.toggle` "exists and is never called" -- true here,
but rxved *does* call it, and its implementation is identical. kwsed and
x5ded inline the same remove-then-add. So the fix went to all four.

**What it does now**, per the decision taken on it: un-favouriting clears
an `active` flag and keeps the row. Re-favouriting restores the rating,
tags, note and original date exactly. Schema version 2; the migration adds
the column with `DEFAULT 1`, so every row in an existing database stays a
live favourite. `remove` no longer deletes; `forget` does, and nothing a
keystroke can reach calls it. `dormant()` lists what is being held.

## 26. `DemoDevice.select` dropped the channel — FIXED

**Status:** **fixed 2026-09-20.** Real, and the test named for it was the
reason it survived.

`demo.select` accepted `channel` and stored nothing, while
`test_selection_goes_out_on_the_chosen_channel` asserted only
`len(selected_log) == 1`. The demo would have passed had the app sent every
selection to channel 1 -- the project's own documented failure mode, two
things sharing a misreading and agreeing perfectly.

`selected_log` now holds `(preset, channel)` and the test asserts the
channel is the one that was set.

## 27. The config module's port and device-ID memory was dead code — FIXED

**Status:** **fixed 2026-09-20.** Real. **Verified**: the only references
to `save_last_port`, `load_last_port`, `save_device_id` and
`load_device_id` anywhere outside the tests were the four names in
`config.__all__`.

`main()` now saves the port and device ID that worked, and tries the
remembered port before the 20-port sweep. A remembered port that has gone
is not an error -- it falls through to the sweep. This is the U6MIDI-Pro
case the docs dwell on: no hint matches that port's name, so without it
every launch meant `--port` or the full sweep.

`ProteusBridge` now carries `port` and `recv_port`, because `description`
is `"out -> in"` for display and is not something `open()` accepts back --
saving it would have produced a config that never matched.

The latent oddity the review spotted in passing is fixed too:
`load_device_id` accepted TOML `device_id = true` as device 1, since
`isinstance(True, int)`. Device 1 is a real device, and this instrument
answers a wrong device ID with silence -- the failure mode that hides
behind every other. It is now rejected, as is anything outside 0-127.

**Re-opened and closed differently, 2026-10-08.** The library rewrite of
the launch path made the *device-ID* half of this write-only again:
`main()` called `save_device_id` on every launch, replacing the settings
file the remembered-port fast path is supposed to trust, and nothing read
the key back. The call is gone. The ID is learned from the identity reply
on every launch and passed through from `--device-id` when the user gives
one; it is not persisted, which is what makes the fast path one round trip
rather than a rewrite. `load_device_id`/`save_device_id` survive in the
shim for a future feature; nothing calls them today.

## 28. `Favorites.refresh_names` was never called — FIXED

**Status:** **fixed 2026-09-20.** Real. **Verified by grep**: no caller
outside the tests.

`_adopt_names` updated the catalog and left the favourites table alone, so
a favourite made before any names were known kept its blank label -- in the
favourites view and in `name` ordering -- even after the very bank read
that supplied the real name. It now refreshes, on the main thread after the
catalog is updated, because the store is SQLite and a worker must not touch
it. Dormant rows are relabelled too, so a restored favourite does not come
back labelled "--".

## 29. Search matches a stale printed name and shows the live one

**Status:** **rejected. Does not reproduce.**

The claim: with a printed name `Real Name` and a live name
`Renamed By Unit`, searching "real" returns the row *showing*
`Renamed By Unit` -- matched on text it does not display.

Executed. `search("real")` returns `('lead', 5, 'Real Name')`;
`search("renamed")` returns `('lead', 5, 'Renamed By Unit')`. Both show
what they matched.

The reason is in the method the finding quotes. The second loop replaces a
hit only `if wanted in name.lower()` -- that is, only when the *live* name
also matches the needle, in which case showing the live name is correct and
not a defect. The two loops key on the same `BANK:NNN` string, so there is
one row per slot and no duplicate either.

What was genuinely missing there is items 12 and 23, now fixed: which of
the two a hit came from, and whether they disagree.

## 30. `favorites._split` crashed on a bare bank id — FIXED

**Status:** **fixed 2026-09-20.** Real and latent. **Reproduced**:
`_split("XLEAD2-1")` raised `ValueError: invalid literal for int() with
base 10: ''`.

The docstring is the contract and it documented two forms; a third input
produced a message about `int()`. `__contains__` inherits it, so the
mistake being reported is a membership test against a whole bank, which
that message says nothing about. It now names the problem and shows the
shape it wanted.

## 31. The import tool silently imported nameless favourites — FIXED

**Status:** **fixed 2026-09-20.** Real. **Reproduced**: a line of `PC  5`
with nothing after it parses to `('XLEAD2-1', 5, '', False)`.

A blank label in the browser is indistinguishable from a deliberately
anonymous favourite, and a truncated scan looks exactly like this. Such
rows are now tagged `check-scan` -- the tag the tool already uses for
entries it is unsure of -- and counted in the summary.

## 32. A favourites database from a newer p2ked gave a traceback — FIXED

**Status:** **fixed 2026-09-20.** Real.

`_migrate` refuses a newer schema, which is the right refusal, but
`main()` constructed the store outside any `try`, so the user saw a
traceback where every other startup failure produces `error: ...`. Now it
exits the same way.

## 33. The all-favourites view ran one SQL query per displayed row — FIXED

**Status:** **fixed 2026-09-20.** Real. Trivial at this scale, and the fix
is smaller than the finding.

`_fill_presets` called `self._favorite_keys(entry.bank_id)` inside the row
loop, redrawn on every toggle. `Favorites.keys()` exists for exactly this,
says so in its docstring, and was never called. One query now builds a
bank-to-numbers map before the loop.

## 34. Worst-case startup stall: ~12 s of silence against a half-answering unit — FIXED

**Status:** **fixed 2026-10-02.** The sweep is gone.

p2ked asked which ROMs the unit had by sending **one name request per ROM**,
twenty of them, at 0.6 s each — up to 12 s of silence before the first paint
against a unit that answers identity and then goes quiet.

The Configuration response already lists every fitted SIMM. Measured on
2026-10-02:

| method | requests | wall clock |
|---|---:|---:|
| `installed_roms` | 20 | 370.7 ms |
| `roms_from_config` (new) | 1 | **16.5 ms** |

23x, and the two were verified to return *identical dicts* on the unit, not
merely the same idea.

`installed_roms` is kept. It asks the question the name reader will actually
ask rather than believing the configuration block, and two independent
readings of one fact are worth more than 350 ms. The cheap one is for
startup, where there is no second reading yet to compare against.

**The trap, recorded because it is easy to get wrong:** user memory is not a
SIMM. The Configuration response reports it as `user_presets`, separately, so
`config.simms` on its own says the unit has no user banks — and a bank pane
built straight from it would start on a ROM and never show USER-0 at all.
`roms_from_config` adds that entry itself.

`DemoDevice` grew the same method, so demo mode takes the same startup path
as hardware and the bank pane filters to the fitted ROMs in both.

See RESOLUTION_NOTES §11.

## 35. App-level Enter could select a preset from an unfocused pane — FIXED

**Status:** **fixed 2026-09-20.** Real, and audible. **Reproduced**: with
`app.screen.set_focus(None)`, one press of Enter selected a preset -- the
unit plays, from a pane the user is not looking at.

The comment at the bindings correctly explained that a *focused* DataTable
consumes Enter, which is why selection normally arrives as RowSelected. It
did not follow that through to the case where nothing is focused, where the
App-level binding fires and `action_select_preset` acts on the preset
table's remembered cursor.

The cursor-silence rule is about movement; this is the same surprise one
step removed. Enter now means "the row I am looking at": it returns early
unless the preset table has focus.

**Reframed, 2026-10-08.** The library port removed the App-level Enter
binding altogether (the rest of the family binds it nowhere; selection
arrives as `RowSelected`). With no binding, a keypress can no longer reach
the guard, so the test that pressed Enter became a test of nothing. The
guard stays as defence in depth, and the test now calls
`action_select_preset()` with the *bank* table focused -- which is the only
way to reach it -- and asserts nothing plays.

## 36. The MidiQuest `.sqs` format is unread — shared across the projects

**Status:** open, and not specific to this instrument.

The owner's instrument folders hold `.sqs` files alongside the `.syx`
dumps. They are **MidiQuest's** own bank format, not the instrument's: an
IFF-style chunked file with `LIST`, `FORM`, `BANK`, `CHNL`, `SHDR`,
`FILE`, `TRAN`, `RECV`, `XTRA`, `MPIN`, `MPOT`, `BODY`, `AUDI`,
`BDEF` and `TDEF` chunks, sizes big-endian, and contents that are not
simply the raw SysEx.

The same format turns up for **every** instrument in the collection, so
decoding it once would serve rxved, kwsed, p2ked, x5ded and nanosyned
alike. Worth doing as shared work rather than five times over.

**Blocked on:** nothing but the decoding. Nothing here depends on it.

---

*Items 37 onward came from a full review of the current code on 2026-10-02,
reading every module rather than a diff. Item 37 is the only one that was
ever a live defect; it is here because the mechanism behind it is the sort
of thing this file exists to stop repeating.*

## 37. The `_busy` flag was checked in four places and set in none — FIXED

**Status:** **fixed 2026-10-02.** Real, and it had been dead since the
worker code was written.

`P2kedApp._busy` guarded four operations — `r`, `m`, `i` and the Enter
selection — and the auto-read path consulted it. Nothing ever set it to
`True`. It was initialised `False`, tested four times, and cleared in the
`finally` of two workers, so every check read `False` and the guard
described in the comments never fired.

The tell was that the comments were already there, describing the line that
was missing. Three of them read, in full:

> Set on the main thread, not in the worker. A `@work(thread=True)` method
> returns at once and would set the flag on its own thread, so two quick
> presses both passed the check above before either worker ran -- two of
> whatever the worker does, from one intent.

That is the race, correctly diagnosed, sitting immediately above a line
that was never written. **Three copies of the same comment and not one
assignment** is worth recording: the diagnosis was done three times and
each time stopped before the fix.

Two further holes would have appeared the moment the flag started working,
and both are the same shape — a worker that reads `_busy` but is not
itself counted:

- `_info_worker` had no `_busy` handling at all. With the flag live,
  pressing `i` would claim it and never release it, and the browser would
  refuse every operation thereafter with a status bar saying "busy".
- `_select_worker` cleared nothing. The same, one keystroke away, and the
  most audible of the three since a selection makes a sound.

All four workers now clear it in `finally`, all four callers set it on the
main thread before spawning, and the per-slot hand-off moved into an
`else` clause so the next operation cannot start while a bank's names are
still crossing to the main thread. Six tests pin it: that nothing starts
while busy, that five presses in one tick spawn exactly one worker, and
that a success, a failure, the info screen and a selection each release
the wire.

The flag's contract is now documented at its definition rather than
implied by three comments: **set synchronously on the main thread**, and
the reason is not obvious. `@work(thread=True)` returns immediately, so a
worker setting the flag on its own thread would set it too late and the
race the comments describe would still exist — just with the flag
populated and useless.

Note what was *not* done: no lock, and no queue. `self._lock` is the lock
and serialises the traffic; `_busy` is a refusal, so the second press says
so instead of silently waiting 2.5 s behind a bank read the user cannot
see. A queue would have been the friendlier behaviour and the wrong one —
the refusal is the whole point, and it is what the status bar is for.

**Blocked on:** nothing.

## 38. `wrap_blocks` treated a zero width as "no wrapping" — see item 17

**Status:** **fixed 2026-10-02.** Tracked with item 17 rather than
duplicated; the degenerate width made every candidate look too wide, so
the break was never taken and the legend became one long line.

## 39. `DemoDevice.preset_name` returned `Optional[str]` — see item 14

**Status:** **fixed 2026-10-02.** Tracked with item 14; the demo now
raises `TimeoutError` for silence, as the bridge does, and its
`read_bank_names` uses the same per-slot loop.

## 40. `p2kcli find` raised on every non-empty search — FIXED

**Status:** **fixed 2026-10-02.** Found by ruff's F821 and mypy's
`name-defined` when the quality-check pipeline was set up.

Two faults in `p2ked/cli.py` `_cmd_find`:

1. **`differs` was used and never bound.** Line 103 read
   `name + (" *" if differs else "")`; the loop unpacked three names and
   none of them was `differs`.
2. **The unpack itself was wrong.** `Catalog.search()` returns
   `(bank_id, program_change, name, differs)` — four items, since items 12
   and 23 — and the loop unpacked three. So the function raised
   `ValueError` before reaching line 103 at all, which is why the undefined
   name never surfaced as a `NameError` at runtime.

**Reproduced before fixing**, exactly as reported by the tools:

    $ python -m p2ked.cli find bell
    error: too many values to unpack (expected 3)

The fix is the fourth name. Both rules have been removed from the
`pyproject.toml` baselines, so an undefined name in that file is reported
again from now on.

**Why no test caught it:** `p2ked/cli.py` had **0% coverage** — no test
touched the file. That was the finding underneath this one. `tests/test_cli.py`
now exists and drives every command through `main()`, so the argument parser,
the dispatch table and the offline/device split are all under test;
`p2ked/cli.py` is at 78%.

## 41. `(not installed)` is not returned by every ROM — CHARACTERISED 2026-10-02

**Status:** characterised, and **closed for every use p2ked makes of it**.
What remains is one unanswered question about the hardware, recorded rather
than resolved, because answering it would take the front panel.

`(not installed)` is load-bearing twice: `read_bank_names` drops absent slots
by it, and `installed_roms` turns "is this ROM fitted?" from a timeout into
an answer. §7 found it on X-Lead v2 and reasoned from there that a unit
answers a request for a preset it does not have.

**Three of the four fitted ROMs agree. Composer does not.**

### What Composer actually does

Asked for a preset it does not have, Composer returns `   :default` and
keeps returning it. Not for a while -- for **every representable preset
number**:

```
COMPOSER  #1022  'brs:SforzadoEnsb'      the last real preset
          #1023  '   :default'          the empty slot (TODO 5)
          #1024  '   :default'
          #2048  '   :default'
          #8192  '   :default'
          #16382 '   :default'          the largest number but one
```

There is no point at which it admits the preset does not exist. **A name
request cannot discover Composer's extent**, and by extension no amount of
probing would tell p2ked where that ROM ends.

(The other three ROMs are exact and deterministic -- 6 repeats of each
boundary slot, 6/6 identical: X-Lead v2 #639 named then #640 absent,
Techno Synth #511 named then #512 absent, Beat Garden likewise.)

### Why this does not bite p2ked, measured rather than argued

Two places depend on the sentinel. Both were checked against the unit:

**1. `installed_roms` is sound.** It asks preset 0 of every ROM in the
table and reads the reply. All **15 unfitted** ROMs answer `(not installed)`
for preset 0 -- Extreme, Audity, Protozoa, Definitive B-3, Xtreme Lead,
Sounds of the ZR, World Expedition, both Orchestrals, Pure Phatt,
Ensoniq Project, Proteus 2500, Vintage Collection, Holy Grail and Advanced
Orchestra -- and all 4 fitted ones answer with a name. The sentinel is
reliable for the only question p2ked ever asks of it.

**2. `read_bank_names` is safe.** It only ever asks about slots the table
says exist, and drops anything that comes back absent. Composer's empty
#1023 is kept and shown as "default", which is what the unit says and what
the catalog says too.

**3. And this is the finding that closes the last loophole:** Composer's
behaviour is exactly why **runtime correction of the ROM table was dropped**
in item 5 rather than deferred. A scheme that worked out each ROM's extent
by probing would have worked for three ROMs and failed silently for
Composer — reporting a ROM far larger than it is, which is the one failure
mode item 5 existed to prevent.

### The constraint, stated for whoever extends this

The sentinel is a **courtesy, not a guarantee**. Anything that needs to know
where a ROM ends must not assume the unit will say so. The ways p2ked gets
that right today are the ROM table (from E-MU's files, checked against this
unit for all four fitted ROMs) and the Configuration response's per-SIMM
count. Neither is a name request.

### Two smaller things found on the way

- **Preset number 16383 is silent on every ROM tested**, fitted or not --
  Techno Synth and Composer alike. It is the largest 14-bit value, so this
  looks like a reserved edge in the firmware rather than an extent boundary.
  Nothing in p2ked asks for it.
- **The unit can go briefly unresponsive.** Once, immediately after a sweep
  of 1664 names, three consecutive requests timed out at 2 s each and then
  the unit recovered and answered normally. Six repeats of each boundary
  slot afterwards were identical every time, so this is not boundary
  nondeterminism. p2ked degrades safely -- `read_bank_names` catches the
  timeout per slot and records no name for it -- and
  `tools/measure_send_gap.py` is built to catch exactly this, which is why
  it compares against a reference read instead of counting successes.

### What is still open

**Why** Composer differs, and **whether its true extent is 1024**. The
catalog says 1024 names, the table says 1024 slots, the Configuration
response says 1024, and the unit holds 1023 populated presets plus one
empty slot -- three independent sources agreeing. The likeliest reading is
that this ROM simply answers "empty" rather than "absent", but that is a
hypothesis about firmware behaviour and is not recorded as a fact.

Answering it properly needs the front panel, or a unit with a different
Composer ROM revision. See RESOLUTION_NOTES §11.

## 43. Silence was claimed where only a wire could be checked — FIXED

**Status:** **fixed 2026-10-02.** Found while reviewing what the third
hardware session had actually established.

That session wrote "nothing sounded", in this file, in
`docs/RESOLUTION_NOTES.md` §11 and in `tools/measure_send_gap.py`. **The unit
had no audio connection.** Nobody could hear whether a read made a noise, so
the claim was not merely unverified — it was unfalsifiable, and it sat in a
document whose entire purpose is separating what was verified from what was
assumed. Worse, it was unfalsifiable *in the reassuring direction*, which is
the kind of unfalsifiable claim that does real damage.

The interesting part is what was available instead. This instrument makes
sound by receiving **Channel Voice** messages, status bytes 0x80-0xEF: Note
On/Off, Control Change, Program Change, Pitch Bend, and both aftertouch
forms. System Exclusive that asks a question cannot do that. So the claim
is not lost, it is replaced by one that is checkable:

> No read emits any Channel Voice message. Which is the only route to sound.

Measured during a full 1024-preset sweep: **1027 messages sent, 1027
System Exclusive, 0 anything else.** And structurally, `p2k/bridge.py` has
five `send_message` call sites; four build System Exclusive, and the three
that do not are the Bank Select CCs and Program Change inside `select()`.

`tests/test_no_sound.py` pins both, with the guard this project's tests
usually carry: a second class asserts a selection *does* emit the expected
three messages, so the read tests cannot pass merely because nothing ever
sends anything. Both halves were checked against deliberate mutations — a
`select()` that sends nothing, and a read method that sends a note — and
each failed the test that should have caught it.

**The lesson, and why it is item 43 rather than a line in a commit
message:** "it was silent" and "it could not have been audible" are
different claims, and on a project whose whole discipline is not writing
down more than was shown, the difference is the whole subject. The first is
a fact about a room; the second is a fact about a wire. Only one of them
survives being checked twice by different people.

**Still genuinely open:** whether the unit made no noise. That needs it
wired to an output and somebody listening. Not attempted.

## 42. `pytest-asyncio` was never a declared dependency — FIXED

**Status:** **fixed 2026-10-02.** Found while setting up the check pipeline.

`pyproject.toml` sets `asyncio_mode = "auto"` under
`[tool.pytest.ini_options]` — a **pytest-asyncio** setting — and
`tests/test_app.py` is marked `@pytest.mark.asyncio`, but pytest-asyncio was
in no dependency list anywhere. It worked only because the development
machine happened to have it installed system-wide.

A clean virtualenv exposed it at once: 34 tests failed with "async def
functions are not natively supported". Now pinned in `requirements-dev.txt`
and in the dev extras.

**The generalisable lesson, and the reason it is here rather than only in
the commit:** a test dependency that is *used* by configuration is as real a
dependency as one imported by a module. `deptry` cannot find this one —
it reports only imports — so the gap had to be closed by hand, and would
have stayed open indefinitely on a machine whose system packages happened to
match.

## 44. The shared settings file and the published library — 2026-10-08

**Status:** partly fixed; two things need a human with push access.

The full review of the `unify` merge is in
`docs/REVIEW-unify-2026-10-08.md`. Most of it is fixed in the tree beside
this note. What is left:

1. ~~**vinsynlib must be pushed and tagged `v0.2.0`.**~~ **Done, 2026-10-09.**
   vinsynlib 0.2.0 is published on PyPI and tagged `v0.2.0`. The tag
   `vinsynlib @ git+…@v0.2.0` now exists, and the ten siblings depend on
   `vinsynlib>=0.2.0` from the index rather than a sibling checkout. What
   remains is the `entry.py` change itself: p2ked uses `MINIMUM = (0, 2, 0)`,
   and the other nine still carry `(0, 1, 0)`.
2. **A per-tool config directory is the proper fix** for nine tools sharing
   one relative `config.toml`. The header guard and the table check stop
   them destroying each other's settings and stop one adopting another's
   remembered port, but the second tool in a directory still cannot save
   its own. Moving the default to `config_dir(tool)/config.toml` fixes that
   properly, at the cost of a family-wide change to `spec.py`'s `--config`
   help and every tool's conformance test. Not done here: it is a contract
   change, not a bug fix.
## 45. Every user-bank preset was marked `*` as saved over — FIXED 2026-10-09

**Status:** **fixed.** Real, and reported from the field: opening the
browser and letting it read a user bank put a trailing `*` on all 128
names, with the footnote "saved over the factory preset" under every one
and a status line reading "read 128 names from USER-2; 128 differ from the
printed catalog".

**Cause.** `Catalog.differs` compared the live name against the printed
one, and a user bank's printed "names" are E-MU's own placeholders. Their
instrument-definition file cannot document what a user saves into user
memory, so the user-bank sections hold `usr:A0` … `usr:D127` — 512 rows
across the four banks. A real preset name can never equal `usr:C0`, so the
comparison was guaranteed to "fail" for every slot in every user bank,
whether or not anybody had touched it. Reproduced against the real
generated catalog:

    USER-0: printed='usr:A0'   differs=True   (before: every slot)
    XTREME-0: printed='arp:…'  differs=True   (a real printed name)

`p2ked/app.py`'s `_auto_read_user_names` already knew this — its docstring
says a catalog entry for a user bank is "a placeholder and always wrong" —
but that knowledge was never carried into `Catalog.differs`, which is where
the `*` is decided.

**Fix, in two parts.**

1. **`Catalog.differs` compares only where the printed list has authority**,
   which is a ROM: a bank whose `rom.writable` is true answers False, because
   there is nothing real to disagree with. `disagreement` therefore no longer
   needs its `writable` parameter (it is gone, rather than left to be passed
   and ignored) and has one sentence left.

2. **The user-bank flag is rebuilt against the right baseline.** The
   comparison that would mean something is this bank against *itself* at the
   start of the session — proposed by the maintainer in review. `r` on a user
   bank takes a baseline on its first read; the next read compares against it
   and flags the presets whose name changed since p2ked was opened. The
   baseline is frozen for the session (re-anchoring would make a `*` vanish
   the moment it was noticed). No printed catalog is involved, so nothing that
   cannot know what a preset is gets a vote.

   The baseline is taken **lazily**, on the first read of each bank, not by
   reading all four user banks at startup: four banks is about ten seconds of
   System Exclusive, the bus carries one thing at a time, and p2ked reads a
   user bank the moment it is looked at anyway. The one cost is that a preset
   edited elsewhere *before* its bank was first opened shows no mark — p2ked
   cannot know what it said before it first asked.

   The mark, the detail footnote, the search view and the status line now come
   from `P2kedApp._marked_because`, which decides which of the two complaints
   a slot is carrying: "changed since p2ked was opened", or the printed list
   being wrong — and says which, because a reader deserves to know which.

**What is still not flagged, and why.** A user bank the unit was in before
p2ked ever asked. There is no source for that but the unit itself, and
asking for it is the baseline read. If an eager startup read of the four user
banks is wanted, it is a small change to `_auto_read_user_names`; it has not
been made because of the ten seconds and the single bus.

Tests: `tests/test_roms.py::TestWhatADisagreementMeans` (user bank never
marked against the printed list, ROM bank still marked, an unknown bank id
keeps the comparison so a
`tests/test_app.py` (a read user bank is not flagged, and the status line
says the baseline), `tests/test_cli.py::TestFind` (the printed-list marker is
exercised on a ROM slot, since a user slot cannot produce that one).
## 46. The favourites view moved from `F` to `v`, as rxved's is — FIXED 2026-10-09

**Status:** **fixed.** Not a defect in itself, but the same error-prone
shift-pair rxved had already moved away from.

`f` **writes** the favourites database and `F` only read it, so a slip of
the shift key turned a browse into an edit. `v` has no such twin, and it is
where rxved had already put it. p2ked now agrees, which also leaves one
fewer thing to learn between the two.

The family's contract still puts `cycle_favorites` on `F`, so this is a
declared divergence -- and `vinsynlib.conformance` asks a tool that renames
a shared key to say so in its own test. `tests/test_conformance.py` now
asserts exactly the two binding problems and the one legend problem this
produces, and nothing else: anything further appearing there is real drift
to be fixed rather than added to the set. Changing the family's key instead
would be the other route, and would touch all nine tools and their
conformance tests; that is a contract change, not this.

Found while doing it, and fixed separately in spirit: `p2kcli select` reads
the remembered channel, and the AST guard in `tests/test_legend.py` covered
`config.save_*` only -- so a *read* of the developer's real `./config.toml`
decided which channel the suite sent on. The guard now covers `load_*` too,
and the test names its file.

## 47. The per-channel parameter IDs — the probe is written, the answer is a session's

**Status:** open, and not closable from software: it needs a unit on the
desk.

`probe_channel_ids()` in `p2ked/masteredit.py` reads a range of parameter
IDs -- 662-1023 by default, the block after the master arpeggiator at
641-661, which is a hint about where to look and is labelled as one -- and
reports which of them answer. It takes a `read` callable, sends nothing, and
does not try to match the answers against the dump's nine fields by itself:
a value that happens to agree once is not a mapping, and this is a finding
to be recorded rather than an assignment to be made automatically.

**Why the answer is not in here.** The Setup Dump carries all nine
per-channel values positionally, so reading them is solved; setting one
needs its parameter ID, and no document to hand lists them.
`CHANNEL_EDIT_IDS` is `None` for that reason, and the edit screen refuses a
per-channel edit with a sentence (`CHANNEL_EDIT_HINT`) rather than sending
to a number it invented. A wrong ID is a write to a place nobody named,
which is the one failure this project's own rules forbid.

**For the next hardware session:** run the probe against a real unit,
establish which answering ID is which of the dump's nine fields, and record
the mapping here -- after which per-channel editing needs nothing but the
table.

## 48. Editing exists — the gate, the log, and the read-back — 2026-10-10

**Status:** done. `p2ked/masteredit.py` is the logic and has no I/O in it,
`p2ked/multi.py` is the screen, `p2ked/app.py` is the wire, and
`p2k/bridge.py` grew `set_parameter()` beside the reads. Item 7's "no
editing, and no plan to add it casually" is reversed; what was built is the
apparatus that item asked for.

The write path is the family's editor shape rather than an invention: a
write gate locked by default (`w` arms it, and the edit screen says which
state it is in instead of leaving the question to a keybinding manual), an
undo log (`z` the last edit, `Z` all of them) that sends the *previous*
value back, because the old value is recorded before the new one goes out,
and a read-back after every edit on the same worker -- nothing lands
between the write and the verification. Only what the read-back agrees with
is logged, so undo cannot restore a thing that never arrived, and a request
the unit ignored rather than refused is caught by that read instead of
looking like a success.

Master parameters only, and that is the whole safety argument: every ID in
`MASTER_PARAMETERS` is one p2ked already reads, read back from a unit and
agreed with the dump (RESOLUTION_NOTES §10). Per-channel editing is refused
with a reason -- see item 47.

Exercised end to end against the demo device: an edit changes the value,
the read-back agrees, the log holds `(385, 2, 0)`, and `z` sends the
previous value back. `tests/test_masteredit.py` covers the gate, the range
check, the refused read-back, the undo log and the probe (`make check`:
323 passed, 1 skipped), and `--allow-write` arms the gate from the command
line while the default stays locked.

**Two things the apparatus needed that are in, now.** `--allow-write` is
wired: `build_parser()` passes `allow_write=True` to `add_common_arguments`
and `main()` threads it into the `EditGate`, so the docstrings' promise is
true. And the undo keys are the browser's too: `P2kedApp` binds `z`/`Z` to
real actions (`action_undo` / `action_undo_all` → `_undo_master_edits`), so
undo works with the edit screen closed instead of the legend advertising
keys that did nothing. One bug found on the way: Textual's modal screens cut
the app's binding chain, so `w` was unreachable while the master editor was
open -- the screen now binds it against the same gate object.

## 49. The modals you could not leave, and the edits you could not see — FIXED 2026-10-10

**Status:** done, in `f78cef5` (382 passed, 1 skipped, 78.32% coverage). Found
by driving the TUI, not by the tests -- which is the point of driving it.

Nine defects, one commit: `escape`/`q` were bound to an `action_close` that
did not exist on either modal (a modal also cuts the app's own `q`, so both
screens were traps); a locked-gate or range refusal was written to the app's
status bar, which the modal covers as its tinted backdrop, so a refusal
looked like silence; a *successful* edit reached the unit but the "now" cell
was never redrawn (`_values` was never updated and `refresh()` repaints
nothing); enum parameters were typed as an index although `choices` already
carried the names; there was no `+`/`-` nudge; the multi screen had no
per-channel detail, so Enter did nothing and the refused-with-a-reason hint
lived where nobody was looking; the MIDI channel was announced once, after
a change, and never shown again; the demo routed all 32 channels to a send,
so it reported "32 of 32 would not sound" over its own deliberately-enabled
channels -- flatter than life, which is the one thing this fake is not
allowed to be; and `z` said "nothing to undo" with a favourite toggled,
because favourites were not in the undo timeline at all.

What landed: `action_close` on all four modals; a status line *inside* the
modal, where the refusals are said; the "now" cell and the note redrawn
after a verified edit; rxved's shape of named-value picker for enum
parameters; gated, range-clamped, undo-able `+`/`-`; a read-only channel
detail (all nine parameters, the why-not reasons, the refusal's reason); the
channel in the window's subtitle; demo channels routed per what they play;
and one undo timeline (`EditChange | FavouriteChange`) so `z` reverses the
most recent change of either kind -- the master edit through the wire, the
favourite through the local store, no frame for it.

## 50. The master FX block is not editable — FIXED 2026-10-10

**Status:** done, in `e16f14f`. `x` on the multi screen opens the FX editor
on the master editor's own apparatus: the same gate, the same read-back
after every send, the same undo.

`FX_PARAMETERS` in `p2ked/masteredit.py` is the block transcribed --
sixteen parameters, ids 513-528, every label, range and named list cited in
§12 ("The master FX block: sixteen parameters, transcribed the same way"),
which also records where the documents disagree. The two algorithm
parameters are named lists (44 and 32 names), so they are picked rather than
typed; the rest are ranges. The IDs are unit-agreed master-block IDs -- the
§10 standard, and the module docstring claims no more than that. Same
standing caveat as the general block: no unit has been asked which range
its firmware enforces, so the first real FX edit is a hardware session like
the first real master edit.
