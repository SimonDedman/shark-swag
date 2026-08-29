#!/usr/bin/env python3
"""One-off: stamp a stable id onto every item in items.json.

Ids are assigned in the file's current order as e01, e02, ..., which is exactly
the numbering picks.py used positionally, so the existing images/final/eNN_n.jpg
filenames stay correct and no image is renamed. Refuses to renumber anything
that already carries an id.
"""
import json

from paths import ITEMS
import entries


def main():
    data = json.loads(ITEMS.read_text())
    already = [it["id"] for s in data["sections"] for sub in s["subsections"]
               for it in sub["items"] if "id" in it]
    if already:
        print(f"already migrated: {len(already)} items carry an id, nothing to do")
        return
    n = 0
    for section in data["sections"]:
        for sub in section["subsections"]:
            for i, item in enumerate(sub["items"]):
                n += 1
                sub["items"][i] = {"id": f"e{n:02d}", **item}
    entries.save_items(data)
    print(f"{n} items stamped e01..e{n:02d}")


if __name__ == "__main__":
    main()
