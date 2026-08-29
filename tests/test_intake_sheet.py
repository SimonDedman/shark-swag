import openpyxl
import pytest

import intake_sheet


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
