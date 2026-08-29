#!/usr/bin/env python3
"""Render the chosen image per entry at the size the docx embeds.

Specs live in images/picks.json, keyed by entry id: "P:<pool_key>" reuses a
pool candidate, "U:<url>" is a source the pool missed, and an optional
"|crop=l,t,r,b" gives fractional crop bounds applied before the automatic
padding trim. An empty spec list means the entry was looked at and has no
usable image, which is not the same as an entry nobody has reached yet.
"""
import json
import sys

from PIL import Image

from paths import PICKS_JSON, POOL_JSON, FINAL
from imgproc import download, load, autocrop, to_height, TARGET_H

POOL = json.loads(POOL_JSON.read_text())


def load_picks():
    return json.loads(PICKS_JSON.read_text())


def save_picks(data):
    PICKS_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def resolve(spec):
    body, _, opts = spec.partition("|")
    crop = None
    for o in opts.split("|"):
        if o.startswith("crop="):
            crop = [float(x) for x in o[5:].split(",")]
    kind, _, val = body.partition(":")
    if kind == "P":
        k, j = val.rsplit("_", 1)
        return POOL[k]["cands"][int(j)]["url"], POOL[k]["link"], crop
    return val, None, crop


def render(entry_id, specs):
    """Write images/final/<entry_id>_<n>.jpg for each spec. Returns the names
    written; a spec that could not be fetched is skipped and reported."""
    written, failures = [], []
    for n, spec in enumerate(specs):
        url, referer, crop = resolve(spec)
        p, note = download(url, referer=referer)
        if p is None:
            failures.append((entry_id, n, note, url))
            continue
        im = load(p)
        if crop:
            w, h = im.size
            im = im.crop((int(crop[0] * w), int(crop[1] * h),
                          int(crop[2] * w), int(crop[3] * h)))
        im, _ = autocrop(im)
        im = to_height(im, TARGET_H)
        name = f"{entry_id}_{n}.jpg"
        im.save(FINAL / name, "JPEG", quality=92, subsampling=0)
        written.append(name)
    return written, failures


def main(only=None):
    picks = load_picks()
    written, failures = [], []
    for entry_id, rec in sorted(picks.items()):
        if only and entry_id not in only:
            continue
        w, f = render(entry_id, rec["specs"])
        written += w
        failures += f
    print(f"{len(written)} images written, {len(failures)} failed")
    for f in failures:
        print("   ", f)
    empty = [k for k, v in picks.items() if not v["specs"]]
    print("entries deliberately without an image:", empty)


if __name__ == "__main__":
    main(only=set(sys.argv[1:]) or None)
