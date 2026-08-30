#!/usr/bin/env python3
"""Turn the pending queue into a review workbook, with a contact sheet per item.

House rules: the Info tab is ordered first, with a frozen, bold heading, and
says what was already done and what the reader must do; the Review tab carries
the frozen, bold, autofiltered header row. Evidence columns sit to the right
of the editable ones, so a guess can always be traced to what produced it.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import DEFAULT_ROW_HEIGHT, points_to_pixels
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.hyperlink import Hyperlink
from PIL import Image, ImageDraw, ImageFont

import entries
import intake_queue
# The ranking below needs pool.score, but importing this also inherits pool.py's
# import-time side effects: it inserts the project root onto sys.path and
# creates images/pool and images/sheets if they are missing. Harmless, but
# anything that imports this module (intake_apply included) inherits it too.
import pool
from imgproc import autocrop, download, load
from paths import HEARTBEAT, INTAKE, SHEETS

# (header, width, source key, editable)
COLUMNS = [
    ("Status", 9, None, True),
    ("Section", 10, "section", True),
    ("Subsection", 20, "sub", True),
    ("Item", 40, "title", True),
    ("Age", 14, "age", True),
    ("Link", 34, "url", True),
    ("Approx. price", 13, "price", True),
    ("Description", 52, None, True),
    ("Suggested by", 18, "sender", True),
    ("NGO?", 10, None, True),
    ("NGO / proceeds to conservation?", 40, "ngo_text", True),
    ("Image pick", 11, "picked", True),
    ("Fetch", 9, "fetch_status", False),
    ("Price source", 12, "price_source", False),
    ("Section keyword", 16, "keyword", False),
    ("Duplicate of", 12, "duplicate_of", False),
    ("Their note", 34, "note", False),
    ("Received", 20, "received", False),
    ("Contact sheet", 14, None, False),
    ("Fetch note", 46, "fetch_note", False),
    ("HTTP", 7, "http", False),
    ("Queue id", 10, "queue_id", False),
]

EVIDENCE_FILL = PatternFill("solid", fgColor="F2F2F2")
# Excel's own conventional hyperlink colours: a relationship-backed
# cell.hyperlink is what LibreOffice actually follows on click, but nothing
# makes it look clickable on its own, so the font is set to match.
HYPERLINK_FONT = Font(color="0563C1", underline="single")
CELL, HDR, COLS = 190, 30, 12

# The INDIRECT()-based per-section Subsection dropdown is built and correct
# - the named ranges it depends on are right (sub_5 -> Lists!$I$2:$I$3,
# holding Kids and Youth) - but Simon confirmed LibreOffice renders it as an
# empty dropdown on his machine regardless. False falls back to one flat
# list of every subsection name across every section, with no filtering by
# Section. Either way, intake_apply.validate() still refuses a subsection
# that does not belong to the chosen section and names the valid ones, so a
# dropdown that fails to appear costs typing, never a bad write. Only worth
# flipping back to True if this workbook is ever opened in Excel instead of
# LibreOffice.
DEPENDENT_SUBSECTION_DROPDOWN = False

STATUS_OPTIONS = ["ACCEPT", "REJECT", "HOLD"]
NGO_OPTIONS = ["Yes", "No", "Not stated"]

# Data validation ranges reach this far past the last data row, so pasting
# extra rows in below the fetched ones still gets a working dropdown.
VALIDATION_ROW_MARGIN = 500

_NGO_NEGATIVE = re.compile(
    r"\bno\s+donation|\bnot\s+applicable\b|\bnot\s+stated\b|\bdoes\s+not\s+donate\b|"
    r"\bno\s+charity\b|\bnot\s+a\s+registered\s+charity\b", re.I)


def guess_ngo_flag(ngo_text):
    """Yes, No, or Not stated for the new NGO? column, guessed from the
    verbatim ngo_text sentence. It is a guess like any other guess in this
    sheet: editable, and it never overwrites the quote itself."""
    text = str(ngo_text or "").strip()
    if not text:
        return "Not stated"
    if _NGO_NEGATIVE.search(text):
        return "No"
    return "Yes"


def section_choices():
    """[(number, label)] for every section in items.json, in document order,
    e.g. ('5', '5. \U0001f3a8 Arts, crafts & stationery')."""
    return [(s["number"], f"{s['number']}. {s['title']}")
            for s in entries.load_items()["sections"]]


def section_label(number):
    """'5' -> '5. \U0001f3a8 Arts, crafts & stationery'. A blank number stays
    blank; an unrecognised one is returned unchanged rather than guessed at,
    so a hand-typed oddity is visible instead of silently swallowed."""
    number = str(number or "").strip()
    if not number:
        return ""
    for num, label in section_choices():
        if num == number:
            return label
    return number


def subsections_for(number):
    """The subsection names that belong to one section number, in document
    order. Reads items.json directly rather than through intake_classify's
    cached lookup, so a test that points entries.ITEMS at a temp file is
    reflected here immediately rather than through a stale cache."""
    number = str(number or "").strip()
    for s in entries.load_items()["sections"]:
        if s["number"] == number:
            return [sub["name"] for sub in s["subsections"]]
    return []


def distinct_ages():
    """Every distinct Age value used anywhere in items.json, including the
    compound ones ("Kids / Youth / Adult" and similar), so an existing value
    already in the document never fails its own dropdown."""
    ages = set()
    for s in entries.load_items()["sections"]:
        for sub in s["subsections"]:
            for item in sub["items"]:
                age = str(item.get("age", "")).strip()
                if age:
                    ages.add(age)
    return sorted(ages)


GALLERY_BONUS = 1000  # far above pool.score's own point scale


def ranked_candidates(row):
    """This row's candidates in the order the contact sheet lays them out.

    The sheet's numbers are what Simon types into Image pick, so exactly one
    function may decide that order: intake_apply resolves a picked index
    through this same call. Ranking is pool.score, against the words of the
    row's own title, the way pool.build_pools derives them - with two
    corrections pool.score alone does not make.

    First, every candidate URL is run through pool.clean() and deduplicated
    by the Amazon image id it resolves to (falling back to the bare URL for
    anything that is not an Amazon image): an Amazon product page repeats the
    same handful of photographs at both its image hosts and a dozen size
    suffixes, so without this a 93-candidate page can be almost entirely one
    picture shown ninety different ways.

    Second, a candidate whose id appears in the product's own image block
    (pool.amazon_gallery_ids) gets a bonus large enough to always outrank one
    that does not, so the item's real photos sort ahead of a same-scored
    thumbnail from a "customers also bought" strip rather than being
    interleaved with it by chance.

    Python's sort is stable, so candidates left equally ranked after both
    corrections keep harvest order.
    """
    cands = row.get("candidates") or []
    words = set(re.findall(r"[a-z]{4,}", (row.get("title") or "").lower()))
    gallery_ids = pool.amazon_gallery_ids(row.get("url", ""))

    deduped, seen = [], set()
    for c in cands:
        url = pool.clean(c.get("url", ""))
        key = pool.amazon_image_id(url) or url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(c, url=url))

    def rank(c):
        # A hand-edited or older queue row may be missing a key pool.score
        # indexes directly; scoring it low is right, crashing the apply is not.
        score = pool.score(dict(url=c.get("url", ""), title=c.get("title", ""),
                                src=c.get("src", "")), words)
        if pool.amazon_image_id(c.get("url", "")) in gallery_ids:
            score += GALLERY_BONUS
        return score

    return sorted(deduped, key=rank, reverse=True)


def contact_sheet(row):
    """A numbered grid of this item's candidate images. Returns None when the
    fetch was blocked or produced no candidates: an absent sheet must not be
    read as 'no good image exists'."""
    cands = ranked_candidates(row)
    if not cands:
        return None
    SHEETS.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    except OSError:
        font = small = ImageFont.load_default()

    cands = cands[:COLS]
    sheet = Image.new("RGB", (COLS * CELL + 20, CELL + HDR + 20), (250, 250, 250))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 6), f"[{row['queue_id']}] {(row.get('title') or row['url'])[:110]}",
              fill=(0, 0, 0), font=font)
    x, y = 10, HDR
    for j, c in enumerate(cands):
        draw.rectangle([x, y, x + CELL - 6, y + CELL - 6], outline=(200, 200, 200))
        draw.text((x + 3, y + CELL - 22), str(j), fill=(120, 120, 120), font=small)
        path, _note = download(c["url"], referer=row["url"])
        if path:
            try:
                im, _ = autocrop(load(path))
                im.thumbnail((CELL - 14, CELL - 14))
                sheet.paste(im, (x + 3 + (CELL - 14 - im.size[0]) // 2,
                                 y + 3 + (CELL - 14 - im.size[1]) // 2))
            except Exception:
                draw.text((x + 8, y + 8), "decode failed", fill=(160, 0, 0), font=small)
        x += CELL
    out = SHEETS / f"pending_{row['queue_id']}.jpg"
    sheet.save(out, "JPEG", quality=88)
    return out


def ensure_contact_sheet(row):
    """This row's contact sheet path, regenerating the JPG first if it is
    missing - deleted by an unrelated cleanup, say - so a gone cache file
    repairs itself rather than silently breaking review. Regenerating costs
    nothing but CPU: imgproc.download caches by URL, so the source images do
    not come off the network again.

    Returns None, never a path to a file that does not exist, when the row
    has no candidates to draw at all; callers must tell that apart from a
    row whose sheet merely needed rebuilding.
    """
    sheet_path = SHEETS / f"pending_{row['queue_id']}.jpg"
    if not sheet_path.exists():
        contact_sheet(row)
    return sheet_path if sheet_path.exists() else None


# Excel/LibreOffice's own default row height, converted to the pixels an
# embedded image's height is measured in, so the row span reserved for a
# contact sheet is derived from its actual size rather than a guessed constant.
_ROW_HEIGHT_PX = points_to_pixels(DEFAULT_ROW_HEIGHT)

IMAGES_NOTE = (
    "Each picture below is numbered from zero, left to right. The number under "
    "the picture you want goes in Image pick on the Review tab; give several, "
    "comma-separated, to keep more than one. Only the pictures shown here, up "
    "to twelve per item, can be chosen."
)


def _rows_spanned(height_px, row_height_px=_ROW_HEIGHT_PX):
    """How many worksheet rows an embedded image this tall occupies at the
    sheet's default row height, plus one blank row of clearance so the next
    heading is never overlapped."""
    return -(-height_px // row_height_px) + 1  # ceil(height / row_height) + 1


def _image_heading(row):
    """'q0001 — Hide & Drink shark coin pouch'. Falls back to the URL the
    same way contact_sheet's own banner text does, so a title-less row still
    gets a readable heading rather than a blank one."""
    return f"{row['queue_id']} — {(row.get('title') or row['url']).strip()}"


def build_images_sheet(wb, rows):
    """The Images tab: the workbook's own copy of every pending row's contact
    sheet, embedded rather than linked, so review never depends on a cached
    JPG surviving on disk after the workbook is built. Ordered last, after
    Info, Review, and Lists.

    A row with no candidates gets its heading and an explanatory line instead
    of a silent gap, so it reads as "this page yielded no candidates" rather
    than as an oversight.
    """
    ws = wb.create_sheet("Images")
    ws.column_dimensions["A"].width = 118
    note = ws.cell(row=1, column=1, value=IMAGES_NOTE)
    note.font = Font(bold=True)
    note.alignment = Alignment(wrap_text=True, vertical="top")

    r = 3
    for row in rows:
        heading = ws.cell(row=r, column=1, value=_image_heading(row))
        heading.font = Font(bold=True)
        r += 1
        sheet_path = ensure_contact_sheet(row)
        if sheet_path is None:
            ws.cell(row=r, column=1,
                    value="No candidate images were found for this item.")
            r += 2
            continue
        img = XLImage(str(sheet_path))
        ws.add_image(img, f"A{r}")
        r += _rows_spanned(img.height)
    return ws


def _last_poll():
    if not HEARTBEAT.exists():
        return "never - the watcher has not run"
    return HEARTBEAT.read_text().strip()


def _info(ws, rows):
    counts = {}
    for r in rows:
        counts[r.get("fetch_status", "?")] = counts.get(r.get("fetch_status", "?"), 0) + 1
    lines = [
        ("Shark swag: submissions awaiting review", True),
        ("", False),
        (f"Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
         f"from intake/queue.json.", False),
        (f"Watcher's last successful poll: {_last_poll()}.", False),
        (f"Rows by fetch status: "
         f"{', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}.", False),
        ("", False),
        ("What has already happened", True),
        ("Each link was fetched, its title, price, and any sentence about donations "
         "were read off the page, a section and age band were guessed from keywords, "
         "and candidate product images were downloaded into a contact sheet.", False),
        ("Every contact sheet is embedded in this workbook's own Images tab, not "
         "only on disk, so the pictures are right here rather than something you "
         "have to know to go looking for.", False),
        ("Nothing has been written to items.json or the document. No description "
         "prose has been written: that part is yours.", False),
        ("", False),
        ("What you need to do, on the Review tab", True),
        ("1. Read the Fetch column first. OK means the page was read. BLOCKED means "
         "the site refused the request, so its blank fields say nothing about the "
         "product. DEAD means the link no longer resolves to a product. EMPTY means "
         "the page was read and held nothing usable. NO_URL means the message carried "
         "no link at all. Fetch note carries the fetch's own account of itself, "
         "including whether the image harvest ran or crashed, so an empty Contact "
         "sheet cell can be told apart from one that was never filled.", False),
        ("2. Check Duplicate of. An eNN value means this item is already in the "
         "document; a qNNNN value means it is already elsewhere in this sheet.", False),
        ("3. Fill in Description. This is the only field with no scraped source, and "
         "an accepted row will be refused without it.", False),
        ("4. Correct Section, Subsection, Item, Age, and Approx. price where the "
         "guess is wrong. Section keyword shows which rule produced the guess. "
         "Subsection must be one of the names already used in that section of the "
         "document; intake_apply.py will list the valid names if it does not match. "
         "Status, Section, Subsection, Age, and NGO? are all offered as dropdowns, "
         "so the valid options are on screen rather than recalled from memory; the "
         "Lists tab shows every option in full, including all of them by section for "
         "Subsection. Subsection's dropdown is filtered to whichever Section is "
         "already chosen on that row where LibreOffice supports it.", False),
        ("5. Open the contact sheet linked in the Contact sheet column and put the "
         "index of the image you want in Image pick. The sheet shows the twelve "
         "best-ranked candidates, numbered from zero, and only those indices can be "
         "chosen. Several are allowed, comma separated, and each must be a plain "
         "whole number: anything else is refused rather than ignored. Leave it blank "
         "for no image.", False),
        ("6. Set Status to ACCEPT, REJECT, or HOLD. Blank counts as HOLD. ACCEPT adds "
         "the entry; REJECT records the link so it is never queued again; HOLD leaves "
         "it for the next workbook. NGO? is a Yes / No / Not stated guess, pre-filled "
         "from the wording in NGO / proceeds to conservation?, so the sheet can be "
         "filtered by it; correct it if it is wrong, but leave the quoted sentence in "
         "the NGO / proceeds to conservation? column itself alone.", False),
        ("", False),
        ("7. Save the workbook, then run:", True),
        ("   ~/.venvs/scrape/bin/python intake_apply.py", False),
        ("It refuses to run if an accepted row is missing its Section, Subsection, "
         "Item, or Description, and names the rows rather than guessing.", False),
    ]
    for n, (text, bold) in enumerate(lines, 1):
        cell = ws.cell(row=n, column=1, value=text)
        cell.font = Font(bold=bold)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 118
    ws.freeze_panes = "A2"
    ws["A1"].font = Font(bold=True, size=13)


def _write_list_column(ws, col, header, values):
    """One bold-headed column of a controlled vocabulary on the Lists tab.
    Returns how many values were written, so callers can size a range."""
    ws.cell(row=1, column=col, value=header).font = Font(bold=True)
    for i, value in enumerate(values, 2):
        ws.cell(row=i, column=col, value=value)
    width = max([len(str(header))] + [len(str(v)) for v in values] + [8]) + 2
    ws.column_dimensions[get_column_letter(col)].width = min(width, 46)
    return len(values)


def build_lists_sheet(wb):
    """A visible Lists tab, readable as a reference in its own right: one
    bold-headed column per controlled vocabulary, plus one column per section
    holding that section's subsections, plus a flat column of every
    subsection across every section for the non-dependent fallback.

    Also defines the sub_<N> named ranges the dependent Subsection dropdown
    resolves through INDIRECT(). Returns {vocabulary_name: (column, count)},
    used to build the Review tab's data validation ranges.
    """
    ws = wb.create_sheet("Lists")
    ranges = {}
    col = 1

    ranges["Status"] = (col, _write_list_column(ws, col, "Status", STATUS_OPTIONS))
    col += 1

    sections = section_choices()
    ranges["Section"] = (col, _write_list_column(
        ws, col, "Section", [label for _, label in sections]))
    col += 1

    ranges["NGO?"] = (col, _write_list_column(ws, col, "NGO?", NGO_OPTIONS))
    col += 1

    ranges["Age"] = (col, _write_list_column(ws, col, "Age", distinct_ages()))
    col += 1

    sub_ranges = {}
    all_subs = []
    for number, label in sections:
        subs = subsections_for(number)
        for name in subs:
            if name not in all_subs:
                all_subs.append(name)
        sub_ranges[number] = (col, _write_list_column(ws, col, f"Subsections: {label}", subs))
        col += 1

    ranges["All subsections"] = (col, _write_list_column(
        ws, col, "All subsections", sorted(all_subs)))
    col += 1

    for number, (c, n) in sub_ranges.items():
        letter = get_column_letter(c)
        last = max(n + 1, 2)
        wb.defined_names[f"sub_{number}"] = DefinedName(
            f"sub_{number}", attr_text=f"Lists!${letter}$2:${letter}${last}")

    ws.freeze_panes = "A2"
    return ranges


def _list_range_formula(col, count):
    """A cell-range reference into the Lists tab, e.g. 'Lists!$B$2:$B$8'.
    Never an inline list: Section alone runs past the 255-character cap on
    formula1='"a,b,c"'."""
    letter = get_column_letter(col)
    last = max(count + 1, 2)
    return f"Lists!${letter}$2:${letter}${last}"


def _add_dropdown(ws, col_index, formula1, title, prompt, error, n_rows):
    letter = get_column_letter(col_index)
    end_row = max(n_rows + 1, 2) + VALIDATION_ROW_MARGIN
    dv = DataValidation(type="list", formula1=formula1, allow_blank=True,
                        showErrorMessage=True, showInputMessage=True,
                        errorTitle="Not a valid option", error=error,
                        promptTitle=title, prompt=prompt)
    # showDropDown is misleadingly named: openpyxl's own alias for it is
    # hide_drop_down, so leaving it at its default (False) is what SHOWS the
    # arrow. Set nothing here; verify by reading dv.showDropDown back rather
    # than trusting this comment.
    dv.sqref = f"{letter}2:{letter}{end_row}"
    ws.add_data_validation(dv)
    return dv


def _attach_dropdowns(ws, ranges, n_rows):
    """Data validation on the five controlled Review columns, each pointing
    at a range on the Lists tab rather than an inline list."""
    col_index = {header: i for i, (header, _w, _k, _e) in enumerate(COLUMNS, 1)}

    _add_dropdown(
        ws, col_index["Status"], _list_range_formula(*ranges["Status"]), "Status",
        "ACCEPT adds this entry to items.json, REJECT records the link so it is "
        "never queued again, and HOLD leaves it for the next workbook. A blank "
        "cell is read as HOLD.",
        "Choose ACCEPT, REJECT, or HOLD.", n_rows)

    _add_dropdown(
        ws, col_index["Section"], _list_range_formula(*ranges["Section"]), "Section",
        "Pick the section this item belongs to. The full, numbered list is on "
        "the Lists tab.",
        "Choose one of the sections listed on the Lists tab.", n_rows)

    section_letter = get_column_letter(col_index["Section"])
    if DEPENDENT_SUBSECTION_DROPDOWN:
        sub_formula = (f'INDIRECT("sub_"&LEFT(${section_letter}2&".",'
                       f'FIND(".",${section_letter}2&".")-1))')
    else:
        sub_formula = _list_range_formula(*ranges["All subsections"])
    _add_dropdown(
        ws, col_index["Subsection"], sub_formula, "Subsection",
        "Pick a subsection belonging to the chosen Section. If this list does "
        "not filter itself by Section in your copy of LibreOffice, see the "
        "Lists tab for every subsection grouped by section: intake_apply.py "
        "still refuses a mismatched pair and names the valid options, so a "
        "dropdown that fails to appear costs typing, never a bad entry.",
        "This is not one of the subsection names intake_apply.py recognises "
        "for the chosen section.", n_rows)

    _add_dropdown(
        ws, col_index["Age"], _list_range_formula(*ranges["Age"]), "Age",
        "Pick an age band, including a compound one such as "
        '"Kids / Youth / Adult" where that is what the document already uses.',
        "Choose one of the age bands listed on the Lists tab.", n_rows)

    _add_dropdown(
        ws, col_index["NGO?"], _list_range_formula(*ranges["NGO?"]), "NGO?",
        "Yes if the NGO / proceeds column states a donation is made, No if it "
        "states that none is made, and Not stated if it says nothing either "
        "way. This is pre-filled as a guess from that column's wording, so "
        "correct it if it is wrong.",
        "Choose Yes, No, or Not stated.", n_rows)


def write_workbook(rows, path):
    wb = Workbook()
    info = wb.active
    info.title = "Info"
    _info(info, rows)

    ws = wb.create_sheet("Review")
    for i, (header, width, _key, editable) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=i, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="bottom")
        if not editable:
            cell.fill = EVIDENCE_FILL
        ws.column_dimensions[get_column_letter(i)].width = width

    for r, row in enumerate(rows, 2):
        sheet_path = None
        for i, (header, _w, key, editable) in enumerate(COLUMNS, 1):
            if header == "Contact sheet":
                sheet_path = ensure_contact_sheet(row)
                value = "images" if sheet_path else ""
            elif header == "Section":
                value = section_label(row.get(key, ""))
            elif header == "NGO?":
                value = guess_ngo_flag(row.get("ngo_text", ""))
            else:
                value = row.get(key, "") if key else ""
            cell = ws.cell(row=r, column=i, value=value)
            if not editable:
                cell.fill = EVIDENCE_FILL
            if header == "Contact sheet" and sheet_path:
                # A relationship-backed hyperlink, not the HYPERLINK()
                # formula: LibreOffice, which is what actually opens these,
                # does not reliably follow the formula on click, but does
                # follow a real hyperlink relationship. file:// is the
                # target scheme it expects for a local path.
                cell.hyperlink = Hyperlink(ref=cell.coordinate,
                                           target=sheet_path.as_uri())
                cell.font = HYPERLINK_FONT
            if header in ("Description", "NGO / proceeds to conservation?", "Their note"):
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(2, len(rows) + 1)}"

    # hide evidence columns that are empty for every row, to keep the sheet
    # readable on one screen
    for i, (header, _w, key, editable) in enumerate(COLUMNS, 1):
        if editable or not key:
            continue
        if not any(str(row.get(key, "")).strip() for row in rows):
            ws.column_dimensions[get_column_letter(i)].hidden = True

    ranges = build_lists_sheet(wb)
    _attach_dropdowns(ws, ranges, len(rows))

    build_images_sheet(wb, rows)

    wb.save(path)
    return path


def _free_path(force=False):
    """Today's workbook, or a time-suffixed one beside it.

    A second run on the same day must never silently replace the first: an
    evening of description prose lives only in that file, and there is no
    backup. --force is the explicit way to say otherwise.
    """
    now = datetime.now()
    path = INTAKE / f"review_{now.strftime('%Y-%m-%d')}.xlsx"
    if force or not path.exists():
        return path
    for stamp in (now.strftime("%H%M"), now.strftime("%H%M%S")):
        candidate = INTAKE / f"review_{now.strftime('%Y-%m-%d')}_{stamp}.xlsx"
        if not candidate.exists():
            return candidate
    raise SystemExit(f"{path} and its time-suffixed siblings all exist; "
                     f"move them aside or pass --force")


def build(path=None, force=False):
    """Queue to workbook. Raises CorruptStateError rather than reporting an
    empty queue when the queue file cannot be read: "nothing to review" and
    "cannot tell what there is to review" are different answers."""
    rows = intake_queue.load_queue()
    if not rows:
        print("queue is empty, nothing to review")
        return None
    for row in rows:
        ensure_contact_sheet(row)
    if path is None:
        path = _free_path(force)
    elif Path(path).exists() and not force:
        raise SystemExit(f"{path} already exists; pass --force to overwrite it, "
                         f"or move it aside first")
    write_workbook(rows, path)
    print(f"{len(rows)} rows -> {path}")
    return path


def sheet_queue_ids(path):
    """The set of queue ids in an existing review workbook's Review tab."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb["Review"]
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        col = headers.index("Queue id")
        return {str(row[col]) for row in ws.iter_rows(min_row=2, values_only=True)
                if row[col]}
    finally:
        wb.close()


def sheet_for_queue():
    """Which workbook a click on the notification, or the launcher, should
    open. Returns (path, built): built says whether build() had to run.

    Reuses an existing intake/review_*.xlsx whose queue ids exactly match the
    pending queue, newest first, because Simon may already have typed
    description prose into it and a rebuild would silently discard that.
    Anything else - nothing pending, or every existing sheet stale or for a
    different set - means a fresh sheet through the ordinary build().
    """
    rows = intake_queue.load_queue()
    if not rows:
        return None, False
    pending = {row["queue_id"] for row in rows}
    candidates = sorted(INTAKE.glob("review_*.xlsx"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            ids = sheet_queue_ids(path)
        except Exception:
            # Unreadable is not a match; fall through to the next candidate,
            # or to building fresh, rather than opening something broken.
            continue
        if ids == pending:
            return path, False
    return build(), True


# Sentinel exit code for --open-review: distinguishes "nothing pending" (a
# normal outcome the caller should announce) from a real crash, which must
# propagate rather than being read as "nothing to review".
EMPTY_QUEUE_EXIT = 3


if __name__ == "__main__":
    if "--open-review" in sys.argv:
        import contextlib
        import io
        # build(), reached via sheet_for_queue(), prints its own progress
        # line; --open-review's contract with its caller is that stdout
        # carries exactly one line, so that noise is discarded rather than
        # mixed in with the path.
        with contextlib.redirect_stdout(io.StringIO()):
            path, _built = sheet_for_queue()
        if path is None:
            print("queue is empty, nothing to review")
            sys.exit(EMPTY_QUEUE_EXIT)
        print(path)
    else:
        build(force="--force" in sys.argv)
