from pathlib import Path

import docx
import pytest
from PIL import Image

import add_images
import entries
from paths import FINAL


def test_entry_index_covers_every_entry():
    index = add_images.entry_index()
    all_ids = {e.id for e in entries.iter_entries()}
    flat = {i for ids in index.values() for i in ids}
    assert flat == all_ids


def test_duplicate_item_names_keep_both_ids_in_order():
    """Two entries can share a name (the same book listed for two age bands);
    the index must hand them out in id order, not collapse them."""
    index = add_images.entry_index()
    for key, ids in index.items():
        assert ids == sorted(ids, key=lambda i: int(i[1:])), key


def test_a_shared_name_in_two_subsections_gets_two_keys():
    """The collision already in the data: the 4D Vision anatomy model is both
    e30 (section 2, Youth) and e55 (section 4, Science & STEM kits). Keyed by
    name alone they share one list and the document order decides which gets
    which images; keyed by name and place they never meet."""
    index = add_images.entry_index()
    keys = [k for k in index if k[0] == "4D Vision great white shark anatomy model"]
    assert len(keys) == 2
    assert all(len(index[k]) == 1 for k in keys)
    assert {index[k][0] for k in keys} == {"e30", "e55"}


def test_no_two_entries_share_a_name_within_one_subsection():
    """A positive control on the key: if this ever fails, the ambiguity path
    below is live in the real data and Simon needs to rename something."""
    index = add_images.entry_index()
    assert [k for k, ids in index.items() if len(ids) > 1] == []


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


# --- Critical 3: name_to_ids() returned ids ascending while the main loop
# walked DOCUMENT order taking the lowest unused id. Those two orders agreed
# only because ids were positional, which is exactly what this branch ended. ---

NAME = "4D Vision great white shark anatomy model"


def _stub_doc(path, blocks):
    """A document shaped the way build_docx.py writes one: Heading 1 per
    section, Heading 2 per subsection, then '▸ name' and its seven fields."""
    d = docx.Document()
    for section_heading, sub, names in blocks:
        d.add_heading(section_heading, level=1)
        d.add_heading(sub, level=2)
        for name in names:
            d.add_paragraph(f"▸ {name}")
            for field in ("Item", "Age", "Link", "Approx. price", "Description",
                          "Suggested by"):
                d.add_paragraph(f"{field}: x")
            d.add_paragraph("NGO / proceeds to conservation?: none stated")
    d.save(path)
    return path


def _make_image(path, size, colour):
    Image.new("RGB", size, colour).save(path, "JPEG")


def _embedded_blobs(path):
    d = docx.Document(path)
    out = []
    for shape in d.inline_shapes:
        rid = shape._inline.graphic.graphicData.pic.blipFill.blip.embed
        out.append(d.part.related_parts[rid].blob)
    return out


@pytest.fixture
def two_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(add_images, "FINAL", tmp_path)
    _make_image(tmp_path / "e30_0.jpg", (40, 20), (255, 0, 0))
    _make_image(tmp_path / "e55_0.jpg", (60, 20), (0, 0, 255))
    return tmp_path


def test_the_same_name_under_two_subsections_gets_its_own_ids_images(two_sections):
    path = _stub_doc(two_sections / "doc.docx", [
        ("2. Youth and teens", "Youth", [NAME]),
        ("4. Learning", "Science & STEM kits", [NAME]),
    ])
    index = {(NAME, "2", "Youth"): ["e30"],
             (NAME, "4", "Science & STEM kits"): ["e55"]}

    result = add_images.main(path=path, index=index)

    assert result["missing"] == []
    assert result["placed"] == 2
    blobs = _embedded_blobs(path)
    assert blobs == [(two_sections / "e30_0.jpg").read_bytes(),
                     (two_sections / "e55_0.jpg").read_bytes()]


def test_a_new_entry_inserted_earlier_does_not_steal_another_entrys_images(two_sections):
    """The demonstrated failure: accept a resubmission of the anatomy model
    into section 1 and it takes e89. The document's first occurrence of the
    name is then the new entry, which under name-only pairing was handed e30's
    images, e30 got e55's, and e55 got none — three entries silently wrong from
    one insertion, with `missing` reporting nothing."""
    _make_image(two_sections / "e89_0.jpg", (30, 20), (0, 255, 0))
    path = _stub_doc(two_sections / "doc.docx", [
        ("1. Basics", "Adult", [NAME]),
        ("2. Youth and teens", "Youth", [NAME]),
        ("4. Learning", "Science & STEM kits", [NAME]),
    ])
    index = {(NAME, "1", "Adult"): ["e89"],
             (NAME, "2", "Youth"): ["e30"],
             (NAME, "4", "Science & STEM kits"): ["e55"]}

    result = add_images.main(path=path, index=index)

    assert result["missing"] == []
    assert _embedded_blobs(path) == [(two_sections / "e89_0.jpg").read_bytes(),
                                     (two_sections / "e30_0.jpg").read_bytes(),
                                     (two_sections / "e55_0.jpg").read_bytes()]


def test_an_ambiguous_pairing_is_reported_rather_than_resolved(two_sections, capsys):
    """Two entries with the same name in the same subsection cannot be told
    apart from the document, so neither gets images and the run says so."""
    path = _stub_doc(two_sections / "doc.docx", [
        ("2. Youth and teens", "Youth", [NAME, NAME]),
    ])
    index = {(NAME, "2", "Youth"): ["e30", "e55"]}

    result = add_images.main(path=path, index=index)

    assert result["placed"] == 0
    assert result["ambiguous"] == {(NAME, "2", "Youth"): ["e30", "e55"]}
    assert len(result["missing"]) == 2
    assert _embedded_blobs(path) == []
    assert "AMBIGUOUS" in capsys.readouterr().out


def test_walk_tracks_the_section_and_subsection_in_scope(two_sections):
    path = _stub_doc(two_sections / "doc.docx", [
        ("1. Basics & everyday", "Adult", ["Shark socks"]),
        ("2. Youth and teens", "Youth", [NAME]),
    ])
    found = add_images.walk(docx.Document(path).paragraphs)
    assert [(f[2], f[3]) for f in found] == [("1", "Adult"), ("2", "Youth")]
    assert all(f[1] is not None for f in found), "every entry found its NGO line"


def test_every_entry_heading_is_still_promoted_even_when_unmatched(two_sections):
    path = _stub_doc(two_sections / "doc.docx", [
        ("9. Nowhere", "Nothing", ["An item with no id at all"]),
    ])
    result = add_images.main(path=path, index={})
    assert result["headings"] == 1
    assert result["missing"] == [("An item with no id at all", "9", "Nothing")]
    styles = [p.style.name for p in docx.Document(path).paragraphs
              if p.text.startswith("▸ ")]
    assert styles == ["Heading 3"]
