#!/usr/bin/env python3
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

"""Import favourites from a plain-text listing into the favourites database.

The listing is the format written beside the user's own scanned printouts:
a bank header naming the catalog key in brackets, then one ``PC nnn`` line
per favourite. That file is deliberately the source of truth rather than a
report -- it is readable, editable by hand, and re-importable, so correcting
a misread mark means editing one line and running this again.

Nothing here reads a scan. Turning marks on paper into this listing is a
separate job; this only loads what that produced.

    python3 tools/import_favourites.py ~/path/to/Favourites.txt
    python3 tools/import_favourites.py --dry-run ~/path/to/Favourites.txt

Existing favourites are left alone unless ``--replace`` is given, and even
then only the banks the file mentions are cleared: a file covering four ROMs
must not silently delete favourites belonging to a fifth.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from p2k import favorites as fav  # noqa: E402

BANK = re.compile(r"\[([A-Z0-9]+-\d+)\]")
ENTRY = re.compile(r"^\s*PC\s+(\d+)\s+(.*?)\s*$")
NOTE = re.compile(r"\s*<--.*$")


def parse(path):
    """``[(bank_id, pc, name, uncertain)]`` from the listing."""
    out = []
    bank = None
    for lineno, line in enumerate(open(path, encoding="utf-8"), 1):
        found = BANK.search(line)
        if found:
            bank = found.group(1)
            continue
        entry = ENTRY.match(line)
        if not entry:
            continue
        if bank is None:
            raise SystemExit(
                f"{path}:{lineno}: a PC line before any bank header. Each "
                f"bank's entries must follow a header naming its catalog key "
                f"in brackets, e.g. [XLEAD2-1].")
        pc = int(entry.group(1))
        if not 0 <= pc <= 127:
            raise SystemExit(f"{path}:{lineno}: program change {pc} is "
                             f"outside 0-127")
        rest = entry.group(2)
        uncertain = "<--" in rest
        out.append((bank, pc, NOTE.sub("", rest).strip(), uncertain))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("listing")
    ap.add_argument("--favorites", default=None,
                    help="database path (default: the per-platform one)")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be imported and write nothing")
    ap.add_argument("--replace", action="store_true",
                    help="first clear existing favourites in the banks this "
                         "file mentions")
    ap.add_argument("--tag", default="",
                    help="tag to attach to every imported favourite")
    ap.add_argument("--skip-uncertain", action="store_true",
                    help="leave out marks the listing flags as faint")
    args = ap.parse_args(argv)

    rows = parse(args.listing)
    if args.skip_uncertain:
        rows = [r for r in rows if not r[3]]
    banks = sorted({r[0] for r in rows})
    flagged = sum(1 for r in rows if r[3])
    print(f"{len(rows)} favourite(s) across {len(banks)} bank(s) "
          f"in {os.path.basename(args.listing)}")
    if flagged:
        print(f"  {flagged} of them flagged faint in the listing")
    if args.dry_run:
        for bank in banks:
            n = [r for r in rows if r[0] == bank]
            print(f"  {bank:14s} {len(n):3d}  {[r[1] for r in n]}")
        print("dry run: nothing written")
        return 0

    path = args.favorites or fav.default_path()
    added = skipped = removed = nameless = 0
    with fav.Favorites(path) as store:
        if args.replace:
            for bank in banks:
                for pc in store.keys_for_bank(bank):
                    store.remove(bank, pc)
                    removed += 1
        for bank, pc, name, uncertain in rows:
            if store.get(bank, pc) is not None:
                skipped += 1
                continue
            tags = args.tag
            if uncertain:
                tags = ",".join(t for t in (tags, "check-scan") if t)
            if not name:
                # A PC line with nothing after the number. It parses, and a
                # blank label is indistinguishable in the browser from a
                # deliberately anonymous favourite -- so it is tagged and
                # counted rather than imported quietly. A truncated scan
                # looks exactly like this.
                nameless += 1
                tags = ",".join(t for t in (tags, "check-scan") if t)
            store.add(bank, pc, name=name, tags=tags)
            added += 1
        total = len(store)
    if removed:
        print(f"removed {removed} existing favourite(s) in those banks")
    print(f"added {added}, already present {skipped}")
    if nameless:
        print(f"{nameless} had no name on their line and are tagged "
              f"check-scan; a truncated scan looks like this")
    print(f"{total} favourite(s) now in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
