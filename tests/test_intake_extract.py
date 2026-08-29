from pathlib import Path

from bs4 import BeautifulSoup

import intake_extract

PAGES = Path(__file__).resolve().parent / "fixtures" / "pages"


def soup(name):
    return BeautifulSoup((PAGES / name).read_text(), "lxml")


def test_title_prefers_json_ld_name():
    assert intake_extract.extract_title(soup("jsonld_product.html")) == "Lemon Shark Onesie"


def test_title_falls_back_to_the_title_tag():
    assert intake_extract.extract_title(soup("itemprop_product.html")) == "Shark socks"


# --- Item title: Amazon's own <title> tag reads "Amazon.com: <name> :
# <category>", which is what would otherwise go verbatim into the shared
# document. #productTitle carries just the product name. ---

REAL_NAME = ("Hide & Drink, Zippered Coin Pouch, Shark Shaped Case, Stuffed Animal, "
             "Bank, Change Bag, Pencil Purse, Shark Shaped Cable Holder, Full Grain "
             "Leather, Handmade Wallet, Charcoal Black")


def test_title_prefers_amazon_producttitle_over_the_title_tag():
    assert intake_extract.extract_title(soup("amazon_producttitle.html")) == REAL_NAME


def test_title_tag_fallback_strips_amazon_prefix_and_category_suffix():
    """No #productTitle on the page: the <title> tag itself is
    "Amazon.com: <name> : Clothing, Shoes & Jewelry", and only the name
    should reach the document."""
    assert intake_extract.extract_title(soup("amazon_title_only.html")) == REAL_NAME


def test_price_from_json_ld_is_formatted_in_house_style():
    price, source = intake_extract.extract_price(soup("jsonld_product.html"),
                                                 "https://example.com/p")
    assert price == "$28"
    assert source == "json-ld"


def test_price_from_itemprop_uses_the_stated_currency():
    price, source = intake_extract.extract_price(soup("itemprop_product.html"),
                                                 "https://example.com/p")
    assert price == "£12.50"
    assert source == "itemprop"


def test_missing_price_is_blank_with_a_blank_source():
    assert intake_extract.extract_price(soup("bare.html"), "https://e.com/p") == ("", "")


def test_ngo_sentence_is_captured_verbatim():
    text = soup("jsonld_product.html").get_text(" ")
    assert intake_extract.extract_ngo(text) == \
        "10% of all lemon shark print sales go to Sharks4Kids."


def test_a_stated_absence_of_donation_is_still_captured():
    """The doc's NGO line says so when a shop states no donation, rather than
    leaving a reader to assume either way."""
    text = soup("itemprop_product.html").get_text(" ")
    assert "No donation is made" in intake_extract.extract_ngo(text)


def test_no_charity_wording_gives_an_empty_string():
    assert intake_extract.extract_ngo("Bamboo socks in three sizes.") == ""


def test_challenge_page_is_blocked_not_empty():
    html = (PAGES / "challenge.html").read_text()
    assert intake_extract.classify_status(200, html, "https://e.com/p", "https://e.com/p") \
        == "BLOCKED"


def test_403_and_429_are_blocked():
    assert intake_extract.classify_status(403, None, "https://e.com/p", None) == "BLOCKED"
    assert intake_extract.classify_status(429, None, "https://e.com/p", None) == "BLOCKED"


def test_404_is_dead():
    assert intake_extract.classify_status(404, None, "https://e.com/p", None) == "DEAD"


def test_a_redirect_to_the_site_root_is_dead():
    """padigear.com does exactly this: the product URL 302s to a shop home page
    that no longer carries the catalogue."""
    assert intake_extract.classify_status(
        200, "<html><title>PADI</title></html>",
        "https://www.padigear.com/products/great-white-baby-onesie",
        "https://www.padi.com/shop-online") == "DEAD"


def test_a_page_with_nothing_extractable_is_empty():
    assert intake_extract.classify_status(
        200, (PAGES / "bare.html").read_text(),
        "https://e.com/p", "https://e.com/p") == "EMPTY"


def test_a_good_page_is_ok():
    assert intake_extract.classify_status(
        200, (PAGES / "jsonld_product.html").read_text(),
        "https://e.com/p", "https://e.com/p") == "OK"


def test_an_exception_is_blocked_never_empty():
    """A connection that never completed proves nothing about the page. Calling
    it EMPTY would turn a network fault into a finding about the product."""
    assert intake_extract.classify_status(None, None, "https://e.com/p", None) == "BLOCKED"


def test_subdomain_consolidation_redirect_is_ok():
    """example.com -> shop.example.com is the same brand, not a dead link."""
    assert intake_extract.classify_status(
        200, (PAGES / "jsonld_product.html").read_text(),
        "https://example.com/products/x",
        "https://shop.example.com/products/x") == "OK"


def test_www_normalisation_redirect_is_ok():
    assert intake_extract.classify_status(
        200, (PAGES / "jsonld_product.html").read_text(),
        "https://www.example.com/products/x",
        "https://example.com/products/x") == "OK"


def test_country_domain_redirect_is_ok():
    """example.com -> example.co.uk is a country-TLD swap of the same brand."""
    assert intake_extract.classify_status(
        200, (PAGES / "jsonld_product.html").read_text(),
        "https://example.com/products/x",
        "https://example.co.uk/products/x") == "OK"


def test_http_to_https_same_host_redirect_is_ok():
    assert intake_extract.classify_status(
        200, (PAGES / "jsonld_product.html").read_text(),
        "http://example.com/products/x",
        "https://example.com/products/x") == "OK"


# --- Important 9: a minified page offers the sentence pattern no boundary to
# stop at, so an unguarded match glues unrelated text either side of the
# keyword and the result is copied verbatim into the shared document as a
# statement about where money goes. ---

def test_a_minified_page_does_not_manufacture_a_charity_claim():
    """Nav, breadcrumbs, bullet lists, and a shipping notice all end up inside
    one 'sentence' around the word conservation. It is not a sentence, and no
    claim is better than an invented one."""
    text = soup("minified.html").get_text(" ")
    assert intake_extract.extract_ngo(text) == ""


def test_a_run_of_lowercase_page_furniture_is_not_a_sentence():
    text = soup("minified_lowercase.html").get_text(" ")
    assert intake_extract.extract_ngo(text) == ""


def test_the_captured_sentence_is_capped_at_three_hundred_characters():
    long_sentence = ("Every purchase donates " + "money to the reef " * 30).strip() + "."
    assert len(long_sentence) > intake_extract.MAX_NGO_CHARS
    assert intake_extract.extract_ngo(long_sentence) == ""


def test_a_real_sentence_after_a_rejected_one_is_still_found():
    """Rejecting a glued run must not cost the genuine sentence behind it."""
    text = ("free shipping proceeds apply to all baskets. "
            "Ten per cent of every sale is donated to the Shark Trust.")
    assert intake_extract.extract_ngo(text) == \
        "Ten per cent of every sale is donated to the Shark Trust."


# --- Residual fix: a page with no whitespace between distinct nav/list nodes
# still has no punctuation between them once flattened, so a run of Title-Case
# fragments passed the old shape test (a bare capital letter) even though it
# holds no real sentence at all. ---

def test_a_glued_run_of_title_case_nav_fragments_is_not_a_sentence():
    """Reproduces the residual: a minified page with no whitespace between
    <nav> items, a promo div, and a shipping bullet, all Title-Case and none
    of it about where any money goes."""
    html = ('<nav><a>Shop all</a><a>Sale</a></nav><div>Our conservation partners</div>'
            '<ul><li>Free UK shipping over fifty pounds</li></ul><p>Printed on demand.</p>')
    text = BeautifulSoup(html, "lxml").get_text(" ")
    assert intake_extract.extract_ngo(text) == ""


def test_a_genuine_lowercase_sentence_is_captured():
    """A donation sentence with no capital letters at all is still a sentence;
    the shape test must not require capitalisation as evidence."""
    text = "ten per cent of proceeds go to sharks."
    assert intake_extract.extract_ngo(text) == "ten per cent of proceeds go to sharks."


# --- Important 4: a crashed image harvest and a page with no usable images
# both leave the Contact sheet cell blank, so extract() must not swallow the
# difference into a field nobody reads. ---

def test_a_crashed_image_harvest_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(intake_extract.harvest, "fetch_full",
                        lambda url: (200, (PAGES / "jsonld_product.html").read_text(),
                                     url, "fetched"))

    def boom(url):
        raise TimeoutError("read timed out")
    monkeypatch.setattr(intake_extract.harvest, "harvest", boom)

    facts = intake_extract.extract("https://example.com/products/x")
    assert facts.status == "OK"
    assert facts.candidates == []
    assert "IMAGE HARVEST FAILED" in facts.note
    assert "TimeoutError" in facts.note


def test_a_page_with_no_images_says_so_differently(monkeypatch):
    monkeypatch.setattr(intake_extract.harvest, "fetch_full",
                        lambda url: (200, (PAGES / "jsonld_product.html").read_text(),
                                     url, "fetched"))
    monkeypatch.setattr(intake_extract.harvest, "harvest",
                        lambda url: ([], "no candidates on the page"))
    facts = intake_extract.extract("https://example.com/products/x")
    assert facts.candidates == []
    assert "FAILED" not in facts.note
    assert "0 candidate(s)" in facts.note


# --- Amazon publishes none of json-ld, Shopify, or itemprop pricing, so a
# real submission (https://www.amazon.com/dp/B07MXKZJDP) came out with a
# blank price. ---

def test_amazon_price_prefers_the_buy_box_over_a_recommendation_price():
    """A 'bought together' widget's price sits in the very same
    span.a-price > span.a-offscreen shape and appears earlier in page order
    than the item's own price, so picking "the first match anywhere" would
    silently return someone else's price."""
    price, source = intake_extract.extract_price(soup("amazon_buybox.html"),
                                                 "https://www.amazon.com/dp/B07MXKZJDP")
    assert price == "$54.99"
    assert source == "amazon"


def test_amazon_price_matches_the_verified_current_price():
    """Positive control against the real cached page.

    The project owner reported this item's price as $55 after looking at the
    live page. The corePrice_feature_div fragment in this fixture is copied
    verbatim from images/htmlcache/ for this exact URL/ASIN, and the literal
    string "$55" does not occur anywhere in that cached HTML (checked by
    grep over the full 2.5 MB page, including every a-price-whole and
    a-offscreen span). The buy-box price actually stated for this ASIN is
    $54.99 - almost certainly what "about $55" referred to - and that is the
    number this test pins down, so a selector change cannot silently drift
    onto some other figure without this test naming the discrepancy.
    """
    price, source = intake_extract.extract_price(soup("amazon_buybox.html"),
                                                 "https://www.amazon.com/dp/B07MXKZJDP")
    assert price == "$54.99"
    assert source == "amazon"


def test_og_price_uses_the_stated_currency():
    price, source = intake_extract.extract_price(soup("og_price.html"),
                                                 "https://example.com/p")
    assert price == "£24.50"
    assert source == "og"


def test_guessed_price_is_a_last_resort_and_names_its_selector():
    price, source = intake_extract.extract_price(soup("guessed_price.html"),
                                                 "https://example.com/p")
    assert price == "$42"
    assert source == "guessed:#current-price"


def test_guessed_price_does_not_prefer_a_struck_through_list_price():
    """The struck $70 sits before the real $42 in document order; a naive
    first-match-in-a-'price'-element would return the list price."""
    price, _source = intake_extract.extract_price(soup("guessed_price.html"),
                                                 "https://example.com/p")
    assert price != "$70"
