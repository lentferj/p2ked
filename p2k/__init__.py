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

"""Shared helpers for the protocol and data layer."""

from __future__ import annotations

__all__ = ["literal"]


def literal(text: str) -> str:
    """``text`` as Rich markup that renders as exactly itself.

    E-MU's specification is quoted in the UI, and its sentences carry
    brackets -- "receive[s] and understand[s] the old setup dump". Rich reads
    a ``[...]`` as a tag and eats it, silently turning a quotation into a
    paraphrase. Preset names can carry brackets too, so any name that is
    wrapped in markup (an italic for a ROM that is not fitted, say) has to be
    escaped first. A sentence quoted from a document has to render as the
    document wrote it.
    """
    return text.replace("[", "\\[")
