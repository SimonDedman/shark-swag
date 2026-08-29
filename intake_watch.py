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
import hashlib
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

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

# systemd's RestartPreventExitStatus is set to this in the unit file: a
# misconfiguration cannot be fixed by trying again in thirty seconds, so the
# daemon says why once and stays down rather than looping with the reason
# buried in the journal.
EXIT_CONFIG = 78                # sysexits.h EX_CONFIG

REVIEW_SCRIPT = Path.home() / ".local" / "bin" / "shark-swag-review"
NOTIFY_ACTION_TIMEOUT = 3600     # a forgotten notification must not be waited on forever


def log(message, dry_run=False):
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')}  {message}"
    print(line, flush=True)
    if dry_run:
        return
    INTAKE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with INTAKE_LOG.open("a") as fh:
        fh.write(line + "\n")


def beat(dry_run=False):
    if dry_run:
        return
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(datetime.now().astimezone().isoformat() + "\n")


class ConfigError(Exception):
    """The daemon cannot start and no amount of retrying will change that."""


def credentials():
    """Read the Gmail app password from the shared .env. Never logged."""
    values = {}
    try:
        text = ENV_FILE.read_text()
    except OSError as e:
        raise ConfigError(f"cannot read {ENV_FILE}: {type(e).__name__}: {e}")
    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    address = values.get("GMAIL_ADDRESS")
    password = values.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise ConfigError(f"GMAIL_ADDRESS or GMAIL_APP_PASSWORD missing from {ENV_FILE}")
    return address, password


def _launch_review():
    """Hand off to the review launcher and do not wait on it: it opens a
    spreadsheet application, which can run for hours."""
    try:
        subprocess.Popen([str(REVIEW_SCRIPT)], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def _notify_and_wait(count, dry_run=False):
    """The blocking half of notify(): runs off the caller's thread, because
    --wait blocks until the notification is dismissed or its action is
    clicked, which must never stall the IDLE loop. A notification that is
    ignored, whose daemon lacks action support, or that errors outright must
    still leave the watcher running, so every failure here is swallowed."""
    try:
        result = subprocess.run(
            ["notify-send", "--wait", "--action=open=Open review sheet",
             "Shark swag", f"{count} new submission(s) staged, ready to review"],
            capture_output=True, text=True, timeout=NOTIFY_ACTION_TIMEOUT)
        if result.stdout.strip() == "open":
            _launch_review()
    except Exception as e:
        log(f"notification action failed harmlessly: {type(e).__name__}: {e}",
            dry_run=dry_run)


def notify(count, dry_run=False):
    """Notify that something was staged, with a button that opens the review
    sheet. Does nothing for a zero count or under --dry-run: a dry run must
    leave no trace, a real desktop notification included."""
    if not count or dry_run:
        return
    threading.Thread(target=_notify_and_wait, args=(count, dry_run), daemon=True).start()


def message_key(submission, raw):
    """A stable ledger key for this message, header or no header.

    Without the fallback a message carrying no Message-ID short-circuits the
    ledger check, is staged again by every catch-up, every IDLE response, and
    every six-hourly sweep, and records the empty-string key that would have
    caught it. The digest of the raw bytes is stable across those passes and
    unique to the message.
    """
    return submission.message_id or "sha1:" + hashlib.sha1(raw).hexdigest()


def process_message(raw, dry_run=False):
    """Message bytes to queue rows. Returns [] if the message was already seen."""
    submission = intake_parse.parse_message(raw)
    submission.message_id = message_key(submission, raw)
    if intake_queue.seen(submission.message_id, path=LEDGER):
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
    for uid, data in client.fetch(uids, ["BODY.PEEK[]"]).items():
        raw = data.get(b"BODY[]")
        if not raw:
            continue
        try:
            staged += len(process_message(raw, dry_run=dry_run))
        except intake_queue.CorruptStateError:
            # Not this message's problem, and not survivable: every later
            # message would hit the same wall. Let it reach watch(), which
            # stops the daemon rather than logging it once per message.
            raise
        except Exception as e:
            log(f"ERROR processing uid {uid}: {type(e).__name__}: {e}", dry_run=dry_run)
    return staged


def watch(dry_run=False):
    try:
        address, password = credentials()
    except ConfigError as e:
        log(f"FATAL: {e}. Fix the .env and start the service again; "
            f"this is not retried.", dry_run=dry_run)
        raise SystemExit(EXIT_CONFIG)
    attempt = 0
    while True:
        try:
            with IMAPClient(HOST, ssl_context=ssl.create_default_context()) as client:
                client.login(address, password)
                client.select_folder(FOLDER)
                attempt = 0
                log(f"connected, watching {FOLDER}", dry_run=dry_run)
                staged = catch_up(client, dry_run)
                beat(dry_run=dry_run)
                notify(staged, dry_run=dry_run)
                log(f"catch-up staged {staged} row(s)", dry_run=dry_run)

                last_sweep = time.time()
                while True:
                    client.idle()
                    try:
                        responses = client.idle_check(timeout=IDLE_SECONDS)
                    finally:
                        client.idle_done()
                    due = time.time() - last_sweep > SWEEP_SECONDS
                    if responses or due:
                        staged = catch_up(client, dry_run)
                        if due:
                            last_sweep = time.time()
                            log(f"sweep staged {staged} row(s)", dry_run=dry_run)
                        elif staged:
                            log(f"push staged {staged} row(s)", dry_run=dry_run)
                        notify(staged, dry_run=dry_run)
                    beat(dry_run=dry_run)
        except KeyboardInterrupt:
            log("stopped by hand", dry_run=dry_run)
            return
        except intake_queue.CorruptStateError as e:
            log(f"FATAL: {e} This is not retried.", dry_run=dry_run)
            raise SystemExit(EXIT_CONFIG)
        except Exception as e:
            wait = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            log(f"connection lost ({type(e).__name__}: {e}); retrying in {wait}s", dry_run=dry_run)
            time.sleep(wait)


if __name__ == "__main__":
    watch(dry_run="--dry-run" in sys.argv)
