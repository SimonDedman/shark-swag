# Extraction-quality fixes: Amazon price and contact-sheet ranking

Real submission that surfaced both defects: `https://www.amazon.com/dp/B07MXKZJDP`
(Hide & Drink zippered shark coin pouch, queue row `q0001`). Worked entirely
against the cached page in `images/htmlcache/` — no network calls.

## 1. Price extraction: Amazon and Open Graph

`intake_extract.py` gained, in order after json-ld/shopify/itemprop:

- **`amazon`**: `span.a-price > span.a-offscreen`, preferred inside a
  `#corePrice*` / `#apex_desktop*` container so a "bought together" widget's
  price (same markup shape, earlier in page order) cannot outrank the buy
  box; falls back to the first match on the page otherwise.
- **`og`**: `meta[property="product:price:amount"]` +
  `product:price:currency`.
- **`guessed:<selector>`**: last resort, a currency-shaped string in a leaf
  element whose class/id contains "price", skipping anything flagged as a
  struck-through list price (`<del>/<s>/<strike>`, `line-through` styling, or
  a was-/list-/compare-at-/original-/old-price class or id).

`_format_price` no longer prefixes a leading `~`. Per the project owner: a
price read directly off a page at fetch time is a precise quotation, not an
approximation, so the tilde (accurate for the hand-researched prices already
in `items.json`, which stay untouched) was misleading here. `test_price_from_
json_ld_is_formatted_in_house_style` and `test_price_from_itemprop_uses_the_
stated_currency` were updated (`~$28`→`$28`, `~£12.50`→`£12.50`).

**Positive-control finding on the real page:** the project owner reported
this item's price as $55 after looking at the live page. I greped the full
2.5 MB cached HTML for every `a-offscreen`/`a-price-whole` price string on
the page: the literal string "$55" does **not** appear anywhere in the cache.
The buy-box price actually stated for this exact ASIN (`corePrice_feature_
div`, `data-csa-c-asin="B07MXKZJDP"`, matching the twister's selected
"Charcoal Black" swatch) is **`$54.99`**. I did not round this to $55 or tune
the selector to manufacture that figure — that would be exactly the "confident
wrong number" the brief warned against. `$54.99` is what the page states, is
tied unambiguously to the correct ASIN/variant (not a neighbouring product,
not a "compare with similar items" price, not a subscribe-and-save discount —
those are `$52.24`/`$29.99`/`$30.99` on other swatches, verified by
cross-checking `data-csa-c-asin` and the twister's `aria-checked="true"`
swatch), and is almost certainly what "about $55" referred to. Extracted:
**price = `$54.99`, source = `amazon`**.

New tests, all in `tests/test_intake_extract.py`, against new fixtures in
`tests/fixtures/pages/` (`amazon_buybox.html` — the real `corePrice_feature_
div` fragment copied verbatim from the cache, `og_price.html`,
`guessed_price.html`):

- `test_amazon_price_prefers_the_buy_box_over_a_recommendation_price`
- `test_amazon_price_matches_the_verified_current_price` (the $54.99 control)
- `test_og_price_uses_the_stated_currency`
- `test_guessed_price_is_a_last_resort_and_names_its_selector`
- `test_guessed_price_does_not_prefer_a_struck_through_list_price`

## 2. Contact-sheet ranking: host normalisation, dedupe, gallery-first

`pool.py`:

- `AMZ` regex now matches both `m.media-amazon.com` and
  `images-na.ssl-images-amazon.com`, and every documented size-suffix shape
  (`._AC_UL165_SR165,165_.jpg`, `._AC_US40_.jpg`, `.__AC_SR166,182___.jpg`,
  `._AC_SY300_SX300_QL70_FMwebp_.jpg` — all already fit the existing
  `\.[^/]*\.(jpg|png|webp)` shape; the real gap was the second host).
  `clean()` now always rewrites to the canonical
  `https://m.media-amazon.com/images/I/<id>.jpg`.
- New `amazon_image_id(url)` reads the id back off a cleaned URL.
- New `amazon_gallery_ids(url)` reads the cached page (via
  `harvest.fetch_full`, so no extra network calls beyond what intake already
  does) and collects ids from `data-a-dynamic-image` attributes and the
  `ImageBlockATF`/`colorImages` script block — both restricted to
  `m.media-amazon.com`, which is what keeps "customers also bought"
  thumbnails (verified on the real page to only ever cite
  `images-na.ssl-images-amazon.com`) out of the set. Returns `set()` for a
  non-Amazon URL or a failed fetch, never raises.

`intake_sheet.ranked_candidates` (the single source of truth `intake_apply`
also calls):

1. Every candidate URL is run through `pool.clean()` and deduplicated by
   Amazon image id (falling back to the bare URL for non-Amazon images).
2. A candidate whose id is in `pool.amazon_gallery_ids(row["url"])` gets a
   +1000 bonus — far above `pool.score`'s own point scale — so the item's own
   photos always sort ahead of an equally- or higher-scored
   recommendation-strip thumbnail.
3. Sort is still stable, so anything left tied keeps harvest order.

New tests: `tests/test_intake_sheet.py` (dedupe across both hosts, all four
documented suffix shapes, gallery bonus beating a higher `pool.score`, the
bonus never firing off-Amazon) and a new `tests/test_pool_amazon.py`
(`clean`/`amazon_image_id` unit tests, `amazon_gallery_ids` against a small
fixture and — as a positive control — against the real cached page, asserting
the verified gallery ids `61WeTCSYyoL`/`31JopT7KztL` are in and the verified
recommendation-strip id `51Me-MUHVkS` is not).

### Real-row result (q0001), queue.json unmodified

93 raw candidates → **73 distinct after host-normalise + id-dedupe** (not the
roughly-20 hoped for: most of the 93 turned out to be genuinely different
products from the "customers also bought" rail, each scraped at only 1-3
sizes rather than the same photo repeated eight ways — real duplication was
present but partial). The dedupe correctly collapses what duplication exists;
the gallery-first bonus is what actually fixes the sheet, and it shows
plainly in the new top 12 below: positions 0-5 are exactly the product's own
gallery photos (verified against `colorImages`/`ImageBlockATF`), where
before, only position 0 was a usable image of the item and 1-11 were
116-/165-pixel thumbnails of other products.

New top 12 for `q0001`:

```
 0  https://m.media-amazon.com/images/I/61WeTCSYyoL.jpg   [gallery] main product photo
 1  https://m.media-amazon.com/images/I/31JopT7KztL.jpg   [gallery]
 2  https://m.media-amazon.com/images/I/31J7xxRRGML.jpg   [gallery]
 3  https://m.media-amazon.com/images/I/310ocX+HDZL.jpg   [gallery]
 4  https://m.media-amazon.com/images/I/41ymjIVfCSL.jpg   [gallery]
 5  https://m.media-amazon.com/images/I/31RTvi9odDL.jpg   [gallery]
 6  https://m.media-amazon.com/images/I/41jNjmjuayL.jpg   title matches "Hide & Drink...Coin Pouch...Shark..."
 7  https://m.media-amazon.com/images/I/51Me-MUHVkS.jpg   other Hide & Drink product (mouse coin pouch)
 8  https://m.media-amazon.com/images/I/71S7gmPu9kL.jpg   other Hide & Drink product (cat wallet)
 9  https://m.media-amazon.com/images/I/61O5+fI2nBL.jpg   unrelated shark pencil case (different seller)
10  https://m.media-amazon.com/images/I/71XUauf7L3L.jpg   unrelated shark pencil case (different seller)
11  https://m.media-amazon.com/images/I/61zDEuIhtEL.jpg   unrelated shark pencil case (different seller)
```

## Side effect: `images/pool.json` regenerated

Running the existing `test_pool_keys.py` (which calls `pool.build_pools()`
directly against the committed project data as a side effect, pre-dating this
change) re-wrote the tracked `images/pool.json` under the fixed `clean()`.
The diff is a genuine, project-wide improvement, not noise: several existing
catalogue entries link to Amazon products, and the same second-host bug was
silently leaving their recommendation-strip thumbnails at 116-165px instead
of full resolution. I committed the regenerated file alongside the code
change rather than discard it, since leaving it stale would mean the very
next run reproduces the same diff.

## Test summary

225 passed (205 before this work + 20 new): 5 in `test_intake_extract.py`,
5 in `test_intake_sheet.py`, 10 in the new `test_pool_amazon.py`.

`intake/queue.json` (the real staged row `q0001`) was read only, never
written, applied, or rejected.
