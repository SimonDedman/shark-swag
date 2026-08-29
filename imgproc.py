#!/usr/bin/env python3
"""Download, auto-crop and normalise product images for the shark-swag docx."""
import hashlib, io
from pathlib import Path

from curl_cffi import requests as creq
from PIL import Image, ImageChops

ROOT = Path("/media/simon/data/Projects/shark-swag")
RAW = ROOT / "images" / "raw"
FIN = ROOT / "images" / "final"
RAW.mkdir(parents=True, exist_ok=True)
FIN.mkdir(parents=True, exist_ok=True)

TARGET_H = 420          # px; ~1.35 in at 300 dpi (8 lines of 10.5pt Calibri)


def download(url, referer=None):
    key = RAW / (hashlib.sha1(url.encode()).hexdigest() + ".bin")
    if key.exists() and key.stat().st_size > 1000:
        return key, "cached"
    # no avif/webp: several CDNs content-negotiate to a format PIL cannot read
    h = {"Accept": "image/jpeg,image/png,image/gif;q=0.9,*/*;q=0.5"}
    if referer:
        h["Referer"] = referer
    try:
        r = creq.get(url, impersonate="chrome124", timeout=45, headers=h)
    except Exception as e:
        return None, f"exception {type(e).__name__}"
    if r.status_code != 200:
        return None, f"http {r.status_code}"
    if len(r.content) < 1000:
        return None, f"tiny ({len(r.content)} bytes)"
    key.write_bytes(r.content)
    return key, "fetched"


def load(path):
    im = Image.open(path)
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    return im


def autocrop(im, tol=12, margin=0.02):
    """Trim a uniform border. Falls back to the original if the trim looks wrong."""
    w, h = im.size
    corners = [im.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    # only trim if the four corners agree (i.e. there really is a flat surround)
    r = [max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3)]
    if max(r) > 24:
        return im, "corners differ - no trim"
    bg = Image.new("RGB", im.size, corners[0])
    diff = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > tol else 0)
    box = diff.getbbox()
    if not box:
        return im, "blank after diff - no trim"
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw * bh < 0.05 * w * h or bw < 40 or bh < 40:
        return im, "trim too aggressive - no trim"
    mx, my = int(bw * margin), int(bh * margin)
    box = (max(0, box[0] - mx), max(0, box[1] - my),
           min(w, box[2] + mx), min(h, box[3] + my))
    out = im.crop(box)
    return out, f"trimmed {w}x{h} -> {out.size[0]}x{out.size[1]}"


def to_height(im, h=TARGET_H):
    ar = im.size[0] / im.size[1]
    return im.resize((max(1, round(h * ar)), h), Image.LANCZOS)


def prepare(url, out_name, referer=None):
    p, note = download(url, referer)
    if p is None:
        return None, note
    try:
        im = load(p)
    except Exception as e:
        return None, f"decode failed: {type(e).__name__}"
    if min(im.size) < 80:
        return None, f"too small {im.size}"
    im, tnote = autocrop(im)
    im = to_height(im)
    out = FIN / f"{out_name}.jpg"
    im.save(out, "JPEG", quality=90, subsampling=0)
    return out, f"{note}; {tnote}; final {im.size[0]}x{im.size[1]}"
