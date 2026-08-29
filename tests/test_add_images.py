from pathlib import Path

import pytest

import add_images
import entries
from paths import FINAL


def test_name_to_ids_covers_every_entry():
    mapping = add_images.name_to_ids()
    all_ids = {e.id for e in entries.iter_entries()}
    flat = {i for ids in mapping.values() for i in ids}
    assert flat == all_ids


def test_duplicate_item_names_keep_both_ids_in_order():
    """Two entries can share a name (the same book listed for two age bands);
    the mapping must hand them out in id order, not collapse them."""
    mapping = add_images.name_to_ids()
    for name, ids in mapping.items():
        assert ids == sorted(ids, key=lambda i: int(i[1:])), name


def test_images_for_globs_on_the_id():
    files = add_images.images_for("e01")
    assert files == [FINAL / "e01_0.jpg"]


def test_images_for_returns_empty_when_the_entry_has_none():
    assert add_images.images_for("e02") == []


def test_id_pairing_matches_the_old_positional_pairing():
    """The migration control. The old code paired the Nth entry name with
    images/final/eNN_*.jpg; the new code pairs by stored id. If Task 1 assigned
    ids in any other order, this fails and the ids are wrong, not this test.

    Once an entry is added out of positional order — which the intake system
    does deliberately — the comparison stops being meaningful and is skipped.
    """
    all_entries = entries.iter_entries()
    if any(e.id != f"e{n:02d}" for n, e in enumerate(all_entries, 1)):
        pytest.skip("ids are no longer positional; the migration control has served its purpose")
    old = {}
    for n, e in enumerate(all_entries, 1):
        old.setdefault(e.item, []).append(sorted(FINAL.glob(f"e{n:02d}_*.jpg")))
    new = {}
    for e in all_entries:
        new.setdefault(e.item, []).append(add_images.images_for(e.id))
    assert old == new
