#!/usr/bin/env python3
"""Product page to the facts an entry needs, with each fact's provenance.

Nothing here infers or paraphrases. A price is the number the page states; the
NGO line is a sentence copied verbatim. A fetch that was blocked is reported as
blocked, never as an absence of information about the product, because those
two lead to opposite decisions.
"""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

import harvest

CHALLENGE = re.compile(
    r"just a moment|cf-browser-verification|captcha|access denied|"
    r"unusual traffic|are you a robot|enable javascript and cookies", re.I)

NGO_KEYWORD = (r"(?:donat\w*|proceeds|charitable|charity|conservation|"
               r"non-?profit|nonprofit|foundation|\d{1,3}\s?%\s+of)")
NGO_SENTENCE = re.compile(rf"[^.!?\n]*\b{NGO_KEYWORD}\b[^.!?\n]*[.!?]", re.I)

# A "sentence" longer than this is not one. On a page with no whitespace
# between tags there are almost no sentence boundaries in the extracted text,
# so the pattern can run from a nav menu, through the keyword, into an
# unrelated paragraph, and the glued result is then copied verbatim into the
# shared document as a factual statement about where money goes.
MAX_NGO_CHARS = 300

SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "AUD": "AUD ", "CAD": "CAD "}

# Common two-label public suffixes. No public-suffix library is installed
# (and none should be added for this); this covers the shapes seen in
# practice. Anything else falls back to the standard second-from-last label.
TWO_PART_SUFFIXES = {"co.uk", "com.au", "co.nz", "co.za", "com.br", "co.jp", "co.in"}


def _brand(netloc):
    """The registrable-domain label, e.g. shop.example.com -> example.

    Strips a leading www. and a trailing port, then takes the label
    immediately before the public suffix, so subdomain and www redirects and
    a same-brand country-TLD swap (example.com <-> example.co.uk) compare
    equal, while a redirect to a genuinely different site (padigear.com vs
    padi.com) does not.
    """
    host = (netloc or "").split(":", 1)[0].lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_PART_SUFFIXES:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return host


@dataclass
class Facts:
    url: str
    status: str = "EMPTY"
    http: int = None
    title: str = ""
    price: str = ""
    price_source: str = ""
    ngo_text: str = ""
    note: str = ""
    candidates: list = field(default_factory=list)


def _jsonld(soup):
    """Every JSON-LD node on the page, flattened."""
    out = []
    for tag in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
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
                out.append(n)
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
    return out


def extract_title(soup):
    for node in _jsonld(soup):
        if node.get("@type") in ("Product", "Book") and node.get("name"):
            return str(node["name"]).strip()
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def _format_price(amount, currency):
    try:
        value = float(str(amount).replace(",", ""))
    except (TypeError, ValueError):
        return ""
    text = f"{value:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    sym = SYMBOL.get((currency or "USD").upper(), (currency or "").upper() + " ")
    return f"~{sym}{text}"


def extract_price(soup, url):
    """Returns (price, source). Source is one of json-ld, shopify, itemprop, ''."""
    for node in _jsonld(soup):
        offers = node.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if isinstance(offers, dict) and offers.get("price"):
            p = _format_price(offers["price"], offers.get("priceCurrency"))
            if p:
                return p, "json-ld"

    if "/products/" in urlsplit(url).path:
        data, _note = harvest.fetch_json(url.split("?")[0].rstrip("/") + ".json")
        variants = (data or {}).get("product", {}).get("variants") or []
        if variants and variants[0].get("price"):
            p = _format_price(variants[0]["price"], "USD")
            if p:
                return p, "shopify"

    meta = soup.find("meta", attrs={"itemprop": "price"})
    if meta and meta.get("content"):
        cur = soup.find("meta", attrs={"itemprop": "priceCurrency"})
        p = _format_price(meta["content"], cur.get("content") if cur else None)
        if p:
            return p, "itemprop"
    return "", ""


# The closed-class scaffolding of an English clause: prepositions, articles,
# conjunctions, copulas. Common to virtually every real sentence, and, on
# their own, incapable of asserting anything.
_FUNCTION_WORDS = {
    "a", "an", "the", "of", "to", "in", "on", "for", "from", "by", "with",
    "at", "as", "is", "are", "was", "were", "be", "been", "being", "and",
    "or", "but", "if", "so", "no", "not", "all", "some", "any", "each",
    "every", "this", "that", "these", "those", "it", "its", "per", "over",
    "under", "into", "onto", "upon", "up", "out",
}

_WORD = re.compile(r"[A-Za-z][\w'-]*")


def _glued_content_before_keyword(prefix):
    """Two words in a row that are neither function words, sitting right
    before the keyword, is the fingerprint of an unrelated fragment glued on
    ahead of the donation clause by tag-stripping: "free shipping" ahead of
    "proceeds ...". A single content word before the keyword, or one braided
    with real function words ("ten per cent of proceeds..."), reads as the
    ordinary run-up to a sentence and is let through.
    """
    prev_content = False
    for word in _WORD.findall(prefix):
        content = word.lower() not in _FUNCTION_WORDS
        if content and prev_content:
            return True
        prev_content = content
    return False


def _title_case_fragment_count(candidate):
    """How many separate runs of consecutive Title-Case words the candidate
    holds. A nav menu glued onto a keyword by tag-stripping reads as several
    short capitalised fragments with nothing but whitespace between them
    ("Shop all Sale Our conservation partners Free UK shipping ..."); a real
    sentence has at most a capitalised opening word and one proper noun.
    """
    runs = 0
    in_run = False
    for word in _WORD.findall(candidate):
        if word[0].isupper():
            if not in_run:
                runs += 1
            in_run = True
        else:
            in_run = False
    return runs


def _sentence_shaped(candidate):
    """Does this run of text hold one real clause, rather than page furniture
    glued together because a minified page offered no sentence boundary to
    stop at?

    Two checks, each aimed at a different way tag-stripping glues unrelated
    text onto the keyword: a run of Title-Case fragments (nav labels, menu
    items) with no punctuation between them, and a pair of ordinary content
    words sitting immediately ahead of the keyword with no preposition,
    article, or conjunction between them and it. Neither check cares whether
    the candidate is capitalised, so a genuine lowercase sentence ("ten per
    cent of proceeds go to sharks.") is judged on the same terms as a
    capitalised one.
    """
    if _title_case_fragment_count(candidate) >= 3:
        return False
    match = re.search(NGO_KEYWORD, candidate, re.I)
    prefix = candidate[:match.start()] if match else candidate
    return not _glued_content_before_keyword(prefix)


def extract_ngo(text):
    """The first sentence that talks about money going somewhere, verbatim.

    A statement that no donation is made is as useful as one that says there is,
    so both are kept. A candidate that is too long to be a sentence, or that
    shows no sign of being prose, is passed over rather than trimmed: this
    string is copied into the shared document unaltered, so a half-quote would
    be worse than no quote. Finding nothing leaves an empty cell, which is not
    a claim either way.
    """
    # Collapse runs of spaces/tabs but keep newlines: the pattern's [^.!?\n]*
    # relies on \n as a block boundary between unrelated page text (e.g. the
    # <title>) and the paragraph that follows it.
    flat = re.sub(r"[ \t]+", " ", text or "")
    for m in NGO_SENTENCE.finditer(flat):
        candidate = m.group(0).strip()
        if len(candidate) > MAX_NGO_CHARS or not _sentence_shaped(candidate):
            continue
        return candidate
    return ""


def classify_status(http, text, requested, final):
    if http is None:
        return "BLOCKED"
    if http in (401, 403, 429, 503):
        return "BLOCKED"
    if http in (404, 410):
        return "DEAD"
    if http != 200:
        return "BLOCKED"
    if text and CHALLENGE.search(text[:4000]):
        return "BLOCKED"
    if final:
        req = urlsplit(requested)
        fin = urlsplit(final)
        if req.path.strip("/") and (_brand(fin.netloc) != _brand(req.netloc) or not fin.path.strip("/")):
            return "DEAD"
    soup = BeautifulSoup(text or "", "lxml")
    if not extract_title(soup) and not extract_price(soup, requested)[0]:
        return "EMPTY"
    return "OK"


def extract(url):
    http, text, final, note = harvest.fetch_full(url)
    status = classify_status(http, text, url, final)
    facts = Facts(url=url, status=status, http=http, note=note)
    if status in ("BLOCKED", "DEAD"):
        return facts
    soup = BeautifulSoup(text or "", "lxml")
    facts.title = extract_title(soup)
    facts.price, facts.price_source = extract_price(soup, url)
    facts.ngo_text = extract_ngo(soup.get_text(" "))
    try:
        facts.candidates, cnote = harvest.harvest(url)
        facts.note = f"{note}; images: {cnote} ({len(facts.candidates)} candidate(s))"[:400]
    except Exception as e:
        # A crashed harvest and a page with no usable images both leave the
        # Contact sheet cell blank, so the difference has to be said out loud
        # somewhere a reader will see it: the note reaches the workbook's
        # Fetch note column.
        facts.candidates = []
        facts.note = (f"{note}; IMAGE HARVEST FAILED ({type(e).__name__}: {e}) "
                      f"- no candidates were collected, which says nothing "
                      f"about whether this page has usable images")[:400]
    return facts
