#!/usr/bin/env python3
"""Harvest candidate product images for every shark-swag entry.

Records HTTP status for every fetch so a block is never mistaken for an absence
(see ~/.claude/WEB-LOOKUPS.md). Only 200s are cached.
"""
import json, re, sys, time, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as creq
from bs4 import BeautifulSoup

ROOT = Path("/media/simon/data/Projects/shark-swag")
CACHE = ROOT / "images" / "htmlcache"
CACHE.mkdir(parents=True, exist_ok=True)
OUT = ROOT / "images" / "candidates.json"

IMPERSONATE = "chrome124"
JUNK = re.compile(r"(logo|icon|favicon|sprite|badge|payment|visa|mastercard|paypal|amex|"
                  r"placeholder|spinner|loading|pixel|1x1|blank|avatar|flag[-_]|social|"
                  r"instagram|facebook|twitter|tiktok|youtube|klarna|afterpay|shopify_pay)", re.I)


def fetch(url, timeout=30):
    """Return (status, text_or_None, note). Cache 200s only."""
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if key.exists():
        return 200, key.read_text(errors="replace"), "cached"
    try:
        r = creq.get(url, impersonate=IMPERSONATE, timeout=timeout,
                     headers={"Accept-Language": "en-US,en;q=0.9"})
    except Exception as e:
        return None, None, f"exception: {type(e).__name__}: {e}"
    if r.status_code == 200:
        key.write_text(r.text, errors="replace")
        return 200, r.text, "fetched"
    return r.status_code, None, f"http {r.status_code}"


def fetch_json(url, timeout=30):
    st, txt, note = fetch(url, timeout)
    if st != 200:
        return None, note
    try:
        return json.loads(txt), note
    except Exception as e:
        return None, f"not json ({e.__class__.__name__})"


def norm(src, base):
    if not src:
        return None
    src = src.strip()
    if src.startswith("data:"):
        return None
    if src.startswith("//"):
        src = "https:" + src
    return urljoin(base, src)


def from_srcset(val, base):
    """Pick the widest candidate. Splits on descriptors, not on commas -- Wix
    transform URLs contain commas (w_63,h_71,al_c) and a naive split breaks them."""
    best, bestw = None, -1
    for m in re.finditer(r"(\S+)(?:\s+(\d+(?:\.\d+)?)([wx]))?(?:\s*,\s*|\s*$)", val.strip()):
        u = norm(m.group(1), base)
        if not u:
            continue
        w = float(m.group(2)) if m.group(2) and m.group(3) == "w" else 0
        if w >= bestw:
            best, bestw = u, w
    return best


def normalise(u):
    """Rewrite CDN transform URLs to a form that returns a decodable JPEG/PNG.

    Wix and imgix both hand back AVIF regardless of Accept when the transform
    is baked into the path, so strip the transform / force the format.
    """
    if not u:
        return u
    m = re.match(r"(https://static\.wixstatic\.com/media/[^/]+\.(?:jpg|jpeg|png|gif))/v1/.*", u, re.I)
    if m:
        return m.group(1)
    if "imgix.net" in u:
        u = re.sub(r"[?&]auto=[^&]*", "", u)
        u += ("&" if "?" in u else "?") + "fm=jpg"
    u = re.sub(r"_(compact|small|medium|large|grande|master|\d{3,4}x\d{0,4})\.(jpg|jpeg|png)",
               r".\2", u)
    return u


def shopify_product(url):
    """Shopify /products/<handle> -> .json gives clean product images."""
    base = url.split("?")[0].rstrip("/")
    data, note = fetch_json(base + ".json")
    if not data or "product" not in data:
        return [], note
    p = data["product"]
    return [dict(url=i["src"], title=p.get("title", ""), src="shopify-product")
            for i in p.get("images", [])], "shopify-product"


def shopify_collection(url, limit=250):
    m = re.match(r"(https?://[^/]+)(/collections/[^/?#]+)?", url)
    if not m:
        return [], "no match"
    host, coll = m.group(1), m.group(2) or ""
    ep = f"{host}{coll}/products.json?limit={limit}"
    data, note = fetch_json(ep)
    if not data or "products" not in data:
        return [], note
    out = []
    for p in data["products"]:
        imgs = p.get("images") or []
        if not imgs:
            continue
        out.append(dict(url=imgs[0]["src"], title=p.get("title", ""),
                        ptype=p.get("product_type", ""), handle=p.get("handle", ""),
                        tags=p.get("tags", []), src="shopify-collection"))
    return out, f"shopify-collection ({len(out)} products)"


def scrape_html(url):
    st, html, note = fetch(url)
    if st != 200:
        return [], note
    soup = BeautifulSoup(html, "lxml")
    out, seen = [], set()

    def add(u, title, src):
        if not u or u in seen or JUNK.search(u):
            return
        seen.add(u)
        out.append(dict(url=u, title=(title or "").strip()[:120], src=src))

    # JSON-LD
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            blob = json.loads(tag.string or "{}")
        except Exception:
            continue
        stack = [blob]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
            elif isinstance(n, dict):
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
                img = n.get("image")
                if img:
                    for u in ([img] if isinstance(img, str) else img):
                        if isinstance(u, dict):
                            u = u.get("url")
                        if isinstance(u, str):
                            add(norm(u, url), n.get("name", ""), "json-ld")

    for prop in ("og:image", "og:image:secure_url", "twitter:image"):
        for meta in soup.find_all("meta", attrs={"property": prop}) + \
                    soup.find_all("meta", attrs={"name": prop}):
            add(norm(meta.get("content"), url), soup.title.string if soup.title else "", "meta")

    for img in soup.find_all("img"):
        u = None
        for attr in ("srcset", "data-srcset"):
            if img.get(attr):
                u = from_srcset(img[attr], url)
                break
        if not u:
            for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-image"):
                if img.get(attr):
                    u = norm(img[attr], url)
                    break
        title = img.get("alt") or img.get("title") or ""
        add(u, title, "img")
    return out, note


def harvest(url):
    cands, notes = [], []
    p = urlparse(url)
    if "/products/" in p.path:
        c, n = shopify_product(url)
        cands += c
        notes.append(n)
    if "/collections/" in p.path or p.path in ("", "/"):
        c, n = shopify_collection(url)
        cands += c
        notes.append(n)
    c, n = scrape_html(url)
    cands += c
    notes.append(n)
    # dedupe on url without query
    seen, out = set(), []
    for c in cands:
        c["url"] = normalise(c["url"])
        k = c["url"].split("?")[0]
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out, "; ".join(str(x) for x in notes)


def main():
    data = json.loads((ROOT / "items.json").read_text())
    entries = []
    for s in data["sections"]:
        for sub in s["subsections"]:
            for it in sub["items"]:
                entries.append(dict(section=s["number"], sub=sub["name"],
                                    item=it["item"], link=it["link"]))
    # the four entries already in the shared doc
    for item, link in [
        ("SPHYRNAS — tees, hoodies, hats, accessories", "https://www.sphyrnas.com/products"),
        ("Sharks Preschool Activity Book", "https://a.co/d/0aaGljoi"),
        ("Underwater Photography and Editing Ebooks", "https://www.gillianshark.com/ebooks"),
        ("Colouring & Facts Book (currently only available as PDF)",
         "https://www.gillianshark.com/colouring-book"),
    ]:
        entries.append(dict(section="EXISTING", sub="", item=item, link=link))

    results = {}
    urls = {}
    for i, e in enumerate(entries, 1):
        urls.setdefault(e["link"], []).append(i)
    print(f"{len(entries)} entries, {len(urls)} distinct URLs", flush=True)

    per_url = {}
    for j, (url, idxs) in enumerate(urls.items(), 1):
        t0 = time.time()
        cands, note = harvest(url)
        per_url[url] = dict(note=note, n=len(cands), candidates=cands[:60])
        print(f"[{j:2d}/{len(urls)}] {len(cands):3d} imgs  {note[:70]:70s}  {url[:60]}"
              f"  ({time.time()-t0:.1f}s)", flush=True)
        time.sleep(1.0)

    OUT.write_text(json.dumps(dict(entries=entries, per_url=per_url), indent=1))
    ok = sum(1 for v in per_url.values() if v["n"] > 0)
    print(f"\nURLs with >=1 candidate: {ok}/{len(urls)}  (empty: {len(urls)-ok})")
    for u, v in per_url.items():
        if v["n"] == 0:
            print(f"  EMPTY  {v['note'][:80]:80s}  {u}")


if __name__ == "__main__":
    main()
