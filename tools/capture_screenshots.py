#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors

"""Capture README screenshots for p2ked.

Drives the Textual app headlessly via run_test, exports SVG via
App.export_screenshot, converts to PNG with cairosvg at 820 px width.

Rules this script obeys (see README "Screenshots" and CLAUDE.md):

- DemoDevice only: no hardware, no MIDI ports, nothing sent. The write gate
  stays locked; no edit is triggered. `f` (favourite) is local-only and is
  the one state-changing key used, to give the favourites views content.
- One fresh app per shot: every shot starts from launch state, so a modal
  left open by one shot can never leak into the next. (A single shared
  session captured the rating modal eleven times over; that is why this
  script exists in this form.)
- Real catalog names come from the local catalog.json (ROM banks); user
  banks show the demo's invented names, as the README says.
- SVG fixups: DejaVu Sans Mono (covers every UI glyph: ★♥↑↓⏎≥▸), the remote
  @font-face blocks removed (no network at capture time), and Rich's macOS
  window chrome (traffic lights + title) stripped so the shot reads as a
  plain terminal capture.
"""

import asyncio
import re
import tempfile
from pathlib import Path

from cairosvg import svg2png

from p2k import catalog as cat
from p2k import favorites as fav
from p2ked.app import P2kedApp
from p2ked.demo import DemoDevice
from p2ked.multi import (
    ChannelDetailScreen,
    FXEditScreen,
    MasterEditScreen,
    MultiScreen,
    SoundPickerScreen,
    ValuePickerScreen,
)
from p2ked.prompts import PromptScreen

REPO_ROOT = Path(__file__).parent.parent
OUT_DIR = REPO_ROOT / "docs" / "screenshots"
SCREEN_W = 820
BROWSER_SIZE = (132, 42)
MODAL_SIZE = (120, 36)
# The multi table has nine columns; at MODAL_SIZE the table is squeezed out
# and only the report renders (found by the "why not" marker going missing).
# Every shot taken through `m` uses the browser frame instead.
# The multi screen is tall: label + master panel + the nine-column table +
# the per-channel report (one line per silent channel) + status + footer.
# At 42 rows the report crowds the table out entirely (found by the
# 'why not' marker going missing). Shots taken through m use a taller
# frame so the table renders with header and first rows.
MULTI_SIZE = (132, 85)
MID_SIZE = (132, 42)

# Text that must appear in each shot's SVG; the run fails loudly on a miss
# rather than committing a wrong picture.
MARKERS = {
    "general": ["Xtreme Lead"],
    "favourites-bank": ["favourite"],
    "favourites-all": ["favourite"],
    "rating-filter": ["rating"],
    "categories": ["bas:"],
    "search": ["Search"],
    "device": ["SIMM"],
    "help": ["Two panes"],
    "channels": ["why not"],
    "channel-detail": ["channel detail"],
    "sound-picker": ["Pick a sound"],
    "master-edit": ["transpose"],
    "master-fx": ["FX A"],
    "value-picker": ["omni"],
    "value-prompt": ["transpose"],
}


def fix_svg(svg: str) -> str:
    """Terminal font, no remote fonts, no window chrome."""
    svg = svg.replace(
        "font-family: Fira Code, monospace",
        'font-family: "DejaVu Sans Mono", monospace',
    )
    svg = re.sub(r"@font-face\s*\{[^}]+\}", "", svg)
    svg = re.sub(r"<circle[^>]*/>", "", svg)
    svg = re.sub(r"<circle[^>]*>.*?</circle>", "", svg)
    svg = re.sub(r'<text[^>]*class="[^"]*-title"[^>]*>.*?</text>', "", svg)
    return svg


def screen_text(svg: str) -> str:
    """The visible text of a shot, for the run transcript."""
    import html

    text = re.sub(r"<style.*?</style>", "", svg, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Table cells are padded with non-breaking spaces in the export; a
    # marker written with plain spaces would never match them.
    text = text.replace("\xa0", " ")
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    return "\n".join(lines)


async def capture(app, pilot, name: str) -> str:
    """Pin hint heights, export, fix, write SVG+PNG. Returns the SVG."""
    await pilot.pause()
    from vinsynlib.ui.hints import KeyHints

    for h in app.query(KeyHints):
        rendered = h.render()
        if rendered:
            h.styles.height = str(str(rendered).count("\n") + 1)
    await pilot.pause()

    svg = fix_svg(app.export_screenshot())
    (OUT_DIR / f"{name}.svg").write_text(svg)
    out_png = OUT_DIR / f"{name}.png"
    svg2png(bytestring=svg.encode(), write_to=str(out_png), output_width=SCREEN_W)
    print(f"  {name}.png ({out_png.stat().st_size // 1024} KB)")
    return svg


def check(name: str, svg: str) -> None:
    text = screen_text(svg).lower()
    wants = MARKERS[name]
    if not any(w.lower() in text for w in wants):
        raise AssertionError(f"{name}: none of {wants} in shot text:\n{text[:800]}")
    print(f"  markers ok: {wants}")


def make_app(tmp: Path) -> P2kedApp:
    (tmp / "config").mkdir(exist_ok=True)
    (tmp / "fav").mkdir(exist_ok=True)
    (tmp / "backups").mkdir(exist_ok=True)
    return P2kedApp(
        DemoDevice(),
        catalog=cat.load(),
        favorites=fav.Favorites(str(tmp / "fav" / "favorites.db")),
        config_path=str(tmp / "config" / "config.toml"),
        backup_dir=str(tmp / "backups"),
    )


async def wait_for_text(app, pilot, marker: str, tries: int = 40) -> None:
    """Poll the visible text until it contains the marker.

    Cursor state (`app._current_bank`) and the table's scroll position do
    not settle on the same tick: the state can read XLEAD-0 while the
    viewport still shows the composer banks. What the screenshot contains
    is the viewport, so wait for that.
    """
    for _ in range(tries):
        if marker.lower() in screen_text(app.export_screenshot()).lower():
            return
        await pilot.pause()
    raise AssertionError(f"never saw {marker!r} on screen")


async def wait_for_screen(app, pilot, cls, tries: int = 60) -> None:
    """Poll until the top screen is an instance of the expected class.

    Text markers can miss when a modal is still animating in or a worker
    has not reported yet; the screen class is what the shot asserts.
    """
    for _ in range(tries):
        if isinstance(app.screen, cls):
            return
        await pilot.pause()
    raise AssertionError(
        f"top screen is {type(app.screen).__name__}, not {cls.__name__}"
    )


async def wait_for_idle(app, pilot, tries: int = 100) -> None:
    """Wait until the wire is free.

    The app reads a bank of names at startup on its own; a key that needs
    the wire (`m`, `i`) pressed during that read is refused with "busy" and
    the press is spent. Local keys (`v`, `V`, `/`, `?`, `C`, `f`) never wait.
    """
    for _ in range(tries):
        if not app._busy:
            return
        await pilot.pause()
    raise AssertionError("wire stayed busy")


async def shot_general(app, pilot):
    # XLEAD-0 displays as "Xtreme Lead bank 0". Navigate by the app's own
    # current-bank state, not by counting presses: the displayed order is
    # the unit's fitted set, not the table order.
    for _ in range(80):
        if app._current_bank == "XLEAD-0":
            break
        await pilot.press("down")
        await pilot.pause()  # let cursor, scroll and state settle per step
    if app._current_bank != "XLEAD-0":
        raise AssertionError(f"navigation stopped at {app._current_bank}")
    await wait_for_text(app, pilot, "Xtreme Lead")
    return await capture(app, pilot, "general")


async def shot_favourites_bank(app, pilot):
    await pilot.press("f")  # mark the cursor preset: the view needs content
    await pilot.pause()
    await pilot.press("down")
    await pilot.press("f")
    await pilot.pause()
    await pilot.press("v")
    return await capture(app, pilot, "favourites-bank")


async def shot_favourites_all(app, pilot):
    await pilot.press("f")
    await pilot.pause()
    await pilot.press("v")
    await pilot.pause()
    await pilot.press("v")
    return await capture(app, pilot, "favourites-all")


async def shot_rating_filter(app, pilot):
    await pilot.press("V")
    await wait_for_text(app, pilot, "rating")
    return await capture(app, pilot, "rating-filter")


async def shot_categories(app, pilot):
    # Categories come from the `xxx:` prefixes in the current bank's names.
    # USER banks under the demo have invented names without prefixes, so go
    # to a ROM bank first — same navigation as the general shot.
    for _ in range(80):
        if app._current_bank == "XLEAD-0":
            break
        await pilot.press("down")
        await pilot.pause()
    if app._current_bank != "XLEAD-0":
        raise AssertionError(f"navigation stopped at {app._current_bank}")
    await wait_for_text(app, pilot, "Xtreme Lead")
    await pilot.press("C")
    return await capture(app, pilot, "categories")


async def shot_search(app, pilot):
    await pilot.press("/")
    await wait_for_text(app, pilot, "Search")
    return await capture(app, pilot, "search")


async def shot_device(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("i")
    await wait_for_text(app, pilot, "SIMMs fitted")
    return await capture(app, pilot, "device")


async def shot_help(app, pilot):
    await pilot.press("?")
    await wait_for_text(app, pilot, "Two panes")
    return await capture(app, pilot, "help")


async def shot_channels(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("m")
    await wait_for_text(app, pilot, "why not")
    return await capture(app, pilot, "channels")


async def shot_channel_detail(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("m")
    await wait_for_screen(app, pilot, MultiScreen)
    for _ in range(9):
        await pilot.press("down")
        await pilot.pause()
    await pilot.press("enter")
    await wait_for_screen(app, pilot, ChannelDetailScreen)
    return await capture(app, pilot, "channel-detail")


async def shot_sound_picker(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("m")
    await wait_for_screen(app, pilot, MultiScreen)
    await pilot.press("s")
    await wait_for_screen(app, pilot, SoundPickerScreen)
    return await capture(app, pilot, "sound-picker")


async def shot_master_edit(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("m")
    await wait_for_screen(app, pilot, MultiScreen)
    await pilot.press("e")
    await wait_for_screen(app, pilot, MasterEditScreen)
    return await capture(app, pilot, "master-edit")


async def shot_master_fx(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("m")
    await wait_for_screen(app, pilot, MultiScreen)
    await pilot.press("x")
    await wait_for_screen(app, pilot, FXEditScreen)
    return await capture(app, pilot, "master-fx")


async def shot_value_picker(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("m")
    await wait_for_screen(app, pilot, MultiScreen)
    await pilot.press("e")
    await wait_for_screen(app, pilot, MasterEditScreen)
    await pilot.press("enter")
    await wait_for_screen(app, pilot, ValuePickerScreen)
    return await capture(app, pilot, "value-picker")


async def shot_value_prompt(app, pilot):
    await wait_for_idle(app, pilot)
    await pilot.press("m")
    await wait_for_screen(app, pilot, MultiScreen)
    await pilot.press("e")
    await wait_for_screen(app, pilot, MasterEditScreen)
    for _ in range(5):
        await pilot.press("down")  # transpose: a plain range
        await pilot.pause()
    await pilot.press("enter")
    await wait_for_screen(app, pilot, PromptScreen)
    return await capture(app, pilot, "value-prompt")


SHOTS = [
    ("general", shot_general, BROWSER_SIZE),
    ("favourites-bank", shot_favourites_bank, BROWSER_SIZE),
    ("favourites-all", shot_favourites_all, BROWSER_SIZE),
    ("rating-filter", shot_rating_filter, MODAL_SIZE),
    ("categories", shot_categories, MODAL_SIZE),
    ("search", shot_search, MODAL_SIZE),
    ("device", shot_device, MODAL_SIZE),
    ("help", shot_help, MODAL_SIZE),
    ("channels", shot_channels, MULTI_SIZE),
    ("channel-detail", shot_channel_detail, MID_SIZE),
    ("sound-picker", shot_sound_picker, MID_SIZE),
    ("master-edit", shot_master_edit, MID_SIZE),
    ("master-fx", shot_master_fx, MID_SIZE),
    ("value-picker", shot_value_picker, MULTI_SIZE),
    ("value-prompt", shot_value_prompt, MULTI_SIZE),
]


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for name, fn, size in SHOTS:
            sub = tmp / name
            sub.mkdir(exist_ok=True)
            app = make_app(sub)
            async with app.run_test(size=size) as pilot:
                svg = await fn(app, pilot)
            check(name, svg)
            print(f"--- {name} ---")
            print(screen_text(svg)[:900])
            print()
    print(f"Done. Screenshots in {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
