import json
import re

import entries
from paths import ITEMS


def test_every_item_has_a_well_formed_id():
    data = entries.load_items()
    for section in data["sections"]:
        for sub in section["subsections"]:
            for item in sub["items"]:
                assert re.fullmatch(r"e\d{2,}", item["id"]), item


def test_ids_are_unique_across_items_and_existing():
    ids = [e.id for e in entries.iter_entries()]
    assert len(ids) == len(set(ids))


def test_the_migrated_ids_all_survive_and_stay_unique():
    """The 88 entries that existed at migration time were given e01..e88, and
    those ids name 155 files in images/final/ and every key in
    images/picks.json. What matters is that all 88 are still present and that
    no id is issued twice; where they sit in the file does not, because the
    intake deliberately inserts new entries in the middle. Asserting the old
    positional order here would fail on the first accepted submission and read
    as a regression when nothing had regressed."""
    ids = [e.id for e in entries.iter_entries()]
    assert {f"e{n:02d}" for n in range(1, 89)} <= set(ids)
    assert len(ids) == len(set(ids))


def test_existing_entries_are_flagged_and_come_last():
    all_entries = entries.iter_entries()
    existing = [e for e in all_entries if e.existing]
    assert [e.id for e in existing] == ["e85", "e86", "e87", "e88"]
    assert existing[0].item.startswith("SPHYRNAS")
    assert existing[0].section == "1"
    assert existing[0].sub == "Adult"


def test_next_id_continues_past_the_highest():
    """Greater than every id in use, whatever the highest happens to be today.
    Hardcoding e89 asserted the size of the list, not the property."""
    issued = {entries.id_num(e.id) for e in entries.iter_entries()}
    assert entries.id_num(entries.next_id()) > max(issued)


def test_next_id_ignores_gaps():
    data = entries.load_items()
    data["sections"][0]["subsections"][0]["items"][0]["id"] = "e99"
    assert entries.next_id(data) == "e100"


def test_next_id_never_reuses_a_deleted_entrys_id(tmp_path, monkeypatch):
    """Deleting an item is a normal editorial act, but its id still names files
    in images/final/ and a key in images/picks.json. Reissuing it would hand a
    new entry the deleted entry's pictures, so the picks keys are part of what
    'already issued' means."""
    picks = tmp_path / "picks.json"
    picks.write_text(json.dumps({"e99": {"specs": [], "note": "from intake q0001"}}))
    monkeypatch.setattr(entries, "PICKS_JSON", picks)

    data = entries.load_items()
    data["sections"][0]["subsections"][0]["items"][0]["id"] = "e99"
    assert entries.next_id(data) == "e100"

    # e99 is now deleted from items.json, and must not come back
    data = entries.load_items()
    assert "e99" not in {e.id for e in entries.iter_entries(data)}
    assert entries.next_id(data) == "e100"


def test_retired_ids_reads_the_real_picks_file():
    """Positive control on the instrument: if this returns nothing, next_id is
    not actually consulting picks.json and the test above proves nothing."""
    assert "e01" in entries.retired_ids()


def test_an_absent_picks_file_is_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(entries, "PICKS_JSON", tmp_path / "nothing-here.json")
    assert entries.retired_ids() == set()


def test_entry_by_id_round_trips():
    assert entries.entry_by_id("e01").id == "e01"
    assert entries.entry_by_id("e85").existing is True
    assert entries.entry_by_id("e999") is None


def test_save_items_is_byte_stable():
    before = ITEMS.read_bytes()
    entries.save_items(entries.load_items())
    assert ITEMS.read_bytes() == before


def test_save_items_keeps_one_item_per_line():
    text = ITEMS.read_text()
    assert '"item":' in text
    for line in text.splitlines():
        assert line.count('"item":') <= 1
