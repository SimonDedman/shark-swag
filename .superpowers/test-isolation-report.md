# Test-isolation guard, hyperlink fix, and dropdown-fallback commit

## 1. Test-isolation guard

### How the module bindings were enumerated

Ran, from the project root:

    grep -rn "from paths import\|import paths" --include="*.py" .

against every non-test `.py` file, giving the complete set of modules that
bind a `paths` name locally:

| module | names bound from `paths` |
|---|---|
| `intake_queue.py` | `LEDGER, QUEUE, REJECTED` |
| `intake_watch.py` | `ENV_FILE, HEARTBEAT, INTAKE_LOG, LEDGER, QUEUE, REJECTED` |
| `intake_apply.py` | `INTAKE, ROOT, SHEETS` |
| `intake_sheet.py` | `HEARTBEAT, INTAKE, SHEETS` |
| `entries.py` | `ITEMS, EXISTING_JSON, PICKS_JSON` (read-only, left alone) |
| `picks.py` | `PICKS_JSON, POOL_JSON, FINAL` (read-only, left alone) |
| `pool.py` | `POOL_DIR, SHEETS, CANDIDATES, EXTRAS, POOL_JSON, ROOT` (not in the brief's enumeration; left alone - see note below) |
| `harvest.py`, `migrate_picks.py`, `migrate_ids.py`, `build_docx.py`, `add_images.py` | read-only names only (`ITEMS`, `ROOT`, `DOCX`, `FINAL`, `HTMLCACHE`, `CANDIDATES`, `PICKS_JSON`) |

From this, the writable-state names that a running pipeline can overwrite
are `SHEETS`, `LEDGER`, `QUEUE`, `REJECTED`, `HEARTBEAT`, `INTAKE_LOG` - the
same six the task specified. `tests/conftest.py` now carries an autouse
`isolate_writable_project_state` fixture that, for each of those six names,
patches the attribute on every module that has it: `paths` itself,
`intake_queue`, `intake_watch`, `intake_apply`, and `intake_sheet`. It
checks `hasattr(module, name)` rather than assuming, so a module that does
not import a given name is skipped rather than gaining a spurious new
attribute.

Read-only committed data (`ITEMS`, `EXISTING_JSON`, `PICKS_JSON`,
`POOL_JSON`, `CANDIDATES`, `EXTRAS`, `HTMLCACHE`, `DOCX`, `FINAL`, `RAW`,
`POOL_DIR`, `IMAGES`, `ROOT`, `ENV_FILE`) is not in the patched set, so
`test_entries.py`, `test_pool_keys.py`, `test_picks.py`, and
`test_add_images.py` keep reading the real files, as before.

**`pool.py` note**: `pool.py` binds its own `SHEETS` too and can write
`sheet{n:02d}.jpg` files into it via `pool.sheets()`, but that function is
only reachable from `pool.py`'s own CLI entrypoint, not from anything the
test suite calls. The task's enumeration named `intake_queue`, `intake_watch`,
`intake_apply`, and `intake_sheet` specifically; `pool.py` was left out of
the patched module list to match that brief exactly, since widening it was
not asked for and the 269 pre-existing tests already ran clean against it.

### Covering tests

- `tests/test_intake_sheet.py::test_isolation_guard_protects_the_real_sheets_dir`
  is the control: it deliberately does **not** monkeypatch
  `intake_sheet.SHEETS` itself (every other contact-sheet test in that file
  does). It writes a contact sheet for a queue id (`q9999`) that cannot
  collide with anything real, then asserts (a) `intake_sheet.SHEETS` was
  actually redirected away from the real `images/sheets/` directory, (b) the
  file landed at the redirected path, and (c) the real `images/sheets/`
  directory's contents are byte-for-byte unchanged before and after.
  Verified as a real control: temporarily flipped the fixture to
  `autouse=False` and reran this one test in isolation - it failed with
  `intake_sheet.SHEETS == real_sheets`, exactly the hole the fixture closes.
  Restored `autouse=True` afterwards and confirmed the file was never
  touched (see md5 check below).
- All 34 tests in `test_intake_sheet.py` and 53 in `test_intake_apply.py`
  that previously carried their own `monkeypatch.setattr(module, "SHEETS"/
  "QUEUE", tmp_path)` lines are now redundant-but-harmless: the autouse
  fixture already points those names at a per-test `tmp_path`, and the
  explicit lines (executed after the fixture, within the same `monkeypatch`
  instance) simply reassign the same kind of value. Nothing was removed
  from them, so no coverage was lost.

### Queue id collision fix

`tests/test_intake_sheet.py` and `tests/test_intake_apply.py` used
`queue_id="q0001"` (and `"q0002"`/`"q0003"` for secondary rows) throughout -
12 and 53 occurrences respectively, including one easy-to-miss literal
`"q000"` prefix check in a heading-overlap test. All were mechanically
renamed `q0001`/`q0002`/`q0003` -> `q9001`/`q9002`/`q9003` (and the `"q000"`
prefix check to `"q900"`), so a hole in the isolation guard can no longer
land on the filename of a real staged submission. Confirmed via
`grep -rn "q0001\|q0002\|q0003"` on both files after the rename: zero hits.

## 2. Contact-sheet hyperlink

`intake_sheet.write_workbook` no longer writes
`=HYPERLINK("file://...","images")` as a formula string. It now sets the
cell's plain text value to `"images"` and assigns
`cell.hyperlink = openpyxl.worksheet.hyperlink.Hyperlink(ref=cell.coordinate,
target=sheet_path.as_uri())`, plus `cell.font = HYPERLINK_FONT` (`0563C1`,
underlined) so it still looks like a link.

**LibreOffice round-trip result**: built a throwaway one-row workbook (in
`.superpowers/roundtrip/`, deleted afterwards, never touching real project
state) with a real contact-sheet JPEG on disk, then ran

    soffice --headless --convert-to xlsx --outdir .superpowers/roundtrip/out \
        .superpowers/roundtrip/before.xlsx

Reading the converted file back with openpyxl: the Contact sheet cell still
carried a real `Hyperlink` object (`id='rId1'`, i.e. a relationship, not a
formula), value `"images"`, font colour `FF0563C1` / underline `single`.
LibreOffice rewrote the target from the absolute `file://.../sheets/
pending_....jpg` URI to a path relative to the new save location
(`../sheets/pending_....jpg`); resolving that relative path against the
converted file's directory landed exactly on the original JPEG. The
relationship and its target both survived intact.

## 3. Dropdown fallback commit

`DEPENDENT_SUBSECTION_DROPDOWN` is committed as `False`. The comment above
it now records: the `INDIRECT()` mechanism and its named ranges (`sub_5` ->
`Lists!$I$2:$I$3`, holding Kids and Youth) are correct, LibreOffice on
Simon's machine renders the dependent dropdown empty regardless, and
flipping it back to `True` is only worth trying if the workbook is ever
opened in Excel.

`test_subsection_dropdown_uses_indirect_and_named_ranges_by_default` (which
asserted the old default of `True`) was replaced with
`test_subsection_dropdown_uses_the_flat_list_by_default`, which asserts the
Subsection dropdown's `formula1` points at the Lists tab's "All subsections"
column with no `INDIRECT()` - the flat-list path the task asked to be
covered. The old mechanism itself is still covered by
`test_subsection_dropdown_can_still_use_indirect_when_explicitly_enabled`,
which now explicitly sets `DEPENDENT_SUBSECTION_DROPDOWN = True` via
monkeypatch rather than relying on it being the default.

Also added one Info-tab line noting that every contact sheet is embedded in
the workbook's own Images tab, not only on disk.

## Live-file md5 check

Captured before any test or exploratory work, and again after everything
above (including the guard-removal control run):

    19deeb6f4915f4c5537144f26a32272d  images/sheets/pending_q0001.jpg
    a5c80a2c54867e1502d425f868dfe744  intake/queue.json
    62f192f639148434b8bab595e69ee9ca  intake/review_2026-08-29.xlsx

Identical both times. None of the three were opened for writing, deleted,
or regenerated at any point. `intake/review_2026-08-29.xlsx` also carries a
LibreOffice `.~lock.review_2026-08-29.xlsx#` file, i.e. it is currently open
in LibreOffice; it was never touched.

## Test run

269 tests passed before this work (with the one pre-existing failure from
the uncommitted `DEPENDENT_SUBSECTION_DROPDOWN = False` edit fixed as part
of task 3). 270 pass after (the 269 plus the new isolation-guard control
test); no test was deleted.
