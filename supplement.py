#!/usr/bin/env python3
"""Per-entry extra image sources for shops whose product grid is JS-rendered.

Teemill/Podos stores (Shark Trust Clothing, Save Our Seas) hide their catalogue
behind /omnis/v3/, and the Shark Trust Shopify shop needs filtering to reach the
art prints rather than the adoptions that dominate the collections page.
"""
import json, re
from pathlib import Path
from curl_cffi import requests as creq

ROOT = Path("/media/simon/data/Projects/shark-swag")


def get(url):
    r = creq.get(url, impersonate="chrome124", timeout=30)
    return r.status_code, r.text


def teemill(division, collection_id=None, limit=24):
    u = f"https://x/omnis/v3/division/{division}/products/?limit={limit}"
    return u, collection_id


def teemill_products(host, division, collection_id=None, limit=24):
    q = f"?limit={limit}" + (f"&collectionId={collection_id}" if collection_id else "")
    st, t = get(f"{host}/omnis/v3/division/{division}/products/{q}")
    if st != 200:
        return [], f"http {st}"
    try:
        data = json.loads(t)
    except Exception:
        return [], "not json"
    items = data["data"] if isinstance(data, dict) and "data" in data else data
    out = []
    for p in items:
        if p.get("image"):
            out.append(dict(url=re.sub(r"[?&]w=\d+", "?w=900", p["image"]),
                            title=p.get("name", ""), src="teemill"))
    return out, f"teemill {len(out)} products"


def shopify_products(host, path="", limit=250, keep=None):
    st, t = get(f"{host}{path}/products.json?limit={limit}")
    if st != 200:
        return [], f"http {st}"
    out = []
    for p in json.loads(t).get("products", []):
        title = p.get("title", "")
        if keep and not keep(title, p):
            continue
        imgs = p.get("images") or []
        if imgs:
            out.append(dict(url=imgs[0]["src"], title=title, src="shopify-filtered"))
    return out, f"shopify {len(out)} products"


def main():
    extras = {}
    log = []

    # 4  Shark Trust Clothing - kids collection (collectionId from /collections/<handle>/)
    c, n = teemill_products("https://sharktrustclothing.com", 3130, 415129)
    extras["4"] = c; log.append(("4", n))

    # 15 Shark Trust Clothing - whole store (adult clothing)
    c, n = teemill_products("https://sharktrustclothing.com", 3130)
    extras["15"] = c; log.append(("15", n))

    # 72 Save Our Seas Foundation shop
    c, n = teemill_products("https://shopsaveourseas.com", 442153)
    extras["72"] = c; log.append(("72", n))

    # 60 Shark Trust shop - art prints, not the adoptions that fill /collections
    c, n = shopify_products("https://shop.sharktrust.org", keep=lambda t, p:
                            re.search(r"print|oceanic|poster|art", t, re.I))
    extras["60"] = c; log.append(("60", n))

    # 62 Shark Trust shop - full range, deliberately mixed product types
    c, n = shopify_products("https://shop.sharktrust.org")
    extras["62"] = c; log.append(("62", n))

    # 68 Monterey Bay Aquarium - beyond plush, so the four are not all soft toys
    c, n = shopify_products("https://shop.montereybayaquarium.org")
    extras["68"] = c; log.append(("68", n))

    (ROOT / "images" / "extras.json").write_text(json.dumps(extras, indent=1))
    for k, n in log:
        print(f"  entry {k:>3s}: {n}")


if __name__ == "__main__":
    main()
