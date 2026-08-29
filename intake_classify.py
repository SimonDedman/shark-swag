#!/usr/bin/env python3
"""Guess a section, subsection, and age band from a product title and a note.

Every guess carries the keyword that produced it, so a wrong one is traceable
to its rule. No rule firing leaves the field blank: an unclassified entry is a
visible question, whereas a default would be an invisible wrong answer.

The NGO host list is derived from section 6 of items.json rather than
hardcoded, so adding an organisation to the document teaches this too.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from entries import load_items

# Order matters: a book about snorkelling is a book, not equipment. And a cage
# diving *experience* is section 7, not section-4 dive gear, so 7 (whose
# keywords are specific: adopt/experience/advent/subscription/gift card/day
# out) is checked before 4's gear words.
#
# "dive"/"diving" is deliberately absent from section 4: against the 84 known
# entries it never once produced a correct hit (no SECTION_4_RULES subsection
# even mentions diving, so a match here could never resolve to a real
# subsection) and it wrongly grabbed four section-7 experiences ("Out to Sea
# Shark Dive", "Eye-to-Eye shark dive gift ticket", ...). "fins?" is narrowed
# to the plural: singular "fin" also matched the brand name "Fin Pin Shop" in
# three unrelated section-1/5 entries, with no true positive lost by requiring
# the plural (see task-7-report.md, Step 5).
SECTION_RULES = [
    ("3", r"\b(books?|isbn|paperback|hardcover|picture book|author|publisher|ebooks?|"
          r"activity book|colouring book|coloring book)\b"),
    ("7", r"\b(adopt\w*|experiences?|advent|subscriptions?|gift cards?|day out)\b"),
    ("4", r"\b(masks?|snorkel\w*|fins|wetsuits?|rash ?guards?|swim\w*|nets?|"
          r"binoculars?|microscopes?)\b"),
    ("5", r"\b(stickers?|colouring|coloring|crafts?|pencils?|stationery|posters?|"
          r"notebooks?)\b"),
    ("2", r"\b(plush|soft toys?|toys?|figures?|figurines?|puzzles?|lego|games?|"
          r"playsets?|chess)\b"),
    ("1", r"\b(tees?|t-shirts?|shirts?|onesies?|bodysuits?|socks?|hoodies?|hats?|"
          r"caps?|necklaces?|bracelets?|earrings?|jewell?ery|scarf|leggings)\b"),
]

AGE_RULES = [
    ("Baby & Toddler", r"\b(baby|babies|toddlers?|infants?|onesies?|bodysuits?|newborns?)\b"),
    ("Kids", r"\b(kids?|child|children|junior)\b"),
    ("Youth", r"\b(youth|teens?|teenagers?)\b"),
]

SECTION_4_RULES = [
    ("Mask, snorkel & fins sets", r"\b(masks?|snorkel\w*|fins)\b"),
    ("Rash guards, wetsuits & swim gear", r"\b(rash ?guards?|wetsuits?|swim\w*|suits?)\b"),
    ("Beach & rockpooling kit", r"\b(nets?|buckets?|rockpool\w*|beach|tide)\b"),
    ("Science & STEM kits", r"\b(kits?|microscopes?|experiments?|stem|science)\b"),
    ("Optics & tech", r"\b(binoculars?|cameras?|torch\w*|lights?|watch\w*|tech)\b"),
]

SECTION_7_RULES = [
    ("Advent calendars & seasonal", r"\b(advent|christmas|seasonal|stocking)\b"),
    ("Adoptions & subscriptions", r"\b(adopt\w*|subscriptions?|sponsor\w*|membership)\b"),
    ("Experiences", r"\b(experiences?|day out|dive|trip|tour|cage)\b"),
]


@dataclass
class Guess:
    section: str = ""
    sub: str = ""
    age: str = ""
    keyword: str = ""


@lru_cache(maxsize=1)
def _sections():
    return {s["number"]: s for s in load_items()["sections"]}


def valid_subs(section):
    s = _sections().get(str(section))
    return [sub["name"] for sub in s["subsections"]] if s else []


@lru_cache(maxsize=1)
def ngo_hosts():
    """Host to section 6 subsection name, read from the entries already filed
    under each organisation."""
    out = {}
    for sub in _sections()["6"]["subsections"]:
        for item in sub["items"]:
            host = urlsplit(item["link"]).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            out[host] = sub["name"]
    return out


def _first_match(rules, text):
    for label, pattern in rules:
        m = re.search(pattern, text, re.I)
        if m:
            return label, m.group(0).lower()
    return "", ""


_GENERIC_SUBDOMAINS = ("shop", "www", "store", "shopping")


def _brand(host):
    """The distinctive label in a domain: 'shop.sharktrust.org' -> 'sharktrust'.

    An organisation's merch may live on a domain that is not a subdomain of
    its own (a Teemill storefront named after it, a redirect, ...), so an
    exact-or-subdomain check on the recorded host alone misses it. Matching
    on this brand label, when it's long enough to be distinctive, catches
    'sharktrustclothing.com' as The Shark Trust's without hardcoding it.
    """
    labels = host.split(".")
    if len(labels) >= 2:
        labels = labels[:-1]  # drop the TLD
    while len(labels) > 1 and labels[0] in _GENERIC_SUBDOMAINS:
        labels = labels[1:]
    return labels[-1] if labels else host


def classify(title, note="", url=""):
    text = f"{title} {note}".strip()
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    for known_host, sub in ngo_hosts().items():
        if not host:
            break
        if host == known_host or host.endswith("." + known_host):
            return Guess(section="6", sub=sub, age=_age(text), keyword=f"host:{known_host}")
        brand = _brand(known_host)
        if len(brand) >= 5 and brand in host:
            return Guess(section="6", sub=sub, age=_age(text), keyword=f"host:{known_host}")

    section, keyword = _first_match(SECTION_RULES, text)
    if not section:
        return Guess()

    age = _age(text)
    if section == "4":
        sub, kind = _first_match(SECTION_4_RULES, text)
        return Guess(section=section, sub=sub, age=age, keyword=f"{keyword}|{kind}".strip("|"))
    if section == "7":
        sub, kind = _first_match(SECTION_7_RULES, text)
        return Guess(section=section, sub=sub, age=age, keyword=f"{keyword}|{kind}".strip("|"))

    sub = age if age in valid_subs(section) else ""
    return Guess(section=section, sub=sub, age=age, keyword=keyword)


def _age(text):
    label, _kw = _first_match(AGE_RULES, text)
    return label or "Adult"
