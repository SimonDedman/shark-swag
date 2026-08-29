#!/usr/bin/env python3
"""Stable entry identity for the shark-swag pipeline.

Every entry carries an `id` stored in the data: in items.json for researched
entries, in existing.json for the four that were already in the shared Google
Doc. Ids are assigned once, when an entry joins the list, and are never
renumbered or reused. Image filenames in images/final/ and the keys of
images/picks.json derive from them, so a renumber would silently pair every
later entry with the wrong picture.
"""
import copy
import json
import re
from dataclasses import dataclass

from paths import ITEMS, EXISTING_JSON, PICKS_JSON

ID_RE = re.compile(r"^e(\d{2,})$")


@dataclass
class Entry:
    id: str
    section: str
    sub: str
    item: str
    link: str
    age: str = ""
    price: str = ""
    desc: str = ""
    by: str = ""
    ngo: str = ""
    existing: bool = False


def load_items():
    return json.loads(ITEMS.read_text())


def save_items(data):
    """Write items.json keeping one item object per line, as the file already is.

    json.dumps(indent=2) would explode every item across eight lines and turn a
    one-item change into an unreadable diff.
    """
    d = copy.deepcopy(data)
    blobs = []
    for section in d["sections"]:
        for sub in section["subsections"]:
            for i, item in enumerate(sub["items"]):
                blobs.append(json.dumps(item, ensure_ascii=False))
                sub["items"][i] = f"\x00{len(blobs) - 1}\x00"
    text = json.dumps(d, indent=2, ensure_ascii=False)
    for n, blob in enumerate(blobs):
        text = text.replace(json.dumps(f"\x00{n}\x00"), blob)
    ITEMS.write_text(text + "\n")


def load_existing():
    return json.loads(EXISTING_JSON.read_text())


def iter_entries(data=None, include_existing=True):
    data = data if data is not None else load_items()
    out = []
    for section in data["sections"]:
        for sub in section["subsections"]:
            for item in sub["items"]:
                out.append(Entry(
                    id=item["id"], section=section["number"], sub=sub["name"],
                    item=item["item"], link=item["link"], age=item.get("age", ""),
                    price=item.get("price", ""), desc=item.get("desc", ""),
                    by=item.get("by", "Simon Dedman (web search)"),
                    ngo=item.get("ngo", "")))
    if include_existing:
        for e in load_existing():
            out.append(Entry(
                id=e["id"], section=e["section"], sub=e["sub"], item=e["item"],
                link=e["link"], age=e.get("age", ""), price=e.get("price", ""),
                desc=e.get("desc", ""), by=e.get("by", ""), ngo=e.get("ngo", ""),
                existing=True))
    return out


def id_num(entry_id):
    m = ID_RE.match(entry_id)
    if not m:
        raise ValueError(f"malformed entry id: {entry_id!r}")
    return int(m.group(1))


def retired_ids():
    """Ids that have been issued but are no longer in items.json or existing.json.

    Deleting an item is a normal editorial act, and images/picks.json keeps its
    key afterwards, as do the files in images/final/. Reading the picks keys is
    what stops a deletion freeing an id for reuse: reissuing one would pair a
    new entry with the deleted entry's pictures. Read as JSON rather than via
    picks.py, which loads the whole pool at import time.
    """
    if not PICKS_JSON.exists():
        return set()          # nothing has been picked yet; not the same as unreadable
    picks = json.loads(PICKS_JSON.read_text())
    return {k for k in picks if ID_RE.match(k)}


def next_id(data=None):
    issued = {e.id for e in iter_entries(data)} | retired_ids()
    return f"e{max(id_num(i) for i in issued) + 1:02d}"


def entry_by_id(entry_id, data=None):
    for e in iter_entries(data):
        if e.id == entry_id:
            return e
    return None
