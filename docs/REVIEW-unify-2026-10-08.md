<!--
SPDX-License-Identifier: GPL-2.0-or-later
SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
-->

# Review: the `unify` merge (vinsynlib adoption), 2026-10-08

> **Status, 2026-10-08: addressed.** Every finding below was fixed in the
> tree, except two things that need a human: vinsynlib must be pushed and
> tagged `v0.2.0` (F1), and the per-tool config directory (F2/F3) is left as
> a documented contract change rather than done unilaterally. The fixes
> touched vinsynlib's `config.py`, `midi.py`, `spec.py`, `__init__.py` and
> tests, and p2ked's `entry.py`, `p2k/bridge.py`, `p2k/config.py`,
> `p2ked/app.py`, `p2ked/cli.py`, a new `p2ked/_report.py`, and the docs.
> `make check` is green in both repositories. `TODO.md` item 44 records what
> is left.
>
> **Status, 2026-10-09: F1 and F5 closed by publication.** vinsynlib 0.2.0 is
> published on PyPI and tagged `v0.2.0`; the ten siblings depend on
> `vinsynlib>=0.2.0` from the index rather than a sibling checkout, the
> `entry.py` version gate has been ported to all ten (fix item 6), and F5's
> install-path findings fall with it. See the notes on F1 and F5 below. The
> findings are kept as written: they are the record of why the gates were
> built this way.

Scope: `ddd9f6d..9b77ebb` on `master`. That is the fast-forward of `unify`
(6403ec6, fc986cc, 52ff7ee, 3d27bbe, 5430ca1, 64d1ac1) plus 9b77ebb on top.
It is reviewed against `../vinsynlib` as it is checked out now (`2f7a8d4`,
two commits ahead of `origin/main`) and against the published `origin/main`
(`3ec7ef4`).

No code was changed. Every "reproduced" below was run on stubs or temporary
copies under `/tmp/opencode/review`. No hardware was used, so none of this
says anything about the wire protocol.

---

## 0. Does it still work with `../vinsynlib`?

| p2ked HEAD against | Result |
|---|---|
| `../vinsynlib` working tree (`2f7a8d4`, local) | **Green.** `make check`: ruff, format, mypy, 246 passed / 1 skipped, coverage 73.31 % (gate 68), pip-audit, vulture, deptry. vinsynlib's own suite: 157 passed; its ruff and strict mypy are clean. |
| `origin/main` (`3ec7ef4`, the one GitHub serves) | **Broken.** `tests/test_entry.py`: 2 failures. Both console scripts stop with `AttributeError: module 'vinsynlib' has no attribute 'is_compatible_version'` before they parse an argument. See F1. |
| `01984ba` (vinsynlib when `unify` was merged) | **Broken**, the same way. |

Checked and fine:

- **Favourites database.** The schema is the same: `SCHEMA_VERSION = 2`, the
  same DDL and the same `active` migration. The data directory is the same
  (`app_name="p2ked"`), so an existing `favorites.db` opens without changes.
- **Settings cache.** The key names are the same (`port`, `recv_port`,
  `channel`, `device_id`), and so are the traps (a bool is not an int,
  escaping, only `OSError` swallowed). p2ked's existing config tests still
  pass against the library.
- **Subcommand aliases.** argparse stores the alias that was typed in
  `args.command`, and `_COMMANDS` and `_OFFLINE` carry both spellings, so
  `roms`/`banks` and `config`/`hardware` all dispatch. Ran
  `p2kcli banks`, `p2kcli --demo hardware`, `p2kcli --demo config`.
- `p2ked --version` and `p2kcli --version` both print `0.1.0`.
- The browser's flags, bindings, legend and terms pass `vinsynlib.conformance`.
  `p2kcli`'s parser also passes `check_flags` when run by hand, but no test
  runs that (F11).

---

## Summary of findings

| # | Severity | Finding |
|---|---|---|
| F1 | **Critical** | The version gate in `entry.py` calls an API that only exists in unpushed vinsynlib commits. Both console scripts crash against the published library. |
| F2 | **High** | The settings writer rewrites *any* `config.toml` in the working directory. Reproduced: a foreign file loses its comments and is left as invalid TOML. `p2kcli` now triggers this wherever it is run. |
| F3 | **High** | All nine tools share one `./config.toml` with the same keys, and `is_emu` accepts any E-MU device. As a result p2ked may adopt another tool's port, and two tools may keep overwriting each other's remembered port. |
| F4 | Medium | Regression: `p2kcli ports` gives a traceback where it used to print a clean error when there is no ALSA sequencer. Reproduced. |
| F5 | Medium | The install path is broken or unsafe. `make install` never installs vinsynlib. The advice in `entry.py` is wrong. The bare `vinsynlib` dependency name is unclaimed on PyPI, which is a dependency-confusion risk. |
| F6 | Medium | The fallback message comes out garbled ("probing X (remembered, did not answer)..."). The dead port is then probed a second time, and the reason it failed is dropped. Reproduced. |
| F7 | Medium | `p2kcli --help` says things that are not true (`--channel` "remembered", `--port`, `--scan`, the `ports` note). This is the "flag that lies" the merge set out to remove. |
| F8 | Medium | On the connect path `--device-id`, `--recv-port` (without `--port`) and `--scan` (with `--port`) are silently ignored. |
| F9 | Low–Med | The browser still rewrites `config.toml` on every launch (`save_device_id`). That key is written and never read. A named port that never answered is still remembered. |
| F10 | Medium | `probe()` leaks an open bridge on unexpected errors and reports a missing MIDI backend as "did not answer". One busy port aborts the whole sweep. |
| F11 | Low–Med | Some tests can no longer fail (mutations survived), and there are coverage gaps in the new code. |
| F12 | Low | p2ked inherits contradictions in the vinsynlib contract (spec, docstrings, `is_compatible_version` edge cases). |
| F13 | Low | Docs and metadata have drifted: LICENSE, pyproject ignores, README template text, dangling `docs/UX-SPEC.md` references, stale comments. |
| F14 | Low | Half-finished de-duplication: `p2k.bridge` still has copies of the `vinsynlib.midi` helpers, and `_cmd_ports` mixes the two. |
| F15 | Low | Tooling: the `audit-vulns` temp file and redundant pass, and the pre-commit mypy hook cannot see vinsynlib. |
| F16 | Medium | The installed console scripts here still call `p2ked.app:main`/`p2ked.cli:main`, so the `entry.py` guard is not actually in effect; `make check` cannot tell. |

---

## F1 — Critical: the version gate depends on API that is not published

> **Resolved, 2026-10-09.** vinsynlib 0.2.0 is published and tagged, so
> `origin/main` has `is_compatible_version` and `__version__` reports `0.2.0`.
> p2ked's `entry.py` now carries the stdlib-only comparison (`_release_parts`)
> against `MINIMUM = (0, 2, 0)` and never imports the library to check it, and
> the same port has been applied to all nine siblings (fix item 6). Fix item 5
> — a check that the published library actually satisfies what `MINIMUM`
> claims — is the one piece still not built.

**Where:** `p2ked/entry.py:54`, `MINIMUM = (0, 1, 0)`, `SOURCE` at line 40.

9b77ebb replaced the local tuple comparison with
`vinsynlib.is_compatible_version(version, MINIMUM)`. That function was added
to vinsynlib in `0106283`, which is **not pushed**: `origin/main` does not
have it. `__version__` stayed at `"0.1.0"` across the change, so the gate
cannot tell the two builds apart. Reproduced:

```
$ PYTHONPATH=<vinsynlib origin/main>/src python -c "from p2ked import entry; entry.app()"
  File ".../p2ked/entry.py", line 54, in _diagnose
    if not vinsynlib.is_compatible_version(version, MINIMUM):
AttributeError: module 'vinsynlib' has no attribute 'is_compatible_version'
```

The module exists to stop a bare traceback naming a library the user never
asked for. Here it produces exactly that traceback. Anyone following the
README (`git clone https://github.com/lentferj/vinsynlib.git`) or the
module's own advice (`pip install "vinsynlib @ git+https://…"`) gets
`origin/main` and hits this. The same commit landed in all ten siblings
(`emorphed`, `ensqsqed`, `eosed`, `k2kremote`, `kwsed`, `nanosyned`,
`rxved`, `s3ked`, `x5ded`), so all of them are affected.

There is also a design flaw. The checker relies on the API of the thing it
is checking, which is the one place where that dependency must not exist.
The module docstring says "it must keep importing nothing but the standard
library", and the intent of that rule is broken even though the letter is
kept.

**Proposed fix (all of it, in this order):**

1. **vinsynlib:** push `0106283` and `2f7a8d4`. Bump the version every time
   public API is added. These two commits add API (`is_compatible_version`,
   `Flag.help_without_config`, `Settings.update(key=None)`), so the next
   version should be `0.2.0` (or `0.1.1` if you prefer). Keep a single
   source of truth: `version = {attr = "vinsynlib.__version__"}` under
   `[tool.setuptools.dynamic]`, with `dynamic = ["version"]`. Then
   pyproject and `__init__` cannot drift apart. Tag it (`v0.2.0`).
2. **p2ked/entry.py:** put the comparison back in the module, stdlib-only,
   with the padding bug fixed:

   ```python
   def _as_tuple(version: str, width: int) -> tuple[int, ...] | None:
       parts: list[int] = []
       for piece in version.split(".")[:width]:
           digits = ""
           for ch in piece:
               if not ch.isdigit():
                   break
               digits += ch
           if not digits:
               break
           parts.append(int(digits))
       if not parts:
           return None
       return tuple(parts + [0] * (width - len(parts)))


   ...
   found = _as_tuple(version, len(MINIMUM))
   if found is None or found < MINIMUM:
       return _too_old(command, version)
   ```

   This also handles `"0.2rc1"`, `"0.1"` and `"1"` (see F12). If you want to
   keep the library function, call it defensively:
   `check = getattr(vinsynlib, "is_compatible_version", None)`, and treat
   `None` as "too old".
3. Set `MINIMUM = (0, 2, 0)` (or whatever is tagged) and pin `SOURCE` to
   that tag: `vinsynlib @ git+https://github.com/lentferj/vinsynlib@v0.2.0`.
4. **Tests:** add `monkeypatch.delattr(vinsynlib, "is_compatible_version")`
   and assert a *message*, not an exception. Add a `__version__ = None`
   case too (line 53 is not covered).
5. **Guard:** a CI job, or `make check-published`, that installs vinsynlib
   from the tag `MINIMUM` names and runs the suite. Without it, `MINIMUM`
   is a claim nothing checks.
6. Apply the same to the nine siblings. It is one patch, applied ten times.

---

## F2 — High: any `config.toml` in the working directory gets rewritten

**Where:** `vinsynlib.config.Settings.update`. In p2ked it is reached from
`ProteusBridge.connect` (`p2k/bridge.py:424-426`), from `app.main`
(`p2ked/app.py:1279-1288`), and from `app._remember_channel`.

`DEFAULT_PATH = "config.toml"` is relative to the working directory, and
`update()` reads whatever is there, merges its own keys in, and rewrites the
whole file. Nested tables are written with Python `repr`. Reproduced in a
scratch directory holding another project's `config.toml`:

```
# before                              # after cfg.save_ports(...)
# Someone else's project config       # p2ked local config - gitignored, safe to delete.
title = "my site"                     title = "my site"
                                      server = {'host': 'localhost', 'port': 8080}
[server]                              port = "Midi Out: X 20:0"
host = "localhost"                    recv_port = "Midi Out: X 20:0"
port = 8080
```

The comments are gone. The header now says *safe to delete* about a file
that was not ours. `server = {'host': …}` is not TOML, so the next read
reports "could not be parsed" and the file stays broken. A top-level `port`
or `channel` key in someone else's file would also be read back as a MIDI
port or channel.

TODO 19 records that the cwd-relative default was **deliberate**: "a
disposable per-checkout cache of which port answered last". That reasoning
still holds for a browser opened in a checkout. What changed is the
context. Before the merge only the browser wrote this file; **fc986cc makes
`p2kcli` write it too**, and `p2kcli` is a pipe tool run from whatever
directory the shell happens to be in, never a checkout it chose. A
`p2kcli status` that sweeps writes `./config.toml` wherever that is. Two
concurrent writers, such as the browser plus `p2kcli`, can also tear the
file, because it is truncated and then rewritten in place.

**Proposed fix:**

1. **Structural, recommended:** stop using the working directory. Add
   `vinsynlib.config.config_dir(app_name)` next to `favorites.data_dir`:
   `$XDG_CONFIG_HOME/<app>` (else `~/.config/<app>`),
   `~/Library/Application Support/<app>` on macOS, `%LOCALAPPDATA%\<app>`
   on Windows. Make `<config_dir>/config.toml` the default. For one
   release, read `./config.toml` as a fallback **only if its first line is
   `# p2ked local config`**, and print once that it has moved. This also
   fixes F3, and it lets `p2kcli` and the browser share a cache no matter
   where they are launched from.
2. **Defensive, whatever happens with 1:** in `Settings.update`, refuse to
   write over a file that exists and does not start with a family header.
   Say so once, the way the unparseable case already does:

   ```python
   if os.path.exists(target):
       with open(target, encoding="utf-8", errors="replace") as fh:
           first = fh.readline().rstrip("\r\n")
       if not (
           first.startswith("# ")
           and first.endswith(" local config - gitignored, safe to delete.")
       ):
           # warn once: "<app>: <target> was not written by <app>; not touching it. Use --config."
           return
   ```

   Also refuse when `data` holds a `dict` or `list`. Writing them as `repr`
   is never right.
3. **Atomic write:** write to `f"{target}.{os.getpid()}.tmp"`, then
   `os.replace(tmp, target)`. A concurrent reader then sees the old file or
   the new one, never a truncated one.
4. Add a library test: a foreign `config.toml` with a table and a comment is
   left byte-for-byte intact.

---

## F3 — High: one shared `config.toml` with shared keys, and an E-MU is an E-MU

**Where:** `p2k/config.py` (`Settings("p2ked", "config.toml")`), every
sibling's equivalent, and `p2k/messages.py:424`
(`"is_emu": data[5] == EMU_ID`).

All nine tools default to the same `./config.toml` and use the same keys.
Two of them talk to other E-MU hardware: `emorphed` (Morpheus) and `eosed`
(E4XT). The identity check here looks only at the manufacturer byte. Run
from one directory (`$HOME`, a project folder), this happens:

- **p2ked adopts another E-MU tool's port.** The fast path probes the port
  `emorphed` remembered. A Morpheus answers with manufacturer `18h`,
  `is_emu` is true, and p2ked treats it as the Proteus. Every request after
  that is a Proteus SysEx frame sent to the wrong instrument. Nothing is
  written, but it is the wrong unit, and nothing on screen says so.
- **Two tools fight over the port.** With a non-E-MU tool (`x5ded`, `kwsed`):
  p2ked probes x5ded's port, gets a foreign reply, sweeps, finds the
  Proteus and **saves it over x5ded's port**. The next x5ded launch does the
  reverse. Each tool's launch after the other's now always sweeps, which
  defeats the reason the remembered port was added.
- **The channel is shared.** Setting channel 5 with `c` in p2ked starts the
  next sibling on channel 5. The header line flips between tools on every
  write.

**Proposed fix:**

1. F2.1, a per-app config directory, makes the collision go away completely.
2. If one file per directory is kept, namespace it. Each tool reads and
   writes its own table (`[p2ked]`). Old top-level keys are read only when
   the header names this app.
3. **Remember who answered, not only where.** After a sweep, store the
   identity triple next to the port, for example
   `identity = "18:0F00:0200"` (manufacturer, family, member, as
   `identity_reply_fields` returns them). On the fast path, reject a reply
   whose triple differs. This needs no further spec knowledge.
4. Optionally, tighten `is_emu` to an `is_proteus` that also checks the
   family byte. **This is a hypothesis.** The demo assumes family `0Fh`,
   the Proteus product ID, but RESOLUTION_NOTES §7 records only manufacturer
   `18h` and device ID `0` from the real unit. Record the family and member
   bytes at the next hardware session before relying on them, and label the
   check as a guess until then (CLAUDE.md).

---

## F4 — Medium: `p2kcli ports` regressed to a traceback without ALSA

**Where:** `p2ked/cli.py:322-344` now calls `vinsynlib.midi.list_ports()`.

`p2k.bridge.list_ports` wraps client construction in `_client()` and turns a
backend failure into `MidiUnavailable` ("no MIDI backend available … in a
container it must be passed through"). `vinsynlib.midi.list_ports` only
wraps the *import*. `rtmidi.MidiIn()` raising `rtmidi.SystemError`, which
is what happens on a host with no ALSA sequencer, goes straight out. The
offline path in `main()` catches only `LookupError`/`ValueError`.
Reproduced by making `rtmidi.MidiIn` raise:

```
before (ddd9f6d): SystemExit: error: no MIDI backend available (MidiInAlsa::initialize: …). On Linux this needs an ALSA sequencer; …
after  (HEAD):    Traceback … vinsynlib/midi.py line 121 … _rtmidi.SystemError: MidiInAlsa::initialize: …
```

Three related problems:

- **Regression, introduced by the merge.** The old `_cmd_ports` used
  `p2k.bridge.list_ports`, whose `_client()` wraps a backend failure. The
  new one uses `vinsynlib.midi.list_ports`, which does not, so a host with
  no ALSA sequencer gets a traceback where it used to get a sentence.
- **Pre-existing, not a regression.** `from p2k.bridge import …` inside
  `_cmd_ports` imports `rtmidi` at module scope, so on a host with no
  python-rtmidi the offline `ports` command dies with `ImportError`.
  Reproduced: with a shadowing `rtmidi` that raises, `p2kcli banks` works
  and `p2kcli ports` prints a traceback. The old code had the same module
  scope import, so this is inherited, not caused by the merge, and it is
  still worth fixing while the function is being touched.
- `_cmd_ports` lists the ports twice, once through vinsynlib and once
  through `p2k.bridge.likely_proteus_ports()`. That is two ALSA clients,
  two error paths, and a listing whose marks can disagree with it on
  hot-plug.
- `vinsynlib.midi.list_ports` builds both clients in one tuple expression.
  If `MidiOut()` raises, `MidiIn()` is never `delete()`d.

**Proposed fix:**

- **p2ked:** list once, through the wrapper that already handles this:

  ```python
  def _cmd_ports(_device, _args) -> None:
      try:
          from p2k import bridge as b

          ins, outs = b.list_ports()
      except ImportError as exc:
          raise SystemExit("error: python-rtmidi is not installed") from exc
      except midi.MidiUnavailable as exc:
          raise SystemExit(f"error: {exc}") from exc
      likely = sorted(b.likely_proteus_ports(ports=(ins, outs)))
      ...
  ```

  Here `likely_proteus_ports`/`bidirectional_ports` gain an optional
  `ports=` parameter, the same shape vinsynlib's take.
- **vinsynlib:** construct each client inside its own `try`, raise
  `MidiUnavailable` on failure, and `delete()` whichever one was created.
  Add a test that patches `MidiIn` to raise.

---

## F5 — Medium: the install path is broken, contradicts itself, and is open to dependency confusion

> **Resolved, 2026-10-09 — by publication rather than by the fixes proposed
> below.** `vinsynlib` is on PyPI at 0.2.0 and p2ked depends on
> `vinsynlib>=0.2.0`, so a plain `pip install -e .` resolves it, the sibling
> checkout and its `--no-deps` dance are gone from the Makefile and the
> README, the dependency-confusion window is closed by the version floor and
> the registration, and `entry.py` prints the one command that works. Item 4
> (declaring `vinsynlib[ui,midi]`) is the only piece still open.

1. **`make install` never installs vinsynlib** (`Makefile:53-60`).
   `requirements-dev.txt` does not list it and the project is installed
   `--no-deps`. On a fresh clone `make install && make check` therefore
   fails on the first `import vinsynlib`. Found by reading the Makefile,
   not run.
   *Fix:* add, before the `-e .` line,
   `test -d ../vinsynlib || { echo "clone vinsynlib beside this checkout: git clone … ../vinsynlib"; exit 1; }`
   and `$(VENV)/bin/python -m pip install --no-deps -e ../vinsynlib`.
2. **`entry.py` gives advice the project's own history says fails**
   (`p2ked/entry.py:65-68`). It says "Installing this project itself brings
   it in too … `pip install -e .`", but commit 3d27bbe records that plain
   pip ignores `[tool.uv.sources]` and fails with "Could not find a version
   that satisfies the requirement vinsynlib". The 5430ca1 commit message
   also says the error mentions "the clone path", and it does not.
   *Fix:* print the three README steps (clone to `../vinsynlib`,
   `pip install --no-deps -e ../vinsynlib`, `pip install -e .`), with
   `uv sync` as the alternative.
3. **Dependency confusion.** `dependencies = ["vinsynlib"]`
   (`pyproject.toml:19`) is unpinned, and the name is **unregistered on
   PyPI** (`https://pypi.org/pypi/vinsynlib/json` returns 404). Anyone who
   runs `pip install -e .` before installing the sibling, which is exactly
   what `entry.py` tells them to do, lets PyPI decide what `vinsynlib` is.
   Today that fails. The day somebody registers the name, it installs their
   code.
   *Fix (one or more):* use a direct reference,
   `"vinsynlib @ git+https://github.com/lentferj/vinsynlib@v0.2.0"`, which
   `[tool.uv.sources]` still overrides for local development. Add a
   version floor, `vinsynlib>=0.2.0`. Register a placeholder `vinsynlib` on
   PyPI, or publish it, which the README already says would collapse all of
   this.
4. Declare the extras that are actually used: `vinsynlib[ui,midi]`. p2ked
   imports `vinsynlib.ui.hints` (needs textual) and `vinsynlib.midi`. It
   happens to declare both itself today, which is why this does not bite.

---

## F6 — Medium: the fallback message is garbled, the dead port is probed twice, and the reason is lost

**Where:** `vinsynlib.midi.open_remembered_or_swept` sends its fallback
notice through `on_try`. Both front ends pass
`on_try=lambda n: print(f"  probing {n}...")` (`p2ked/app.py:1269`,
`p2ked/cli.py:438`). Reproduced with the `tests/test_connect.py` rig and
p2ked's real `on_try`:

```
  probing Midi Out: E-MU Proteus 2000 1 20:0 (remembered, did not answer)...
  probing Midi Out: E-MU Proteus 2000 1 20:0...
  probing Midi Out: Scarlett 18i8 USB MIDI 1 24:0...
```

- Line 1 reads as an action in progress, not a failure that already
  happened. The announcement the whole of fc986cc was written for is the
  least readable line on the screen. `test_a_dead_remembered_port_falls_back_and_says_so`
  uses `said.append` and so never sees the printed form.
- Line 2: the sweep tries the dead port again, which costs another
  `AUTODETECT_TIMEOUT` on every fallback.
- The *reason* is dropped. `probe` raises `DeviceError("no output port named …; have [...]")`
  when the port has gone, which is the renumbering case `--scan` exists
  for, and a different `DeviceError` when it is silent. The user is told
  "did not answer" in both cases.
- Also a regression: the old inline path printed `  <port> (remembered)` on
  success. The fast path now prints nothing, so a launch never says which
  port it used.

**Proposed fix:**

- **vinsynlib:** give the fallback its own hook, and let the sweep skip the
  port that just failed:

  ```python
  def open_remembered_or_swept(
      *,
      probe,
      sweep,
      remembered=None,
      scan=False,
      remember=None,
      on_try=None,
      on_fallback: Callable[[str, BaseException], None] | None = None,
  ):
      failed: str | None = None
      if remembered is not None and not scan:
          send, recv = remembered
          try:
              return probe(send, recv)
          except (DeviceError, OSError) as exc:
              failed = send
              if on_fallback is not None:
                  on_fallback(send, exc)
              elif on_try is not None:
                  on_try(f"{send} (remembered, did not answer)")
      device = sweep(on_try, exclude=(failed,) if failed else ())
      ...
  ```

- **p2ked:** `autodetect(..., exclude=())` filters `candidates`. Both front
  ends share one reporter, for example `p2ked/_report.py`, so they cannot
  drift apart:

  ```python
  def fallback(port: str, exc: BaseException) -> None:
      print(
          f"  {port}: remembered, but {exc}. Probing every port (--scan does this on purpose).",
          file=sys.stderr,
      )


  def connected(bridge) -> None:
      print(f"  {bridge.port} (remembered)", file=sys.stderr)
  ```

- Add a front-end test that captures stderr through `main()`, not through
  `said.append`.

---

## F7 — Medium: `p2kcli --help` makes promises it does not keep

Live output (`p2kcli --help`):

```
--port PORT   MIDI port name
--scan        probe every MIDI port again, instead of trusting the remembered one, and update config.toml
--channel N   channel to send on, 1-16 (default: remembered, or 1)
```

- `--channel … (default: remembered, …)`: `p2kcli` never reads the
  remembered channel. `_cmd_select` uses `args.channel or 1`
  (`p2ked/cli.py:290`).
- `--port PORT   MIDI port name`: this is the `help_without_config` variant
  picked because `config=False`. But since fc986cc, `p2kcli` *does* default
  to the port remembered in `config.toml`.
- `--scan … update config.toml`: correct, but the file is the one in
  whatever directory you are in, and nothing on this command line can point
  it elsewhere.
- The `ports` note (`p2ked/cli.py:339-341`) says "`p2kcli status` asks every
  port". It no longer does when a port is remembered. It should say
  `p2kcli --scan status`.

The parser comment (`cli.py:357-361`) still justifies `config=False` with
"nothing in p2kcli *offers* either". That stopped being true in the same
merge: `_build_device` now reads and writes the settings file.

**Proposed fix:**

- Build `p2kcli` with `config=True`, and use `args.config or cfg.DEFAULT_PATH`
  in `_build_device`. The flag would then be true, `--port` gets the
  canonical help, and the browser and CLI can share a non-default cache
  (`--config ~/p2k.toml`).
- In `_cmd_select`:
  `channel = cli.channel_of(args, default=cfg.load_channel(path) or 0)`.
  This uses the library helper that exists for exactly this off-by-one.
  The alternative is to override the help, but reading the channel is the
  more useful fix.
- Fix the `ports` note.
- Add to `tests/test_conformance.py`:

  ```python
  def test_the_pipe_front_end_matches_the_family() -> None:
      from p2ked import cli

      assert not conformance.check_flags(
          cli.build_parser(),
          required=(
              "port",
              "scan",
              "recv-port",
              "demo",
              "channel",
              "device-id",
              "catalog",
              "config",
          ),
          forbidden=("favorites",),
      )
  ```

---

## F8 — Medium: flags that are accepted and then ignored on the connect path

Both `app.main` and `cli._build_device` take the `if args.port:` branch or
call `connect()`, and `connect()` takes neither a device ID nor an input
port. So:

| Command line | What happens |
|---|---|
| `--device-id 5` without `--port` | ignored; the ID is learned from the reply |
| `--recv-port X` without `--port` | ignored |
| `--scan` with `--port` | ignored (and `--scan --demo`) |

The `--device-id` help says "the unit's SysEx device ID, where the hardware
has one". The merge's stated rule is "a flag that is accepted and then
ignored teaches the user that a flag can lie".

**Proposed fix:** reject contradictions after `validate_common` and pass the
rest through:

```python
if args.recv_port and not args.port:
    midi.fail("--recv-port needs --port: it names the input that goes with it")
if args.scan and args.port:
    midi.fail("--scan searches for the port and --port names it; use one")
...
device = b.ProteusBridge.connect(
    config_path=..., scan=args.scan, device_id=args.device_id, on_try=...
)
```

In `connect`/`autodetect`, when `device_id` is given, use it instead of the
learned one. Better still, report a mismatch: "the unit says 0, --device-id
said 5".

---

## F9 — Low–Medium: the browser still rewrites the file the fast path must not touch

**Where:** `p2ked/app.py:1279-1288`.

The comment right above the block says "a fast launch must not rewrite it",
and `test_it_does_not_rewrite_the_config` asserts that for `connect()`. But
`main()` then calls `cfg.save_device_id(...)` unconditionally, which
rewrites the whole file on **every** launch. `load_device_id` is never
called anywhere in `p2k/` or `p2ked/` (grep), so `device_id` is a key that
is written and never read. **TODO 27 is stale as a result:** it says the
device-ID memory was made live, and the merge has made it write-only
again. Also, on the `--port` path the named port is
saved, and so is device ID 127, even when `learn_device_id` returned
`None` ("no identity reply; using broadcast"). The next launch's fast path
then probes a port that never answered.

Also asymmetric between the front ends: `p2ked --port X` remembers X, and
`p2kcli --port X` does not (`p2ked/cli.py:_build_device` returns without
saving). The merge's own commit message says "A port the user named on this
command line is worth remembering too"; that is only implemented in the
browser.

**Proposed fix:** drop the `save_device_id` call, or read the value and use
it as the default for F8's `--device-id`. Write the named pair only when
`learned is not None`. Give `p2kcli` the same "named a port, remember it"
step, or move both into a shared helper so they cannot disagree. Assert in
a test that `main()`'s fast path leaves the file's mtime alone.

---

## F10 — Medium: error handling in `probe()` and the sweep

**Where:** `p2k/bridge.py:402-422` (probe) and `459-477` (autodetect loop).

1. If `bridge.learn_device_id()` raises anything (an rtmidi error mid-read,
   for instance), the bridge is never closed. The exception is not a
   `DeviceError`, so `open_remembered_or_swept` re-raises it, and the open
   ALSA port leaks. That is the exact fault `list_ports`' docstring
   describes. `autodetect` wraps `identify` for this reason, and `probe`
   does not.
2. `except Exception as exc: raise DeviceError(str(exc))` around `cls.open`
   also catches `MidiUnavailable`, so "no MIDI backend on this host" turns
   into "remembered, did not answer" followed by a sweep that fails the
   same way.
3. Pre-existing, but now on the main path: in `autodetect`, `cls.open(port, …)`
   is outside the `try`. One port that another program holds, or that
   vanished between listing and opening, aborts the **whole** sweep with
   that port's error instead of moving on to the next one.

**Proposed fix:**

```python
def probe(send, recv):
    try:
        bridge = cls.open(
            send,
            recv_port=recv,
            device_id=m.BROADCAST_DEVICE,
            timeout=AUTODETECT_TIMEOUT,
        )
    except midi.MidiUnavailable:
        raise
    except Exception as exc:
        raise DeviceError(str(exc)) from exc
    try:
        learned = bridge.learn_device_id(timeout=AUTODETECT_TIMEOUT)
    except Exception as exc:
        bridge.close()
        raise DeviceError(f"{send!r}: {exc}") from exc
    if learned is None:
        bridge.close()
        raise DeviceError(f"nothing identifying itself answered on {send!r}")
    bridge.timeout = DEFAULT_TIMEOUT
    return bridge
```

In `autodetect`, wrap the `open` call: on `DeviceError` or an rtmidi
error, report it through `on_try` and `continue`. If every candidate
failed to open, add that to the final `DeviceNotFound` text.

---

## F11 — Low–Medium: tests that cannot fail, and gaps

Mutation-tested on throwaway copies:

- **`test_the_session_timeout_is_not_the_probe_timeout` is vacuous.**
  Deleting `bridge.timeout = DEFAULT_TIMEOUT` from `probe()` leaves all 21
  tests in `test_connect.py` passing. `_FakeBridge.__init__` always sets
  `timeout = b.DEFAULT_TIMEOUT` (line 75), and `fake_open` drops the
  `timeout` it was given (lines 119-125).
  *Fix:* `made.timeout = rest.get("timeout", b.DEFAULT_TIMEOUT)` in
  `fake_open`. Then the stub opens at the probe timeout and the assertion
  can fail.
- **The Enter focus guard is no longer tested.** Replacing
  `if not table.has_focus:` with `if False:` in `action_select_preset`
  leaves `test_audit_fixes.py` and `test_app.py` (53 tests) green. Once the
  App-level `enter` binding is gone, nothing presses Enter outside a
  focused table, so `test_enter_does_nothing_when_the_preset_pane_is_not_focused`
  passes whether or not the guard exists. The method's comment (`app.py:898-903`)
  still describes "this App-level binding". TODO 35 is now a fix with
  nothing left to fix.
  *Fix:* either delete the guard, the test, and the comment, and note it in
  TODO 35, or keep the guard as defence in depth and test it directly: put
  focus on `#bank-table`, call `app.action_select_preset()`, and assert
  that nothing was selected.
- **`fake_autodetect`'s docstring says the real ordering and decision are
  exercised.** They are the fake's. `autodetect`'s body (`bridge.py:452-478`)
  is still uncovered. The commit's "first thing ever to execute any of its
  discovery code" is true for `connect` only.
  *Fix:* stub `list_ports` and `cls.open` (not `autodetect`), so the real
  loop, its hint ordering and F10.3 are covered.
- **`test_entry.py`** never tests a library that lacks the function it
  calls (see F1.4). Lines 49 and 53 are not covered.
- **CLI canonical names:** `test_cli.py` runs `--demo config` but never
  `--demo hardware` or `banks`. The `_OFFLINE` test only checks that the
  set contains the names, not that they dispatch.
- **No test runs against the published library** (F1.5).
- `tests/test_entry.py` carries a two-line GPL header, where CLAUDE.md asks
  for the full block in every `.py`.

---

## F12 — Low: contradictions in the vinsynlib contract that p2ked inherits

- **"Not a licence to sweep", and then it sweeps.** UX-SPEC §4 and the
  `open_remembered_or_swept` docstring both say "A remembered port that
  does not answer is not a licence to sweep … would then quietly overwrite
  the file it was told to trust". The code, the next paragraph ("When it
  does fall back, it says so"), the library's tests and p2ked's `connect`
  all fall back *and* overwrite.
  *Fix:* settle it in the spec. For a DIN-cabled unit, falling back with a
  clear notice (F6) is the better behaviour, so delete the contradicting
  paragraph.
- **`spec.SUBCOMMANDS`:** `hardware` is declared `needs="nothing"` with help
  "(no unit needed)", and its aliases `config` and `inquire` query the unit
  in p2ked and elsewhere. Nothing enforces command help yet. A future
  check would push p2ked into a false claim.
  *Fix:* `needs="device"`, help "what the unit reports about itself".
- **`is_compatible_version`:** `"0.2rc1"`, `"0.2.0b1"` and `"1.0.0+local"`
  hit `int()` on a non-numeric piece and return `False`, so `entry.py`
  would say "needs 0.1.0 or newer, and 0.2rc1 is installed". The
  stdlib-only helper in F1.2 handles these.
- `check_flags` now accepts any extension of the family help
  (`startswith`). fc986cc's "pins the help text … exactly" is no longer
  true. That is fine, but worth knowing when reading the test.

---

## F13 — Low: docs and metadata drift

- **LICENSE "Third-party references" was not updated.** It still says
  `p2ked/app.py`'s KeyHints/wrap_blocks, `p2k/favorites.py`'s store, and
  the bridge's "read-modify-write config store" are ported from rxved.
  Those now live in vinsynlib, and vinsynlib is not mentioned. CLAUDE.md
  asks for attribution in both the file header and LICENSE.
  *Fix:* replace those three entries with one `vinsynlib (GPL-2.0-or-later)`
  entry naming what is used, and point to vinsynlib's own per-file
  attributions.
- **pyproject per-file-ignores for `p2k/config.py` and `p2k/favorites.py`
  are still there** (`pyproject.toml:143-157`), though the 6403ec6 message
  says they were "removed rather than left guarding nothing". The
  "Severity note … F821 … REAL BUG" comment (line 127) is stale since
  TODO 40.
- **README:**
  - Line 108 is missing the project name: " is provided **as is**…".
  - Lines 102 and 104 are a duplicated `---`.
  - The Support/AI/Risk text is generic family copy that does not fit p2ked:
    "mapping zones", "disk image", "binary formats", "aural A/B",
    "These tools can write to hardware and storage media". CLAUDE.md says
    p2ked does not write to the unit and should not start. Write those
    paragraphs for this tool, or say plainly that they describe the family.
  - Line 249: "last year's p2kcli". The project started in September 2026,
    so "earlier versions of p2kcli".
  - Lines 243-246: the comment column is one space off from the lines
    above.
  - **Run** (around line 207) still says `p2ked  # autodetect …`. It does
    not mention the remembered port, `--scan`, or where `config.toml`
    lives, which is the main user-visible change of fc986cc.
- **`docs/UX-SPEC.md`** is cited in `p2k/favorites.py:33`,
  `p2ked/cli.py:359` and `tests/test_conformance.py:19`, but it lives in
  vinsynlib. Say "vinsynlib's docs/UX-SPEC.md".
- **`p2k/config.py:81-95` (`load_port_pair`):** the reason given, "the
  browser has always written `recv_port` only when it differed from
  `port`", is wrong. Since 7955fd8 `bridge.recv_port` is always set and was
  always saved. The fallback is harmless, but only hand-edited files need
  it.
- **README's install line does not match this environment.**
  `.venv/pyvenv.cfg` says `include-system-site-packages = false`, while the
  README says `python3 -m venv --system-site-packages .venv` is
  "deliberate". Not a code defect, but the documented reason ("ALSA's
  sequencer and the system `python-rtmidi` are used rather than a fresh
  build") is not what this checkout actually did. Worth checking that the
  documented recipe is the one that works.
- `p2k/config.py` `load_port_pair` reads the file twice (`load_port`, then
  `load_recv_port`). Harmless alone, but a writer between the two reads
  could pair one run's output port with the next run's input port. Read the
  document once and pull both keys.
- `tests/test_connect.py` docstring: "p2k/bridge.py is at 24%" (it is
  48.88 % now).
- Commit-message claims that do not hold. These are recorded for the
  history and need no action. "A launch that had lost its port printed
  exactly what a fast launch prints": the old fast path printed
  `(remembered)`. "p2kcli does not take --config … nothing there reads
  either": see F7.
- Pre-existing and outside this range, but it contradicts the new README
  text: CLAUDE.md's "There is no hardware … Nothing may be described as
  verified" against README/bridge "verified against hardware on
  2026-09-12". One of them needs updating. CLAUDE.md is the stale one,
  given RESOLUTION_NOTES §7 and §11.

---

## F14 — Low: unfinished de-duplication

- `p2k/bridge.py` still carries its own `list_ports`, `bidirectional_ports`
  and `install_clean_exit`, which are near-copies of `vinsynlib.midi`.
  After F4, make them thin wrappers: `list_ports` wraps the library one and
  adds the ALSA/container hint, and `likely_proteus_ports` becomes
  `midi.likely_ports(_HINTS, ports)` filtered to bidirectional ports.
- `p2k.terms.TERMS` is imported only by tests. No user-facing string is
  built from it. Either use it (help text, `HELP`, the CLI headings) or say
  in the module that it is a declaration for the conformance check only.
  `test_the_vocabulary_is_declared` cannot fail in practice:
  `Terminology.__post_init__` already raises at import.
- `p2k/favorites.py` could be `_bound = _favorites.bind("p2ked")`, with
  `Favorites` kept as the subclass for the typed `__enter__`. Optional.
- Naming: `p2ked/app.py` imports `vinsynlib.cli as vincli`, and
  `p2ked/cli.py` imports it bare as `cli` inside a module that is itself
  called `cli`. Pick one, preferably `vincli`.

---

## F15 — Low: tooling

- **`audit-vulns`** (`Makefile:106-122`) writes `.audit-runtime-req.txt`
  into the repository root. It is not gitignored, and an interrupted run
  leaves it behind. The pass is also redundant: `requirements-dev.txt`
  already pins `textual`, `python-rtmidi` and `rich`, which the second
  pass audits. The first pass resolves pyproject's *ranges* against PyPI
  today, not what is installed.
  *Fix:* drop the first pass and audit `requirements-dev.txt` only. If the
  runtime set should be audited separately, run
  `pip-audit --skip-editable` against `.venv`, which needs no temp file.
- **The pre-commit `mypy` hook** (`mirrors-mypy`, isolated env, only `mypy`
  as a dependency) cannot import vinsynlib. With the global
  `ignore_missing_imports = true`, every vinsynlib call becomes `Any`
  there, so the hook is much weaker than `make typecheck`, which does see
  `py.typed`.
  *Fix:* make it a `repo: local`, `language: system` hook running
  `.venv/bin/mypy`, the way `make typecheck` does.

---

## F16 — Medium: the guard is declared but not actually installed

`pyproject.toml` declares `p2ked = "p2ked.entry:app"` and
`p2ked.egg-info/entry_points.txt` agrees, but the console scripts in this
working environment do not:

```
$ head -3 .venv/bin/p2ked
#!/home/lentferj/git-repos/p2ked/.venv/bin/python
from p2ked.app import main        # <- not p2ked.entry:app
$ head -3 .venv/bin/p2kcli
from p2ked.cli import main        # <- not p2ked.entry:cli
```

The scripts are dated 2 October, the `egg-info` 6 October, so the
regeneration that updated the metadata did not replace the scripts.
Whatever the local cause, the consequence is concrete: **running `p2ked`
here does not go through `entry.py` at all**, so the missing-library message
added by 5430ca1 is bypassed. Reproduced with a shadowing `vinsynlib` that
raises `ImportError`:

```
$ ... /venv/bin/p2ked --help
    from vinsynlib import cli as vincli
ImportError: simulated: vinsynlib broken
```

`make check` cannot catch this, because it imports `p2ked.entry` directly
and never runs the console script.

Two things follow:

1. **A reinstall is required after the merge.** `pip install -e .` (or
   `make install`) regenerates the scripts. Anyone who pulled the source
   without reinstalling has the old entry points that pointed straight at
   `p2ked.app`, and this is exactly the "pulled the source without
   reinstalling" case `entry.py`'s docstring was written for — which it
   cannot help with, because it is not being called.
2. **Add an end-to-end check**, so the guard has a test that fails when it
   is disconnected. For example, a test that reads the console script
   generated by the build (`importlib.metadata.entry_points`) and asserts
   `p2ked == "p2ked.entry:app"`, or a `make` target that removes the
   scripts, reinstalls, and runs `p2ked --help` against a shadowed library.

## Suggested order of work

1. **F1** (vinsynlib: push, bump, tag; then entry.py in all ten projects).
   Until then, nobody can install p2ked from what is published.
2. **F2 + F3** together, since one design change fixes both: a per-app
   config directory, or at least an ownership header plus namespacing.
3. **F4, F10:** small, local, and they restore error paths that used to
   work.
4. **F6, F7, F8, F9:** the user-visible honesty fixes. F6 needs one small
   vinsynlib API addition.
5. **F5:** the install path, alongside the F1 tag.
6. F11 tests for each of the above, then F12–F15 as housekeeping.
