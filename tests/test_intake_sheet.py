import openpyxl
import pytest

import intake_sheet
import pool


ROW = dict(queue_id="q0001", message_id="m1", received="2026-08-28T09:14:02-07:00",
           sender="Simon Dedman", note="nephew has a pair",
           url="https://shop.com/products/socks", url_norm="https://shop.com/products/socks",
           fetch_status="OK", http=200, fetch_note="fetched", title="Shark socks",
           price="~£12.50", price_source="itemprop",
           ngo_text="5% of profits go to the Shark Trust.", section="1", sub="Adult",
           age="Adult", keyword="socks", duplicate_of="", candidates=[], picked="")

BLOCKED = dict(ROW, queue_id="q0002", fetch_status="BLOCKED", http=403, title="",
               price="", price_source="", ngo_text="", section="", sub="", keyword="")


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "review.xlsx"
    intake_sheet.write_workbook([ROW, BLOCKED], path)
    return openpyxl.load_workbook(path)


def test_info_tab_is_first(book):
    assert book.sheetnames[0] == "Info"


def test_review_tab_exists(book):
    assert "Review" in book.sheetnames


def test_header_row_is_frozen_bold_and_filtered(book):
    ws = book["Review"]
    assert ws.freeze_panes == "A2"
    assert ws["A1"].font.bold is True
    assert ws.auto_filter.ref is not None


def test_status_column_is_first_and_empty(book):
    ws = book["Review"]
    assert ws["A1"].value == "Status"
    assert ws["A2"].value in (None, "")


def test_every_row_reaches_the_sheet(book):
    ws = book["Review"]
    assert ws.max_row == 3


def test_scraped_values_are_pre_filled(book):
    ws = book["Review"]
    headers = [c.value for c in ws[1]]
    row = {h: ws.cell(row=2, column=i + 1).value for i, h in enumerate(headers)}
    assert row["Item"] == "Shark socks"
    assert row["Approx. price"] == "~£12.50"
    assert row["Suggested by"] == "Simon Dedman"
    assert row["Description"] in (None, "")


def test_a_blocked_row_says_blocked_and_does_not_look_empty(book):
    ws = book["Review"]
    headers = [c.value for c in ws[1]]
    row = {h: ws.cell(row=3, column=i + 1).value for i, h in enumerate(headers)}
    assert row["Fetch"] == "BLOCKED"
    assert row["Item"] in (None, "")


def test_info_tab_states_the_counts_and_the_last_poll(book):
    text = " ".join(str(c.value) for r in book["Info"].iter_rows() for c in r if c.value)
    assert "BLOCKED" in text
    assert "last successful poll" in text.lower()
    assert "ACCEPT" in text and "REJECT" in text and "HOLD" in text


# --- Important 4: fetch_note and the HTTP status were written into every queue
# row and read by nothing, so a crashed image harvest looked exactly like a
# page with no usable images. ---

def test_the_fetch_note_reaches_a_column(tmp_path):
    row = dict(ROW, fetch_note="fetched; IMAGE HARVEST FAILED (TimeoutError: read timed out)")
    path = tmp_path / "review.xlsx"
    intake_sheet.write_workbook([row], path)
    ws = openpyxl.load_workbook(path)["Review"]
    headers = [c.value for c in ws[1]]
    assert "Fetch note" in headers
    cell = ws.cell(row=2, column=headers.index("Fetch note") + 1)
    assert "IMAGE HARVEST FAILED" in cell.value


def test_the_http_status_reaches_a_column(book):
    ws = book["Review"]
    headers = [c.value for c in ws[1]]
    assert "HTTP" in headers
    assert ws.cell(row=3, column=headers.index("HTTP") + 1).value == 403


def test_an_unused_evidence_column_is_still_hidden(tmp_path):
    """The hide-empty rule keeps the new columns from crowding the sheet when
    every fetch went cleanly."""
    row = dict(ROW, fetch_note="", http=None)
    path = tmp_path / "review.xlsx"
    intake_sheet.write_workbook([row], path)
    ws = openpyxl.load_workbook(path)["Review"]
    headers = [c.value for c in ws[1]]
    from openpyxl.utils import get_column_letter
    col = get_column_letter(headers.index("Fetch note") + 1)
    assert ws.column_dimensions[col].hidden is True


# --- Important 7: the contact sheet showed twelve candidates in harvest order,
# not pool.py's ranking, so on a page with 88 candidates the twelve Simon saw
# were an unrepresentative slice of the page. ---

CANDS = [
    dict(url="https://shop.com/img/footer-logo.png", title="", src="img"),
    dict(url="https://shop.com/img/shark-socks-1200x.jpg", title="Shark socks",
         src="shopify-product"),
    dict(url="https://shop.com/img/banner.png", title="", src="meta"),
]


def test_the_contact_sheet_is_ranked_not_page_ordered():
    ranked = intake_sheet.ranked_candidates(dict(ROW, candidates=CANDS))
    assert [c["src"] for c in ranked] == ["shopify-product", "meta", "img"]


def test_ranking_is_stable_for_equally_scored_candidates():
    same = [dict(url=f"https://shop.com/{i}.jpg", title="", src="img") for i in range(5)]
    ranked = intake_sheet.ranked_candidates(dict(ROW, candidates=same))
    assert [c["url"] for c in ranked] == [c["url"] for c in same]


def test_a_row_with_no_candidates_ranks_to_nothing():
    assert intake_sheet.ranked_candidates(dict(ROW, candidates=[])) == []


# --- A real Amazon submission (https://www.amazon.com/dp/B07MXKZJDP) came
# back with 93 candidates that were almost all the same handful of photos
# repeated across two hosts and a dozen sizes, plus a "customers also
# bought" strip of other products' thumbnails outranking the item's own
# picture by pool.score alone. ---

AMZ_ROW = dict(ROW, url="https://www.amazon.com/dp/B07MXKZJDP", title="Shark coin pouch")


def test_amazon_candidates_are_deduped_by_image_id_across_both_hosts(monkeypatch):
    """The same photograph, at both Amazon image hosts and several size
    suffixes, must occupy exactly one cell."""
    monkeypatch.setattr(pool, "amazon_gallery_ids", lambda url: set())
    cands = [
        dict(url="https://m.media-amazon.com/images/I/61WeTCSYyoL._AC_SL1500_.jpg",
             title="", src="img"),
        dict(url="https://m.media-amazon.com/images/I/61WeTCSYyoL._AC_SY355_.jpg",
             title="", src="img"),
        dict(url="https://images-na.ssl-images-amazon.com/images/I/"
                 "61WeTCSYyoL._AC_UL165_SR165,165_.jpg", title="", src="img"),
        dict(url="https://m.media-amazon.com/images/I/71ZNXxkkJPL._AC_SX679_.jpg",
             title="", src="img"),
    ]
    ranked = intake_sheet.ranked_candidates(dict(AMZ_ROW, candidates=cands))
    assert len(ranked) == 2
    assert {c["url"] for c in ranked} == {
        "https://m.media-amazon.com/images/I/61WeTCSYyoL.jpg",
        "https://m.media-amazon.com/images/I/71ZNXxkkJPL.jpg",
    }


def test_amazon_candidates_normalise_every_documented_suffix_shape(monkeypatch):
    monkeypatch.setattr(pool, "amazon_gallery_ids", lambda url: set())
    cands = [
        dict(url="https://images-na.ssl-images-amazon.com/images/I/"
                 "XID1._AC_UL165_SR165,165_.jpg", title="", src="img"),
        dict(url="https://m.media-amazon.com/images/I/XID2._AC_US40_.jpg",
             title="", src="img"),
        dict(url="https://m.media-amazon.com/images/I/XID3.__AC_SR166,182___.jpg",
             title="", src="img"),
        dict(url="https://m.media-amazon.com/images/I/"
                 "XID4._AC_SY300_SX300_QL70_FMwebp_.jpg", title="", src="img"),
    ]
    ranked = intake_sheet.ranked_candidates(dict(AMZ_ROW, candidates=cands))
    assert {c["url"] for c in ranked} == {
        f"https://m.media-amazon.com/images/I/XID{n}.jpg" for n in range(1, 5)
    }


def test_gallery_ids_are_ranked_ahead_of_a_higher_scored_recommendation(monkeypatch):
    """The item's own photo (low pool.score, since it carries no matching
    title words and no size hint) must still beat a recommendation-strip
    thumbnail that happens to score higher on those grounds alone."""
    monkeypatch.setattr(pool, "amazon_gallery_ids",
                        lambda url: {"OWNPHOTO"} if "amazon" in url else set())
    cands = [
        dict(url="https://images-na.ssl-images-amazon.com/images/I/"
                 "OTHERPRODUCT._AC_UL165_SR165,165_.jpg",
             title="shark coin pouch large 1200x", src="img"),
        dict(url="https://m.media-amazon.com/images/I/OWNPHOTO._AC_SY355_.jpg",
             title="", src="img"),
    ]
    ranked = intake_sheet.ranked_candidates(dict(AMZ_ROW, candidates=cands))
    assert pool.amazon_image_id(ranked[0]["url"]) == "OWNPHOTO"


def test_gallery_bonus_does_not_apply_off_amazon(monkeypatch):
    """A non-Amazon row never calls out to amazon_gallery_ids's network/cache
    path at all, so ranking for every other shop is unaffected."""
    calls = []

    def fake_gallery_ids(url):
        calls.append(url)
        return set()
    monkeypatch.setattr(pool, "amazon_gallery_ids", fake_gallery_ids)
    intake_sheet.ranked_candidates(dict(ROW, candidates=CANDS))
    assert calls == [ROW["url"]]  # called, but correctly returns nothing for a non-Amazon URL


def test_amazon_gallery_ids_returns_nothing_for_a_non_amazon_url():
    assert pool.amazon_gallery_ids("https://shop.com/products/socks") == set()


# --- Important 10: the index-to-candidate contract was asserted nowhere. The
# number drawn under cell j must be the index that selects ranked[j]. ---

def test_the_drawn_index_labels_follow_the_ranked_candidate_list(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_sheet, "SHEETS", tmp_path)
    asked = []

    def fake_download(url, referer=None):
        asked.append(url)
        return None, "stubbed"
    monkeypatch.setattr(intake_sheet, "download", fake_download)

    row = dict(ROW, candidates=CANDS)
    out = intake_sheet.contact_sheet(row)
    assert out == tmp_path / "pending_q0001.jpg"
    assert out.exists()
    # cell 0 is drawn from the first ranked candidate, cell 1 from the second,
    # and so on: the labels are positions in this list, and nothing else.
    assert asked == [c["url"] for c in intake_sheet.ranked_candidates(row)]


# --- Important 12: a second run on the same day silently destroyed an evening
# of description prose. ---

def test_build_does_not_overwrite_todays_workbook(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    intake_sheet.intake_queue.save_queue([dict(ROW, candidates=[])])

    first = intake_sheet.build()
    first.write_bytes(first.read_bytes() + b"")   # stands in for an edited file
    marker = first.stat().st_size
    second = intake_sheet.build()

    assert second != first
    assert first.exists() and first.stat().st_size == marker


def test_build_refuses_an_explicit_path_that_already_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    intake_sheet.intake_queue.save_queue([dict(ROW, candidates=[])])
    target = tmp_path / "review.xlsx"
    target.write_text("an evening of prose")
    with pytest.raises(SystemExit):
        intake_sheet.build(path=target)
    assert target.read_text() == "an evening of prose"


def test_force_overwrites_deliberately(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    intake_sheet.intake_queue.save_queue([dict(ROW, candidates=[])])
    target = tmp_path / "review.xlsx"
    target.write_text("stale")
    assert intake_sheet.build(path=target, force=True) == target
    assert openpyxl.load_workbook(target).sheetnames[0] == "Info"


# --- Critical 1: an unreadable queue must not report itself as an empty one. ---

def test_build_on_a_corrupt_queue_raises_rather_than_saying_it_is_empty(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    (tmp_path / "queue.json").write_text('[{"queue_id": "q0001"}, {"que')
    with pytest.raises(intake_sheet.intake_queue.CorruptStateError):
        intake_sheet.build()
    assert "queue is empty" not in capsys.readouterr().out


# --- New feature: sheet_for_queue() picks which workbook a click should open.
# It must never open a stale sheet, and must never rebuild (and so risk
# clobbering) one that already matches the pending queue exactly. ---

def test_sheet_queue_ids_reads_the_queue_id_column(tmp_path):
    path = tmp_path / "review.xlsx"
    intake_sheet.write_workbook([ROW, BLOCKED], path)
    assert intake_sheet.sheet_queue_ids(path) == {"q0001", "q0002"}


def test_sheet_for_queue_with_an_empty_queue_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    intake_sheet.intake_queue.save_queue([])
    assert intake_sheet.sheet_for_queue() == (None, False)


def test_sheet_for_queue_reuses_an_exact_match(tmp_path, monkeypatch):
    """A sheet whose queue ids equal the pending set is reused untouched, so
    description prose already typed into it is never lost."""
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    intake_sheet.intake_queue.save_queue(
        [dict(ROW, candidates=[]), dict(BLOCKED, candidates=[])])

    built = intake_sheet.build()
    built.write_bytes(built.read_bytes() + b"")  # stands in for edited prose
    marker = built.stat().st_size

    path, was_built = intake_sheet.sheet_for_queue()
    assert path == built
    assert was_built is False
    assert path.stat().st_size == marker


def test_sheet_for_queue_builds_fresh_when_a_new_submission_has_arrived(
        tmp_path, monkeypatch):
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    intake_sheet.intake_queue.save_queue([dict(ROW, candidates=[])])
    first = intake_sheet.build()

    intake_sheet.intake_queue.save_queue(
        [dict(ROW, candidates=[]), dict(BLOCKED, candidates=[])])
    path, was_built = intake_sheet.sheet_for_queue()

    assert was_built is True
    assert path != first
    assert intake_sheet.sheet_queue_ids(path) == {"q0001", "q0002"}


def test_sheet_for_queue_ignores_a_sheet_for_a_different_set(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_sheet, "INTAKE", tmp_path)
    monkeypatch.setattr(intake_sheet.intake_queue, "QUEUE", tmp_path / "queue.json")
    intake_sheet.intake_queue.save_queue([dict(BLOCKED, candidates=[])])
    stale = intake_sheet.build()

    intake_sheet.intake_queue.save_queue([dict(ROW, candidates=[])])
    path, was_built = intake_sheet.sheet_for_queue()

    assert was_built is True
    assert path != stale
    assert intake_sheet.sheet_queue_ids(path) == {"q0001"}
