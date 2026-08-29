from pathlib import Path

import pytest

import intake_parse

MAIL = Path(__file__).resolve().parent / "fixtures" / "mail"


def load(name):
    return intake_parse.parse_message((MAIL / f"{name}.eml").read_bytes())


def test_bare_url_yields_one_url_and_an_empty_note():
    s = load("bare_url")
    assert s.urls == ["https://luckybugclothing.com/products/shark-onesie"]
    assert s.note == ""


def test_sender_and_date_are_captured():
    s = load("bare_url")
    assert s.sender == "Simon Dedman"
    assert s.date.startswith("2026-08-28T09:14:02")
    assert s.message_id == "bare1@mail.gmail.com"


def test_note_keeps_prose_and_drops_the_url_and_signature():
    s = load("link_plus_note")
    assert "proceeds go somewhere useful" in s.note
    assert "http" not in s.note
    assert "-- " not in s.note


def test_several_urls_are_kept_in_order_and_trailing_punctuation_stripped():
    s = load("multi_url")
    assert s.urls == ["https://example.com/a", "https://example.com/b",
                      "https://example.com/c"]


def test_a_message_with_no_url_still_parses():
    s = load("no_url")
    assert s.urls == []
    assert "advent calendar" in s.note


def test_forwarded_headers_and_quotes_are_stripped_from_the_note():
    s = load("forwarded")
    assert s.urls == ["https://www.sharktrustclothing.com/products/oceanic-31-tee"]
    assert "Forwarded message" not in s.note
    assert "shop@sharktrust.org" not in s.note
    assert "New organic cotton tees" not in s.note
    assert "Worth a look for the Youth band." in s.note


def test_html_only_message_yields_the_href():
    s = load("html_only")
    assert s.urls == ["https://shop.sheddaquarium.org/products/plush-shark"]
    assert "This one is lovely" in s.note


@pytest.mark.parametrize("raw,expected", [
    ("https://WWW.Example.COM/Products/Shark/",
     "https://example.com/Products/Shark"),
    ("https://example.com/p?utm_source=x&utm_medium=y",
     "https://example.com/p"),
    ("https://example.com/p?variant=4471#reviews",
     "https://example.com/p?variant=4471"),
    ("http://example.com/p?fbclid=abc&colour=blue",
     "http://example.com/p?colour=blue"),
])
def test_normalise_url(raw, expected):
    assert intake_parse.normalise_url(raw) == expected


def test_normalise_url_keeps_the_product_variant():
    """A Shopify variant is part of the identity of the thing being suggested;
    dropping it would merge two genuinely different items."""
    a = intake_parse.normalise_url("https://shop.com/p?variant=1")
    b = intake_parse.normalise_url("https://shop.com/p?variant=2")
    assert a != b
