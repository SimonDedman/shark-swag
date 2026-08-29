import json
import re

import pool
from paths import POOL_JSON


def test_build_pools_keys_on_entry_id():
    pools = pool.build_pools()
    for key in pools:
        assert re.fullmatch(r"e\d{2,}", key), key
    assert "e01" in pools
    assert "e88" in pools


def test_pool_entries_carry_their_item_and_link():
    pools = pool.build_pools()
    assert pools["e85"]["item"].startswith("SPHYRNAS")
    assert pools["e85"]["link"] == "https://www.sphyrnas.com/products"


def test_written_pool_json_matches_returned_pools():
    pools = pool.build_pools()
    assert json.loads(POOL_JSON.read_text()).keys() == pools.keys()


def test_extras_are_still_prepended_by_id():
    """extras.json is keyed by the old positional index; the migration must
    carry it across or the supplemented shops lose their catalogue images."""
    pools = pool.build_pools()
    extras = json.loads((POOL_JSON.parent / "extras.json").read_text())
    for key in extras:
        assert key.startswith("e"), f"extras.json key {key!r} was not migrated"
        assert pools[key]["cands"][0]["score"] == 999
