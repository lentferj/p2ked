#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors

"""Capture README screenshots for p2ked.

Drives the Textual app headlessly via run_test, exports SVG via App.export_screenshot,
converts to PNG with cairosvg at a standard width (820 px). All captures use
DemoDevice (no hardware, no ports). A temporary config directory isolates the run
from the user's real data.

Screens captured:
- general.png          browser, ROM bank selected, catalog names visible
- favourites-bank.png  v once -> this bank's favourites
- favourites-all.png   v twice -> all favourites
- rating-filter.png    V -> RatingFilterScreen
- categories.png       C -> category prompt
- search.png           / -> SearchScreen
- device.png           i -> ReportScreen "Device"
- help.png             ? -> ReportScreen "p2ked"
- channels.png         m -> MultiScreen (32 channels + master panel + why-not)
- channel-detail.png   enter on row -> ChannelDetailScreen
- sound-picker.png     s -> SoundPickerScreen
- master-edit.png      e -> MasterEditScreen
- master-fx.png        x -> MasterFXScreen
- value-picker.png     enter on named-value row -> ValuePickerScreen
- value-prompt.png     enter on numeric row -> PromptScreen
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

# ─── constants ──────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
OUT_DIR = REPO_ROOT / "docs" / "screenshots"
SCREEN_W = 820  # standard output width in pixels
CONSOLE_W = 132  # terminal columns
CONSOLE_H = 42  # terminal rows


# ─── helpers ────────────────────────────────────────────────────────────────


def fix_svg_font(svg: str) -> str:
    """Rewrite font-family to a monospace that has our glyphs and
    strip window chrome.
    """
    svg = svg.replace('font-family="monospace"', 'font-family="FreeMono"')
    svg = svg.replace('font-family="Monospace"', 'font-family="FreeMono"')
    svg = re.sub(r'font-family="[^"]*"', 'font-family="FreeMono"', svg)
    return svg


async def capture(
    app, pilot, name: str, *, modal: bool = False, fix_hints: bool = True
) -> None:
    """Pause, fix hints height, export SVG, convert to PNG."""
    await pilot.pause()

    if fix_hints:
        # Pin KeyHints height so it doesn't eat table rows
        from vinsynlib.ui.hints import KeyHints

        for h in app.query(KeyHints):
            rendered = h.render()
            if rendered:
                lines = str(rendered).count("\n") + 1
                h.styles.height = str(lines)

    await pilot.pause()

    svg = app.export_screenshot()
    svg = fix_svg_font(svg)

    out_svg = OUT_DIR / f"{name}.svg"
    out_png = OUT_DIR / f"{name}.png"

    out_svg.write_text(svg)

    # Convert to PNG at standard width
    svg2png(
        bytestring=svg.encode("utf-8"),
        write_to=str(out_png),
        output_width=SCREEN_W,
    )

    print(f"  captured {name}.png ({out_png.stat().st_size / 1024:.1f} KB)")


# ─── screen capture coroutines ──────────────────────────────────────────────


async def shot_general(app, pilot):
    """Browser with ROM bank selected showing catalog names."""
    for _ in range(5):
        await pilot.press("down")
    await capture(app, pilot, "general")


async def shot_favourites_bank(app, pilot):
    """v once -> this bank's favourites."""
    await pilot.press("v")
    await capture(app, pilot, "favourites-bank")


async def shot_favourites_all(app, pilot):
    """v twice -> all favourites."""
    await pilot.press("v")
    await pilot.pause()
    await pilot.press("v")
    await capture(app, pilot, "favourites-all")


async def shot_rating_filter(app, pilot):
    """V -> RatingFilterScreen."""
    await pilot.press("V")
    await capture(app, pilot, "rating-filter", modal=True)


async def shot_categories(app, pilot):
    """C -> category prompt (bas:-style text input)."""
    await pilot.press("C")
    await capture(app, pilot, "categories", modal=True)


async def shot_search(app, pilot):
    """/ -> SearchScreen."""
    await pilot.press("/")
    await capture(app, pilot, "search", modal=True)


async def shot_device(app, pilot):
    """i -> ReportScreen 'Device'."""
    await pilot.press("i")
    await capture(app, pilot, "device", modal=True)


async def shot_help(app, pilot):
    """? -> ReportScreen 'p2ked' (help)."""
    await pilot.press("?")
    await capture(app, pilot, "help", modal=True)


async def shot_channels(app, pilot):
    """m -> MultiScreen."""
    await pilot.press("m")
    await capture(app, pilot, "channels", modal=True)


async def shot_channel_detail(app, pilot):
    """enter on a channel row -> ChannelDetailScreen."""
    await pilot.press("m")
    await pilot.pause()
    for _ in range(9):
        await pilot.press("down")
    await pilot.press("enter")
    await capture(app, pilot, "channel-detail", modal=True)


async def shot_sound_picker(app, pilot):
    """s -> SoundPickerScreen (from MultiScreen)."""
    await pilot.press("m")
    await pilot.pause()
    await pilot.press("s")
    await capture(app, pilot, "sound-picker", modal=True)


async def shot_master_edit(app, pilot):
    """e -> MasterEditScreen (from MultiScreen)."""
    await pilot.press("m")
    await pilot.pause()
    await pilot.press("e")
    await capture(app, pilot, "master-edit", modal=True)


async def shot_master_fx(app, pilot):
    """x -> FXEditScreen (from MultiScreen)."""
    await pilot.press("m")
    await pilot.pause()
    await pilot.press("x")
    await capture(app, pilot, "master-fx", modal=True)


async def shot_value_picker(app, pilot):
    """enter on a named-value row (e.g. MIDI mode) -> ValuePickerScreen."""
    await pilot.press("m")
    await pilot.pause()
    await pilot.press("e")
    await pilot.pause()
    await pilot.press("enter")
    await capture(app, pilot, "value-picker", modal=True)


async def shot_value_prompt(app, pilot):
    """enter on a numeric row (e.g. transpose) -> PromptScreen with range."""
    await pilot.press("m")
    await pilot.pause()
    await pilot.press("e")
    await pilot.pause()
    for _ in range(5):
        await pilot.press("down")
    await pilot.press("enter")
    await capture(app, pilot, "value-prompt", modal=True)


# ─── main orchestration ─────────────────────────────────────────────────────


async def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        config_dir = tmp / "config"
        fav_dir = tmp / "fav"
        backup_dir = tmp / "backups"
        config_dir.mkdir()
        fav_dir.mkdir()
        backup_dir.mkdir()

        config_path = config_dir / "config.toml"
        fav_path = fav_dir / "favorites.db"
        backup_path = backup_dir

        catalog = cat.load()
        favorites = fav.Favorites(fav_path)

        app = P2kedApp(
            DemoDevice(),
            catalog=catalog,
            favorites=favorites,
            config_path=str(config_path),
            backup_dir=str(backup_path),
        )

        shots = [
            ("general", shot_general),
            ("favourites-bank", shot_favourites_bank),
            ("favourites-all", shot_favourites_all),
            ("rating-filter", shot_rating_filter),
            ("categories", shot_categories),
            ("search", shot_search),
            ("device", shot_device),
            ("help", shot_help),
            ("channels", shot_channels),
            ("channel-detail", shot_channel_detail),
            ("sound-picker", shot_sound_picker),
            ("master-edit", shot_master_edit),
            ("master-fx", shot_master_fx),
            ("value-picker", shot_value_picker),
            ("value-prompt", shot_value_prompt),
        ]

        async with app.run_test(size=(CONSOLE_W, CONSOLE_H)) as pilot:
            for name, fn in shots:
                try:
                    await fn(app, pilot)
                except Exception as e:
                    print(f"  FAILED {name}: {e}")
                    continue

        print(f"\nDone. Screenshots in {OUT_DIR}")


if __name__ == "__main__":
    import asyncio
    import re
    import tempfile
    from pathlib import Path

    from cairosvg import svg2png

    from p2k import catalog as cat
    from p2k import favorites as fav
    from p2ked.app import P2kedApp
    from p2ked.demo import DemoDevice

    OUT_DIR = Path(__file__).parent.parent / "docs" / "screenshots"
    SCREEN_W = 820
    CONSOLE_W = 132
    CONSOLE_H = 42

    asyncio.run(main())
