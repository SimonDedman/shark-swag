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


def test_ids_follow_the_original_positional_order():
    """The 88 entries that existed at migration time are e01..e88 in file order,
    which is the numbering picks.py used positionally. Anything else would orphan
    the files already in images/final/. Entries added later take the next free id
    and are deliberately not positional."""
    ids = [e.id for e in entries.iter_entries()]
    assert ids[:88] == [f"e{n:02d}" for n in range(1, 89)]


def test_existing_entries_are_flagged_and_come_last():
    all_entries = entries.iter_entries()
    existing = [e for e in all_entries if e.existing]
    assert [e.id for e in existing] == ["e85", "e86", "e87", "e88"]
    assert existing[0].item.startswith("SPHYRNAS")
    assert existing[0].section == "1"
    assert existing[0].sub == "Adult"


def test_next_id_continues_past_the_highest():
    assert entries.next_id() == "e89"


def test_next_id_ignores_gaps_and_never_reuses():
    data = entries.load_items()
    data["sections"][0]["subsections"][0]["items"][0]["id"] = "e99"
    assert entries.next_id(data) == "e100"


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
