#!/usr/bin/env python3
"""Durable state for the intake: which messages have been processed, which rows
are waiting for review, and which links have already been turned down.

Messages are tracked by Message-ID rather than by IMAP UID, because UIDs are
only meaningful until the folder's UIDVALIDITY changes, and are never marked
\\Seen, because reading the mail on a phone must not change what the daemon does.

All three stores share one read/write pair, and it refuses to lie in either
direction. A file that is absent means "nothing yet", and returns the default.
A file that exists but cannot be read as what it must be means "cannot look":
it is renamed aside and the read raises, because degrading to the default here
would let the next write destroy staged submissions and hand out queue ids that
already name contact sheets on disk. Writes go through a temp file and
os.replace, so a kill mid-write, which is ordinary under Restart=always, leaves
the previous good file rather than a truncated one.
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from paths import LEDGER, QUEUE, REJECTED
from entries import iter_entries
from intake_parse import normalise_url


class CorruptStateError(RuntimeError):
    """A state file exists but could not be read as what it must be.

    Raised, never returned, so "we could not look" can never be mistaken for
    "we looked and there was nothing".
    """


def _quarantine(path, why):
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    aside = path.with_name(f"{path.name}.corrupt-{stamp}")
    n = 0
    while aside.exists():
        n += 1
        aside = path.with_name(f"{path.name}.corrupt-{stamp}-{n}")
    os.replace(path, aside)
    raise CorruptStateError(
        f"{path} {why}. Nothing was read from it and it has been moved to "
        f"{aside}; repair or delete that file before running again.")


def _load(path, default, shape):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        _quarantine(path, f"is not valid JSON ({e})")
    if not isinstance(data, shape):
        _quarantine(path, f"holds a JSON {type(data).__name__}, not a {shape.__name__}")
    return data


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def seen(message_id, path=None):
    return message_id in _load(path or LEDGER, {}, dict)


def record_message(message_id, urls, path=None):
    path = path or LEDGER
    ledger = _load(path, {}, dict)
    ledger.setdefault(message_id, dict(seen=datetime.now().astimezone().isoformat(),
                                       urls=list(urls)))
    _save(path, ledger)


def load_queue(path=None):
    return _load(path or QUEUE, [], list)


def save_queue(rows, path=None):
    _save(path or QUEUE, rows)


def next_queue_id(rows):
    highest = max((int(r["queue_id"][1:]) for r in rows if r.get("queue_id")), default=0)
    return f"q{highest + 1:04d}"


def add_row(row, path=None):
    path = path or QUEUE
    rows = load_queue(path)
    row = dict(row)
    row["queue_id"] = next_queue_id(rows)
    rows.append(row)
    save_queue(rows, path)
    return row


def load_rejected(path=None):
    return _load(path or REJECTED, {}, dict)


def reject(norm_url, reason, path=None):
    path = path or REJECTED
    data = load_rejected(path)
    data[norm_url] = dict(date=datetime.now().astimezone().isoformat(), reason=reason)
    _save(path, data)


def known_links(data=None):
    """Normalised link to entry id, for everything already in the document."""
    return {normalise_url(e.link): e.id for e in iter_entries(data)}


def duplicate_of(norm_url, queue_path=None, rejected_path=None, data=None):
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
        blurb=facts.blurb,
        blurb_source=facts.blurb_source,
        section=guess.section,
        sub=guess.sub,
        age=guess.age,
        keyword=guess.keyword,
        duplicate_of="",
        candidates=facts.candidates,
        picked="",
    )
