# Embedded contact sheets in the review workbook

## The problem

The `Contact sheet` column held `=HYPERLINK("/abs/path/pending_q0001.jpg","images")`.
Two faults: LibreOffice wants a `file://` URI, not a bare POSIX path, and the
JPG it pointed at had already been deleted by an earlier cleanup, so the
hyperlink resolved to nothing with no visible sign anything was wrong.

## What was built

`intake_sheet.py`:

- `ensure_contact_sheet(row)` — returns the row's contact-sheet path,
  regenerating the JPG first (via the existing `contact_sheet()`) if it is
  missing, or `None` if the row has no candidates at all. Both the `Contact
  sheet` hyperlink and the new `Images` tab call this, so neither can be
  handed a path to a file that does not exist. `build()`'s own per-row loop
  now calls it too, so a cache file only regenerates when actually absent
  (previously it rebuilt every sheet unconditionally on every `build()`
  call).
- The `Contact sheet` hyperlink now uses `sheet_path.as_uri()`, giving a
  `file://` URI LibreOffice actually opens, and stays blank only when
  `ensure_contact_sheet` genuinely returns `None`.
- A new `Images` worksheet, appended last (`Info`, `Review`, `Lists`,
  `Images`), built by `build_images_sheet(wb, rows)`:
  - a bold note at the top explaining zero-based numbering, comma-separated
    multi-picks, and the twelve-candidate cap;
  - per pending row, in queue order: a bold heading (`q0001 — <title>`),
    then the row's contact sheet embedded with
    `openpyxl.drawing.image.Image`;
  - a row with no candidates gets its heading followed by "No candidate
    images were found for this item." instead of a silent gap;
  - the blank-row gap after each image is computed from the image's actual
    pixel height against the sheet's own default row height
    (`openpyxl.utils.units.DEFAULT_ROW_HEIGHT`/`points_to_pixels`), not a
    guessed constant, so a taller sheet can't collide with the next heading.

## Tests (all in `tests/test_intake_sheet.py`)

Ran `/home/simon/.venvs/scrape/bin/python -m pytest -q`: **269 passed**
(260 pre-existing + 9 new), after updating one pre-existing assertion
(`test_lists_tab_exists_ordered_after_info_and_review`) to include the new
`Images` tab in the expected sheet order.

New tests, each confirmed to fail on the pre-change `intake_sheet.py` (via
`git stash`) and pass after:

- `test_images_tab_embeds_a_real_image_for_a_row_with_candidates` — asserts
  on `ws._images`, i.e. a genuine embed, not just a formula or note.
- `test_images_tab_heading_names_the_queue_id_and_title`
- `test_images_tab_notes_a_row_with_no_candidates_rather_than_a_gap`
- `test_a_second_row_heading_is_never_overlapped_by_the_first_rows_image` —
  derives the minimum required gap from the embedded image's own pixel
  height and checks the actual gap exceeds it.
- `test_contact_sheet_hyperlink_is_a_file_uri`
- `test_contact_sheet_cell_stays_blank_when_there_is_no_sheet`
- `test_build_regenerates_a_deleted_contact_sheet_rather_than_skipping_it` —
  builds, deletes the JPG, rebuilds, and asserts both the JPG and the
  embedded image in `Images` are back.
- `test_ensure_contact_sheet_leaves_an_existing_file_untouched` — regenerate
  only fires on absence, not unconditionally.
- `test_ensure_contact_sheet_returns_none_for_a_row_with_no_candidates`

Confirmed via `git stash push -- intake_sheet.py`: with only the test file
changed, 9 of these fail (`AttributeError`/`KeyError`/assertion mismatches);
`git stash pop` restored the implementation and all 269 passed again.

## LibreOffice round-trip, on the real q0001 row

Regenerated the real, currently-missing `images/sheets/pending_q0001.jpg`
(14,350 bytes) and rebuilt `intake/review_2026-08-29.xlsx` in place via
`intake_sheet.build(path=..., force=True)` — the existing file for today had
no Status/Description/Image pick filled in, so nothing of the owner's was at
risk. `intake/queue.json`'s real `q0001` row was only read, never written.

Round-tripped with:

    soffice --headless --convert-to xlsx --outdir <tmp> intake/review_2026-08-29.xlsx

Result: converts cleanly, no repair dialog. Reopening the converted file
shows all four sheets in order (`Info`, `Review`, `Lists`, `Images`), exactly
one embedded image (2300x240 px, matching the original), the same absolute
anchor position (LibreOffice re-expressed it as a `TwoCellAnchor` with a row
offset in EMU rather than a `OneCellAnchor`, but the true pixel position is
unchanged), and the `Contact sheet` hyperlink formula intact as
`=HYPERLINK("file:///media/simon/data/Projects/shark-swag/images/sheets/pending_q0001.jpg","images")`.

## Workbook size, one real row

`intake/review_2026-08-29.xlsx` (the real q0001 row, rebuilt with the fix):
**16,950 bytes** — up from 10,615 bytes for the previous (broken-hyperlink,
no-Images-tab) version of the same file.
