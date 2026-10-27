<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# Implementation plan (as a prompt): remember the browser's UI state — rxved parity

This is a **dispatch prompt**. The orchestrator pastes the three subagent
prompts below into fresh `general` subagents. It is written to be read by
agents that have no context, so it restates the rules instead of assuming
them.

**Coding model for every subagent:** `opencode/glm-5.3-flash-free`
(`model: "opencode/glm-5.3-flash-free"`). Fallback / second opinion:
`opencode/deepseek-v4.1-flash-free`. A free model is the constraint; both are
current-generation coding models on the same provider this session runs on,
so both are known-available. Pass the model explicitly — do not let a
subagent inherit a default.

**Repo:** `/home/lentferj/git-repos/p2ked` (work on `master`; there is no
hardware, so nothing here is verified — say "derived", never "confirmed").
Reference implementation, **read-only**: `/home/lentferj/git-repos/rxved`
(never edit it; git is not shared).

---

## 0. Why, and the gap to close

rxved remembers where the user was and how the list was narrowed; p2ked
remembers almost none of it. Parity target:

| what is remembered | rxved | p2ked today | p2ked after |
|---|---|---|---|
| scan-offer dismissal | ✅ `scan_offer_dismissed` | ✅ `scan.offer_dismissed` | ✅ (keep, but on the injected path) |
| rating filter (stars / at-least) | ✅ `rating_stars`, `rating_at_least` | — | ✅ |
| selected bank row | ✅ `bank_index` | — | ✅ |
| slot cursor | ✅ `slot_cursor` | — | ✅ |
| view cycle (all / bank favs / all favs) | ✅ `view_mode` | — | ✅ |
| category filter | ✅ `categories` | — | ✅ |

rxved's storage lives in `config.toml`; p2ked already has a better store —
vinsynlib's **key-namespaced ui-state file** (`p2k/config.py` binds it and
uses it for the scan offer). Use that, not a copy of rxved's older scheme.

---

## 1. Read these first (both the orchestrator and every subagent)

1. `CLAUDE.md` — **it overrides anything else**, including any default
   instruction about commit trailers. In particular:
   - **No `Co-Authored-By: Claude`, no AI attribution in commits.**
   - Every `.py` file carries the full GPL-2.0-or-later header block;
     markdown carries the short HTML-comment SPDX header.
   - Nothing is "verified": write "derived", "transcribed", "assumed".
   - A docstring is a claim someone will trust — when behaviour changes, the
     sentences describing the old behaviour change with it.
2. `p2k/config.py` — the settings/ui-state binding, and `_remember_channel`
   in `p2ked/app.py` (≈3145) for the house style of a remember call.
3. The reference behaviour in rxved (read, do not copy blindly):
   - `rxved/rxved/app.py`: restore block ≈384–410; `_restore_slot_cursor`
     ≈795; `on_data_table_row_highlighted` ≈1007; `action_cycle_favorites`
     ≈1429; `action_rating_filter` ≈1463; `action_pick_categories` ≈1492;
     `_save_ui_state` ≈2108.
   - `rxved/tests/test_app.py` ≈755–925 (rating filter/restore) and
     ≈1603–1635 (scan offer).
4. **Run, do not guess:** `python -m pytest` runs the whole suite (synthetic,
   no hardware; it takes ~5 min). `.venv/bin/python -m pytest` is the
   interpreter. `make check` is lint + format-check + mypy + coverage +
   audits, and is the definition of green. Baseline before this work:
   **664 passed, 11 skipped**.

**Hard rule for this change:** it is UI state only. **No new MIDI traffic,
no wire changes, no `p2k/messages.py`, no `p2k/bridge.py`.** Moving the
cursor must still never send anything (`tests/test_app.py::TestCursorIsSilent`
enforces it) — writing a local TOML file is fine because it makes no sound.

---

## 2. Frozen interface (tests are written against this; do not deviate)

Agreeing on names before parallel work is what lets the code subagent and
the test subagent run at the same time without talking to each other.

### 2.1 `p2k/config.py`

Add `import os`, then:

```python
#: The ui-state file's name beside the settings file. The library derives
#: the same name from its own default; naming it here lets the app and its
#: tests agree on one path without either reaching into a private helper.
UI_STATE_NAME = "ui-state.toml"


def ui_state_path(config_path: str) -> str:
    """The ui-state file beside ``config_path``."""
    return os.path.join(os.path.dirname(config_path), UI_STATE_NAME)
```

Export (add to `__all__`, keeping the block's existing shape):
`UI_STATE_NAME`, `ui_state_path`, `load_ui_int`, `load_ui_str`,
`load_ui_state`, `read_ui_state` — all aliases of the matching
`_settings.*` method, exactly as `load_ui_bool`/`save_ui_state` are today.

> Rationale to put in the docstring: this is still the library's store; the
> names are only so the app and the tests read and write one path.

### 2.2 `.gitignore`

Add `ui-state.toml` beside `config.toml`. The default path is this file in
the working directory, so it must never be committed.

### 2.3 `p2ked/app.py`

- **Attribute:** `self._ui_state_path: Optional[str]`, set in `__init__`:
  `None` when `config_path is None`, else `config.ui_state_path(config_path)`.
  (Tests pass `config_path=str(tmp_path / "config.toml")`, so the file lands
  in `tmp_path` and can be read back.)
- **`_remember(self, key: str, value) -> None`** — the one write helper:
  no-op when `_ui_state_path is None`; otherwise
  `config.save_ui_state(key, value, self._ui_state_path)`. Only `OSError` may
  be swallowed (the library already swallows it inside the write). A
  `TypeError`/`ValueError` is a programming error and **must be heard**.
  `value=None` means "forget this key".
- **`_ui_bool` / `_ui_int` / `_ui_str` helpers** (same shape, calling
  `config.load_ui_*` with `self._ui_state_path`), or call `config` inline —
  either is fine; keep one style.
- **Key names (frozen):**

  | key | type | stored value |
  |---|---|---|
  | `browser.bank_index` | int | selected bank row (index into `_bank_ids`) |
  | `browser.slot_cursor` | int | selected preset row |
  | `browser.view_mode` | str | one of `VIEW_CYCLE` |
  | `browser.categories` | str | sorted category codes joined with `,`; `None` when the filter is empty |
  | `browser.rating_stars` | int | `RatingFilter.stars`; `None` when no filter |
  | `browser.rating_at_least` | bool | `RatingFilter.at_least`; `None` when no filter |
  | `scan.offer_dismissed` | bool | the existing key — **unchanged name** |

- **Attributes:** keep `self._saved_slot_cursor: Optional[int]` (one-shot)
  and add `self._saved_bank_index: Optional[int]` if you need it for
  `on_mount`; add `self._restore_slot_cursor(self, cursor: int) -> None`.

The library's `save_ui_state` stores **scalars only** and raises on a list
or set — which is *why* categories are a joined string rather than a list.

---

## 3. Behaviour spec

### 3.1 Restore (in `__init__`, after `self._categories = set()` at ≈1853)

Read once from `self._ui_state_path` (skip entirely when it is `None`), and
validate before trusting — a hand-edited file must not wedge the app:

- `bank_index`: int, `0 <= i < len(self._bank_ids)` → set
  `self._current_bank = self._bank_ids[i]` and remember `i` for `on_mount`.
  Out of range: ignore.
- `slot_cursor`: int `>= 0` → store in `self._saved_slot_cursor`.
- `view_mode`: string **and** `in VIEW_CYCLE` → set `self.view_mode`.
- `categories`: string → `self._categories = {c.strip() for c in value.split(",") if c.strip()}`.
- `rating_stars` (int, library already rejects bool) with
  `rating_at_least` (bool): build `RatingFilter(stars=stars, at_least=...)`
  and restore it **only if it is in `RATING_FILTER_STATES`** (so a
  hand-edited `stars=0, at_least=true` — `≥0`, which is not a filter — is
  ignored rather than matching everything).
- `scan.offer_dismissed`: bool → `self._scan_offer_dismissed`
  (a new attribute; see 3.3). Absent/`False` → not dismissed.

`_update_subtitle()` is already called at the top of `on_mount`, which is
after `__init__`, so restored filters/views appear in the header without an
extra call.

### 3.2 `on_mount` (≈1967)

- `_fill_banks()` and `_fill_presets(self._current_bank)` are unchanged, but
  `self._current_bank` now comes from restore.
- **After** the preset columns exist and `_fill_presets` has run, move the
  bank cursor to the restored row so the highlight matches the pane:
  `banks.move_cursor(row=self._saved_bank_index)` when it is `0 <= i < len(self._bank_ids)`.
  (Do it after the columns exist — `_fill_presets` would fail against a
  table with no columns.)
- Apply the saved slot cursor, then `banks.focus()`, then re-apply after
  focus settles with `self.set_timer(0.1, lambda: self._restore_slot_cursor(saved))`
  — the same fix and reason as rxved's (`bank_table.focus()` can reset the
  visual cursor). Clear `self._saved_slot_cursor` after the first use:
  it is a one-shot restore, not a standing override.

### 3.3 Save on change (the point of the change — each transition writes as it happens)

- **Bank row** — `on_data_table_row_highlighted` (≈2616), bank-table branch:
  capture `bank_id = self._bank_ids[row]` and compute
  `changed = bank_id != self._current_bank` **before** calling
  `_fill_presets` (which assigns `_current_bank`). Keep the existing
  `self._fill_presets(bank_id)`, then save `browser.bank_index = row` **only
  when `changed`**. The message can be delivered after `_filling` is
  cleared, so the guard has to be the value comparison, not the flag
  (rxved's comment at ≈1014 says the same).
- **Slot row** — same handler, preset-table branch: after `_show_detail`,
  save `browser.slot_cursor = event.cursor_row` **only when the preset table
  has focus** (`self.query_one("#preset-table").has_focus`). This is what
  stops startup's programmatic moves from overwriting the saved position.
- **View cycle** — `action_cycle_favorites` (≈2451): after
  `self.view_mode = VIEW_CYCLE[...]` and the refill, save
  `browser.view_mode = self.view_mode` and call `self._update_subtitle()`
  (it does not today, and the subtitle now names the view — see 3.4).
- **Rating filter** — `action_rating_filter`'s `apply` (≈2496): after setting
  `self.rating_filter`, save both keys:
  - no filter: `browser.rating_stars = None`, `browser.rating_at_least = None`
    (this is the only way clearing survives a restart);
  - a filter: `chosen.stars` and `chosen.at_least`.
  `None` here means *remove the key*, not "unchanged", because this API
  takes one key per call.
- **Categories** — `action_pick_categories`'s `chosen` (≈2526): after
  `self._categories = wanted`, save `browser.categories = ",".join(sorted(wanted))`
  or `None` when empty; and call `self._update_subtitle()` (see 3.4).
- **Scan offer** — `_maybe_offer_scan` (≈2832) must read through the
  injected path: replace `cfg.load_ui_bool("scan.offer_dismissed", default=False)`
  with the app's own load (same key, `self._ui_state_path`), and
  `_scan_offer_answered`'s `cfg.save_ui_state(...)` with `self._remember(...)`.
  Behaviour for the user is unchanged; the point is that a test can now
  point the app at a `tmp_path` instead of monkeypatching the module
  functions.

### 3.4 No silent narrowing (required, not optional)

Once these are remembered, a fresh launch can open on a narrowed list with
**nothing on screen saying why** — exactly the failure `CLAUDE.md` warns
about, and exactly why rxved shows its filters in the sub-title. Extend
`_update_subtitle` (≈2596) to name every active narrowing, keeping the
existing order and separator (`"   ·   "`):

```
parts = []
if self.rating_filter is not None:
    parts.append(self.rating_filter.label)          # "rating ≥3"
if self._categories:
    parts.append("/".join(sorted(self._categories)))
if self.view_mode != VIEW_ALL:
    parts.append(VIEW_LABELS[self.view_mode])
filters = ("   ·   " + "   ·   ".join(parts)) if parts else ""
self.sub_title = self._channel_line() + filters
```

With nothing active this must still produce exactly
`"sending on MIDI channel 1"` (an existing test asserts it). Update the
`_update_subtitle` docstring: its current "the category filter is only ever
a view the user asked for" premise is false the moment categories are
remembered across runs — say so.

---

## 4. Subagent prompts (paste verbatim; one fresh `general` subagent each)

Spawn **A** and **B** in parallel, then **C**. Do not let A and B edit each
other's files; the interface in §2 is what keeps them compatible.

---

### Subagent A — implementation (owns `p2ked/app.py`, `p2k/config.py`, `.gitignore`, `README.md`)

> You are implementing in `/home/lentferj/git-repos/p2ked` on `master`. Work
> only in `p2ked/app.py`, `p2k/config.py`, `.gitignore` and `README.md`.
> Another agent is editing `tests/` — do not touch it.
>
> **First read `CLAUDE.md` from top to bottom.** It overrides every default
> you carry, in particular: no `Co-Authored-By: Claude` or any AI
> attribution anywhere; GPL-2.0-or-later headers stay; nothing is "verified";
> docstrings must match the behaviour after your change, not before.
>
> Then read `docs/PLAN-remembered-ui-state.md` §1–§3 in full — it is the
> specification, and §2 is a frozen interface you must not rename. Read
> `p2k/config.py`, `p2ked/app.py` (the modules named in the anchors), and
> `rxved/rxved/app.py` at the anchors listed in §1 for the reference
> behaviour. rxved is read-only reference.
>
> Do all of §2 and §3. Match the house style exactly: every non-obvious
> decision gets a docstring/comment that says **why**, cites the sibling or
> the failure it prevents, and distinguishes measured from assumed. Reuse
> `_remember_channel`'s tone for `_remember`.
>
> Update the affected docstrings: `_update_subtitle` (§3.4), the
> `self._categories` comment, `on_data_table_row_highlighted`, and add a
> short `# --- remembering the screen ---` section where the helpers live.
> Add a short README paragraph after the `config.toml` one (≈line 230)
> naming `ui-state.toml` and listing what it remembers.
>
> **Do not** touch `p2k/messages.py`, `p2k/bridge.py`, `p2ked/multi.py`, or
> anything that talks to the wire. This change makes no MIDI traffic.
>
> Verify yourself before you hand back:
> - `.venv/bin/python -m pytest tests/test_app.py tests/test_scan.py tests/test_favorites.py -q`
> - `.venv/bin/ruff check --no-cache p2k p2ked && .venv/bin/ruff format p2k p2ked`
> - `.venv/bin/mypy`
> Report the exact commands, their result, and anything you could not do.
> Do not commit.

---

### Subagent B — tests (owns `tests/test_remembered_state.py` (new) and `tests/test_scan.py`)

> You are writing tests in `/home/lentferj/git-repos/p2ked` on `master`.
> Work only in `tests/`. Another agent is implementing the feature in
> `p2ked/app.py` and `p2k/config.py` against the same frozen interface — do
> not edit source, and do not "fix" a failure by changing the interface.
>
> **First read `CLAUDE.md`** (no AI attribution; GPL header on the new file;
> invented names only — E-MU preset names must never appear in fixtures).
> Then read `docs/PLAN-remembered-ui-state.md` §2 and §3, which freeze the
> key names, the `ui_state_path` helper, the `_ui_state_path` attribute and
> the restore/save behaviour. Mirror `tests/test_favorites.py` and
> `tests/test_scan.py` for fixtures (`P2kedApp(DemoDevice(), …, config_path=str(tmp_path / "config.toml"))`,
> `Favorites(str(tmp_path / "f.db"))`, `async with app.run_test(size=(200, 50))`).
>
> Create `tests/test_remembered_state.py` with a module docstring saying
> what it pins and why (a preference that comes back without saying so is
> the failure this file exists to prevent), and cover at least:
>
> 1. **Store round-trips** (`p2k.config`, no app): each key saves and reads
>    back through `config.save_ui_state` + `config.load_ui_int/load_ui_str/load_ui_bool`
>    at `config.ui_state_path(path)`; `value=None` removes the key.
> 2. **Saving one key leaves the others alone** (the trap that made rxved's
>    `None`-as-unset impossible): save bank/cursor/rating, then save the
>    view; all four survive; then clear the rating and the position survives.
> 3. **Restore on construction**: pre-write a ui-state file, build the app,
>    `await pilot.pause()`, and assert `view_mode`, `rating_filter`,
>    `_categories`, and (after the settle timer, `await pilot.pause(0.2)`)
>    the bank-table and preset-table `cursor_row`.
> 4. **Written on change**: press `v` (view), apply a rating via `V`, and
>    `C` for a category; read the ui-state file and assert the exact key and
>    value, and that clearing writes/removes the right keys.
> 5. **A slot cursor is saved only while the preset pane is focused**, and
>    startup's programmatic moves do not overwrite it.
> 6. **Bad values are ignored, not obeyed**: out-of-range `bank_index`, an
>    unknown `view_mode`, `rating_stars = true` (a bool is not one star), and
>    `stars = 0, at_least = true` (not a filter) all leave the default state.
> 7. **No path, no file**: `P2kedApp(DemoDevice())` (no `config_path`) has
>    `app._ui_state_path is None`, still runs, and `_remember(...)` writes
>    nothing (assert no `ui-state.toml` under `tmp_path`, and that the app
>    never touches the CWD).
> 8. **The sub-title names a restored narrowing** — rating, categories and
>    a non-default view — and is exactly `"sending on MIDI channel 1"` when
>    nothing is active.
> 9. **The cursor still sends no MIDI**: moving through banks and presets
>    writes the file but plays nothing (mirror `TestCursorIsSilent`; the
>    demo device records selections).
>
> Rewrite `tests/test_scan.py::TestTheOffer.test_never_remembers_the_answer`
> and `test_a_dismissed_offer_stays_dismissed` to use the real injected path
> (write/read `tmp_path/…/ui-state.toml`) instead of monkeypatching
> `p2k.config.save_ui_state`/`load_ui_bool`. Keep the test names' intent.
>
> Run `.venv/bin/python -m pytest tests/test_remembered_state.py tests/test_scan.py -q`
> and `.venv/bin/ruff check --no-cache tests && .venv/bin/ruff format tests`.
> If a test fails because source is not written yet, say so in your report
> rather than weakening the assertion. Do not commit.

---

### Subagent C — independent verification (do not edit unless told; model `opencode/deepseek-v4.1-flash-free`)

> You are verifying a change in `/home/lentferj/git-repos/p2ked` that makes
> the browser remember UI state. You did not write it. Use a **different
> model** from the implementers on purpose: two readers sharing one
> misreading agree perfectly.
>
> Read `docs/PLAN-remembered-ui-state.md` (the spec), `CLAUDE.md`, then the
> diff. Run `make check` and report the exact result. Independently check,
> and report anything you cannot confirm:
> - The parity table in §0 is actually closed; every listed key is written
>   **and** read, including the clearing path (`None` removes the key, so a
>   cleared filter does not return on the next launch).
> - No MIDI was added: no new calls into `p2k/bridge.py` or
>   `p2k/messages.py`; `TestCursorIsSilent` still passes.
> - No silent narrowing: a restored rating/category/view is visible in the
>   sub-title (§3.4), and the wording in the docstrings matches the new
>   behaviour rather than the old.
> - `ui-state.toml` is gitignored; no invented/E-MU preset name appears in
>   any test fixture.
> - The unsafe reads are refused: out-of-range bank index, unknown view,
>   bool-for-int stars, `≥0`.
> - Coverage did not fall below the `fail_under` gate.
>
> Produce a numbered review: **must-fix** (a claim the code does not
> support, or a test that passes for the wrong reason) versus **nice-to-have**,
> each with file:line. Do not commit and do not silently fix; the
> orchestrator routes fixes back to subagent A.

---

## 5. Orchestrator protocol

1. Confirm the baseline: `.venv/bin/python -m pytest -q` → 664 passed,
   11 skipped. Cut a branch (`ui-state-parity`).
2. Dispatch **A** and **B in parallel** with the model above.
3. When both return: run `make check` yourself. On any failure, continue the
   *same* A session (`sessionID`) with the exact failure output — do not
   start a fresh agent, and do not let it touch `tests/` to make a failure
   go away.
4. Dispatch **C** on `opencode/deepseek-v4.1-flash-free`. Route every
   must-fix back to A's session, then re-run C on the relevant hunk only.
5. Commit in logical chunks, **no AI attribution** (CLAUDE.md): one for
   `p2k/config.py` + `.gitignore` (the store plumbing), one for
   `p2ked/app.py` + `README.md` (the browser), one for the tests. Message
   style: `feat(browser): <what changed>`, matching `git log`.
6. Optional follow-ups, only if the maintainer asks (do **not** invent
   scope): the `nothing to undo`/subtitle wording, and whether the
   category picker's UX (a typed prompt in p2ked vs rxved's counted picker)
   should also converge.

## 6. Explicitly out of scope

- Any wire/protocol change; any new MIDI traffic.
- Replacing p2ked's category **prompt** with rxved's counted picker.
- Migrating old `config.toml` ui keys (there are none: the only existing key
  is `scan.offer_dismissed`, which keeps its name and file).
- Editing `rxved`, or any sibling repo.
