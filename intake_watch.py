#!/usr/bin/env python3
"""Watch the sharkswag Gmail label and stage every new submission.

IDLE gives push delivery, but a dead IDLE socket looks exactly like a quiet
inbox, and this machine sleeps. So the daemon also scans the whole folder on
every start and every SWEEP_SECONDS, staging anything absent from the ledger.
Push is for latency; the sweep is for truth.

systemd owns liveness. Nothing here checks for a running process: in this
harness a pgrep pattern matches the searching command itself and always says
yes.
"""
import os
import ssl
import sys
import time
from datetime import datetime

from imapclient import IMAPClient

import intake_classify
import intake_extract
import intake_parse
import intake_queue
from paths import ENV_FILE, HEARTBEAT, INTAKE_LOG, LEDGER, QUEUE, REJECTED

HOST = "imap.gmail.com"
FOLDER = "sharkswag"
IDLE_SECONDS = 15 * 60          # Gmail drops an idle connection at about 29 minutes
SWEEP_SECONDS = 6 * 60 * 60
RECONNECT_BACKOFF = (30, 60, 120, 300, 600)


def log(message):
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')}  {message}"
    print(line, flush=True)
    INTAKE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with INTAKE_LOG.open("a") as fh:
        fh.write(line + "\n")


def beat():
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(datetime.now().astimezone().isoformat() + "\n")


def credentials():
    """Read the Gmail app password from the shared .env. Never logged."""
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    address = values.get("GMAIL_ADDRESS")
    password = values.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise SystemExit(f"GMAIL_ADDRESS or GMAIL_APP_PASSWORD missing from {ENV_FILE}")
    return address, password


def notify(count):
    if not count:
        return
    os.system(f'notify-send "Shark swag" "{count} new submission(s) staged" >/dev/null 2>&1')


def process_message(raw, dry_run=False):
    """Message bytes to queue rows. Returns [] if the message was already seen."""
    submission = intake_parse.parse_message(raw)
    if submission.message_id and intake_queue.seen(submission.message_id, path=LEDGER):
        return []

    rows = []
    if not submission.urls:
        row = dict(
            message_id=submission.message_id, received=submission.date,
            sender=submission.sender, note=submission.note, url="", url_norm="",
            fetch_status="NO_URL", http=None,
            fetch_note="the message carried no link", title=submission.subject,
            price="", price_source="", ngo_text="", section="", sub="", age="",
            keyword="", duplicate_of="", candidates=[], picked="")
        rows.append(row if dry_run else intake_queue.add_row(row, path=QUEUE))
    else:
        for url in submission.urls:
            facts = intake_extract.extract(url)
            guess = intake_classify.classify(facts.title, submission.note, url)
            row = intake_queue.new_row(submission, url, facts, guess)
            row["duplicate_of"] = intake_queue.duplicate_of(
                row["url_norm"], queue_path=QUEUE, rejected_path=REJECTED)
            rows.append(row if dry_run else intake_queue.add_row(row, path=QUEUE))

    if not dry_run:
        intake_queue.record_message(submission.message_id, submission.urls, path=LEDGER)
    return rows


def catch_up(client, dry_run=False):
    """Stage everything in the folder that the ledger has never seen.

    Runs on every start and on every sweep, so a missed IDLE notification, a
    sleeping machine, or a socket that went quiet costs at most one sweep.
    """
    uids = client.search(["ALL"])
    if not uids:
        return 0
    staged = 0
    for uid, data in client.fetch(uids, ["RFC822"]).items():
        raw = data.get(b"RFC822")
        if not raw:
            continue
        try:
            staged += len(process_message(raw, dry_run=dry_run))
        except Exception as e:
            log(f"ERROR processing uid {uid}: {type(e).__name__}: {e}")
    return staged


def watch(dry_run=False):
    address, password = credentials()
    attempt = 0
    while True:
        try:
            with IMAPClient(HOST, ssl_context=ssl.create_default_context()) as client:
                client.login(address, password)
                client.select_folder(FOLDER)
                attempt = 0
                log(f"connected, watching {FOLDER}")
                staged = catch_up(client, dry_run)
                beat()
                notify(staged)
                log(f"catch-up staged {staged} row(s)")

                last_sweep = time.time()
                while True:
                    client.idle()
                    responses = client.idle_check(timeout=IDLE_SECONDS)
                    client.idle_done()
                    due = time.time() - last_sweep > SWEEP_SECONDS
                    if responses or due:
                        staged = catch_up(client, dry_run)
                        if due:
                            last_sweep = time.time()
                            log(f"sweep staged {staged} row(s)")
                        elif staged:
                            log(f"push staged {staged} row(s)")
                        notify(staged)
                    beat()
        except KeyboardInterrupt:
            log("stopped by hand")
            return
        except Exception as e:
            wait = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            log(f"connection lost ({type(e).__name__}: {e}); retrying in {wait}s")
            time.sleep(wait)


if __name__ == "__main__":
    watch(dry_run="--dry-run" in sys.argv)
