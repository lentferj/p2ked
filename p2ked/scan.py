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

"""The whole-device name scan: the offer, and its progress.

Two screens and no MIDI: the app owns the worker and the wire, and these
only ask and report. That keeps the rule the rest of the tree keeps -- the
main thread does not touch a port -- and lets the offer and the progress be
tested without a unit.

A scan is **read-only**. It is the same Generic Name Request `r` sends,
one bank at a time: nothing is selected, nothing is written, nothing makes
a sound. There is no gate and no ``--yes`` for that reason.
"""

from __future__ import annotations

import contextlib
import threading
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Static

__all__ = ["ScanOffer", "ScanOfferScreen", "ScanScreen"]

#: The offer's three answers. Plain strings rather than an enum: they cross
#: a screen boundary as a value, and there is nothing to serialise.
ScanOffer = str  # "scan" | "later" | "never"


class ScanOfferScreen(ModalScreen[ScanOffer]):
    """Offer to scan the device when there is no name catalog at all.

    Three answers rather than a yes/no, because "no" and "never again" are
    different, and only one of them should stop the question coming back.
    """

    BINDINGS: ClassVar[list] = [
        ("y", "scan", "Scan"),
        ("n", "later", "Not now"),
        ("d", "never", "Don't ask again"),
        ("escape", "later", "Not now"),
    ]

    DEFAULT_CSS = """
    ScanOfferScreen {
        align: center middle;
    }
    #scan-offer {
        width: 72;
        height: auto;
        border: solid $primary;
        padding: 1 2;
    }
    #scan-offer-prompt {
        height: auto;
        padding: 1;
    }
    #scan-offer-buttons {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    """

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt_text = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="scan-offer"):
            yield Static(self.prompt_text, id="scan-offer-prompt")
            with Horizontal(id="scan-offer-buttons"):
                yield Button("Scan", variant="primary", id="scan")
                yield Button("Not now", id="later")
                yield Button("Don't ask again", id="never")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "later")

    def action_scan(self) -> None:
        self.dismiss("scan")

    def action_later(self) -> None:
        self.dismiss("later")

    def action_never(self) -> None:
        self.dismiss("never")


class ScanScreen(ModalScreen[None]):
    """Progress for a whole-device scan, with a Cancel button.

    The worker lives in the app; this shows what it reports and raises a
    flag when the user cancels. The flag is checked between banks -- a read
    in flight is not interrupted -- so cancelling is honest about stopping
    at the next boundary rather than mid-message.
    """

    BINDINGS: ClassVar[list] = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ScanScreen {
        align: center middle;
    }
    #scan-dialog {
        width: 72;
        height: auto;
        border: solid $primary;
        padding: 1 2;
    }
    #scan-title {
        height: auto;
        padding: 1;
    }
    #scan-line {
        height: auto;
        padding: 0 1;
    }
    #scan-buttons {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    """

    def __init__(self, cancel: threading.Event) -> None:
        super().__init__()
        self._cancel = cancel
        self._cancelled = False
        #: The latest line, kept here as well as on screen: the worker can
        #: report progress before this screen has composed, and a query for a
        #: widget that is not there yet must not raise.
        self._line = "starting..."

    def compose(self) -> ComposeResult:
        with Vertical(id="scan-dialog"):
            yield Static("[b]Scanning the device[/b]", id="scan-title")
            yield Static(self._line, id="scan-line")
            with Horizontal(id="scan-buttons"):
                yield Button("Cancel", id="cancel")

    def set_progress(self, line: str) -> None:
        """Main thread. What the worker wants shown. Safe before mount."""
        self._line = line
        with contextlib.suppress(NoMatches):
            self.query_one("#scan-line", Static).update(line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        """Raise the flag; the scan stops at the next bank boundary."""
        if self._cancelled:
            return
        self._cancelled = True
        self._cancel.set()
        self.set_progress("cancelling - stopping after this bank...")
        with contextlib.suppress(NoMatches):
            self.query_one("#cancel", Button).disabled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled
