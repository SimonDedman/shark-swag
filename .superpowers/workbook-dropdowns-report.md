# Workbook dropdowns, Section descriptor, NGO? column, Amazon title fix

## What was built

### 1. A visible Lists tab plus data validation on five Review columns

`intake_sheet.build_lists_sheet()` adds a `Lists` worksheet, created after
`Info` and `Review` so `wb.sheetnames == ["Info", "Review", "Lists"]`. It is
never hidden. Columns, in order: `Status` (ACCEPT/REJECT/HOLD), `Section`
(the full "N. emoji Title" descriptor for every section in `items.json`),
`NGO?` (Yes/No/Not stated), `Age` (every distinct age value used anywhere in
`items.json`, via `distinct_ages()`), one column per section holding that
section's subsections (headed "Subsections: N. Title"), and a final "All
subsections" column (the flat, deduplicated union, for the non-dependent
fallback).

`intake_sheet._attach_dropdowns()` puts `DataValidation(type="list", ...)` on
Status, Section, Subsection, Age, and NGO?, each `formula1` a cell-range
reference into `Lists` (e.g. `Lists!$D$2:$D$14`), never an inline
`"a,b,c"` list — confirmed necessary, since the Section list alone
(7 descriptors with emoji) already exceeds convenient inline length and the
255-character cap would bite as soon as more sections or long subsection
lists were added. Each range extends `VALIDATION_ROW_MARGIN = 500` rows past
the data so pasted rows still validate. Every dropdown carries
`showErrorMessage=True` with a British-English `error`/`errorTitle`, and a
`promptTitle`/`prompt` explaining the field.

**`formula1` deliberately omits the leading `=`** shown in the task's own
example (`"Lists!$A$2:$A$4"`, not `"=Lists!$A$2:$A$4"`). I checked this
empirically: openpyxl writes whatever string is given straight into
`<formula1>`, and a leading `=` produces `<formula1>=Lists!...</formula1>`,
which is not the shape real Excel/LibreOffice-authored files use (a cell's
own `<f>` tag never carries the `=` either). I verified both forms round-trip
through a real `soffice --headless --convert-to xlsx` conversion; the `=`-free
form is what LibreOffice itself writes back out, so that is what I kept.

**`showDropDown`**: left at its default (`False`) everywhere. openpyxl's own
source aliases this attribute to `hide_drop_down`, i.e. the name is inverted
from what it suggests — `False` is what shows the arrow. Verified by writing
a workbook, reopening it with `openpyxl.load_workbook`, and asserting
`dv.showDropDown in (None, False)` on every validation
(`test_dropdown_arrow_is_shown_after_a_round_trip`), rather than trusting the
constructor argument.

**Real LibreOffice round-trip check** (not part of the automated suite,
since it needs `soffice` and takes a couple of seconds): I ran
`soffice --headless --convert-to xlsx` on a generated workbook containing
real emoji section labels, the INDIRECT() Subsection formula, and the
`sub_N` named ranges, then reopened the LibreOffice-resaved file with
openpyxl. Everything survived intact: named ranges, the INDIRECT formula
text, the emoji, and `showDropDown="false"`. This does not prove the
*dropdown UI* filters correctly when a human clicks the cell (that needs an
interactive check), but it does confirm LibreOffice parses and preserves the
whole mechanism rather than silently dropping or mangling it on save.

### 2. Section carries its descriptor

`intake_sheet.section_label("5")` → `"5. \U0001f3a8 Arts, crafts & stationery"`,
built from `items.json` (`entries.load_items()`) rather than hardcoded.
`write_workbook` uses this to fill the Section cell. A blank number stays
blank; an unrecognised number passes through unchanged (visible rather than
silently swallowed).

`intake_apply.normalise_section()` parses the leading digits back out
(`"5. \U0001f3a8 Arts, crafts & stationery"` → `"5"`) and also accepts a bare
`"5"` unchanged. `read_workbook` calls it on every row's Section value before
`validate()` or `apply_row()` ever see it, so both always work with a plain
number regardless of which shape the cell held.

### 3. Dependent Subsection dropdown

One named range per section, `sub_1` … `sub_7`, each pointing at that
section's column on `Lists` (e.g. `sub_5` → `Lists!$I$2:$I$3`). The
Subsection column's `formula1` is:

```
INDIRECT("sub_"&LEFT($B2&".",FIND(".",$B2&".")-1))
```

(`$B2` is wherever the Section column actually is, computed at runtime, not
hardcoded.) Appending `"."` to the cell value before both `LEFT` and `FIND`
makes this work identically whether the cell holds the full descriptor or a
bare number typed by hand — no `#VALUE!` from a missing `.`.

**Fallback constant: `intake_sheet.DEPENDENT_SUBSECTION_DROPDOWN`.** Set it to
`False` if the INDIRECT-based filtering misbehaves in Simon's copy of
LibreOffice; this switches the Subsection dropdown to the flat "All
subsections" range (every subsection name across every section, no
filtering). Both paths are exercised by tests
(`test_subsection_dropdown_uses_indirect_and_named_ranges_by_default`,
`test_subsection_dropdown_falls_back_to_a_flat_list_when_disabled`).

`intake_apply.validate()`'s existing section/subsection cross-check is
untouched — it still refuses a mismatched pair and lists the valid names
regardless of which dropdown mode is active.

### 4. NGO? column and the Amazon item title

New `NGO?` column inserted immediately before `NGO / proceeds to
conservation?` in `intake_sheet.COLUMNS`. `guess_ngo_flag()` pre-fills it:
empty `ngo_text` → `Not stated`; text matching a "no donation" /
"not applicable" / "not a registered charity" pattern → `No`; anything else
non-empty → `Yes`. It is editable and never touches the verbatim quote in
the neighbouring column. `intake_apply` reads none of it (it is a filtering
aid, not data that reaches `items.json`), and every header `intake_apply.py`
does read by name (`Section`, `Subsection`, `Item`, `Age`, `Link`,
`Approx. price`, `Description`, `Suggested by`,
`NGO / proceeds to conservation?`, `Image pick`, `Queue id`, `Status`) still
exists verbatim in `COLUMNS` — checked by
`test_every_header_intake_apply_reads_by_name_still_exists_verbatim`.

`intake_extract.extract_title()` now tries `#productTitle` (Amazon's own
element for the real product name) after JSON-LD and `og:title`, before the
`<title>` fallback. When only `<title>` is available, `_clean_amazon_title()`
strips a leading `"Amazon.com: "` and a trailing `" : <category>"` — but only
when the title actually starts with `"Amazon.com: "`, so another shop's
legitimately colon-bearing title is never touched. Verified against the real
cached page for the live queue row (`intake/queue.json`'s `q0001`,
`B07MXKZJDP`): its real `#productTitle` and its `<title>`-stripped fallback
both produce the identical clean name.

## Tests

Added 35 tests (225 → 260, all passing):

- `tests/test_intake_extract.py` (+2): `test_title_prefers_amazon_producttitle_over_the_title_tag`,
  `test_title_tag_fallback_strips_amazon_prefix_and_category_suffix`, against
  two new fixtures (`amazon_producttitle.html`, `amazon_title_only.html`)
  built from the real cached page for the queued Amazon item.
- `tests/test_intake_sheet.py` (+35... see file for the full list): Lists tab
  existence/order/visibility/bold headings; `section_choices`/`section_label`
  correctness including blank and unknown-number cases; the Section cell's
  descriptor and its blank case; `guess_ngo_flag` (Yes/No/Not stated) and its
  presence and position in the sheet; compound Age values being present in
  the Age list; each of the five dropdowns' `formula1` read back from a
  reopened file and asserted to be a range (`Lists!$...`) or an `INDIRECT(`
  expression, never an inline quoted list; named ranges `sub_1`…`sub_7`
  existing and pointing at `Lists` ranges; the `DEPENDENT_SUBSECTION_DROPDOWN`
  fallback producing the flat range instead; `showDropDown` reading back
  False/None; error/prompt text present on every validation; the validation
  range's margin past the data; and a zero-row workbook still building
  correctly.
- `tests/test_intake_apply.py` (+9): `normalise_section` on a descriptor, a
  bare number, and blank; `read_workbook` normalising a dropdown-written
  Section; `validate()` still passing a descriptor-shaped row after the
  round trip; `apply_row` still accepting a hand-typed bare section number
  directly; the header-name contract test; and the NGO?-column-is-harmless
  round trip.

Command used throughout: `/home/simon/.venvs/scrape/bin/python -m pytest -q`.
Final run: **260 passed in 2.40s**.

## Decided differently from the literal brief

- **No leading `=` in `formula1`** for range references (see above) — the
  task's own example shows one, but it produces non-standard OOXML and I
  verified LibreOffice itself strips it on save, so I wrote it correctly the
  first time rather than matching the example literally.
- **`subsections_for()` and `section_label()`/`section_choices()` read
  `entries.load_items()` directly** rather than going through
  `intake_classify._sections()` (which is `@lru_cache`d process-wide). Using
  the cached version would have made the Lists tab reflect a stale
  `items.json` in exactly the test scenarios (`isolated_apply`) that
  monkeypatch `entries.ITEMS` to a temp file — an existing latent quirk in
  `intake_classify` I did not touch, but avoided depending on.
- Added a couple of sentences to the Info tab (steps 4 and 6) describing the
  new dropdowns, the Lists tab, and the NGO? column, since the Info tab is
  the one place documented as explaining every column — not explicitly
  requested, but consistent with the existing house rule.

## Files touched

`intake_sheet.py`, `intake_apply.py`, `intake_extract.py`,
`tests/test_intake_sheet.py`, `tests/test_intake_apply.py`,
`tests/test_intake_extract.py`, plus two new fixtures under
`tests/fixtures/pages/`. `intake/queue.json` (the real staged `q0001` row)
was read only, never modified or applied.
