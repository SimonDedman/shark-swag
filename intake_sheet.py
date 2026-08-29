#!/usr/bin/env python3
"""Turn the pending queue into a review workbook, with a contact sheet per item.

House rules: the Info tab is ordered first, with a frozen, bold heading, and
says what was already done and what the reader must do; the Review tab carries
the frozen, bold, autofiltered header row. Evidence columns sit to the right
of the editable ones, so a guess can always be traced to what produced it.
"""
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont

import intake_queue
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
    ("NGO / proceeds to conservation?", 40, "ngo_text", True),
    ("Image pick", 11, "picked", True),
    ("Fetch", 9, "fetch_status", False),
    ("Price source", 12, "price_source", False),
    ("Section keyword", 16, "keyword", False),
    ("Duplicate of", 12, "duplicate_of", False),
    ("Their note", 34, "note", False),
    ("Received", 20, "received", False),
    ("Contact sheet", 14, None, False),
    ("Queue id", 10, "queue_id", False),
]

EVIDENCE_FILL = PatternFill("solid", fgColor="F2F2F2")
CELL, HDR, COLS = 190, 30, 12


def contact_sheet(row):
    """A numbered grid of this item's candidate images. Returns None when the
    fetch was blocked or produced no candidates: an absent sheet must not be
    read as 'no good image exists'."""
    cands = row.get("candidates") or []
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
        ("Nothing has been written to items.json or the document. No description "
         "prose has been written: that part is yours.", False),
        ("", False),
        ("What you need to do, on the Review tab", True),
        ("1. Read the Fetch column first. OK means the page was read. BLOCKED means "
         "the site refused the request, so its blank fields say nothing about the "
         "product. DEAD means the link no longer resolves to a product. EMPTY means "
         "the page was read and held nothing usable. NO_URL means the message carried "
         "no link at all.", False),
        ("2. Check Duplicate of. An eNN value means this item is already in the "
         "document; a qNNNN value means it is already elsewhere in this sheet.", False),
        ("3. Fill in Description. This is the only field with no scraped source, and "
         "an accepted row will be refused without it.", False),
        ("4. Correct Section, Subsection, Item, Age, and Approx. price where the "
         "guess is wrong. Section keyword shows which rule produced the guess. "
         "Subsection must be one of the names already used in that section of the "
         "document; intake_apply.py will list the valid names if it does not match.",
         False),
        ("5. Open the contact sheet linked in the last column and put the index of "
         "the image you want in Image pick. The sheet shows only the first twelve "
         "candidates, numbered from zero, and only those indices can be chosen. "
         "Several are allowed, comma separated. Leave it blank for no image.", False),
        ("6. Set Status to ACCEPT, REJECT, or HOLD. Blank counts as HOLD. ACCEPT adds "
         "the entry; REJECT records the link so it is never queued again; HOLD leaves "
         "it for the next workbook.", False),
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
        for i, (header, _w, key, editable) in enumerate(COLUMNS, 1):
            if header == "Contact sheet":
                sheet_path = SHEETS / f"pending_{row['queue_id']}.jpg"
                value = (f'=HYPERLINK("{sheet_path}","images")'
                         if sheet_path.exists() else "")
            else:
                value = row.get(key, "") if key else ""
            cell = ws.cell(row=r, column=i, value=value)
            if not editable:
                cell.fill = EVIDENCE_FILL
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

    wb.save(path)
    return path


def build(path=None):
    rows = intake_queue.load_queue()
    if not rows:
        print("queue is empty, nothing to review")
        return None
    for row in rows:
        contact_sheet(row)
    path = path or INTAKE / f"review_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    write_workbook(rows, path)
    print(f"{len(rows)} rows -> {path}")
    return path


if __name__ == "__main__":
    build()
