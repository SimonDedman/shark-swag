#!/usr/bin/env python3
"""Durable state for the intake: which messages have been processed, which rows
are waiting for review, and which links have already been turned down.

Messages are tracked by Message-ID rather than by IMAP UID, because UIDs are
only meaningful until the folder's UIDVALIDITY changes, and are never marked
\\Seen, because reading the mail on a phone must not change what the daemon does.
"""
import json
from datetime import datetime

from paths import LEDGER, QUEUE, REJECTED
from entries import iter_entries
from intake_parse import normalise_url


def _load(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def seen(message_id, path=LEDGER):
    return message_id in _load(path, {})


def record_message(message_id, urls, path=LEDGER):
    ledger = _load(path, {})
    ledger.setdefault(message_id, dict(seen=datetime.now().astimezone().isoformat(),
                                       urls=list(urls)))
    _save(path, ledger)


def load_queue(path=QUEUE):
    return _load(path, [])


def save_queue(rows, path=QUEUE):
    _save(path, rows)


def next_queue_id(rows):
    highest = max((int(r["queue_id"][1:]) for r in rows if r.get("queue_id")), default=0)
    return f"q{highest + 1:04d}"


def add_row(row, path=QUEUE):
    rows = load_queue(path)
    row = dict(row)
    row["queue_id"] = next_queue_id(rows)
    rows.append(row)
    save_queue(rows, path)
    return row


def load_rejected(path=REJECTED):
    return _load(path, {})


def reject(norm_url, reason, path=REJECTED):
    data = load_rejected(path)
    data[norm_url] = dict(date=datetime.now().astimezone().isoformat(), reason=reason)
    _save(path, data)


def known_links(data=None):
    """Normalised link to entry id, for everything already in the document."""
    return {normalise_url(e.link): e.id for e in iter_entries(data)}


def duplicate_of(norm_url, queue_path=QUEUE, rejected_path=REJECTED, data=None):
    """Entry id, queue id, "REJECTED", or "" for something genuinely new."""
    match = known_links(data).get(norm_url)
    if match:
        return match
    if norm_url in load_rejected(rejected_path):
        return "REJECTED"
    for row in load_queue(queue_path):
        if row.get("url_norm") == norm_url:
            return row["queue_id"]
    return ""


def new_row(submission, url, facts, guess):
    """Assemble one pending row. No queue_id yet; add_row allocates that."""
    return dict(
        message_id=submission.message_id,
        received=submission.date,
        sender=submission.sender,
        note=submission.note,
        url=url,
        url_norm=normalise_url(url),
        fetch_status=facts.status,
        http=facts.http,
        fetch_note=facts.note,
        title=facts.title,
        price=facts.price,
        price_source=facts.price_source,
        ngo_text=facts.ngo_text,
        section=guess.section,
        sub=guess.sub,
        age=guess.age,
        keyword=guess.keyword,
        duplicate_of="",
        candidates=facts.candidates,
        picked="",
    )
