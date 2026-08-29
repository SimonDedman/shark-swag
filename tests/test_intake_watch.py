import json
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


def test_beat_writes_a_parseable_timestamp(isolated):
    intake_watch.beat()
    from datetime import datetime
    datetime.fromisoformat((isolated / "heartbeat").read_text().strip())
