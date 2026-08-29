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


def test_price_from_json_ld_is_formatted_in_house_style():
    price, source = intake_extract.extract_price(soup("jsonld_product.html"),
                                                 "https://example.com/p")
    assert price == "~$28"
    assert source == "json-ld"


def test_price_from_itemprop_uses_the_stated_currency():
    price, source = intake_extract.extract_price(soup("itemprop_product.html"),
                                                 "https://example.com/p")
    assert price == "~£12.50"
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
