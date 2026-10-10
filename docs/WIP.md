<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# WIP — the multi menu (rxved parity) and editing

**Closed at hand-off, 2026-10-10: every item below landed on `master`, and
`make check` is green (323 passed, 1 skipped, 75.98% coverage).**

The note below is kept as the record of what the work was. The first session
picked the tree up BROKEN and uncommitted, ran `make check`, fixed the
failures in the order listed, and committed in logical chunks; the "Not
started" list followed: the edit-path tests (`tests/test_masteredit.py`),
§12, CLAUDE.md, TODO items 9/47/48, the README, the DISCLAIMER, and this
header. Two doc caveats the follow-up passes left stale are now true:
`--allow-write` is wired, and `z`/`Z` undo from the browser.

---

## The plan, and the decisions already taken

These are settled. Do not re-litigate them; if you disagree, change the note
rather than silently doing it differently.

* **Editing is IN.** The maintainer chose it. CLAUDE.md still says p2ked
  "does not write to the unit's memory, and should not start" — **CLAUDE.md
  is now wrong and must be updated** to describe the apparatus below.
* **Read-only still applies to the read path.** The multi screen reads one
  Setup Dump and needs no writes.
* **Writes follow the family's editor shape**, not a new invention:
  a write gate (`w`, or `--allow-write` to start armed, locked by default),
  an undo log (`z` / `Z`), and a read-back after every edit.
* **Nothing is written to a parameter ID p2ked cannot name.** The master
  parameters have IDs that were read back from a unit and agreed with the
  dump (RESOLUTION_NOTES §10). The per-channel ones do not, so per-channel
  editing is *refused with a reason* rather than guessed at.
* **Multisetup browsing is deferred**, per the maintainer ("record that for
  later"). The primitive that makes it possible is built and documented;
  there is no UI.
* Writes touch `p2ked` only. Other repos are read as reference.

## Reference material

Extracted from the PDFs on this machine, readable as text:

```
/tmp/opencode/manual/p2000.txt      Proteus 2000 Operation Manual (11538 lines)
/tmp/opencode/manual/sysex.txt      Proteus Family SysEx Specification v2.2
/tmp/opencode/manual/paramtree.txt  PROTEUS 2000 PARAMETER TREE v2.26
```

`/tmp` is a small tmpfs on this box and was full at one point — check
`df -h /tmp` before writing anything large there.

The three facts that shape the work, all transcribed below in the file:

* **"Multi" is two different things on this machine.** MIDI Mode
  (Omni/Poly/Multi, parameter 385) decides whether *any* per-channel setting
  means anything. Multisetups are 128 stored snapshots of all 32 channels,
  selected with cc00=80, cc32=00, then a Program Change. They are not the
  same feature and the code keeps them apart.
* **Only the *current* setup can be dumped.** To read setup 42 you must make
  it current, and the only way is `Copy Master Setup (2Ch)` — "Copy destroys
  whatever Parameters existed in the Destination location", and either the
  source or destination must be the Setup Edit Buffer (-1). That is the
  whole of multisetup browsing: dump to back up, copy N to the edit buffer,
  dump again, restore.
* **The dump declares its own counts** (master general/MIDI/effects, non-
  channel, channels, parameters per channel) in its header, so the channel
  block is found structurally, not by a hardcoded offset. p2ked already does
  this; keep it that way.

---

## Done, but uncommitted

* `p2k/messages.py` — `ChannelState.silence_reasons()` (the full documented
  cause set; `silent_because` is now its first entry), `Command.COPY_MASTER_SETUP`,
  `SETUP_EDIT_BUFFER`, `copy_master_setup()`, `parse_copy_master_setup()`.
  Round-trip verified: `copy_master_setup(42, -1)` → `f0180f7f552c022a00 7f7f f7`.
* `p2k/bridge.py` — `set_parameter()`, `copy_master_setup()`.
* `p2ked/masteredit.py` — **new.** `MASTER_PARAMETERS` / `MASTER_BY_ID`
  (transcribed ranges and labels, with citations), `EditGate`, `EditLog`,
  `MasterEditor` (pure logic: `allow` / `finish` / `undo_plan` /
  `undo_report`), `probe_channel_ids()`. No I/O in it, on purpose.
* `p2ked/prompts.py` — **new.** `PromptScreen` moved out of `app.py`,
  because `multi.py` needs it and importing `app.py` from a screen is a
  cycle. `app.py` re-exports it, so old import sites still work.
* `p2ked/multi.py` — **new.** `MultiScreen` (32 channels, all nine
  parameters, master panel, full why-not column, `r` to re-read) and
  `MasterEditScreen` (gated, undo, per-parameter prompt), plus
  `CHANNEL_EDIT_HINT`.
* `p2ked/app.py` — `ChannelScreen` deleted, `MultiScreen` wired in,
  `w`/`z`/`Z` bindings, gate and editor created lazily, `_apply_master_edit`
  / `_undo_master_edits` workers with read-back.
* `p2ked/cli.py` — `_cmd_channels` rewritten with `--json` and new columns;
  helpers `_plays`, `_rom_name`, `_master_line`.
* `pyproject.toml` — per-file ignores for the three new modules.

## BROKEN — the immediate fix, in order

1. **`p2ked/cli.py` has a duplicate `sub.add_parser("channels")` block**
   immediately after the working one, taking `--json`. Delete the second
   block entirely and put the `--json` argument on the *original*
   subparser (grep for it: it is the `"channels"` help line about "every
   MIDI channel: what it plays, and why it might not").
2. **`ruff check` and `ruff format`** were passing before the CLI edit and
   have not been run since. Run them.
3. **`p2ked/demo.py` needs `set_parameter()` and `copy_master_setup()`** —
   it owns the state the editor mutates, and without them the app cannot be
   imported in a test. Mirror the existing `read_parameter` shape; the demo
   should record what was set so a test can assert it.
4. **`tests/test_app.py` still imports the deleted `ChannelScreen`**
   (line 27) and has three `TestChannelScreen` tests to convert to
   `MultiScreen`. Run the suite to find the rest.
5. **`make check`**, then commit.

## Not started

* Tests for the edit path: gate locked by default, a locked edit refused,
  range refused, a refused read-back not logged, undo sends the previous
  value, `probe_channel_ids` writes nothing.
* `docs/RESOLUTION_NOTES.md` §12 — the transcription, with page cites for
  every number: the nine per-channel parameters, the master blocks and their
  counts, the Copy Master Setup semantics, the Parameter Value Edit format.
* `CLAUDE.md` — the write apparatus, and the rule that a parameter ID is
  never invented.
* `TODO.md` — close item 9's "p2ked has nothing equivalent"; add 46
  (editing exists, with its apparatus) and 47 (the probe; the per-channel
  IDs are the hardware session's job).
* README — `m`, `w`, `z`, `Z`, `--allow-write`, `p2kcli channels --json`.

## The one honest gap

Per-channel editing is refused, with a sentence explaining why. That is not
laziness: a wrong parameter ID is a write to a number nobody knows, which
this project's own rules forbid. `probe_channel_ids()` is the read-only way
to establish them on a real unit, and the next hardware session should run
it and record the answer in TODO 47.
