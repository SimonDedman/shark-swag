"""Unit tests for the Amazon-specific corrections to pool.clean and the new
pool.amazon_gallery_ids: extraction-quality defect #2 from a real submission
(https://www.amazon.com/dp/B07MXKZJDP), whose contact sheet was 93 candidates
that were almost all the same handful of photos repeated across two hosts and
a dozen sizes, with "customers also bought" thumbnails outranking the item's
own picture.
"""
from pathlib import Path

import pool

PAGES = Path(__file__).resolve().parent / "fixtures" / "pages"


def test_clean_normalises_the_canonical_host():
    url = "https://m.media-amazon.com/images/I/61WeTCSYyoL._AC_SL1500_.jpg"
    assert pool.clean(url) == "https://m.media-amazon.com/images/I/61WeTCSYyoL.jpg"


def test_clean_normalises_the_recommendation_strip_host():
    """images-na.ssl-images-amazon.com is the host pool.clean's original AMZ
    regex never matched, so every recommendation-strip thumbnail passed
    through uncleaned."""
    url = ("https://images-na.ssl-images-amazon.com/images/I/"
           "61WeTCSYyoL._AC_UL165_SR165,165_.jpg")
    assert pool.clean(url) == "https://m.media-amazon.com/images/I/61WeTCSYyoL.jpg"


def test_clean_handles_every_documented_suffix_shape():
    suffixes = [
        "._AC_UL165_SR165,165_.jpg",
        "._AC_US40_.jpg",
        ".__AC_SR166,182___.jpg",
        "._AC_SY300_SX300_QL70_FMwebp_.jpg",
    ]
    for suffix in suffixes:
        url = f"https://m.media-amazon.com/images/I/XID{suffix}"
        assert pool.clean(url) == "https://m.media-amazon.com/images/I/XID.jpg", suffix


def test_clean_leaves_a_non_amazon_url_alone():
    url = "https://shop.com/img/shark-socks-1200x.jpg"
    assert pool.clean(url) == url


def test_amazon_image_id_reads_back_a_cleaned_url():
    assert pool.amazon_image_id("https://m.media-amazon.com/images/I/ABC123.jpg") == "ABC123"


def test_amazon_image_id_is_none_for_a_non_amazon_url():
    assert pool.amazon_image_id("https://shop.com/img/x.jpg") is None


def test_gallery_ids_come_from_the_image_block_not_the_recommendation_strip(monkeypatch):
    html_text = (PAGES / "amazon_gallery.html").read_text()
    monkeypatch.setattr(pool.harvest, "fetch_full",
                        lambda url: (200, html_text, url, "cached"))
    ids = pool.amazon_gallery_ids("https://www.amazon.com/dp/TESTASIN")
    assert ids == {"AAAAAAAAAA1", "AAAAAAAAAA2", "AAAAAAAAAA3"}
    assert "BBBBBBBBBB1" not in ids


def test_gallery_ids_are_empty_for_a_non_amazon_url():
    assert pool.amazon_gallery_ids("https://shop.com/products/socks") == set()


def test_gallery_ids_are_empty_rather_than_raising_when_the_fetch_fails(monkeypatch):
    monkeypatch.setattr(pool.harvest, "fetch_full",
                        lambda url: (None, None, None, "exception: TimeoutError"))
    assert pool.amazon_gallery_ids("https://www.amazon.com/dp/TESTASIN") == set()


def test_gallery_ids_match_the_real_cached_page():
    """Positive control against the real cache for the submission that
    surfaced this defect: the product's own gallery ids are found, and none
    of the known recommendation-strip ids from that page leak in."""
    import harvest
    http, text, _final, _note = harvest.fetch_full("https://www.amazon.com/dp/B07MXKZJDP")
    assert http == 200, "requires the page already in images/htmlcache/"
    ids = pool.amazon_gallery_ids("https://www.amazon.com/dp/B07MXKZJDP")
    # The buy-box's own landing photo and its first alt-image, verified
    # (2026-08-29) against the cached page's ImageBlockATF/colorImages block.
    assert {"61WeTCSYyoL", "31JopT7KztL"} <= ids
    # A recommendation-strip thumbnail from the same cached page, verified to
    # sit only on images-na.ssl-images-amazon.com there, never in the gallery.
    assert "51Me-MUHVkS" not in ids
