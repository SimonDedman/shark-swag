import json

import pytest

import intake_queue as q


@pytest.fixture
def paths(tmp_path):
    return dict(ledger=tmp_path / "ledger.json",
                queue=tmp_path / "queue.json",
                rejected=tmp_path / "rejected.json")


def test_an_unseen_message_is_not_seen(paths):
    assert q.seen("a@b", path=paths["ledger"]) is False


def test_a_recorded_message_is_seen(paths):
    q.record_message("a@b", ["https://x.com/1"], path=paths["ledger"])
    assert q.seen("a@b", path=paths["ledger"]) is True


def test_recording_twice_does_not_duplicate(paths):
    q.record_message("a@b", ["https://x.com/1"], path=paths["ledger"])
    q.record_message("a@b", ["https://x.com/1"], path=paths["ledger"])
    assert len(json.loads(paths["ledger"].read_text())) == 1


def test_queue_ids_increment_and_are_zero_padded(paths):
    assert q.next_queue_id([]) == "q0001"
    assert q.next_queue_id([{"queue_id": "q0001"}, {"queue_id": "q0009"}]) == "q0010"


def test_add_row_allocates_an_id_and_persists(paths):
    row = q.add_row({"url": "https://x.com/1"}, path=paths["queue"])
    assert row["queue_id"] == "q0001"
    assert q.load_queue(path=paths["queue"])[0]["url"] == "https://x.com/1"


def test_known_links_maps_normalised_links_to_entry_ids():
    links = q.known_links()
    assert links["https://luckybugclothing.com/products/shark-onesie"] == "e01"


def test_duplicate_of_finds_an_existing_entry(paths):
    dup = q.duplicate_of("https://luckybugclothing.com/products/shark-onesie",
                         queue_path=paths["queue"], rejected_path=paths["rejected"])
    assert dup == "e01"


def test_duplicate_of_finds_a_row_already_queued(paths):
    q.add_row({"url": "https://x.com/1", "url_norm": "https://x.com/1"},
              path=paths["queue"])
    assert q.duplicate_of("https://x.com/1", queue_path=paths["queue"],
                          rejected_path=paths["rejected"]) == "q0001"


def test_duplicate_of_reports_a_previously_rejected_link(paths):
    q.reject("https://x.com/2", "not shark themed", path=paths["rejected"])
    assert q.duplicate_of("https://x.com/2", queue_path=paths["queue"],
                          rejected_path=paths["rejected"]) == "REJECTED"


def test_duplicate_of_is_empty_for_something_new(paths):
    assert q.duplicate_of("https://x.com/brand-new", queue_path=paths["queue"],
                          rejected_path=paths["rejected"]) == ""


def test_duplicate_detection_positive_control(paths):
    """The control on the matcher: every link already in the document must be
    found as a duplicate. If this passes while real duplicates slip through,
    the matcher is reading the wrong field. Several entries deliberately share a
    link (a shop listed under two age bands), so the match is asserted against
    the set of ids carrying that link rather than one id."""
    from collections import defaultdict
    from entries import iter_entries
    from intake_parse import normalise_url
    by_link = defaultdict(set)
    for e in iter_entries():
        by_link[normalise_url(e.link)].add(e.id)
    for link, ids in by_link.items():
        found = q.duplicate_of(link, queue_path=paths["queue"],
                               rejected_path=paths["rejected"])
        assert found in ids, (link, found, ids)


def test_new_row_carries_every_field_the_sheet_needs():
    from intake_parse import Submission
    from intake_extract import Facts
    from intake_classify import Guess
    sub = Submission(message_id="m1", sender="Simon Dedman",
                     date="2026-08-28T09:14:02-07:00", subject="s",
                     urls=["https://x.com/1"], note="nice")
    facts = Facts(url="https://x.com/1", status="OK", http=200, title="Shark socks",
                  price="~$12", price_source="json-ld", ngo_text="5% donated.",
                  note="fetched", candidates=[{"url": "https://x.com/i.jpg"}])
    guess = Guess(section="1", sub="Adult", age="Adult", keyword="socks")
    row = q.new_row(sub, "https://x.com/1", facts, guess)
    for key in ("message_id", "received", "sender", "note", "url", "url_norm",
                "fetch_status", "http", "fetch_note", "title", "price",
                "price_source", "ngo_text", "section", "sub", "age", "keyword",
                "duplicate_of", "candidates", "picked"):
        assert key in row, key


# --- Critical 1: a corrupt state file must never read as an empty one, and a
# write must never leave a truncated file behind. ---

def test_a_truncated_queue_raises_instead_of_reading_as_empty(paths):
    """The demonstrated failure: a half-written queue.json loaded as [], one
    add_row then rewrote it with a single row, two staged submissions were
    gone, and next_queue_id handed out q0001 again onto another item's stale
    contact sheet."""
    paths["queue"].write_text('[{"queue_id": "q0001", "url": "https://x.com/1"}, {"que')
    with pytest.raises(q.CorruptStateError):
        q.load_queue(path=paths["queue"])


def test_a_corrupt_queue_is_moved_aside_and_named_in_the_error(paths):
    paths["queue"].write_text("{not json at all")
    with pytest.raises(q.CorruptStateError) as exc:
        q.load_queue(path=paths["queue"])
    aside = list(paths["queue"].parent.glob("queue.json.corrupt-*"))
    assert len(aside) == 1
    assert str(aside[0]) in str(exc.value)
    assert not paths["queue"].exists()


def test_add_row_on_a_corrupt_queue_refuses_rather_than_overwriting(paths):
    paths["queue"].write_text('[{"queue_id": "q0001"}, {"que')
    with pytest.raises(q.CorruptStateError):
        q.add_row({"url": "https://x.com/2"}, path=paths["queue"])
    # the bad bytes survive under the quarantine name; nothing was destroyed
    aside = list(paths["queue"].parent.glob("queue.json.corrupt-*"))
    assert aside[0].read_text().startswith('[{"queue_id": "q0001"}')


def test_a_dict_shaped_queue_raises_instead_of_failing_later(paths):
    """Previously this reached duplicate_of and died with AttributeError deep
    inside the daemon's per-message handler."""
    paths["queue"].write_text('{"q0001": {"url": "https://x.com/1"}}')
    with pytest.raises(q.CorruptStateError) as exc:
        q.load_queue(path=paths["queue"])
    assert "dict" in str(exc.value)


def test_a_list_shaped_ledger_raises(paths):
    paths["ledger"].write_text('["a@b"]')
    with pytest.raises(q.CorruptStateError):
        q.seen("a@b", path=paths["ledger"])


def test_a_list_shaped_rejected_map_raises(paths):
    paths["rejected"].write_text('[]')
    with pytest.raises(q.CorruptStateError):
        q.load_rejected(path=paths["rejected"])


def test_an_absent_file_is_still_nothing_to_do_not_a_failure(paths):
    assert q.load_queue(path=paths["queue"]) == []
    assert q.load_rejected(path=paths["rejected"]) == {}
    assert q.seen("a@b", path=paths["ledger"]) is False


def test_a_failed_write_leaves_the_previous_good_file(paths, monkeypatch):
    q.save_queue([{"queue_id": "q0001"}, {"queue_id": "q0002"}], path=paths["queue"])
    good = paths["queue"].read_text()

    def boom(src, dst):
        raise OSError("power cut")
    monkeypatch.setattr(q.os, "replace", boom)
    with pytest.raises(OSError):
        q.save_queue([{"queue_id": "q0003"}], path=paths["queue"])

    assert paths["queue"].read_text() == good
    assert list(paths["queue"].parent.glob("*.tmp")) == []


def test_a_successful_write_leaves_no_temp_file(paths):
    q.save_queue([{"queue_id": "q0001"}], path=paths["queue"])
    assert list(paths["queue"].parent.glob("*.tmp")) == []
    assert len(q.load_queue(path=paths["queue"])) == 1
