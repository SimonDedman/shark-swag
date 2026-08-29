import json
import re

import picks
from paths import PICKS_JSON, FINAL


def test_picks_json_is_keyed_by_entry_id():
    data = picks.load_picks()
    for key in data:
        assert re.fullmatch(r"e\d{2,}", key), key


def test_every_entry_has_a_picks_record():
    import entries
    ids = {e.id for e in entries.iter_entries()}
    assert set(picks.load_picks()) == ids


def test_pool_specs_reference_ids_not_positions():
    for key, rec in picks.load_picks().items():
        for spec in rec["specs"]:
            if spec.startswith("P:"):
                assert re.match(r"P:e\d{2,}_\d{2}", spec), (key, spec)


def test_notes_survived_the_migration():
    data = picks.load_picks()
    assert "JS-only" in data["e02"]["note"]
    assert "JS-only" in data["e14"]["note"]
    assert "wrong title" in data["e42"]["note"]


def test_deliberately_empty_entries_are_still_empty():
    """Three storefronts render client-side and have no usable image. An empty
    spec list means 'looked, found nothing', and must not become 'not looked at'."""
    data = picks.load_picks()
    assert data["e02"]["specs"] == []
    assert data["e14"]["specs"] == []
    assert data["e66"]["specs"] == []


def test_resolve_pool_spec_returns_a_url_and_referer():
    url, referer, crop = picks.resolve("P:e01_00")
    assert url.startswith("http")
    assert referer.startswith("http")
    assert crop is None


def test_resolve_direct_spec_passes_the_url_through():
    url, referer, crop = picks.resolve("U:https://example.com/a.jpg")
    assert url == "https://example.com/a.jpg"
    assert referer is None


def test_resolve_parses_a_crop():
    url, referer, crop = picks.resolve("P:e16_00|crop=0,0.44,1,1")
    assert crop == [0.0, 0.44, 1.0, 1.0]


def test_rendered_filenames_match_what_is_on_disk():
    """e16 has one pick, so images/final/e16_0.jpg exists and e16_1.jpg does not."""
    assert (FINAL / "e16_0.jpg").exists()
    assert not (FINAL / "e16_1.jpg").exists()
