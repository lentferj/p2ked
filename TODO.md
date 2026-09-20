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

## 4. `SEND_GAP` is a guess

**Status:** open, blocked on hardware.

E-MU gives no inter-message timing at all; the only guidance is to keep a
message under 244 data bytes. `SEND_GAP` is the sibling projects'
conservative default. A name sweep of a 1024-preset ROM spends a thousand
of them, so this is worth measuring early.

## 5. Preset counts are bank counts

**Status:** open, and now fixable. A unit answers past the end of a ROM with
the name `(not installed)` rather than going silent, so the real extent of
every fitted ROM can be found by asking — silently, and without a timeout.
`roms.is_absent` recognises it and `read_bank_names` drops those rows; using
it to *correct* the table at runtime is the remaining work.

The instrument-definition files describe *banks*, not populated presets, so
`roms.ROMS` gives every ROM `banks * 128`. A ROM whose last bank is partly
empty will show rows that name nothing. Deliberate: an over-long bank shows
empty rows, a short one hides presets, and a hidden preset is not
discoverable by the person looking for it.

A unit's Configuration response reports the real per-SIMM preset count and
could correct this at runtime.

## 5b. ROM 14 has no name

**Status:** open, needs the front panel.

A unit reported SIMM ID 14 with 640 presets, and it answers name requests
for all 640. No instrument-definition file to hand covers MSB 14, so p2ked
has the numbers but not the ROM's own name, and System Exclusive has no
object type to ask for one. It is in the table as "ROM 14 (unidentified)".

The unit's own display knows. Whoever has the unit can say.

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
switches and routing, plus a report on why a channel is silent. p2ked has
nothing equivalent.

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

**Blocked on:** nothing.

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

## 14. `DemoDevice.preset_name` and the bridge's differ in return type

**Status:** open, cosmetic; see item 22, which checked the hazard and found
none. **Verified** -- `p2ked/demo.py:306` returns
`Optional[str]`, `p2k/bridge.py:359` returns `str` and raises
`TimeoutError` for silence.

The demo is deliberately not a mock of the bridge; it is a second
implementation that never opens a port. Still, the two are used
interchangeably by the app, and the difference is exactly where a `None`
would reach code written against the bridge's signature.

**Blocked on:** nothing. Either match the bridge and raise, or say in
`demo.py` why it does not.

## 15. The `tomllib` fallback in `config.py` cannot execute

**Status:** open, harmless. **Verified** -- `pyproject.toml:10` declares
`requires-python = ">=3.11"` and `tomllib` entered the standard library in
3.11, so the `except ModuleNotFoundError` branch at `p2k/config.py:42-44`
is unreachable and `tomllib is None` is never true.

Note there are guards downstream that test `tomllib is None` (`_read`
returns early on it). Removing the fallback means removing those too, or
they become the dead code instead.

**Blocked on:** nothing.

## 16. A tool reads a file without closing it

**Status:** open, real in **one** of the three places cited.

`tools/import_favourites.py:56` iterates `enumerate(open(path,
encoding="utf-8"), 1)`, which holds the file open for the whole loop with
no name to close it by. That one is real.

The other two the review names are already correct: `tools/extract_catalog.py`
lines 100 and 126 both use `with open(...) as handle`, as does line 337.

**Blocked on:** nothing; one line.

## 17. `wrap_blocks` does not guard against `width <= 0`

**Status:** open, safe. **Verified** -- `p2ked/app.py:87`, no guard; the
only caller clamps with `max(self.size.width - 2, 20)`.

Worth noting what the function is for, per its own docstring: the legend
wraps rather than truncating, because a footer that silently drops its
last few keys teaches the user those keys do not exist. A width of 0 would
be the degenerate version of exactly that failure.

**Blocked on:** nothing. `width = max(width, 1)`.

## 18. `roms.presets` recomputes its base offset on every call

**Status:** open, cosmetic. **Verified** -- `p2k/roms.py:332-337` walks
`entry.rom.lsbs` to find the bank's base each time, and `_fill_presets`
calls it on every cursor move.

At 128 presets across 74 banks this is not measurable. The reason to leave
it alone is stronger than the reason to cache it: `lsbs` is the installed
ROM set, which the app can change at runtime when the fitted-ROM filter is
toggled, so a cache keyed on `bank_id` would need invalidating on exactly
the event most likely to be forgotten.

**Blocked on:** a reason. None yet.

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

**Status:** open, a suggestion rather than a defect. Not acted on.

mypy is not installed here and none of the four sibling projects configures
it. The two places the review names as beneficiaries have both since been
settled by other means: item 22's signature mismatch is real but
unreachable (see there), and item 23's return type has changed shape and is
pinned by a test. Worth doing across all four together, or not at all --
one project with `mypy --strict` and three without is the worst of both.

**Blocked on:** a decision to adopt it everywhere.

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

## 22. `DemoDevice.preset_name` silence behaviour differs from bridge

**Status:** open, cosmetic. **The hazard it claims does not exist.**

The return types do differ, as item 14 says: `Optional[str]` against `str`.

But "the app calls both interchangeably" is not so. Checked every call
site: `preset_name` has three callers, and each is inside the class that
defines it -- `bridge.py:430`, `bridge.py:507` and `demo.py:323`. The app
never calls it at all; it calls `read_bank_names`, and the demo's own
version already skips `None`. There is no path by which a `None` reaches
code written against the bridge's signature.

So: a consistency wart worth tidying, not a crash waiting to happen. Fixing
it is still the right call, and option (a) -- make the demo raise -- is
still the better one.

**Blocked on:** nothing.

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

## 34. Worst-case startup stall: ~12 s of silence against a half-answering unit

**Status:** open, bounded, **not acted on** -- and partly mitigated by
item 27.

The sweep of 20 ROMs at 0.6 s still runs before the first paint, so a unit
that answers identity and then goes quiet still costs up to 12 s with no
per-ROM progress. What item 27 changes is the *other* stall in front of it:
the port sweep is now skipped when a remembered port answers.

Shortening the per-ROM timeout wants the same hardware session that
measures `SEND_GAP` (item 4). Guessing it shorter without measuring is how
a ROM that is fitted stops being listed.

**Blocked on:** a measurement.

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
