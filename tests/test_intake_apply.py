import json

import pytest

import intake_apply
import intake_sheet


def sheet_row(**over):
    base = dict(queue_id="q0001", message_id="m1", received="2026-08-28T09:14:02-07:00",
                sender="Simon Dedman", note="", url="https://shop.com/products/socks",
                url_norm="https://shop.com/products/socks", fetch_status="OK", http=200,
                fetch_note="fetched", title="Shark socks", price="~£12.50",
                price_source="itemprop", ngo_text="5% donated.", section="1",
                sub="Adult", age="Adult", keyword="socks", duplicate_of="",
                candidates=[], picked="")
    base.update(over)
    return base


@pytest.fixture
def workbook(tmp_path):
    def build(rows, statuses, descriptions=None):
        path = tmp_path / "review.xlsx"
        intake_sheet.write_workbook(rows, path)
        import openpyxl
        wb = openpyxl.load_workbook(path)
        ws = wb["Review"]
        headers = [c.value for c in ws[1]]
        for i, (status, desc) in enumerate(zip(statuses, descriptions or [""] * len(rows)), 2):
            ws.cell(row=i, column=headers.index("Status") + 1, value=status)
            ws.cell(row=i, column=headers.index("Description") + 1, value=desc)
        wb.save(path)
        return path
    return build


def test_read_workbook_returns_one_dict_per_row(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], ["Bamboo socks."])
    rows = intake_apply.read_workbook(path)
    assert len(rows) == 1
    assert rows[0]["Status"] == "ACCEPT"
    assert rows[0]["Description"] == "Bamboo socks."
    assert rows[0]["Queue id"] == "q0001"


def test_a_blank_status_reads_as_hold(workbook):
    path = workbook([sheet_row()], [None])
    assert intake_apply.read_workbook(path)[0]["Status"] == "HOLD"


def test_validate_refuses_an_accepted_row_with_no_description(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], [""])
    errors = intake_apply.validate(intake_apply.read_workbook(path))
    assert errors
    assert "q0001" in errors[0]
    assert "Description" in errors[0]


def test_validate_refuses_an_accepted_row_with_no_section(workbook):
    path = workbook([sheet_row(section="")], ["ACCEPT"], ["Bamboo socks."])
    errors = intake_apply.validate(intake_apply.read_workbook(path))
    assert any("Section" in e for e in errors)


def test_validate_refuses_a_subsection_that_does_not_exist(workbook):
    path = workbook([sheet_row(sub="Grown-ups")], ["ACCEPT"], ["Bamboo socks."])
    errors = intake_apply.validate(intake_apply.read_workbook(path))
    assert any("Grown-ups" in e for e in errors)


def test_validate_passes_a_complete_row(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], ["Bamboo socks."])
    assert intake_apply.validate(intake_apply.read_workbook(path)) == []


def test_rejected_and_held_rows_are_not_validated(workbook):
    path = workbook([sheet_row(section=""), sheet_row(queue_id="q0002", section="")],
                    ["REJECT", "HOLD"], ["", ""])
    assert intake_apply.validate(intake_apply.read_workbook(path)) == []


def test_apply_row_inserts_into_the_named_subsection_with_a_fresh_id():
    data = {"sections": [{"number": "1", "title": "t", "subsections":
                          [{"name": "Adult", "items": [{"id": "e01", "item": "x",
                                                        "link": "https://a"}]}]}]}
    row = {"Status": "ACCEPT", "Section": "1", "Subsection": "Adult",
           "Item": "Shark socks", "Age": "Adult", "Link": "https://shop.com/p",
           "Approx. price": "~£12.50", "Description": "Bamboo socks.",
           "Suggested by": "Simon Dedman",
           "NGO / proceeds to conservation?": "5% donated.", "Image pick": "",
           "Queue id": "q0001"}
    new_id = intake_apply.apply_row(row, data)
    items = data["sections"][0]["subsections"][0]["items"]
    assert len(items) == 2
    assert items[1]["id"] == new_id
    assert items[1]["item"] == "Shark socks"
    assert items[1]["desc"] == "Bamboo socks."
    assert items[1]["by"] == "Simon Dedman"
    assert new_id != "e01"


def test_apply_row_does_not_disturb_existing_ids():
    data = {"sections": [{"number": "1", "title": "t", "subsections":
                          [{"name": "Adult", "items": [{"id": "e01", "item": "x",
                                                        "link": "https://a"}]}]}]}
    row = {"Status": "ACCEPT", "Section": "1", "Subsection": "Adult",
           "Item": "Shark socks", "Age": "Adult", "Link": "https://shop.com/p",
           "Approx. price": "", "Description": "d", "Suggested by": "s",
           "NGO / proceeds to conservation?": "", "Image pick": "", "Queue id": "q0001"}
    intake_apply.apply_row(row, data)
    assert data["sections"][0]["subsections"][0]["items"][0]["id"] == "e01"


# --- Task 11 addition: an Image pick index must be one Simon actually saw on
# the contact sheet (which lays out only the first CONTACT_SHEET_COLS
# candidates), and must exist among this row's own candidates. ---

def test_validate_refuses_an_image_pick_off_the_contact_sheet(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], ["Bamboo socks."])
    rows = intake_apply.read_workbook(path)
    rows[0]["Image pick"] = str(intake_apply.CONTACT_SHEET_COLS)
    queue = {"q0001": {"candidates": [{"url": f"https://x/{i}.jpg"} for i in range(20)]}}
    errors = intake_apply.validate(rows, queue)
    assert errors
    assert "q0001" in errors[0]
    assert str(intake_apply.CONTACT_SHEET_COLS) in errors[0]


def test_validate_refuses_an_image_pick_past_this_rows_own_candidates(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], ["Bamboo socks."])
    rows = intake_apply.read_workbook(path)
    rows[0]["Image pick"] = "3"
    queue = {"q0001": {"candidates": [{"url": "https://x/0.jpg"}, {"url": "https://x/1.jpg"}]}}
    errors = intake_apply.validate(rows, queue)
    assert errors
    assert "q0001" in errors[0]
    assert "3" in errors[0]


def test_validate_accepts_an_in_range_image_pick(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], ["Bamboo socks."])
    rows = intake_apply.read_workbook(path)
    rows[0]["Image pick"] = "1"
    queue = {"q0001": {"candidates": [{"url": "https://x/0.jpg"}, {"url": "https://x/1.jpg"}]}}
    assert intake_apply.validate(rows, queue) == []
