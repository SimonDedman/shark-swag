#!/usr/bin/env python3
"""Build a ranked candidate pool per entry, download it, and lay out contact sheets."""
import json, re, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, "/media/simon/data/Projects/shark-swag")
from imgproc import prepare, download, load, autocrop
from paths import POOL_DIR, SHEETS, CANDIDATES, EXTRAS, POOL_JSON, ROOT
from entries import iter_entries

for p in (POOL_DIR, SHEETS):
    p.mkdir(parents=True, exist_ok=True)

BAD = re.compile(r"\.svg($|\?)|/sash/|kindle|QR-store|books-voyager|nav[-_]|/G/01/|"
                 r"transparent-pixel|grey-pixel|fls-na|frontend-static|heart-outline|"
                 r"cover\.\d+\.\d+x\d+|_CB\d|prime|smile|associates", re.I)
AMZ = re.compile(r"(https://m\.media-amazon\.com/images/I/[A-Za-z0-9+%\-]+)\.[^/]*\.(jpg|png|webp)", re.I)


def clean(url):
    """Normalise Amazon size-suffixed URLs up to full resolution."""
    m = AMZ.match(url)
    if m:
        return f"{m.group(1)}.jpg"
    return url


def score(c, entry_words):
    s = 0
    src = c["src"]
    s += {"shopify-product": 60, "shopify-collection": 50, "json-ld": 40, "meta": 35, "img": 10}.get(src, 0)
    t = (c.get("title") or "").lower()
    if t:
        hits = sum(1 for w in entry_words if len(w) > 3 and w in t)
        s += 8 * hits
    if re.search(r"1200x|_SL\d{3,}|2400|_AC_|large|master", c["url"]):
        s += 5
    return s


def build_pools():
    """Rank each entry's candidates, keyed by the entry's stable id.

    Candidate URLs come from candidates.json, which is keyed by product URL, so
    entry order in that file is irrelevant here.
    """
    d = json.loads(CANDIDATES.read_text())
    extras = json.loads(EXTRAS.read_text()) if EXTRAS.exists() else {}
    pools = {}
    for e in iter_entries():
        v = d["per_url"][e.link]
        words = set(re.findall(r"[a-z]{4,}", e.item.lower()))
        cands, seen = [], set()
        # supplementary sources first: they are catalogue products, not page furniture
        for c in extras.get(e.id, []):
            u = clean(c["url"])
            if u.split("?")[0] in seen:
                continue
            seen.add(u.split("?")[0])
            cands.append(dict(url=u, title=c.get("title", ""), src=c["src"], score=999))
        for c in v["candidates"]:
            u = clean(c["url"])
            if BAD.search(u):
                continue
            k = u.split("?")[0]
            if k in seen:
                continue
            seen.add(k)
            cands.append(dict(url=u, title=c.get("title", ""), src=c["src"],
                              score=score(c, words)))
        cands.sort(key=lambda c: -c["score"])
        pools[e.id] = dict(item=e.item, link=e.link, section=e.section,
                           sub=e.sub, cands=cands[:24])
    POOL_JSON.write_text(json.dumps(pools, indent=1))
    return pools


def fetch_pool(pools, workers=8):
    jobs = []
    for k, v in pools.items():
        for j, c in enumerate(v["cands"]):
            jobs.append((f"{k}_{j:02d}", c["url"], v["link"]))
    print(f"{len(jobs)} images to fetch")
    results = {}

    def work(job):
        name, url, ref = job
        out = POOL_DIR / f"{name}.jpg"
        if out.exists():
            return name, "cached"
        p, note = download(url, referer=ref)
        if p is None:
            return name, note
        try:
            im = load(p)
        except Exception as ex:
            return name, f"decode {type(ex).__name__}"
        if min(im.size) < 90:
            return name, f"small {im.size}"
        im, _ = autocrop(im)
        ar = im.size[0] / im.size[1]
        im.resize((max(1, round(300 * ar)), 300), Image.LANCZOS).save(out, "JPEG", quality=88)
        return name, "ok"

    with ThreadPoolExecutor(workers) as ex:
        for name, note in ex.map(work, jobs):
            results[name] = note
    ok = sum(1 for v in results.values() if v in ("ok", "cached"))
    print(f"usable: {ok}/{len(jobs)}")
    fails = {}
    for n, v in results.items():
        if v not in ("ok", "cached"):
            fails[v.split(" ")[0]] = fails.get(v.split(" ")[0], 0) + 1
    print("failure modes:", fails)
    (ROOT / "images" / "pool_fetch.json").write_text(json.dumps(results, indent=1))
    return results


def sheets(pools, per_sheet=3, cols=12):
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except Exception:
        font = small = ImageFont.load_default()
    CELL, HDR = 190, 34
    keys = sorted(pools, key=lambda k: int(k[1:]))
    n = 0
    for s in range(0, len(keys), per_sheet):
        chunk = keys[s:s + per_sheet]
        rows = len(chunk)
        W = cols * CELL + 20
        H = rows * (CELL + HDR + 24) + 20
        sheet = Image.new("RGB", (W, H), (250, 250, 250))
        dr = ImageDraw.Draw(sheet)
        y = 10
        for k in chunk:
            v = pools[k]
            dr.text((10, y), f"[{k}] {v['item'][:100]}", fill=(0, 0, 0), font=font)
            y += HDR
            x = 10
            for j in range(cols):
                p = POOL_DIR / f"{k}_{j:02d}.jpg"
                dr.rectangle([x, y, x + CELL - 6, y + CELL - 6], outline=(200, 200, 200))
                dr.text((x + 3, y + CELL - 4), str(j), fill=(120, 120, 120), font=small)
                if p.exists():
                    im = Image.open(p)
                    im.thumbnail((CELL - 12, CELL - 12))
                    sheet.paste(im, (x + 3 + (CELL - 12 - im.size[0]) // 2,
                                     y + 3 + (CELL - 12 - im.size[1]) // 2))
                x += CELL
            y += CELL + 24
        out = SHEETS / f"sheet{n:02d}.jpg"
        sheet.save(out, "JPEG", quality=88)
        n += 1
    print(f"{n} sheets -> {SHEETS}")


if __name__ == "__main__":
    pools = build_pools()
    fetch_pool(pools)
    sheets(pools)
