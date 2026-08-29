import json
import threading
import time
from pathlib import Path

import pytest

import intake_watch
from intake_extract import Facts

MAIL = Path(__file__).resolve().parent / "fixtures" / "mail"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """No network, no real queue: extraction is stubbed and state goes to tmp."""
    monkeypatch.setattr(intake_watch, "QUEUE", tmp_path / "queue.json")
    monkeypatch.setattr(intake_watch, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr(intake_watch, "REJECTED", tmp_path / "rejected.json")
    monkeypatch.setattr(intake_watch, "HEARTBEAT", tmp_path / "heartbeat")
    monkeypatch.setattr(intake_watch, "INTAKE_LOG", tmp_path / "intake.log")

    def fake_extract(url):
        return Facts(url=url, status="OK", http=200, title="Shark socks",
                     price="~£12.50", price_source="itemprop",
                     ngo_text="5% of profits go to the Shark Trust.",
                     note="fetched", candidates=[{"url": "https://x.com/i.jpg",
                                                  "title": "socks", "src": "img"}])
    monkeypatch.setattr(intake_watch.intake_extract, "extract", fake_extract)
    return tmp_path


def test_a_message_becomes_one_queue_row_per_url(isolated):
    raw = (MAIL / "multi_url.eml").read_bytes()
    rows = intake_watch.process_message(raw)
    assert len(rows) == 3
    assert [r["queue_id"] for r in rows] == ["q0001", "q0002", "q0003"]


def test_the_message_is_recorded_so_it_is_not_processed_twice(isolated):
    raw = (MAIL / "bare_url.eml").read_bytes()
    assert len(intake_watch.process_message(raw)) == 1
    assert intake_watch.process_message(raw) == []


def test_a_message_with_no_url_is_still_queued_visibly(isolated):
    raw = (MAIL / "no_url.eml").read_bytes()
    rows = intake_watch.process_message(raw)
    assert len(rows) == 1
    assert rows[0]["fetch_status"] == "NO_URL"
    assert "advent calendar" in rows[0]["note"]


def test_a_duplicate_link_is_flagged_not_dropped(isolated, monkeypatch):
    raw = (MAIL / "bare_url.eml").read_bytes()
    rows = intake_watch.process_message(raw)
    assert rows[0]["duplicate_of"] == "e01", \
        "the lemon shark onesie is already entry e01"


def test_the_note_and_sender_reach_the_row(isolated):
    rows = intake_watch.process_message((MAIL / "link_plus_note.eml").read_bytes())
    assert rows[0]["sender"] == "Simon Dedman"
    assert "proceeds go somewhere useful" in rows[0]["note"]


def test_dry_run_writes_nothing(isolated):
    raw = (MAIL / "bare_url.eml").read_bytes()
    rows = intake_watch.process_message(raw, dry_run=True)
    assert len(rows) == 1
    assert not (isolated / "queue.json").exists()
    assert not (isolated / "ledger.json").exists()


def test_dry_run_writes_absolutely_nothing(isolated):
    """--dry-run is what gets pointed at the real mailbox first: it must not
    leave a queue, a ledger, a heartbeat, or a log line behind either."""
    raw = (MAIL / "bare_url.eml").read_bytes()
    rows = intake_watch.process_message(raw, dry_run=True)
    intake_watch.beat(dry_run=True)
    intake_watch.log("would have staged something", dry_run=True)
    assert len(rows) == 1
    assert list(isolated.iterdir()) == []


def test_beat_writes_a_parseable_timestamp(isolated):
    intake_watch.beat()
    from datetime import datetime
    datetime.fromisoformat((isolated / "heartbeat").read_text().strip())


class _FakeClient:
    """Enough of an IMAPClient to exercise catch_up() without ever logging in."""

    def __init__(self, raw):
        self._raw = raw
        self.fetch_calls = []

    def search(self, criteria):
        return [1]

    def fetch(self, uids, items):
        self.fetch_calls.append(list(items))
        return {1: {b"BODY[]": self._raw}}


def test_catch_up_peeks_instead_of_marking_seen(isolated):
    """RFC822 (and BODY[] without .PEEK) sets \\Seen as a side effect; a
    catch-up scan must never do that to Simon's real mailbox."""
    raw = (MAIL / "bare_url.eml").read_bytes()
    client = _FakeClient(raw)
    staged = intake_watch.catch_up(client)
    assert client.fetch_calls == [["BODY.PEEK[]"]]
    assert staged == 1


def test_catch_up_ignores_a_response_missing_the_body_key(isolated):
    class EmptyClient(_FakeClient):
        def fetch(self, uids, items):
            self.fetch_calls.append(list(items))
            return {1: {}}

    client = EmptyClient(b"")
    assert intake_watch.catch_up(client) == 0


# --- Important 5: a message with no Message-ID short-circuited the ledger
# check and was staged again by every catch-up, every IDLE response, and every
# six-hourly sweep, re-fetching the URL and re-downloading images each time. ---

def test_a_message_with_no_message_id_is_staged_once(isolated):
    raw = (MAIL / "no_message_id.eml").read_bytes()
    assert len(intake_watch.process_message(raw)) == 1
    assert intake_watch.process_message(raw) == []
    assert intake_watch.process_message(raw) == []
    assert len(json.loads((isolated / "queue.json").read_text())) == 1


def test_the_synthetic_ledger_key_is_not_the_empty_string(isolated):
    raw = (MAIL / "no_message_id.eml").read_bytes()
    intake_watch.process_message(raw)
    keys = list(json.loads((isolated / "ledger.json").read_text()))
    assert keys != [""]
    assert keys[0].startswith("sha1:")


def test_the_synthetic_key_is_stable_across_passes(isolated):
    raw = (MAIL / "no_message_id.eml").read_bytes()
    import intake_parse
    a = intake_watch.message_key(intake_parse.parse_message(raw), raw)
    b = intake_watch.message_key(intake_parse.parse_message(raw), raw)
    assert a == b


def test_a_real_message_id_is_still_preferred(isolated):
    raw = (MAIL / "bare_url.eml").read_bytes()
    import intake_parse
    assert intake_watch.message_key(intake_parse.parse_message(raw), raw) == \
        "bare1@mail.gmail.com"


def test_two_headerless_messages_do_not_collide(isolated):
    a = (MAIL / "no_message_id.eml").read_bytes()
    b = a.replace(b"headerless-shark", b"headerless-whale")
    assert len(intake_watch.process_message(a)) == 1
    assert len(intake_watch.process_message(b)) == 1


# --- Minor: credentials() raised SystemExit, which watch()'s except Exception
# does not catch, so a missing env var became a 30-second systemd restart loop
# with the reason only in the journal. ---

def test_missing_credentials_fail_once_with_a_no_restart_exit_code(isolated, monkeypatch, tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("# nothing useful here\n")
    monkeypatch.setattr(intake_watch, "ENV_FILE", env)
    with pytest.raises(SystemExit) as exc:
        intake_watch.watch()
    assert exc.value.code == intake_watch.EXIT_CONFIG
    assert str(env) in (isolated / "intake.log").read_text()


def test_an_unreadable_env_file_is_the_same_failure(isolated, monkeypatch, tmp_path):
    monkeypatch.setattr(intake_watch, "ENV_FILE", tmp_path / "does-not-exist.env")
    with pytest.raises(SystemExit) as exc:
        intake_watch.watch()
    assert exc.value.code == intake_watch.EXIT_CONFIG


def test_credentials_never_reach_the_log(isolated, monkeypatch, tmp_path):
    env = tmp_path / "half.env"
    env.write_text("GMAIL_ADDRESS=someone@example.com\n")
    monkeypatch.setattr(intake_watch, "ENV_FILE", env)
    with pytest.raises(SystemExit):
        intake_watch.watch()
    assert "someone@example.com" not in (isolated / "intake.log").read_text()


# --- Critical 1: an unreadable state file is not one message's problem, so it
# must reach watch() rather than be logged once per message forever. ---

def test_catch_up_does_not_swallow_a_corrupt_state_file(isolated, monkeypatch):
    import intake_queue
    (isolated / "queue.json").write_text('[{"queue_id": "q0001"}, {"que')
    client = _FakeClient((MAIL / "bare_url.eml").read_bytes())
    with pytest.raises(intake_queue.CorruptStateError):
        intake_watch.catch_up(client)


# --- New feature: a clickable notification, wired to the review launcher.
# notify-send --wait blocks until dismissed or clicked, so it must run off
# the IDLE loop's own thread, must do nothing under --dry-run or for a zero
# count, and an ignored or failed notification must never take the watcher
# down or leave anything hanging. ---

def test_notify_spins_no_thread_for_a_zero_count(isolated, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not spin a thread for a zero count")
    monkeypatch.setattr(intake_watch.threading, "Thread", boom)
    intake_watch.notify(0)


def test_notify_spins_no_thread_under_dry_run(isolated, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not spin a thread under --dry-run")
    monkeypatch.setattr(intake_watch.threading, "Thread", boom)
    intake_watch.notify(5, dry_run=True)


def test_notify_returns_before_the_notification_is_dismissed(isolated, monkeypatch):
    """--wait blocks; notify() itself must not, or a click hangs the daemon
    that is supposed to be watching the mailbox."""
    released = threading.Event()

    def slow_run(*a, **k):
        released.wait(timeout=2)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr(intake_watch.subprocess, "run", slow_run)
    start = time.time()
    intake_watch.notify(3)
    assert time.time() - start < 0.5
    released.set()


def test_notify_and_wait_launches_the_review_script_on_the_open_action(
        isolated, monkeypatch):
    launched = []
    monkeypatch.setattr(intake_watch, "_launch_review", lambda: launched.append(True))
    monkeypatch.setattr(intake_watch.subprocess, "run",
                         lambda *a, **k: type("R", (), {"stdout": "open\n"})())
    intake_watch._notify_and_wait(2)
    assert launched == [True]


def test_notify_and_wait_does_nothing_when_the_notification_is_dismissed(
        isolated, monkeypatch):
    launched = []
    monkeypatch.setattr(intake_watch, "_launch_review", lambda: launched.append(True))
    monkeypatch.setattr(intake_watch.subprocess, "run",
                         lambda *a, **k: type("R", (), {"stdout": ""})())
    intake_watch._notify_and_wait(2)
    assert launched == []


def test_notify_and_wait_survives_a_missing_notify_send(isolated, monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError("notify-send: command not found")
    monkeypatch.setattr(intake_watch.subprocess, "run", fake_run)
    intake_watch._notify_and_wait(1, dry_run=True)  # must not raise


def test_launch_review_starts_the_script_detached_and_unwaited(isolated, monkeypatch):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(intake_watch.subprocess, "Popen", fake_popen)
    intake_watch._launch_review()
    args, kwargs = calls[0]
    assert args == [str(intake_watch.REVIEW_SCRIPT)]
    assert kwargs["start_new_session"] is True


def test_launch_review_survives_a_missing_script(isolated, monkeypatch):
    def fake_popen(*a, **k):
        raise OSError("no such file or directory")
    monkeypatch.setattr(intake_watch.subprocess, "Popen", fake_popen)
    intake_watch._launch_review()  # must not raise
