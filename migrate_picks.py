#!/usr/bin/env python3
"""One-off: move picks.PICKS out of source and into images/picks.json, keyed by
entry id. Pool specs "P:15_01" become "P:e15_01"; the inline comments in the
source become a `note` field so the reasoning is not lost.
"""
import json
import re

import picks
from paths import PICKS_JSON
from entries import iter_entries

# The comments that sit beside individual entries in the current PICKS literal.
NOTES = {
    2: "PADI Gear storefront is JS-only",
    3: "first hit on the shop search; it is the octopus bodysuit, not a shark print",
    14: "Wix storefront is JS-only",
    42: "Amazon /images/P/<isbn> returns the wrong title for this one",
    66: "Wix storefront is JS-only",
}


def migrate_spec(spec):
    return re.sub(r"^P:(\d+)_", lambda m: f"P:e{int(m.group(1)):02d}_", spec)


def main():
    if PICKS_JSON.exists():
        print("images/picks.json already exists, nothing to do")
        return
    ids = {int(e.id[1:]): e.id for e in iter_entries()}
    out = {}
    for n, specs in sorted(picks.PICKS.items()):
        out[ids[n]] = dict(specs=[migrate_spec(s) for s in specs], note=NOTES.get(n, ""))
    missing = [e.id for e in iter_entries() if e.id not in out]
    for eid in missing:
        out[eid] = dict(specs=[], note="no pick recorded")
    PICKS_JSON.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out)} entries written to {PICKS_JSON}"
          f" ({len(missing)} had no PICKS entry)")


if __name__ == "__main__":
    main()
