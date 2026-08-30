# Per-row Subsection validation, replacing the flat/INDIRECT switch

## The problem

Subsection's dropdown held all 23 subsection names across all seven
sections — eleven of them section 6's NGO names — regardless of which
section a row was actually in. `DEPENDENT_SUBSECTION_DROPDOWN` chose between
that flat list and an `INDIRECT()`-based per-section filter, but the
`INDIRECT` branch renders as an empty dropdown in LibreOffice (confirmed on
Simon's machine), so the flat list was the only branch that actually worked,
and Simon judged it "more annoying than it is useful."

## What was built

`intake_sheet.py`:

- Removed `DEPENDENT_SUBSECTION_DROPDOWN` and its comment entirely, along
  with the `INDIRECT()` formula construction it switched on.
- Added `_attach_subsection_dropdowns(ws, col_index, ranges, rows, n_rows)`,
  called from `_attach_dropdowns` (which now takes `rows` instead of
  `n_rows`, since it needs each row's own `section` value). It:
  - Groups the review rows by their guessed Section number.
  - For each distinct known section, attaches **one** `DataValidation`
    whose `formula1` is the bare named range `sub_<N>` (e.g. `sub_1`,
    `sub_5`) already defined on the `Lists` tab, with each of that
    section's rows added to the validation's `sqref` via `dv.add(cell)`
    rather than one validation per row.
  - Any row with a blank Section, or an unrecognised one, is swept into one
    further validation pointing at the existing flat "All subsections"
    range — the honest fallback, kept for exactly this reason.
  - The trailing rows past the last data row (out to the existing
    `VALIDATION_ROW_MARGIN` of 500) are added to that same fallback
    validation, since there is no per-row Section to key off there.
- Two new prompt constants, British English with Oxford commas:
  `SUBSECTION_PROMPT_KNOWN` ("These are the subsections for the section
  this row is currently in. If you change Section, this list will not
  follow it: intake_apply.py will refuse the mismatch and print the valid
  names.") and `SUBSECTION_PROMPT_FALLBACK`, which names the blank-Section
  situation explicitly.
- Reworded the Info tab's step 4 to describe per-row filtering instead of
  the old "where LibreOffice supports it" hedge, and updated
  `build_lists_sheet`'s docstring (no more mention of `INDIRECT`).
- `sub_1`…`sub_7` named ranges and the flat "All subsections" Lists column
  are unchanged.

## Tests (`tests/test_intake_sheet.py`)

Removed (obsolete, since neither branch of the removed switch is the wanted
behaviour): `test_subsection_dropdown_uses_the_flat_list_by_default`,
`test_subsection_dropdown_can_still_use_indirect_when_explicitly_enabled`.

Added, plus two helpers (`_dvs_for_column`, `_rows_of`) since a column can
now carry more than one validation:

- `test_subsection_dropdown_is_split_one_validation_per_distinct_section` —
  four rows across sections 1, 2, and 5 produce exactly three per-section
  validations (`sub_1`, `sub_2`, `sub_5`), each covering exactly its own
  rows.
- `test_a_blank_section_row_gets_the_all_subsections_fallback` — the
  existing `BLOCKED` fixture row (blank Section) gets the flat range, and
  is not swept into `sub_1` alongside `ROW`.
- `test_a_blank_section_subsection_prompt_explains_why` — the fallback
  prompt mentions the blank Section.
- `test_a_known_section_subsection_prompt_names_the_situation` — the
  per-section prompt names the section, `intake_apply.py`, and the
  Section-change caveat.
- `test_trailing_rows_beyond_the_data_get_the_all_subsections_fallback` —
  row `2 + VALIDATION_ROW_MARGIN` falls under the fallback, while the one
  real data row (its own section) does not.

Kept but touched: `test_named_ranges_exist_for_every_section` is unchanged
(sub_1…sub_7 still exist and are still what this feature uses).

All five new tests were run and confirmed failing against the pre-change
code, then passing after the implementation.

### Test output

```
$ /home/simon/.venvs/scrape/bin/python -m pytest -q
........................................................................ [ 26%]
........................................................................ [ 52%]
........................................................................ [ 79%]
.........................................................                [100%]
273 passed in 2.65s
```

(270 baseline − 2 removed obsolete tests + 5 new tests = 273.) Also ran
`tests/test_intake_sheet.py::test_isolation_guard_protects_the_real_sheets_dir`
on its own to confirm the autouse isolation fixture is intact and untouched.

## LibreOffice round-trip

Built a workbook with four rows (sections 1, 2, 5, and blank) via
`intake_sheet.write_workbook` into the scratchpad, then:

```
soffice --headless --convert-to xlsx --outdir <scratch>/converted <scratch>/roundtrip_src.xlsx
```

Reopening the converted file with openpyxl showed all four Subsection
validations survived intact:

```
formula1= sub_1  sqref= C2      (section 1 row)
formula1= sub_2  sqref= C3      (section 2 row)
formula1= sub_5  sqref= C4      (section 5 row)
formula1= Lists!$L$2:$L$24  sqref= C5:C505   (blank-section row + trailing margin,
                                              merged by LibreOffice into one range)
```

and the `sub_1`/`sub_2`/`sub_5` named ranges round-tripped unchanged
(`Lists!$E$2:$E$5`, `Lists!$F$2:$F$4`, `Lists!$I$2:$I$3`).

## Live files

`intake/queue.json`, `intake/review_2026-08-29.xlsx`, and
`images/sheets/pending_q0001.jpg` were not touched. MD5s taken before any
work and re-checked after completion are identical:

- `intake/queue.json`: `a5c80a2c54867e1502d425f868dfe744`
- `intake/review_2026-08-29.xlsx`: `544e8288ab785fc6f77d7c331dcb9ecc`
- `images/sheets/pending_q0001.jpg`: `70eb4a25af0e7ac76302513c847127e7`
