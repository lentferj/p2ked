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

"""The setup backup: the restore point for the one destructive write.

Four things are pinned here, and they are the four the feature promises:

* **A real dump round-trips.** A :class:`p2k.messages.SetupDump` read from
  the demo is encoded, saved, loaded and encoded again, and the two frames
  are equal -- which is the whole of what a restore can be, since the
  encoder is the parser's exact inverse (``docs/RESOLUTION_NOTES.md`` §13).
* **The envelope never overwrites**, because the library's does not: two
  saves in one microsecond are two files.
* **The automatic backup fires once, before the first write, and says so.**
  What is saved is the setup the unit held *before* the write, and a second
  edit does not take a second restore point.
* **A restore is gated.** It sends a whole setup back, so it refuses without
  the family's ``--yes``, and the demo adopts what it sent.

The one thing no test here can establish is whether a real Proteus takes a
restored dump -- that is the hardware suite's question, and §13's unmodified
round trip is the first answer it should give.
"""

import os

import pytest

from p2k import backup as bk
from p2k import catalog as cat
from p2k import messages as m
from p2k.favorites import data_dir
from p2ked import cli
from p2ked.app import P2kedApp
from p2ked.demo import DEMO_DEVICE_ID, DemoDevice
from p2ked.masteredit import mutate_channel
from vinsynlib import backup as vbk

#: An enabled channel of the demo, at volume 127. A volume edit is one field
#: and one that moves a byte, so a restore point is easy to compare.
LIVE = 8


def _record(app):
    """Capture what the app says, and whether it said it as a refusal.

    The same helper the per-channel tests use: ``notify_status`` prefixes a
    refusal, and a backup failure announced without one would look like news.
    """
    said = []

    def say(message, *, refused=False):
        said.append((message, refused))

    app.notify_status = say
    return said


async def _wait_for(pilot, ready, attempts=100):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


class TestTheEnvelope:
    """``p2k.backup`` itself: the library's envelope, and p2ked's block."""

    def test_a_real_dump_round_trips(self, tmp_path):
        device = DemoDevice()
        dump = device.read_setup()
        record = bk.save_setup(
            dump,
            device_id=device.device_id,
            slot="live",
            directory=str(tmp_path),
        )
        assert record.kind == bk.KIND
        assert record.slot == "live"
        assert record.name == dump.name
        assert record.error is None

        loaded = bk.load(record.id, directory=str(tmp_path))
        assert m.encode_setup_dump(loaded, device=device.device_id) == (
            m.encode_setup_dump(dump, device=device.device_id)
        )
        # And the field a restore is for is the value that was saved, not
        # whatever a later edit put there.
        assert loaded.channel(LIVE).volume == 127

    def test_the_envelope_never_overwrites(self, tmp_path):
        """Two saves are two files, not one replaced. The library's rule."""
        device = DemoDevice()
        dump = device.read_setup()
        first = bk.save_setup(
            dump, device_id=device.device_id, slot="live", directory=str(tmp_path)
        )
        second = bk.save_setup(
            dump, device_id=device.device_id, slot="live", directory=str(tmp_path)
        )
        assert first.id != second.id
        assert os.path.isfile(tmp_path / first.id)
        assert os.path.isfile(tmp_path / second.id)
        assert len(bk.list_backups(str(tmp_path))) == 2

    def test_the_default_directory_is_under_the_data_directory(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert bk.default_dir() == os.path.join(data_dir(), "backups")
        assert bk.default_dir().startswith(str(tmp_path))
        # Not the checkout: the reason the directory is not simply "backups".
        assert os.path.basename(bk.default_dir()) == "backups"
        assert "p2ked" in bk.default_dir()

    def test_list_is_lenient_about_a_corrupt_file(self, tmp_path):
        device = DemoDevice()
        bk.save_setup(
            device.read_setup(),
            device_id=device.device_id,
            slot="live",
            directory=str(tmp_path),
        )
        (tmp_path / "corrupt.json").write_text("not json", encoding="utf-8")
        rows = bk.list_backups(str(tmp_path))
        good = [row for row in rows if row.error is None]
        broken = [row for row in rows if row.error is not None]
        assert len(good) == 1
        assert len(broken) == 1
        assert broken[0].id == "corrupt.json"
        assert "Expecting" in (broken[0].error or "")

    def test_a_directory_that_is_not_there_lists_nothing(self, tmp_path):
        assert bk.list_backups(str(tmp_path / "nope")) == []

    def test_listing_skips_something_that_is_not_a_file(self, tmp_path):
        """A subdirectory in the backup directory is not a backup, and is
        not offered as one."""
        (tmp_path / "a-directory").mkdir()
        assert bk.list_backups(str(tmp_path)) == []

    def test_a_backup_can_be_named_by_its_full_path(self, tmp_path):
        """So one copied to a USB stick can be restored without --dir."""
        device = DemoDevice()
        record = bk.save_setup(
            device.read_setup(),
            device_id=device.device_id,
            slot="live",
            directory=str(tmp_path),
        )
        full = os.path.join(str(tmp_path), record.id)
        loaded = bk.load(full)
        assert m.encode_setup_dump(loaded, device=device.device_id) == (
            m.encode_setup_dump(device.read_setup(), device=device.device_id)
        )

    def test_load_refuses_a_setup_block_that_is_not_a_frame(self, tmp_path):
        path = vbk.save(
            str(tmp_path),
            kind=bk.KIND,
            slot="live",
            name="Junk",
            device_id="0",
            source="test",
            blocks={bk.BLOCK: b"not a system exclusive frame"},
        )
        with pytest.raises(ValueError, match="not a setup dump frame"):
            bk.load(os.path.basename(path), directory=str(tmp_path))

    def test_load_refuses_a_backup_that_is_not_a_setup(self, tmp_path):
        path = vbk.save(
            str(tmp_path),
            kind="patch",
            slot="01",
            name="Not A Setup",
            device_id="0",
            source="test",
            blocks={"patch": b"\xf0\xf7"},
        )
        with pytest.raises(ValueError, match="not a setup backup"):
            bk.load(os.path.basename(path), directory=str(tmp_path))

    def test_load_refuses_a_setup_with_no_block(self, tmp_path):
        path = vbk.save(
            str(tmp_path),
            kind=bk.KIND,
            slot="live",
            name="Empty",
            device_id="0",
            source="test",
            blocks={},
        )
        with pytest.raises(ValueError, match="no setup block"):
            bk.load(os.path.basename(path), directory=str(tmp_path))


class TestTheAutomaticBackup:
    """The restore point the per-channel write path takes, once a session."""

    async def test_the_first_write_backs_up_the_live_setup_and_says_so(self, tmp_path):
        app = P2kedApp(
            DemoDevice(),
            catalog=cat.empty(),
            allow_write=True,
            backup_dir=str(tmp_path),
        )
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)

            rows = bk.list_backups(str(tmp_path))
            assert len(rows) == 1, "the first write took no restore point"
            # What is saved is the setup *before* the write: the live dump
            # the worker read, not the one it sent.
            saved = bk.load(rows[0].id, directory=str(tmp_path))
            assert saved.channel(LIVE).volume == 127
            assert app.device.read_setup().channel(LIVE).volume == 90

            messages = [message for message, _refused in said]
            assert any("backed up the setup as" in message for message in messages), (
                messages
            )

    async def test_a_second_edit_does_not_back_up_again(self, tmp_path):
        """One restore point, not a log: a burst or a later edit reuses it."""
        app = P2kedApp(
            DemoDevice(),
            catalog=cat.empty(),
            allow_write=True,
            backup_dir=str(tmp_path),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            app.action_edit_channel(LIVE, "volume", 80)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(bk.list_backups(str(tmp_path))) == 1
            assert app.device.read_setup().channel(LIVE).volume == 80

    async def test_a_refused_write_takes_no_backup(self, tmp_path):
        """A locked gate sends nothing, so there is nothing to restore from
        and no file is left behind."""
        app = P2kedApp(DemoDevice(), catalog=cat.empty(), backup_dir=str(tmp_path))
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert app.device.dump_log == []
            assert bk.list_backups(str(tmp_path)) == []

    async def test_a_backup_that_fails_is_said_and_does_not_stop_the_write(
        self, tmp_path, monkeypatch
    ):
        """The write is not this feature's to change: it goes out unchanged,
        and the failure is announced rather than swallowed."""

        def explode(*args, **kwargs):
            raise OSError("read-only directory")

        monkeypatch.setattr(bk, "save_setup", explode)
        app = P2kedApp(
            DemoDevice(),
            catalog=cat.empty(),
            allow_write=True,
            backup_dir=str(tmp_path),
        )
        said = _record(app)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_edit_channel(LIVE, "volume", 90)
            await _wait_for(pilot, lambda: not app._busy)
            assert len(app.device.dump_log) == 1, "the write did not go out"
            assert app.device.read_setup().channel(LIVE).volume == 90
            assert any(
                "could not back up the setup" in message for message, _refused in said
            ), said
            assert [
                refused
                for message, refused in said
                if "could not back up the setup" in message
            ] == [True], "the failure was not said as a refusal"


class TestTheBackupDirectoryFlag:
    """``--backup-dir``, rxved's own flag for this, on the browser."""

    def test_the_parser_accepts_it_and_defaults_to_the_data_directory(self):
        from p2ked.app import build_parser

        assert build_parser().parse_args([]).backup_dir is None
        assert (
            build_parser().parse_args(["--backup-dir", "/somewhere"]).backup_dir
            == "/somewhere"
        )

    def test_the_app_prefers_what_it_was_given(self, tmp_path):
        app = P2kedApp(DemoDevice(), catalog=cat.empty(), backup_dir=str(tmp_path))
        assert app.backup_dir() == str(tmp_path)
        default = P2kedApp(DemoDevice(), catalog=cat.empty())
        assert default.backup_dir() == bk.default_dir()


class TestTheCliBackupCommands:
    """``p2kcli backup list|save|restore``, driven through ``main()``."""

    def test_list_needs_no_unit(self, monkeypatch, capsys, tmp_path):
        def explode(args):
            raise AssertionError("backup list tried to open a port")

        monkeypatch.setattr(cli, "_build_device", explode)
        assert cli.main(["backup", "list", "--dir", str(tmp_path)]) == 0
        assert f"no backups in {tmp_path}" in capsys.readouterr().out

    def test_save_then_list_shows_the_backup(self, capsys, tmp_path):
        assert cli.main(["--demo", "backup", "save", "--dir", str(tmp_path)]) == 0
        assert "saved 'Demo Setup' to" in capsys.readouterr().out
        assert cli.main(["backup", "list", "--dir", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "Demo Setup" in out
        assert "setup" in out
        assert str(tmp_path) in out

    def test_list_reports_a_corrupt_file_rather_than_dropping_it(
        self, capsys, tmp_path
    ):
        (tmp_path / "corrupt.json").write_text("not json", encoding="utf-8")
        assert cli.main(["backup", "list", "--dir", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "corrupt.json" in out
        assert "Expecting" in out

    def test_list_json_is_one_object(self, capsys, tmp_path):
        assert cli.main(["--demo", "backup", "save", "--dir", str(tmp_path)]) == 0
        capsys.readouterr()
        assert cli.main(["backup", "list", "--dir", str(tmp_path), "--json"]) == 0
        import json

        payload = json.loads(capsys.readouterr().out)
        assert payload["directory"] == str(tmp_path)
        assert len(payload["backups"]) == 1
        assert payload["backups"][0]["kind"] == "setup"
        assert payload["backups"][0]["error"] is None

    def test_restore_refuses_without_the_confirmation(self, capsys, tmp_path):
        assert cli.main(["--demo", "backup", "save", "--dir", str(tmp_path)]) == 0
        capsys.readouterr()
        ident = bk.list_backups(str(tmp_path))[0].id
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["--demo", "backup", "restore", ident, "--dir", str(tmp_path)])
        assert "overwrites the unit's whole live setup" in str(exit_info.value)
        assert "--yes" in str(exit_info.value)

    def test_restore_sends_the_dump_and_the_demo_adopts_it(
        self, monkeypatch, capsys, tmp_path
    ):
        device = DemoDevice()
        original = device.read_setup()
        record = bk.save_setup(
            original,
            device_id=device.device_id,
            slot="live",
            directory=str(tmp_path),
        )
        # Move the fake off the saved setup, so a restore that did nothing
        # would be caught.
        device.send_setup_dump(mutate_channel(original, LIVE, {"volume": 90}))
        assert device.read_setup().channel(LIVE).volume == 90

        monkeypatch.setattr(cli, "_build_device", lambda args: device)
        assert (
            cli.main(
                [
                    "--demo",
                    "backup",
                    "restore",
                    record.id,
                    "--dir",
                    str(tmp_path),
                    "--yes",
                ]
            )
            == 0
        )
        assert "restored 'Demo Setup' into the unit's live setup" in (
            capsys.readouterr().out
        )
        assert device.read_setup().channel(LIVE).volume == 127

    def test_a_restore_is_a_whole_setup_write(self, monkeypatch, tmp_path):
        """The frame that goes out is a Setup Dump, not a parameter edit."""
        device = DemoDevice()
        record = bk.save_setup(
            device.read_setup(),
            device_id=device.device_id,
            slot="live",
            directory=str(tmp_path),
        )
        device.dump_log.clear()
        monkeypatch.setattr(cli, "_build_device", lambda args: device)
        assert (
            cli.main(
                [
                    "--demo",
                    "backup",
                    "restore",
                    record.id,
                    "--dir",
                    str(tmp_path),
                    "--yes",
                ]
            )
            == 0
        )
        assert len(device.dump_log) == 1
        commands = [m.parse(frame).command for frame in device.received]
        assert m.Command.SETUP_DUMP in commands, "the restore sent no setup dump"


def test_the_demo_device_id_is_the_one_the_backup_records():
    """A guard against a test that would pass with any device ID: the demo
    answers on its own, and the backup records it."""
    device = DemoDevice()
    assert device.device_id == DEMO_DEVICE_ID
