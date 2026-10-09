# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  p2ked contributors
#
# This file is part of p2ked.
#
# p2ked is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# p2ked is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""``p2kcli``, driven through its argument parser.

Every command is run through `main()` rather than called directly, so the
argument names, the subparser wiring and the dispatch table are all under
test. A test that called `_cmd_find` with a hand-built namespace would have
passed while the command was broken for a real user.

**Names used here are invented**, per CLAUDE.md: E-MU's preset names are
not committed to this repository and a fixture is not an exception.

The offline commands open no MIDI port. The ones that need a device run
against `DemoDevice` via `--demo`, which likewise opens none.
"""

import json

import pytest

from p2k import roms
from p2ked import cli


@pytest.fixture
def catalog_file(tmp_path):
    """A two-bank printed catalog, as ``tools/extract_catalog.py`` writes.

    Returned as a path because the CLI takes one.
    """
    payload = {
        "source": "invented-for-the-tests",
        "generated": "2026-10-02",
        "banks": {
            "USER-0": [
                {"pc": 0, "name": "Printed Bell"},
                {"pc": 1, "name": "Rusted Pad"},
            ],
            "XLEAD-0": [
                {"pc": 5, "name": "Kelp Forest"},
            ],
        },
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestOfflineCommands:
    """The commands that need no unit and no MIDI stack."""

    def test_roms_lists_the_table(self, capsys, catalog_file):
        assert cli.main(["--catalog", catalog_file, "roms"]) == 0
        out = capsys.readouterr().out
        assert "XLEAD" in out and "Xtreme Lead" in out
        # The 'named' column counts catalogued banks per ROM.
        assert "Composer" in out

    def test_list_shows_one_bank(self, capsys, catalog_file):
        assert cli.main(["--catalog", catalog_file, "list", "USER-0"]) == 0
        out = capsys.readouterr().out
        assert "Printed Bell" in out
        assert "Rusted Pad" in out

    def test_resolve_inverts_a_selection(self, capsys, catalog_file):
        assert cli.main(["--catalog", catalog_file, "resolve", "7", "1", "5"]) == 0
        out = capsys.readouterr().out
        assert "Xtreme Lead" in out
        assert "133" in out, "the ROM-relative preset number"

    def test_resolve_refuses_an_msb_it_does_not_know(self, capsys, catalog_file):
        """A ROM outside the table is a real answer, not a crash."""
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--catalog", catalog_file, "resolve", "99", "0", "0"])
        assert "99" in str(exit_info.value)

    def test_an_unknown_bank_names_the_error(self, capsys, catalog_file):
        with pytest.raises(SystemExit):
            cli.main(["--catalog", catalog_file, "list", "NOSUCH-9"])


class TestFind:
    """`p2kcli find`, and the disagreement marker.

    This is the command that was broken: `Catalog.search` returns
    `(bank_id, program_change, name, differs)` but `_cmd_find` unpacked
    three names and then read a fourth, `differs`, that was never bound.
    Every non-empty search raised `ValueError` before reaching the marker
    it was supposed to draw. Tracked as TODO.md item 40.
    """

    def _catalog_with_a_disagreement(self, catalog_file):
        """The printed catalog, plus one slot the unit has renamed.

        A **ROM** slot, deliberately: a user bank cannot produce a
        disagreement any more (its printed names are placeholders), so this
        is the only kind of slot that can carry the `*`.
        """
        from p2k import catalog as cat

        catalog = cat.load(catalog_file)
        catalog.set_live_name("XLEAD-0", 5, "Renamed By Unit")
        return catalog

    def test_it_finds_a_name(self, capsys, catalog_file, monkeypatch):
        monkeypatch.setattr(
            cli,
            "_catalog",
            lambda args: self._catalog_with_a_disagreement(catalog_file),
        )
        assert cli.main(["--catalog", catalog_file, "find", "bell"]) == 0
        out = capsys.readouterr().out
        assert "USER-0" in out
        assert "Printed Bell" in out

    def test_the_disagreement_is_marked(self, capsys, catalog_file, monkeypatch):
        """The `*`, and the footnote that explains it.

        A search is where this matters most: the browser marks a slot the
        user is already looking at, while a search result is a name from a
        bank they have not opened.
        """
        monkeypatch.setattr(
            cli,
            "_catalog",
            lambda args: self._catalog_with_a_disagreement(catalog_file),
        )
        assert cli.main(["--catalog", catalog_file, "find", "kelp"]) == 0
        out = capsys.readouterr().out
        assert "*" in out, "a name the unit disagrees about must be marked"
        assert "disagree" in out, "the footnote explaining the marker"

    def test_an_agreeing_name_is_not_marked(self, capsys, catalog_file):
        """Only a genuine disagreement gets the `*`."""
        assert cli.main(["--catalog", catalog_file, "find", "bell"]) == 0
        out = capsys.readouterr().out
        assert "Printed Bell" in out
        assert "disagree" not in out

    def test_the_live_name_is_shown_when_it_matches(
        self, capsys, catalog_file, monkeypatch
    ):
        monkeypatch.setattr(
            cli,
            "_catalog",
            lambda args: self._catalog_with_a_disagreement(catalog_file),
        )
        assert cli.main(["--catalog", catalog_file, "find", "renamed"]) == 0
        assert "Renamed By Unit" in capsys.readouterr().out

    def test_no_hits_says_so_on_stderr(self, capsys, catalog_file):
        assert cli.main(["--catalog", catalog_file, "find", "zzzz"]) == 0
        captured = capsys.readouterr()
        assert "nothing matching" in captured.err
        assert captured.out == "", "no table is printed for an empty search"

    def test_the_search_is_case_insensitive(self, capsys, catalog_file):
        assert cli.main(["--catalog", catalog_file, "find", "BELL"]) == 0
        assert "Printed Bell" in capsys.readouterr().out


class TestDeviceCommandsAgainstTheDemo:
    """The commands that need a unit, run against DemoDevice.

    `--demo` opens no port, so these are synthetic like the rest of the
    suite.
    """

    def test_config_lists_fitted_roms(self, capsys):
        assert cli.main(["--demo", "config"]) == 0
        out = capsys.readouterr().out
        assert "user presets" in out
        assert "SIMMs fitted" in out

    def test_channels_shows_all_thirty_two(self, capsys):
        assert cli.main(["--demo", "channels"]) == 0
        out = capsys.readouterr().out
        assert "32 channels" in out
        assert "MIDI mode" in out

    def test_names_reads_a_bank(self, capsys):
        assert cli.main(["--demo", "names", "USER-0"]) == 0
        out = capsys.readouterr().out
        assert "on the unit" in out
        # 128 rows, none of them the sentinel.
        assert out.count("\n") >= 128
        assert "(not installed)" not in out

    def test_status_reports_an_emu(self, capsys):
        assert cli.main(["--demo", "status"]) == 0
        assert "E-MU" in capsys.readouterr().out

    def test_select_sends_the_three_numbers(self, capsys, monkeypatch, tmp_path):
        """The one command that makes a sound.

        Asserted on the demo's record, so the three numbers are checked
        rather than merely "something was sent".

        ``--config`` names a file of the test's own. `select` now reads the
        remembered channel, and the default is *relative* -- so without this
        the suite would send on whatever channel the developer's checkout
        had left in `./config.toml`, which is exactly the leak the AST check
        in test_legend.py exists to stop.
        """
        from p2ked.demo import DemoDevice

        device = DemoDevice()
        monkeypatch.setattr(cli, "_build_device", lambda args: device)
        config = tmp_path / "settings.toml"
        assert cli.main(["--config", str(config), "select", "USER-0", "3"]) == 0
        assert device.selected_log, "nothing was selected"
        entry, channel = device.selected_log[0]
        assert (entry.msb, entry.lsb, entry.program_change) == (0, 0, 3)
        assert channel == 0
        assert "MSB 0" in capsys.readouterr().out

    def test_a_remembered_channel_is_used(self, capsys, monkeypatch, tmp_path):
        """`--channel` if given, else the one used last time, else 1.

        The help text has said "(default: remembered, or 1)" since the
        library took over the parser, and `select` used to read
        `args.channel or 1` -- so the remembered half was a promise nothing
        kept. This is that promise, pinned.
        """
        from p2k import config as cfg
        from p2ked.demo import DemoDevice

        config = tmp_path / "settings.toml"
        # Zero-based, as the cache stores it and as `select` sends it: the
        # browser saves `self.channel`, which is already the wire value.
        cfg.save_channel(9, str(config))
        device = DemoDevice()
        monkeypatch.setattr(cli, "_build_device", lambda args: device)

        assert cli.main(["--config", str(config), "select", "USER-0", "3"]) == 0
        assert device.selected_log[0][1] == 9
        assert "MIDI channel 10" in capsys.readouterr().out

        # An explicit --channel still wins over what was remembered.
        device.selected_log.clear()
        assert (
            cli.main(
                ["--config", str(config), "--channel", "2", "select", "USER-0", "3"]
            )
            == 0
        )
        assert device.selected_log[0][1] == 1

    def test_an_offline_command_never_builds_a_device(self, monkeypatch, catalog_file):
        """The `_OFFLINE` promise, enforced rather than asserted in prose.

        `main()` dispatches an offline command as `handler(None, args)`, so
        it must never reach `_build_device`. Pointing that at a factory
        that raises proves it for the whole set at once, rather than
        trusting the list to stay in step with the dispatch table.
        """

        def explode(args):
            raise AssertionError("an offline command tried to open a port")

        monkeypatch.setattr(cli, "_build_device", explode)
        # Global options come before the subcommand; argparse rejects them
        # after it.
        for argv in (
            ["roms"],
            ["list", "USER-0"],
            ["find", "bell"],
            ["resolve", "0", "0", "0"],
        ):
            status = cli.main(["--catalog", catalog_file, *argv])
            assert status == 0, argv

    def test_the_offline_set_matches_the_documented_one(self):
        # Compared as sorted lists: SIM300 treats a name bound to a literal
        # as a constant and wants it on the left of `==`, which is the Yoda
        # style the rule exists to discourage. Sorted lists also give a
        # readable diff when it fails.
        #
        # Both spellings of the bank table are here because both dispatch:
        # `banks` is now canonical and `roms` is the alias it kept, so a
        # command line written against last year's p2kcli still opens no port.
        documented = ["banks", "find", "list", "ports", "resolve", "roms"]
        assert sorted(cli._OFFLINE) == documented


class TestArgumentValidation:
    def test_the_channel_range_is_checked(self):
        for bad in ("0", "17", "-1"):
            with pytest.raises(SystemExit) as exit_info:
                cli.main(["--channel", bad, "--demo", "status"])
            assert "1-16" in str(exit_info.value)

    def test_a_command_is_required(self):
        with pytest.raises(SystemExit):
            cli.main([])


class TestTheRomTableIsWhatTheCliClaims:
    """The CLI and p2k/roms.py must not disagree about the table.

    `_cmd_roms` prints `entry.bank_count` and a name count; this checks
    those numbers against the module they are derived from, so a change to
    the ROM table cannot quietly make the CLI's summary a fiction.
    """

    def test_every_rom_row_is_present(self, capsys, catalog_file):
        assert cli.main(["--catalog", catalog_file, "roms"]) == 0
        out = capsys.readouterr().out
        for entry in roms.ROMS:
            assert entry.id in out, entry.id
            assert entry.name in out, entry.name


class TestAskingWhichRomsAreFitted:
    """`roms_from_config`, the cheap answer to the startup question.

    One Configuration request instead of one name request per ROM. TODO.md
    item 34; measured at 16.5 ms against 370.7 ms on a Proteus 2000 on
    2026-10-02, with the two agreeing exactly.

    Checked here against the demo device, and -- for the part that matters
    -- against `installed_roms`, so the two answers are asserted to be the
    same rather than merely each plausible.
    """

    def test_it_covers_every_rom_in_the_table(self):
        from p2ked.demo import DemoDevice

        installed = DemoDevice().roms_from_config()
        assert set(installed) == {
            roms.USER_ROM_ID if e is roms.USER else e.msb for e in roms.ROMS
        }

    def test_only_the_fitted_roms_are_present(self):
        from p2ked.demo import DEMO_SIMMS, DemoDevice

        installed = DemoDevice().roms_from_config()
        present = {rom_id for rom_id, yes in installed.items() if yes}
        expected = {roms.USER_ROM_ID} | {roms.rom(rom_id).msb for rom_id in DEMO_SIMMS}
        assert present == expected

    def test_user_memory_is_present_and_is_not_a_simm(self):
        """The trap: user memory is reported as a size, not as a SIMM.

        A configuration response alone lists no user banks, so a bank pane
        built straight from `config.simms` would start on a ROM and never
        show USER-0 at all.
        """
        from p2ked.demo import DemoDevice

        device = DemoDevice()
        assert roms.USER_ROM_ID not in {
            s.simm_id for s in device.hardware_config().simms
        }
        assert device.roms_from_config()[roms.USER_ROM_ID] is True

    def test_the_config_answer_equals_the_name_probe_answer(self):
        """Two independent paths to the same question, asserted equal.

        `roms_from_config` reads the Configuration response; the probe reads
        a Generic Name reply per ROM and recognises the absent sentinel --
        the logic `ProteusBridge.installed_roms` uses, and which the demo
        device does not expose as a method, so it is spelled out here over
        the demo's own protocol.

        This is the check that matters: one Configuration response and
        twenty name replies are two readings of the same fact, and they are
        compared against a real unit every time this is re-run (TODO 34).
        """
        from p2k import roms as table
        from p2ked.demo import DemoDevice

        device = DemoDevice()
        by_config = device.roms_from_config()

        by_probe = {}
        for entry in table.ROMS:
            rom_id = table.USER_ROM_ID if entry is table.USER else entry.msb
            try:
                name = device.preset_name(0, rom_id)
            except TimeoutError:
                continue  # unknown, not absent
            by_probe[rom_id] = not table.is_absent(name)

        assert by_config == by_probe
        assert by_config[table.USER_ROM_ID] is True

    def test_an_absent_rom_is_false_not_missing(self):
        from p2ked.demo import DemoDevice

        installed = DemoDevice().roms_from_config()
        # PROTOZOA is not in DEMO_SIMMS.
        assert installed[roms.rom("PROTOZOA").msb] is False
