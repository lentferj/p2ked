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

## 12. `catalog.search` drops the disagreement it knows about

**Status:** open, real, and the most useful item on this list. **Verified.**

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

**Blocked on:** nothing. Return the `differs` flag alongside, and have the
search report render the same marker the browser does.

## 13. `bridge.identify` does not drain before sending

**Status:** **rejected -- does not reproduce.**

`ProteusBridge.identify` calls `self._drain()` as its first statement,
`p2k/bridge.py:272`, and has since the initial commit `d003569`. The
finding states the opposite. Every bridge method that sends a request
drains first; there is no exception to align.

## 14. `DemoDevice.preset_name` and the bridge's differ in return type

**Status:** open, cosmetic. **Verified** -- `p2ked/demo.py:306` returns
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
