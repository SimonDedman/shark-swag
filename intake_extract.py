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

NGO_SENTENCE = re.compile(
    r"[^.!?\n]*\b(?:donat\w*|proceeds|charitable|charity|conservation|"
    r"non-?profit|nonprofit|foundation|\d{1,3}\s?%\s+of)\b[^.!?\n]*[.!?]", re.I)

SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "AUD": "AUD ", "CAD": "CAD "}


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


def extract_ngo(text):
    """The first sentence that talks about money going somewhere, verbatim.

    A statement that no donation is made is as useful as one that says there is,
    so both are kept.
    """
    # Collapse runs of spaces/tabs but keep newlines: the pattern's [^.!?\n]*
    # relies on \n as a block boundary between unrelated page text (e.g. the
    # <title>) and the paragraph that follows it.
    m = NGO_SENTENCE.search(re.sub(r"[ \t]+", " ", text or ""))
    return m.group(0).strip() if m else ""


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
        if req.path.strip("/") and (fin.netloc != req.netloc or not fin.path.strip("/")):
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
        facts.note = f"{note}; images: {cnote}"[:400]
    except Exception as e:
        facts.note = f"{note}; image harvest failed: {type(e).__name__}"
    return facts
