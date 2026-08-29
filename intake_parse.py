#!/usr/bin/env python3
"""Turn a raw email into a Submission: who sent it, what they linked, and what
they said about it.

Normalised URLs exist only for matching. The original URL is what goes into the
entry, because a shop's canonical link is the one a reader should follow.
"""
import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
TRAILING = ".,;:!?'‘’“”"

TRACK_PREFIXES = ("utm_", "mc_", "_branch", "pk_")
TRACK_EXACT = {"fbclid", "gclid", "igsh", "ref", "ref_", "si", "source", "mkt_tok",
               "gad_source", "srsltid"}

FORWARD_LINE = re.compile(
    r"^\s*(>|-{2,}\s*Forwarded message|From:|To:|Cc:|Sent:|Date:|Subject:|"
    r"On .*wrote:)", re.I)


@dataclass
class Submission:
    message_id: str
    sender: str
    date: str
    subject: str
    urls: list = field(default_factory=list)
    note: str = ""


def normalise_url(url):
    """A comparison key, not a link. Lowercases the host, drops www, drops the
    fragment and tracking parameters, and strips a trailing slash."""
    p = urlsplit(url.strip())
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not (k.lower().startswith(TRACK_PREFIXES) or k.lower() in TRACK_EXACT)]
    path = p.path.rstrip("/")
    return urlunsplit((p.scheme.lower(), host, path, urlencode(query), ""))


def extract_urls(text):
    out, seen = [], set()
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(TRAILING)
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _bodies(msg):
    """Return (plain_text, html) with either possibly empty."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            try:
                payload = part.get_content()
            except Exception:
                continue
            if ctype == "text/plain":
                plain += payload
            elif ctype == "text/html":
                html += payload
    else:
        payload = msg.get_content()
        if msg.get_content_type() == "text/html":
            html = payload
        else:
            plain = payload
    return plain, html


def _note_from(text, urls):
    """Prose only: no URLs, no forwarded headers, no quoted lines, no signature."""
    lines = []
    for line in (text or "").splitlines():
        if line.strip() in ("--", "-- "):
            break
        if FORWARD_LINE.match(line):
            continue
        for u in urls:
            line = line.replace(u, "")
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines).strip()


def parse_message(raw):
    msg = message_from_bytes(raw, policy=policy.default)
    plain, html = _bodies(msg)

    urls = extract_urls(plain)
    html_text = ""
    if html:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("http") and href not in urls:
                urls.append(href)
        html_text = soup.get_text("\n")
        urls += [u for u in extract_urls(html_text) if u not in urls]

    note = _note_from(plain, urls) or _note_from(html_text, urls)

    name, addr = parseaddr(msg.get("From", ""))
    try:
        date = parsedate_to_datetime(msg.get("Date", "")).isoformat()
    except Exception:
        date = ""
    return Submission(
        message_id=(msg.get("Message-ID", "") or "").strip("<> \t"),
        sender=name or addr,
        date=date,
        subject=(msg.get("Subject", "") or "").strip(),
        urls=urls,
        note=note,
    )
